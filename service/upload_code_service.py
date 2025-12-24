import os
import uuid
import json
import tarfile
import zipfile
import py7zr
import pathlib
from red_kbs_analyzer.run_logs.logger import logger
from datetime import datetime
import requests
from red_kbs_analyzer import RedKBSAnalyzer
from neo4j import GraphDatabase
from openai import OpenAI
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
from setting import (CHAT_MODEL_API_KEY, CHAT_MODEL_NAME, CHAT_URL, EMBEDDING_URL, EMBEDDING_API_KEY,
                     NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER,
                     MILVUS_HOST, MILVUS_PORT, MILVUS_USER, MILVUS_PASSWORD, MILVUS_DB_NAME, MILVUS_COLLECTION, MILVUS_CONSISTENCY_LEVEL, MILVUS_SECURE)

AUTH = (NEO4J_USER, NEO4J_PASSWORD)
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

def get_filename_without_extension(file_path):
    """获取文件名（不含扩展名），特殊处理 .tar.gz"""
    # 提取文件名（去掉路径）
    file_name = os.path.basename(file_path)
    
    # 处理 .tar.gz
    if file_name.endswith('.tar.gz'):
        return file_name[:-7]  # 去掉 .tar.gz
    else:
        return pathlib.Path(file_name).stem

def create_extract_dir(file_path, base_dir="upload_code"):
    """根据压缩包文件名创建解压目录"""
    filename = get_filename_without_extension(file_path)
    extract_dir = os.path.join(base_dir, filename)
    os.makedirs(extract_dir, exist_ok=True)
    return extract_dir

def extract_tar_file(file_path, base_dir="upload_code"):
    """解压 .tar 或 .tar.gz 文件到指定文件夹"""
    extract_dir = create_extract_dir(file_path, base_dir)
    with tarfile.open(file_path, "r") as tar:
        tar.extractall(path=extract_dir, filter='data')
    return extract_dir

def extract_zip_file(file_path, base_dir="upload_code"):
    """解压 .zip 文件到指定文件夹"""
    extract_dir = create_extract_dir(file_path, base_dir)
    with zipfile.ZipFile(file_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)
    return extract_dir

def extract_7z_file(file_path, base_dir="upload_code"):
    """解压 .7z 文件到指定文件夹"""
    extract_dir = create_extract_dir(file_path, base_dir)
    with py7zr.SevenZipFile(file_path, mode='r') as z:
        z.extractall(path=extract_dir)
    return extract_dir

def get_file_type(file_name):
    """获取文件类型，特殊处理双重扩展名"""
    if file_name.endswith('.tar.gz'):
        return 'tar.gz'
    else:
        return file_name.split('.')[-1]

def split_filename_correctly(file_name):
    """正确拆分文件名和扩展名，处理双重扩展名"""
    if file_name.endswith('.tar.gz'):
        name_part = file_name[:-7]  # 去掉 .tar.gz
        ext_part = '.tar.gz'
    else:
        name_part, ext_part = os.path.splitext(file_name)
    return name_part, ext_part

def save_file_and_extract(file):
    upload_code_dir = 'upload_code'  # 相对于项目根目录
    # 确保目录存在
    if not os.path.exists(upload_code_dir):
        os.makedirs(upload_code_dir)
        
    file_name = file.filename
    
    # 使用新的文件类型检测函数
    file_type = get_file_type(file_name)
    if file_type not in ['tar', 'zip', '7z', 'tar.gz']:
        raise ValueError(f"不支持的文件类型: {file_type}")
    
    # 生成时间字符串
    time_str = datetime.now().strftime('%Y%m%d%H%M%S')

    # 使用新的文件名拆分函数
    name_part, ext_part = split_filename_correctly(file_name)
    # 拼接新文件名
    new_file_name = f"{name_part}_{time_str}{ext_part}"

    file_path = os.path.join(upload_code_dir, new_file_name)
    
    # 保存到指定目录
    file.save(file_path)
    
    # 进行文件解压
    if file_type in ['tar', 'tar.gz']:
        extract_dir = extract_tar_file(file_path)
    elif file_type == 'zip':
        extract_dir = extract_zip_file(file_path)
    elif file_type == '7z':
        extract_dir = extract_7z_file(file_path)
    
    return name_part, file_path, new_file_name, file_type, extract_dir

def analysis_code(extract_dir, source_name):
    # 创建OpenAI配置
    llm_config = RedKBSAnalyzer.create_llm_config(
        provider="openai",
        api_key=CHAT_MODEL_API_KEY,
        base_url=CHAT_URL,  # 可选
        model=CHAT_MODEL_NAME
    )
    
    # 创建分析器实例
    analyzer = RedKBSAnalyzer(llm_config=llm_config)
    
    # 分析项目
    result = analyzer.analyze_project(
        project_path=extract_dir,
        project_name=source_name,
        metadata={}
    )
    
    return result

def generate_code_chunk_description(code_data, file_name=None):
    """
    为代码块生成description
    
    Args:
        code_data: 代码内容
        file_name: 文件名（可选）
        
    Returns:
        description字符串，如果生成失败返回None
    """
    try:
        # 限制代码长度，避免prompt过长
        code_preview = code_data[:2000] if len(code_data) > 2000 else code_data
        
        user_prompt = f"""
请分析以下代码块的功能和作用，用简洁的中文描述（100字以内）：

文件: {file_name if file_name else "未知文件"}

代码:
```python
{code_preview}
```

请返回JSON格式：
{{"description": "代码功能描述"}}

注意：只返回JSON数据，不要返回其他内容。
"""
        
        client = OpenAI(
            api_key=CHAT_MODEL_API_KEY,
            base_url=CHAT_URL,
        )
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_prompt}
        ]
        
        response = client.chat.completions.create(
            model=CHAT_MODEL_NAME,
            messages=messages,
            response_format={'type': 'json_object'},
            temperature=0,
            stream=False
        )
        
        result = json.loads(response.choices[0].message.content)
        description = result.get("description", "")
        
        if description:
            logger.info(f"[generate_code_chunk_description] 成功生成description，长度={len(description)}")
            return description
        else:
            logger.warning(f"[generate_code_chunk_description] description为空")
            return None
            
    except Exception as e:
        logger.error(f"[generate_code_chunk_description] 生成description失败: {e}")
        return None

def handle_json_file(data, insert_number):
    behind_uuid = str(uuid.uuid4())
    software_uuid = f"software-{behind_uuid}"
    behind_file_uuid = "file-{}-{}"
    
    logger.info(f"[handle_json_file] 开始处理上传 JSON，生成软件 UUID={software_uuid}")
    # # 用户上传的和文件一样, 都是 0
    insert_number = 0
    
    # 先进行软件信息拼凑, embedding 信息后面再加入
    software_name = data["software_name"]
    software_description = data["software_summary"]
    logger.info(f"[handle_json_file] 软件名称={software_name}，描述长度={len(software_description) if software_description else 0}")
    
    # 拿取 tactic 列表
    # tactics_id_list = []
    tactics_id_list2 = []

    tactics_data = data.get("software_tactics")
    if tactics_data and tactics_data.get("status") == "success":
        tactics_list = tactics_data.get("tactics")  
        for single_tactic in tactics_list:
            # tactics_id_list.append({"tactic_id": single_tactic.get("tactic_id"), 
            #                         "tactic_evidence": single_tactic.get("evidence")})
            tactics_id_list2.append(single_tactic.get("tactic_id"))
    logger.info(f"[handle_json_file] 收到 {len(tactics_id_list2)} 个战术 ID: {tactics_id_list2}")
    
    # 插入 mitre_attack_code_software 节点
    with driver.session() as session:
        merge_query = """
        MERGE (software:BaseEntity:MitreAttackCodeSoftware {software_uuid: $software_uuid})
        ON CREATE SET
            software.name = $software_name,
            software.software_uuid = $software_uuid,
            software.description = $software_description,
            software.tactic_id_list = $tactic_id_list,
            software.insert_number = $insert_number
        RETURN elementId(software) AS software_element_id
        """
        result = session.run(merge_query, software_uuid=software_uuid, software_name=software_name, 
                    software_description=software_description, tactic_id_list=tactics_id_list2, 
                    insert_number=insert_number)
        software_element_id = result.single()["software_element_id"]
    logger.info(f"[handle_json_file] 完成软件节点 MERGE，elementId={software_element_id}")
        
    # 拿取 code_files 需要的数据
    # 获取所有 file 的 uuid
    all_file_ids = []
    # 获取所有 chunk element_id
    all_chunk_element_id = []
    
    software_files_data = data.get("software_files")
    if software_files_data:
        logger.info(f"[handle_json_file] 开始处理 {len(software_files_data)} 个文件")
        index = 0
        for single_file in software_files_data:
            file_name = single_file.get("file_name")
            file_uuid = behind_file_uuid.format(behind_uuid, index)
            all_file_ids.append(file_uuid)
            logger.info(f"[handle_json_file] 处理文件[{index}] name={file_name} uuid={file_uuid}")
            with driver.session() as session:
                merge_file_query = """
                MERGE (file:MitreAttackCodeSoftwareFile {file_uuid: $file_uuid})
                ON CREATE SET
                    file.name = $file_name,
                    file.software_uuid = $software_uuid,
                    file.insert_number = $insert_number,
                    file.file_uuid = $file_uuid
                RETURN file
                """
                session.run(merge_file_query, file_uuid=file_uuid, file_name=file_name, software_uuid=software_uuid, insert_number=insert_number)
            logger.info(f"[handle_json_file] 文件节点 MERGE 完成 uuid={file_uuid}")
            index += 1
            
            # 全量入库：处理文件的所有代码块
            all_chunks = single_file.get("chunks", [])
            code_data_total = single_file.get("file_technique")
            
            # 构建 chunk_number -> ttp 的映射，用于查找哪些代码块有技术
            ttp_map = {}
            if code_data_total and code_data_total.get("status") and code_data_total.get("result"):
                ttps = code_data_total.get("ttps", [])
                for ttp in ttps:
                    chunk_num = ttp.get("chunk_number")
                    if chunk_num is not None:
                        ttp_map[chunk_num] = ttp
                logger.info(f"[handle_json_file] 文件[{file_name}] 有 {len(ttps)} 个技术，{len(all_chunks)} 个代码块")
            
            if not all_chunks:
                logger.info(f"[handle_json_file] 文件[{file_name}] 没有代码块")
                continue
            
            # 遍历所有代码块，全量入库
            code_index = 0
            for chunk in all_chunks:
                chunk_number = chunk.get("chunk_number", code_index)
                code_data = chunk.get("code", "")
                
                # 跳过空代码块
                if not code_data or not str(code_data).strip():
                    logger.info(f"[handle_json_file] 代码块[{chunk_number}] 跳过，原因: code 为空")
                    code_index += 1
                    continue
                
                # 为所有代码块生成description
                description = generate_code_chunk_description(code_data, file_name)
                
                # 从 ttp_map 中获取与当前代码块关联的技术信息（保留技术关联信息）
                # 注释掉原有的description获取逻辑，改为为所有代码块生成description
                # # 从 ttp_map 中获取与当前代码块关联的技术信息
                # ttp = ttp_map.get(chunk_number)
                # if ttp:
                #     # 使用 LLM 返回的代码相关性描述作为 description
                #     description = ttp.get("code_relevance") or ttp.get("name")
                #     technique_id = ttp.get("technique_id")
                #     have_code = ttp.get("have_code", False)
                #     relevance = ttp.get("relevance")
                # else:
                #     description = None
                #     technique_id = None
                #     have_code = False
                #     relevance = None
                
                # 从 ttp_map 中获取技术关联信息（但不覆盖description）
                ttp = ttp_map.get(chunk_number)
                if ttp:
                    technique_id = ttp.get("technique_id")
                    have_code = ttp.get("have_code", False)
                    relevance = ttp.get("relevance")
                else:
                    technique_id = None
                    have_code = False
                    relevance = None
                
                chunk_start_line = chunk.get("start_line", 0)
                chunk_end_line = chunk.get("end_line", 0)
                code_uuid = "code-{}-{}-{}-{}".format(behind_uuid, index, chunk_number, code_index)
                
                logger.info(
                    f"[handle_json_file] 代码块[{chunk_number}] 入库，technique={technique_id}, "
                    f"行号={chunk_start_line}-{chunk_end_line}"
                )
                
                with driver.session() as session:
                    merge_code_query = """
                    MERGE (code:BaseEntity:MitreAttackCodeSoftwareCodeChunk {code_uuid: $code_uuid})
                    ON CREATE SET
                        code.code_uuid = $code_uuid,
                        code.file_uuid = $file_uuid,
                        code.insert_number = $insert_number,
                        code.code_data = $code_data,
                        code.description = $description,
                        code.technique_id = $technique_id,
                        code.chunk_start_line = $chunk_start_line,
                        code.chunk_end_line = $chunk_end_line,
                        code.have_code = $have_code,
                        code.relevance = $relevance
                    RETURN elementId(code) as chunk_element_id
                    """
                    result2 = session.run(
                        merge_code_query,
                        code_uuid=code_uuid,
                        file_uuid=file_uuid,
                        insert_number=insert_number,
                        code_data=code_data,
                        description=description,
                        technique_id=technique_id,
                        chunk_start_line=chunk_start_line,
                        chunk_end_line=chunk_end_line,
                        have_code=have_code,
                        relevance=relevance,
                    )
                    chunk_element_id = result2.single()["chunk_element_id"]
                    all_chunk_element_id.append(chunk_element_id)
                logger.info(f"[handle_json_file] 代码块节点 MERGE 成功 code_uuid={code_uuid}, elementId={chunk_element_id}")
                code_index += 1
    else:
        logger.info("[handle_json_file] 未提供 software_files 数据")
    all_chunk_element_id.append(software_element_id)
    logger.info(f"[handle_json_file] 总计文件UUID {len(all_file_ids)} 个，代码块节点 {len(all_chunk_element_id) - 1} 个")
    return all_file_ids, software_uuid, all_chunk_element_id

def send_request_embedding(text):
    # text 形如 [element_id, description]
    texts = [text[1]]
    texts_ids = [text[0]]
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": EMBEDDING_API_KEY,
    }
    body = {"texts": texts}
    try:
        response = requests.post(url=EMBEDDING_URL, headers=headers, json=body)
        if response.status_code == 200:
            data = response.json()
            embeddings = data.get("embeddings")
            if embeddings:
                return texts_ids, embeddings
            logger.info(f"[send_request_embedding] Stella 返回为空 elementId={texts_ids}")
            return None
        logger.info(f"[send_request_embedding] Stella 请求失败 status={response.status_code}, body={response.text}")
        return None
    except Exception as e:
        logger.info(f"[send_request_embedding] Stella 请求异常: {e}")
        return None

def add_embedding_data_to_neo4j():
    """
    获取 Neo4j 中的 code_data，生成 code_embedding，并写回节点。
    description 仅保存文本，不再生成 embedding。
    """
    with driver.session() as session:
        search_code_query = """
        MATCH (n:MitreAttackCodeSoftwareCodeChunk)
        WHERE n.code_data IS NOT NULL
          AND n.code_embedding IS NULL
        RETURN elementId(n) AS element_id,
               n.code_data AS code_data,
               n.description AS description
        """
        code_chunks = list(session.run(search_code_query))
    logger.info(f"[add_embedding_data_to_neo4j] 待处理代码块 {len(code_chunks)} 条")
    
    processed_ids = []
    for record in code_chunks:
        element_id = record["element_id"]
        code_data = record["code_data"]
        description = record["description"]
        if not code_data:
            logger.info(f"[add_embedding_data_to_neo4j] code_data 为空，跳过 elementId={element_id}")
            continue
        
        embedding_result = send_request_embedding([element_id, code_data])
        if not embedding_result:
            logger.info(f"[add_embedding_data_to_neo4j] code_data 向量化失败，跳过 elementId={element_id}")
            continue
        
        texts_ids, embeddings_list = embedding_result
        if not texts_ids or not embeddings_list:
            logger.info(f"[add_embedding_data_to_neo4j] 向量结果为空，跳过 elementId={element_id}")
            continue
        
        code_embedding = embeddings_list[0]
        with driver.session() as session:
            update_query = """
            MATCH (n)
            WHERE elementId(n) = $element_id
            SET n.code_embedding = $code_embedding,
                n.description = coalesce(n.description, $description)
            """
            session.run(
                update_query,
                element_id=element_id,
                code_embedding=code_embedding,
                description=description,
            )
        processed_ids.append(element_id)
        logger.info(f"[add_embedding_data_to_neo4j] 更新 code_embedding elementId={element_id}")
    
    return processed_ids

def add_relateship(all_file_ids, software_uuid, insert_number):
    insert_number = 0
    """添加三种节点的关系：软件-文件、文件-代码片段、代码片段-技术"""
    with driver.session() as session:
        # 1. 软件节点和文件节点的关系
        for file_uuid in all_file_ids:
            # 建立软件节点和文件节点的双向关系
            merge_software_file_query = """
            MATCH (software:MitreAttackCodeSoftware {software_uuid: $software_uuid}), (file:MitreAttackCodeSoftwareFile {file_uuid: $file_uuid})
            MERGE (software)-[r:CODE_SOFTWARE_HAS_CODE_SOFTWARE_FILE]->(file)
            ON CREATE SET r.insert_number = $insert_number
            MERGE (file)-[r2:CODE_SOFTWARE_FILE_BELONG_CODE_SOFTWARE]->(software)
            ON CREATE SET r2.insert_number = $insert_number
            """
            session.run(merge_software_file_query, software_uuid=software_uuid, file_uuid=file_uuid, insert_number=insert_number)
            
            # 2. 文件节点和代码片段节点的关系
            merge_file_code_query = """
            MATCH (file:MitreAttackCodeSoftwareFile {file_uuid: $file_uuid}), (code:MitreAttackCodeSoftwareCodeChunk {file_uuid: $file_uuid})
            MERGE (file)-[r:CODE_SOFTWARE_FILE_HAS_CODE_SOFTWARE_CODE_CHUNK]->(code)
            ON CREATE SET r.insert_number = $insert_number
            MERGE (code)-[r2:CODE_SOFTWARE_CODE_CHUNK_BELONG_CODE_SOFTWARE_FILE]->(file)
            ON CREATE SET r2.insert_number = $insert_number
            """
            session.run(merge_file_code_query, file_uuid=file_uuid, insert_number=insert_number)
        # 3. 代码片段节点和技术节点的关系
        for file_uuid in all_file_ids:
            # 查询该文件下的所有代码片段及其技术 ID
            search_code_techniques_query = """
            MATCH (code:MitreAttackCodeSoftwareCodeChunk {file_uuid: $file_uuid})
            RETURN code.code_uuid AS code_uuid, code.technique_id AS technique_id
            """
            code_techniques = session.run(search_code_techniques_query, file_uuid=file_uuid)
            
            # 建立代码片段节点和技术节点的关系（只对有technique_id的代码块建立关系）
            for code_tech_record in code_techniques:
                code_uuid = code_tech_record["code_uuid"]
                technique_id = code_tech_record["technique_id"]
                # 跳过没有technique_id的代码块
                if not technique_id:
                    continue
                merge_code_technique_query = """
                MATCH (code:MitreAttackCodeSoftwareCodeChunk {code_uuid: $code_uuid}), (tech:MitreAttackTechnique {attack_id: $technique_id})
                MERGE (code)-[r:CODE_SOFTWARE_CODE_CHUNK_BELONG_TECHNIQUE]->(tech)
                ON CREATE SET r.insert_number = $insert_number
                MERGE (tech)-[r2:TECHNIQUE_HAS_CODE_SOFTWARE_CODE_CHUNK]->(code)
                ON CREATE SET r2.insert_number = $insert_number
                """
                session.run(merge_code_technique_query, code_uuid=code_uuid, technique_id=technique_id, insert_number=insert_number)
        # 4. 软件节点和战术的关系
        search_software_query = """
            MATCH (software:MitreAttackCodeSoftware {software_uuid: $software_uuid})
            RETURN software.tactic_id_list AS tactic_id_list
        """
        software_tactics = session.run(search_software_query, software_uuid=software_uuid)
        
        for tactic_record in software_tactics:
            tactic_id_list = tactic_record["tactic_id_list"]
            for tactic_id in tactic_id_list:
                # 建立软件节点和战术节点的双向关系
                merge_software_tactic_query = """
                MATCH (software:MitreAttackCodeSoftware {software_uuid: $software_uuid}), (tactic:MitreAttackTactic {attack_id: $tactic_id})
                MERGE (software)-[r:CODE_SOFTWARE_BELONG_TACTIC]->(tactic)
                ON CREATE SET r.insert_number = $insert_number
                MERGE (tactic)-[r2:TACTIC_HAS_CODE_SOFTWARE]->(software)
                ON CREATE SET r2.insert_number = $insert_number
                """
                session.run(merge_software_tactic_query, software_uuid=software_uuid, tactic_id=tactic_id, insert_number=insert_number)

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
    
    # 查询指定 ID 的 BaseEntity 节点
    query = """
    UNWIND $element_ids AS element_id
    MATCH (n:MitreAttackCodeSoftwareCodeChunk)
    WHERE elementId(n) = element_id
      AND n.code_embedding IS NOT NULL
    RETURN elementId(n) as element_id,
           n.code_data as code_data,
           n.description as description,
           n.code_embedding as code_embedding
    """
    
    try:
        with driver.session() as session:
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
            code_data = record["code_data"]
            description = record["description"]
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

def handle_code(source_name, file_path, file_name, file_type, extract_dir, insert_number):
    result = analysis_code(extract_dir, source_name)
    
    try:
        all_file_ids, software_uuid, all_embedding_element_id = handle_json_file(result.to_dict(), insert_number)
        add_embedding_data_to_neo4j()
        add_relateship(all_file_ids, software_uuid, insert_number)
        
        # 最后添加 milvus
        add_milvus(all_embedding_element_id)        
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
