import os
import uuid
import json
import tarfile
import zipfile
import py7zr
import pathlib
from datetime import datetime
from elasticsearch import Elasticsearch
import requests
from red_kbs_analyzer import RedKBSAnalyzer
from neo4j import GraphDatabase
from setting import (CHAT_MODEL_API_KEY, CHAT_MODEL_NAME, CHAT_URL, EMBEDDING_URL, ES_AUTH_NAME, 
                     ES_AUTH_PASSWORD, ES_INDEX, ES_PORT, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, ES_HOST, )

AUTH = (NEO4J_USER, NEO4J_PASSWORD)
driver = GraphDatabase.driver(NEO4J_URI, auth=AUTH)

es = Elasticsearch(
                hosts=[{"host": ES_HOST, "port": ES_PORT, "scheme": "http"}],
                basic_auth=(ES_AUTH_NAME, ES_AUTH_PASSWORD),
            )

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

def handle_json_file(data):
    behind_uuid = str(uuid.uuid4())
    software_uuid = f"software-{behind_uuid}"
    behind_file_uuid = "file-{}-{}"
    
    # 用户上传的和文件一样, 都是 0
    insert_number = 0
    
    # 先进行软件信息拼凑, embedding 信息后面再加入
    software_name = data["software_name"]
    software_description = data["software_summary"]
    
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
        
    # 拿取 code_files 需要的数据
    # 获取所有 file 的 uuid
    all_file_ids = []
    # 获取所有 chunk element_id
    all_chunk_element_id = []
    
    software_files_data = data.get("software_files")
    if software_files_data:
        index = 0
        for single_file in software_files_data:
            file_name = single_file.get("file_name")
            file_uuid = behind_file_uuid.format(behind_uuid, index)
            all_file_ids.append(file_uuid)
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
            index += 1
            
            # 现在来弄代码快
            code_data_total = single_file.get("file_technique")
            if code_data_total:
                if code_data_total.get("status") and code_data_total.get("result"):
                    ttps = code_data_total.get("ttps")
                    if ttps:
                        code_index = 0
                        for code_item in ttps:
                            chunk_number = code_item.get("chunk_number")
                            code_uuid = "code-{}-{}-{}-{}".format(behind_uuid, index, chunk_number, code_index)
                            if code_item.get("have_code") and code_item.get("relevance") >= 0.9:
                                description = code_item.get("code_relevance")
                                code_data = code_item.get("chunk_code")
                                technique_id = code_item.get("technique_id")
                                chunk_start_line = code_item.get("chunk_start_line")
                                chunk_end_line = code_item.get("chunk_end_line")
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
                                        code.chunk_end_line = $chunk_end_line
                                    RETURN elementId(code) as chunk_element_id
                                    """
                                    result2 = session.run(merge_code_query, code_uuid=code_uuid, file_uuid=file_uuid, insert_number=insert_number, 
                                                code_data=code_data, description=description, technique_id=technique_id, 
                                                chunk_start_line=chunk_start_line, chunk_end_line=chunk_end_line)
                                    chunk_element_id = result2.single()["chunk_element_id"]
                                    all_chunk_element_id.append(chunk_element_id)
                            code_index += 1
    all_chunk_element_id.append(software_element_id)
    return all_file_ids, software_uuid, all_chunk_element_id

def send_request_embedding(text):
    texts = []
    texts_ids = [] 
    texts.append(text[1])
    texts_ids.append(text[0])
    
    url = EMBEDDING_URL
    # 构建请求体
    req_body = {
        "texts": texts
    }
    # 设置请求头
    headers = {
        "Content-Type": "application/json"
    }
    try:
        # 发送POST请求
        response = requests.post(url=url, headers=headers, json=req_body)
        # 检查响应状态
        if response.status_code == 200:
            data = response.json()
            embedding1 = data['embeddings'][0]

            embeddings_list = [embedding1]
            return texts_ids, embeddings_list
        else:
            # print(f"\n请求失败! 状态码: {response.status_code}")
            # print(f"错误信息: {response.text}")
            return None
    except Exception as e:
        # print(f"\n发生错误: {str(e)}")
        return None

def add_embedding_data_to_neo4j():
    # 两种标签的结点需要进行embedding
    with driver.session() as session:
        # 查询 MitreAttackCodeSoftware 节点
        search_software_query = """
        MATCH (n:MitreAttackCodeSoftware)
        WHERE n.description_embedding IS NULL
        RETURN elementId(n) AS element_id, n.description AS description
        """
        software_data = session.run(search_software_query)
        total_list = []
        for software_record in software_data:
            element_id = software_record["element_id"]
            description = software_record["description"]
            if not description:
                continue
            total_list.append([element_id, description])
        
        # 查询另一种节点（假设标签为 AnotherNodeType）
        search_another_query = """
        MATCH (n:MitreAttackCodeSoftwareCodeChunk)
        WHERE n.description_embedding IS NULL
        RETURN elementId(n) AS element_id, n.description AS description
        """
        another_data = session.run(search_another_query)
        for another_record in another_data:
            element_id = another_record["element_id"]
            description = another_record["description"]
            if not description:
                continue
            total_list.append([element_id, description])
        # 批量处理 embedding
        for i in total_list:
            texts_ids, embeddings_list = send_request_embedding(i)
            if texts_ids and embeddings_list:
                for index, element_id2 in enumerate(texts_ids):
                    with driver.session() as session:
                        # 更新节点 embedding
                        update_query = """
                        MATCH (n)
                        WHERE elementId(n) = $element_id
                        SET n.description_embedding = $embedding
                        """
                        session.run(update_query, element_id=element_id2, embedding=embeddings_list[index])

def add_relateship(all_file_ids, software_uuid):
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
            MATCH (file:MitreAttackCodeSoftwareFile {file_uuid: $file_uuid})
            RETURN file.code_uuid AS code_uuid, file.technique_id AS technique_id
            """
            code_techniques = session.run(search_code_techniques_query, file_uuid=file_uuid)
            
            # 建立代码片段节点和技术节点的关系
            for code_tech_record in code_techniques:
                code_uuid = code_tech_record["code_uuid"]
                technique_id = code_tech_record["technique_id"]
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
def add_es(all_embedding_element_id):
    # 查询指定 ID 的 BaseEntity 节点
    query = """
    UNWIND $element_ids AS element_id
    MATCH (n:BaseEntity)
    WHERE elementId(n) = element_id AND n.description IS NOT NULL
    RETURN elementId(n) as element_id, n.description as description, n.description_embedding as description_embedding
    """
    
    with driver.session() as session:
        result = session.run(query, element_ids=all_embedding_element_id)
        all_records = list(result)
    
    success_count = 0
    error_count = 0
    index_name = ES_INDEX
    
    # 开始插入数据
    for record in all_records:
        try:
            # 准备文档数据
            doc = {
                "neo4j_id": record["element_id"],
                "description": record["description"],
                "description_embedding": record["description_embedding"]
            }
            
            # 将文档索引到 ES
            response = es.index(
                index=index_name,
                document=doc,
                id=record["element_id"]  # 使用 neo4j 的 ID 作为文档 ID
            )
            
            success_count += 1
            
            # 每100条打印一次进度
            if success_count % 100 == 0:
                print(f"已成功导入{success_count}条记录...")
                
        except Exception as e:
            error_count += 1
            print(f"导入记录失败: {str(e)}")
            
    print(f"导入完成！成功: {success_count}, 失败: {error_count}")

def handle_code(source_name, file_path, file_name, file_type, extract_dir):
    result = analysis_code(extract_dir, source_name)
    
    try:
        all_file_ids, software_uuid, all_embedding_element_id = handle_json_file(result.to_dict())
        add_embedding_data_to_neo4j()
        add_relateship(all_file_ids, software_uuid)
        
        # 最后添加 es
        add_es(all_embedding_element_id)        
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
