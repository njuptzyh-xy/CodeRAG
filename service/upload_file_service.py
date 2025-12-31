import sys
import os

# 将项目根目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import requests
from datetime import datetime
from openai import OpenAI
from neo4j import GraphDatabase
from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    Function,
    FunctionType,
    utility,
)
from pymilvus.exceptions import MilvusException
from setting import (CHAT_MAX_TOKENS, CHAT_MODEL_API_KEY, CHAT_MODEL_NAME, CHAT_URL, DOWNLOAD_FILE_CHUNK_URL, EMBEDDING_URL, 
                     OCR_URL, UPLOAD_FILE_CHUNK_URL, NEO4J_USER, NEO4J_PASSWORD, NEO4J_URI, NEO4J_DATABASE, EMBEDDING_API_KEY,
                     MILVUS_HOST, MILVUS_PORT, MILVUS_USER, MILVUS_PASSWORD, MILVUS_DB_NAME, MILVUS_COLLECTION, MILVUS_CONSISTENCY_LEVEL, MILVUS_SECURE)
from utils.map_prompt import ANALYZE_FILE_TECHNIQUE_PROMPT

# 临时修改：由于磁盘空间不足，将路径改为 /root/workspace/ch 下
# 原代码（等磁盘空间足够后改回）：
# UPLOAD_FILE_DIR = 'upload_file'  # 相对于项目根目录
# 临时路径
UPLOAD_FILE_DIR = '/root/workspace/ch/upload_file'

AUTH = (NEO4J_USER, NEO4J_PASSWORD)

SESSION_KWARGS = {"database": NEO4J_DATABASE}

driver = GraphDatabase.driver(NEO4J_URI, auth=AUTH)

# 连接 Milvus - 改进错误处理
milvus_connected = False
try:
    connections.connect(
        alias="default",
        host=MILVUS_HOST,
        port=str(MILVUS_PORT),
        user=MILVUS_USER,
        password=MILVUS_PASSWORD,
        db_name=MILVUS_DB_NAME,
        secure=MILVUS_SECURE,
    )
    milvus_connected = True
    print(f"Milvus 连接成功: {MILVUS_HOST}:{MILVUS_PORT}")
except Exception as e:
    print(f"Milvus 连接失败: {e}")
    print(f"连接参数: host={MILVUS_HOST}, port={MILVUS_PORT}, user={MILVUS_USER}, db={MILVUS_DB_NAME}")

# 创建一个全局的 Session 对象
session = requests.Session()

# 可以在这里为 Session 对象配置适配器，例如设置连接池大小
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
session.mount('http://', adapter)
session.mount('https://', adapter)

def submit_task_to_parse(file_path, file_type):
    # 进行提交切分操作
    submit_url = UPLOAD_FILE_CHUNK_URL

    with open(file_path, "rb") as f:
        file_name = os.path.basename(file_path)
        files = {
            "file": (os.path.basename(file_path), f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        }
        data = {
            "file_type": file_type,
            "metadata": '{"chunk_size": 2048,"chunk_overlap": 512}'
        }
        response = session.post(submit_url, files=files, data=data)
        if response.status_code == 200:
            task_data = response.json()
            task_id = task_data.get("task_id")
            message = task_data.get("message")
            print(f"{file_name} 任务提交成功，任务ID: {task_id}")
        elif response.status_code == 202:
            task_data = response.json()
            task_id = task_data.get("task_id")
            message = task_data.get("message")
            print(f"{file_name} 任务提交成功，任务ID: {task_id}")
        elif response.status_code == 400 or response.status_code == 500:
            task_data = response.json()
            message = task_data.get("detail")
            print(f"{file_name} 提交失败，错误信息: {message}")
            return {"status": "error", "message": message}

    return {"status": "success", "task_id": task_id, "message": message}

def download_file_data(task_id, file_name):
    download_url = DOWNLOAD_FILE_CHUNK_URL + str(task_id)
    response = session.get(download_url)
    if response.status_code == 200:
        response_data = response.json()
        if response_data["status"] == "SUCCESS":
            new_file_name = "{}.json".format(file_name)
            result_file_path = os.path.join(UPLOAD_FILE_DIR, new_file_name)
            if not os.path.exists(result_file_path):
                with open(result_file_path, "w", encoding="utf-8") as f:
                    json.dump(response_data, f, ensure_ascii=False, indent=2)
            return {"status": "SUCCESS", "file_name": new_file_name}
        elif response_data["status"] == "PENDING" or response_data["status"] == "PROCESSING":
            return {"status": "PROCESSING"}
        elif response_data["status"] == "FAILED":
            error_info = response_data["error_info"]
            return {"status": "FAILED", "error_info": error_info}
    else:
        return {"status": "FAILED", "error_info": {}}

def judge_data_about_safe(response_data):
    user_prompt = f"""
        {response_data}
    
        上面是从一个图片中提取出来的数据，
        帮我判断一下上面这段数据是否是安全相关的知识或者代码、命令行命令相关的数据。
        如果是则反回标志信息 sign 为 1，代表相关， 标志信息为 0 则是不相关。

        对于相关的返回json信息：
        {{"sign": 1}}
        对于不相关的返回 json 信息。
        {{"sign": 0}}

        注意:只返回json数据
    """
    
    client = OpenAI(
        api_key=CHAT_MODEL_API_KEY,
        base_url=CHAT_URL,
    )
    
    messages = [{"role": "user", "content": user_prompt}, {"role": "system", "content": "You are a helpful assistant."}]
    
    response = client.chat.completions.create(
        model=CHAT_MODEL_NAME,
        messages=messages,
        response_format={
            'type': 'json_object'
        },
        temperature=0,
        stream=False
    )
    return json.loads(response.choices[0].message.content)

def get_picture_data_by_ocr(picture_data):
    ocr_url = OCR_URL
    payload = {
        "base64_str": picture_data
    }
    response = session.post(ocr_url, json=payload)
    if response.status_code == 200:
        response_data = response.json().get("ocr_result")
        # 接下来判断 response_data 的类型，
        # 使用模型判断是否是安全相关的知识或者代码、命令行命令相关的数据
        safe_sign = judge_data_about_safe(response_data)
        safe_sign = safe_sign.get("sign")
        return {"status": "success", "safe_sign": safe_sign, "response_data": response_data}
    else:
        # 获取非200状态码的响应信息
        try:
            error_response = response.json()
            return {"status": "error", "safe_sign": 0, "response_data": error_response}
        except json.JSONDecodeError:
            # 如果响应不是JSON格式，返回文本内容
            return {"status": "error", "safe_sign": 0, "response_data": response.text}


def handle_picture_in_json_file(chunk_json_file_path):
    try:
        with open(chunk_json_file_path, "r", encoding="utf-8") as f:
            file_data = json.load(f)
    except Exception as e:
        return {"status": "error", "message": "切块文件打开失败"}

    file_data_chunk = file_data.get("chunks_list")
    if not file_data_chunk:
        return {"status": "error", "message": "没有发现文件内容"}
    
    for chunk_index, chunk in enumerate(file_data_chunk):
        if chunk.get("metadata", {}).get("chunk_type") == "image":
            picture_data = chunk.get("content")
            try:
                picture_data = get_picture_data_by_ocr(picture_data)
                picture_sign = picture_data["safe_sign"]
                reponse_result = picture_data["response_data"]
                response_status = picture_data["status"]    
                if picture_sign and response_status == "success":
                    chunk["safe_sign"] = 1
                    if reponse_result:
                        chunk["content"] = reponse_result
                else:
                    chunk["safe_sign"] = 0
            except Exception as e:
                chunk["safe_sign"] = 0
    # 处理完后写回
    with open(chunk_json_file_path, "w", encoding="utf-8") as f:
        json.dump(file_data, f, ensure_ascii=False, indent=2)
        return {"status": "success"}

def delete_image_sign(path):
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    chunks_list = data.get("chunks_list", [])
    # 过滤掉 chunk_type 为 image 且 safe_sign 为 0 的 chunk
    new_chunks_list = [
        chunk for chunk in chunks_list
        if not (chunk.get("metadata", {}).get("chunk_type") == "image" and chunk.get("safe_sign") == 0)
    ]
    data["chunks_list"] = new_chunks_list
    # 写回文件
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

def get_all_documents_text(path, file_name):
    # 进行文件分析
    # 先将 chunk 整合成一个完整的文件
    # 将文章数据的 content 拼接到一起
    file_text = ""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    chunks_list = data.get("chunks_list")
    for chunk in chunks_list:
        content = chunk.get("content")
        file_text += content
    # 写入文件路径
    new_file_name = "{}.txt".format(file_name)
    save_path = os.path.join(UPLOAD_FILE_DIR, new_file_name)
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(file_text)
    
    return save_path, new_file_name

def get_summary_for_document(document_text):
    user_prompt = f"""
        {document_text}
    
        上面是一个文章的内容，帮我给这个文章做一个总结，
        先判断这个文章是否和计算机安全领域知识有关系，包括一些攻击手段、路径、步骤等。
        接下来，如果是和安全知识有关要着重关注文章中的安全知识、技术手段、技术流程、技术原理。
        如果和安全知识不相关就普通总结就好。
        
        总结文章内容在 2000 字左右。
        
        返回 json 数据:
        {{"summary": "总结的内容"}}

        注意:只返回json数据
    """
    
    client = OpenAI(
        api_key=CHAT_MODEL_API_KEY,
        base_url=CHAT_URL,
    )
    
    messages = [{"role": "user", "content": user_prompt}, {"role": "system", "content": "You are a helpful assistant."}]
    
    response = client.chat.completions.create(
        model=CHAT_MODEL_NAME,
        messages=messages,
        response_format={
            'type': 'json_object'
        },
        temperature=0,
        stream=False
    )
    return json.loads(response.choices[0].message.content)

def get_all_documents_summary(path):
    with open(path, "r", encoding="utf-8") as f:
        file_data = f.read()    

    # 分段总结
    file_part = []
    max_length = CHAT_MAX_TOKENS
    for i in range(0, len(file_data), max_length):
        file_part.append(file_data[i: i + max_length])
    
    # 现在给每一段 part 做总结之后，在给所有的分总结一个总结
    part_summaries = []        # 这是分段总结结果列表
    for part_item in file_part:
        summary = get_summary_for_document(part_item)
        part_summaries.append(summary['summary']) # 假设返回字典里有'summary'字段
    
    # 2. 汇总所有分段摘要
    all_summaries = "\n".join(part_summaries)
    final_summary = get_summary_for_document(all_summaries)
    if final_summary.get("summary"):
        return final_summary.get("summary")
    else:
        return "error"

def map_document_technical_request(document_text):
    user_prompt = ANALYZE_FILE_TECHNIQUE_PROMPT.format(ducument_text=document_text)
    
    client = OpenAI(
        api_key=CHAT_MODEL_API_KEY,
        base_url=CHAT_URL,
    )
    
    messages = [{"role": "user", "content": user_prompt}, {"role": "system", "content": "You are a helpful assistant."}]
    
    response = client.chat.completions.create(
        model=CHAT_MODEL_NAME,
        messages=messages,
        response_format={
            'type': 'json_object'
        },
        temperature=0,
        stream=False
    )
    return json.loads(response.choices[0].message.content)
        
def map_document_to_technical(path):
    with open(path, "r", encoding="utf-8") as f:
        document_text = f.read()
    try:
        max_length = CHAT_MAX_TOKENS  # 可根据实际模型 token 限制调整
        parts = [document_text[i:i+max_length] for i in range(0, len(document_text), max_length)]
        part_results = []
        for part in parts:
            result = map_document_technical_request(part)
            part_results.append(result)
        
        # 汇总所有分段的技术点描述
        total_technique_ids = []
        for item in part_results:
            if item.get("result"):
                item_ttps = item.get("ttps")
                if item_ttps:
                    for ttp in item_ttps:
                        if ttp["relevance"] >= 0.9 and ttp["have_text"]:
                            total_technique_ids.append(ttp["technique_id"])
        
        # 需要返回这个技术信息
        return {"data": total_technique_ids, "status": "success"}
    except Exception as e:
        return {"data": str(e), "status": "error"}

def insert_neo4j_document_data_without_embedding(technique_ids, source_name, chunk_json_file_name, file_name_txt, summary_text, document_insert_number=0):
    document_path = os.path.join(UPLOAD_FILE_DIR, file_name_txt)
    with open(document_path, "r", encoding="utf-8") as f:
        # 文章正文
        document_full_text = f.read()
        
    document_summary_data = summary_text
        
    # 插入批次，这是用户自己上传，所以设定一个比较特殊的数字
    document_insert_number = 0
        
    document_insert_type = "user_upload_article"
                        
    document_source_info = "userUpload-{}".format(source_name)
    with driver.session(**SESSION_KWARGS) as session:
        # 插入节点
        cypher = """
            MERGE (n:BaseEntity:MitreAttackArticleDocument {title: $source_name})
            ON CREATE SET
                n.article_summary = $document_summary_data,
                n.full_text = $document_full_text,
                n.insert_number = $document_insert_number,
                n.insert_type = $document_insert_type,
                n.mitre_attack_id_list = $document_tec_data_list,
                n.source_info = $document_source_info,
                n.title = $source_name
            RETURN elementId(n) as element_id
        """
        result = session.run(
            cypher,
            document_summary_data=document_summary_data,
            document_full_text=document_full_text,
            document_insert_number=document_insert_number,
            document_insert_type=document_insert_type,
            document_tec_data_list=technique_ids,
            document_source_info=document_source_info,
            source_name=source_name
        )
        document_element_id = result.single()["element_id"]
        
        # print("看看 documengt_id\n", document_element_id)

def get_embhedding(chunk_description):
    headers = {
        "Content-Type": "application/json",
        "x-api-key": EMBEDDING_API_KEY,
    }
    body = {"texts": [chunk_description]}
    try:
        response = requests.post(url=EMBEDDING_URL, headers=headers, json=body)
        if response.status_code == 200:
            data = response.json()
            embeddings = data.get("embeddings")
            if embeddings:
                return embeddings[0]
            print(f"[get_embhedding] Stella 返回为空")
            return None
        print(f"[get_embhedding] Stella 请求失败 status={response.status_code}, body={response.text}")
        return None
    except Exception as e:
        print(f"[get_embhedding] Stella 请求异常: {e}")
        return None

def insert_neo4j_chunk(chunk_json_file_name, source_name):
    chunk_file_path = os.path.join(UPLOAD_FILE_DIR, chunk_json_file_name)
    with open(chunk_file_path, "r", encoding="utf-8") as f:
        # 文章 chunk 数据
        total_chunk_data_json = json.load(f)
    chunks_list = total_chunk_data_json.get("chunks_list")
    
    all_chunk_element_id = []
    for chunk_item in chunks_list:
        chunk_description = chunk_item.get("content")
        # 先取出 id/index，避免 embedding 失败时变量未定义
        chunk_index = chunk_item.get("metadata", {}).get("chunk_number")
        chunk_id = chunk_item.get("metadata", {}).get("chunk_id")

        chunk_description_embedding = get_embhedding(chunk_description)
        if chunk_description_embedding is None:
            print(f"{chunk_id or chunk_index} chunk 描述embedding 失败")
            continue

        chunk_insert_number = 0
        chunk_insert_type = "user_upload_article_chunk"
            
        chunk_source_info = "userUpload-{}".format(source_name)
        with driver.session(**SESSION_KWARGS) as session:
            # 插入节点
            insert_document_chunk_query = """
                MERGE (n:BaseEntity:MitreAttackArticleChunk {chunk_id: $chunk_id})
                ON CREATE SET
                    n.chunk_index = $chunk_index,
                    n.description = $chunk_description,
                    n.description_embedding = $chunk_description_embedding,
                    n.chunk_id = $chunk_id,
                    n.insert_number = $chunk_insert_number,
                    n.insert_type = $chunk_insert_type,
                    n.source_info = $chunk_source_info
                RETURN elementId(n) as chunk_element_id
            """
            result = session.run(
                insert_document_chunk_query,
                chunk_index=chunk_index,
                chunk_description=chunk_description,
                chunk_description_embedding=chunk_description_embedding,
                chunk_id=chunk_id,
                chunk_insert_number=chunk_insert_number,
                chunk_insert_type=chunk_insert_type,
                chunk_source_info=chunk_source_info
            )
            chunk_element_id = result.single()["chunk_element_id"]
            all_chunk_element_id.append(chunk_element_id)
    return all_chunk_element_id
            
def add_document_chunk_rel(source_name):
    source_info = "userUpload-{}".format(source_name)
    with driver.session(**SESSION_KWARGS) as session:
        # 查询所有 insert_number=5 且为 MitreAttackArticleChunk 的节点及其 source_info
        cypher = """
        MATCH (c:MitreAttackArticleChunk)
        WHERE c.insert_number = 0 AND c.source_info = $source_info
        RETURN c.chunk_id AS chunk_id
        """
        result = session.run(cypher, source_info=source_info)

        index = 0
        for chunk in result:
            chunk_id = chunk.get("chunk_id")

            # 用 source_info 匹配 MitreAttackArticleDocument 节点，建立双向关系
            rel_cypher = """
            MATCH (c:MitreAttackArticleChunk), (d:MitreAttackArticleDocument)
            WHERE c.chunk_id = $chunk_id AND d.source_info = $source_info
            MERGE (d)-[r1:DOCUMENT_HAS_CHUNK {insert_number: 0}]->(c)
            MERGE (c)-[r2:CHUNK_BELONG_TO_DOCUMENT {insert_number: 0}]->(d)
            """
            session.run(rel_cypher, chunk_id=chunk_id, source_info=source_info)
            print(f"已建立关系: chunk_id={chunk_id}, source_info={source_info}")
            index += 1

def add_document_tec_rel(source_name):
    source_info = "userUpload-{}".format(source_name)

    with driver.session(**SESSION_KWARGS) as session:
        cypher = """
        MATCH (d:MitreAttackArticleDocument)
        WHERE d.insert_number = 0 AND d.source_info = $source_info
        RETURN elementId(d) AS doc_id, d.mitre_attack_id_list AS mitre_attack_id_list
        """
        result = session.run(cypher, source_info=source_info)
        for record in result:
            doc_id = record.get("doc_id")
            mitre_attack_id_list = record.get("mitre_attack_id_list")  # 这是一个列表

            if not mitre_attack_id_list:
                continue
            for attack_id in mitre_attack_id_list:
                # 为每个 attack_id 建立关系
                rel_cypher = """
                MATCH (d)
                WHERE elementId(d) = $doc_id
                MATCH (t:MitreAttackTechnique {attack_id: $attack_id})
                MERGE (d)-[:DOCUMENT_BELONG_TECHNIQUE {insert_number: 0}]->(t)
                MERGE (t)-[:TECHNIQUE_HAS_DOCUMENT {insert_number: 0}]->(d)
                """
                session.run(rel_cypher, doc_id=doc_id, attack_id=attack_id)

def _ensure_milvus_collection():
    """确保 Milvus collection 存在，如果不存在则创建"""
    if not milvus_connected:
        raise RuntimeError("Milvus 未连接，无法创建 collection")
    
    collection_name = MILVUS_COLLECTION
    vector_dim = 1024  # 根据用户要求，向量维度为 1024
    
    # 检查 collection 是否存在
    try:
        has_collection = utility.has_collection(collection_name)
    except Exception as e:
        print(f"检查 collection 是否存在时出错: {e}")
        raise
    
    if not has_collection:
        print(f"Milvus collection {collection_name} 不存在，开始创建 (dim={vector_dim})...")
        
        try:
            # 定义字段：code_data + description + code__embedding
            fields = [
                FieldSchema(
                    name="neo4j_id",
                    dtype=DataType.VARCHAR,
                    is_primary=True,
                    auto_id=False,
                    max_length=128,
                ),
                FieldSchema(
                    name="code_data",
                    dtype=DataType.VARCHAR,
                    max_length=65535,
                    enable_analyzer=True,
                    analyzer_params={
                        "tokenizer": "jieba",  # 中英文分词
                        "filter": ["lowercase"],
                    },
                ),
                FieldSchema(
                    name="description",
                    dtype=DataType.VARCHAR,
                    max_length=65535,
                    enable_analyzer=True,
                    analyzer_params={
                        "tokenizer": "jieba",
                        "filter": ["lowercase"],
                    },
                ),
                FieldSchema(
                    name="code__embedding",
                    dtype=DataType.FLOAT_VECTOR,
                    dim=vector_dim,
                ),
                FieldSchema(
                    name="sparse_vector",
                    dtype=DataType.SPARSE_FLOAT_VECTOR,
                ),
            ]
            
            # 创建 BM25 函数，将 description 转为稀疏向量
            bm25_function = Function(
                name="description_bm25",
                input_field_names=["description"],
                output_field_names=["sparse_vector"],
                function_type=FunctionType.BM25,
            )
            
            # 创建 schema
            schema = CollectionSchema(
                fields=fields,
                functions=[bm25_function],
                description="Collection for storing document chunks with embeddings",
            )
            
            # 创建 collection
            collection = Collection(
                name=collection_name,
                schema=schema,
                consistency_level=MILVUS_CONSISTENCY_LEVEL,
            )
            print(f"Collection {collection_name} 创建成功")
            
            # 创建索引
            try:
                # 为稠密向量创建索引
                collection.create_index(
                    field_name="code__embedding",
                    index_params={
                        "index_type": "FLAT",
                        "metric_type": "COSINE",
                    },
                )
                print(f"为 collection {collection_name} 的向量字段创建索引完成")
            except MilvusException as exc:
                if "already exist" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                    print(f"创建向量字段索引时出错: {exc}")
                    raise
            
            try:
                # 为稀疏向量创建索引
                collection.create_index(
                    field_name="sparse_vector",
                    index_params={
                        "index_type": "SPARSE_INVERTED_INDEX",
                        "metric_type": "BM25",
                    },
                )
                print(f"为 collection {collection_name} 的稀疏向量字段创建索引完成")
            except MilvusException as exc:
                if "already exist" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                    print(f"创建稀疏向量字段索引时出错: {exc}")
                    raise
            
            # 加载 collection
            collection.load()
            print(f"Milvus collection {collection_name} 创建并加载完成")
            
            # 验证 collection 是否真的存在
            if utility.has_collection(collection_name):
                print(f"✓ 验证成功: collection {collection_name} 已存在")
            else:
                raise RuntimeError(f"Collection {collection_name} 创建失败，验证时不存在")
                
        except Exception as e:
            print(f"创建 collection {collection_name} 时出错: {e}")
            import traceback
            traceback.print_exc()
            raise
    else:
        collection = Collection(name=collection_name)
        # 检查并创建缺失的索引
        try:
            index_info = collection.indexes
        except Exception as e:
            print(f"获取 collection 索引信息时出错: {e}")
            index_info = []
            
        vector_has_index = any(
            idx.field_name == "code__embedding" for idx in index_info
        )
        sparse_has_index = any(
            idx.field_name == "sparse_vector" for idx in index_info
        )
        
        # 如果需要创建索引，先释放 collection
        need_reload = False
        if not vector_has_index or not sparse_has_index:
            try:
                collection.release()
            except Exception:
                pass  # 如果未加载，忽略异常
        
        if not vector_has_index:
            try:
                collection.create_index(
                    field_name="code__embedding",
                    index_params={
                        "index_type": "FLAT",
                        "metric_type": "COSINE",
                    },
                )
                print(f"为 collection {collection_name} 的向量字段创建索引完成")
                need_reload = True
            except MilvusException as exc:
                if "already exist" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                    print(f"创建向量字段索引时出错: {exc}")
        
        if not sparse_has_index:
            try:
                collection.create_index(
                    field_name="sparse_vector",
                    index_params={
                        "index_type": "SPARSE_INVERTED_INDEX",
                        "metric_type": "BM25",
                    },
                )
                print(f"为 collection {collection_name} 的稀疏向量字段创建索引完成")
                need_reload = True
            except MilvusException as exc:
                if "already exist" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                    print(f"创建稀疏向量字段索引时出错: {exc}")
        
        # 确保 collection 已加载
        if need_reload:
            collection.load()
        else:
            try:
                collection.load()
            except Exception:
                pass  # 如果已经加载，忽略异常
        print(f"Milvus collection {collection_name} 已存在")
    
    return collection

def add_milvus(all_embedding_element_id):
    """将数据添加到 Milvus 向量数据库"""
    if not milvus_connected:
        print("错误: Milvus 未连接，无法插入数据")
        return
    
    # 查询指定 ID 的节点，使用 description 作为 code_data 写入 Milvus
    query = """
    UNWIND $element_ids AS element_id
    MATCH (n:BaseEntity)
    WHERE elementId(n) = element_id AND n.description IS NOT NULL
    RETURN elementId(n) as element_id,
           n.description as description,
           n.description as code_data,
           n.description_embedding as code_embedding
    """
    
    try:
        with driver.session(**SESSION_KWARGS) as session:
            result = session.run(query, element_ids=all_embedding_element_id)
            all_records = list(result)
    except Exception as e:
        print(f"从 Neo4j 查询数据失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    if not all_records:
        print("没有找到需要导入的记录")
        return
    
    print(f"从 Neo4j 查询到 {len(all_records)} 条记录")
    
    # 确保 collection 存在
    try:
        collection = _ensure_milvus_collection()
    except Exception as e:
        print(f"确保 collection 存在时出错: {e}")
        import traceback
        traceback.print_exc()
        return
    
    success_count = 0
    error_count = 0
    
    # 准备批量插入的数据
    neo4j_ids = []
    code_datas = []
    descriptions = []
    embeddings = []
    
    for record in all_records:
        try:
            neo4j_id = str(record["element_id"])
            description = record["description"]
            code_data = record["code_data"]
            embedding = record["code_embedding"]
            
            # 验证数据
            if not neo4j_id or not code_data or not embedding:
                error_count += 1
                print(f"跳过记录 {neo4j_id}: 数据不完整")
                continue
            
            # 验证向量维度
            if not isinstance(embedding, list):
                error_count += 1
                print(f"跳过记录 {neo4j_id}: 向量不是列表类型")
                continue
                
            actual_dim = len(embedding)
            if actual_dim != 1024:
                error_count += 1
                print(f"跳过记录 {neo4j_id}: 向量维度不正确 (期望 1024, 实际 {actual_dim})")
                continue
            
            neo4j_ids.append(neo4j_id)
            code_datas.append(code_data)
            descriptions.append(description or "")
            embeddings.append(embedding)
            
        except Exception as e:
            error_count += 1
            print(f"处理记录失败: {str(e)}")
            import traceback
            traceback.print_exc()
    
    print(f"准备插入 {len(neo4j_ids)} 条有效记录")
    
    # 批量插入数据
    if neo4j_ids:
        try:
            # 确保字段顺序与 schema 定义一致: neo4j_id, code_data, description, code__embedding
            entities = [neo4j_ids, code_datas, descriptions, embeddings]
            print(f"开始插入数据到 collection {MILVUS_COLLECTION}...")
            result = collection.upsert(entities)
            print(f"Upsert 返回结果: {result}")
            success_count = len(neo4j_ids)
            
            # 每100条打印一次进度
            if success_count % 100 == 0:
                print(f"已成功导入{success_count}条记录...")
            
            # 验证插入是否成功 - 查询 collection 中的记录数
            try:
                collection.flush()  # 确保数据被持久化
                num_entities = collection.num_entities
                print(f"Collection {MILVUS_COLLECTION} 当前包含 {num_entities} 条记录")
            except Exception as e:
                print(f"查询 collection 记录数时出错: {e}")
            
            print(f"导入完成！成功: {success_count}, 失败: {error_count}")
        except MilvusException as e:
            print(f"Milvus 批量插入失败: {str(e)}")
            print(f"错误类型: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            error_count += len(neo4j_ids)
        except Exception as e:
            print(f"插入数据时发生未知错误: {str(e)}")
            print(f"错误类型: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            error_count += len(neo4j_ids)
    else:
        print("没有有效数据需要导入")

def handle_file(source_name, file_path, file_name, file_type, document_insert_number=0):
    # 提交切分
    task_id_and_message_data = submit_task_to_parse(file_path, file_type)
    if task_id_and_message_data["status"] == "error":
        return task_id_and_message_data
    
    task_id = task_id_and_message_data["task_id"]
    task_message = task_id_and_message_data["message"]
    
    # 轮询任务状态
    chunk_json_file_name = None
    is_sign = True
    error_info = None
    while True:
        status = download_file_data(task_id, file_name)
        if status["status"] == "SUCCESS":
            chunk_json_file_name = status["file_name"]
            print(f"{file_name} 文件切分成功")
            break
        elif status["status"] == "PROCESSING":
            continue
        elif status["status"] == "FAILED":
            is_sign = False
            error_info = status["error_info"]
            print(f"{file_name} 文件切分失败，错误信息: {error_info}")
            break
    
    # 先判断是不是失败了
    if not is_sign:
        return {"status": "error", "message": error_info}
    
    # 处理文件中的图片，有和安全有关的替换成文字
    chunk_json_file_path = os.path.join(UPLOAD_FILE_DIR, chunk_json_file_name)
    status = handle_picture_in_json_file(chunk_json_file_path)
    if status["status"] == "success":
        print(f"{file_name} 文字替换完成")
    else:
        print(f"{file_name} 文字替换失败，错误信息: {status['message']}")

    # 将文件中的和安全无关的图片删掉
    delete_image_sign(chunk_json_file_path)
    print(f"{file_name} 无关图片删除完成")
    
    # 将整个 json 组合成一个 txt 文件 解析json文本块和图片ocr后的内容串起来
    save_path, file_name_txt = get_all_documents_text(chunk_json_file_path, chunk_json_file_name)
    
    # 获得文章总结
    summary_text = get_all_documents_summary(save_path)
    if summary_text == "error":
        return {"status": "error", "message": "get document summary failed!"}
    print(f"{file_name} 文章总结完成")

    # 接下来进行技术矩阵对应
    technical_dict = map_document_to_technical(save_path)
    if technical_dict["status"] == "error":
        return {"status": "error", "message": technical_dict["data"]}
    technique_ids = technical_dict["data"]
    print(f"{file_name} 技术矩阵对应完成")

    # 进行文章插入
    insert_neo4j_document_data_without_embedding(technique_ids, source_name, chunk_json_file_name, file_name_txt, summary_text, document_insert_number)
    print(f"{file_name} 文章插入完成")
    # 进行 chunk 插入
    all_chunk_element_id = insert_neo4j_chunk(chunk_json_file_name, source_name)
    print(f"{file_name} chunk 插入完成")
    # 增加 文章 chunk 关系
    add_document_chunk_rel(source_name)
    print(f"{file_name} 文章-chunk 关系建立完成")
    
    # 增加文章 技术关系
    add_document_tec_rel(source_name)
    print(f"{file_name} 文章-技术关系建立完成")
    
    # 增加 milvus
    add_milvus(all_chunk_element_id)
    print(f"{file_name} milvus 添加完成")
    
    return {"status": "success"}
    
    
def save_file(file):
    # 临时修改：由于磁盘空间不足，将路径改为 /root/workspace/ch 下
    # 原代码（等磁盘空间足够后改回）：
    # upload_file_dir = 'upload_file'  # 相对于项目根目录
    # # 确保目录存在
    # if not os.path.exists(upload_file_dir):
    #     os.makedirs(upload_file_dir)
    
    # 临时路径
    upload_file_dir = UPLOAD_FILE_DIR
    # 确保目录存在
    if not os.path.exists(upload_file_dir):
        os.makedirs(upload_file_dir)
        
    file_name = file.filename
    
    # 查看文件类型,除了固定文件类型,其他文件类型都不处理
    file_type = file_name.split('.')[-1]
    if file_type not in ['pdf', 'docx', 'doc', 'txt', 'md', 'pptx', 'jpg', 'png', 'xlsx']:
        raise ValueError(f"不支持的文件类型: {file_type}")
    
    # 生成时间字符串
    time_str = datetime.now().strftime('%Y%m%d%H%M%S')

    # 拆分文件名和扩展名
    name_part, ext_part = os.path.splitext(file_name)
    # 拼接新文件名
    new_file_name = f"{name_part}_{time_str}{ext_part}"

    file_path = os.path.join(upload_file_dir, new_file_name)
    
    # 保存到指定目录
    file.save(file_path)
    
    return name_part, file_path, new_file_name, file_type