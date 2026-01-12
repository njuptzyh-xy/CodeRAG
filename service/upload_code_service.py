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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from setting import (
    CHAT_MODEL_API_KEY,
    CHAT_MODEL_NAME,
    CHAT_URL,
    EMBEDDING_URL,
    EMBEDDING_API_KEY,
    OPENAI_URL,
    OPENAI_MODEL_NAME,
    OPENAI_TEMPERATURE,
    OPENAI_MAX_TOKENS,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    NEO4J_DATABASE,
    MILVUS_HOST,
    MILVUS_PORT,
    MILVUS_USER,
    MILVUS_PASSWORD,
    MILVUS_DB_NAME,
    MILVUS_COLLECTION,
    MILVUS_CONSISTENCY_LEVEL,
    MILVUS_SECURE,
)
from gitea_service import upload_to_gitea

# 临时修改：由于磁盘空间不足，将路径改为 /root/workspace/ch 下
# 原代码（等磁盘空间足够后改回）：
# UPLOAD_CODE_DIR = 'upload_code'  # 相对于项目根目录
# 临时路径
UPLOAD_CODE_DIR = "upload_code"

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
    print(
        f"连接参数: host={MILVUS_HOST}, port={MILVUS_PORT}, user={MILVUS_USER}, db={MILVUS_DB_NAME}"
    )


def get_filename_without_extension(file_path):
    """获取文件名（不含扩展名），特殊处理 .tar.gz"""
    # 提取文件名（去掉路径）
    file_name = os.path.basename(file_path)

    # 处理 .tar.gz
    if file_name.endswith(".tar.gz"):
        return file_name[:-7]  # 去掉 .tar.gz
    else:
        return pathlib.Path(file_name).stem


def create_extract_dir(file_path, base_dir=UPLOAD_CODE_DIR):
    """根据压缩包文件名创建解压目录"""
    filename = get_filename_without_extension(file_path)
    extract_dir = os.path.join(base_dir, filename)
    os.makedirs(extract_dir, exist_ok=True)
    return extract_dir


def extract_tar_file(file_path, base_dir=UPLOAD_CODE_DIR):
    """解压 .tar 或 .tar.gz 文件到指定文件夹"""
    extract_dir = create_extract_dir(file_path, base_dir)
    with tarfile.open(file_path, "r") as tar:
        tar.extractall(path=extract_dir, filter="data")
    return extract_dir


def extract_zip_file(file_path, base_dir=UPLOAD_CODE_DIR):
    """解压 .zip 文件到指定文件夹"""
    extract_dir = create_extract_dir(file_path, base_dir)
    with zipfile.ZipFile(file_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)
    return extract_dir


def extract_7z_file(file_path, base_dir=UPLOAD_CODE_DIR):
    """解压 .7z 文件到指定文件夹"""
    extract_dir = create_extract_dir(file_path, base_dir)
    with py7zr.SevenZipFile(file_path, mode="r") as z:
        z.extractall(path=extract_dir)
    return extract_dir


def get_file_type(file_name):
    """获取文件类型，特殊处理双重扩展名"""
    if file_name.endswith(".tar.gz"):
        return "tar.gz"
    else:
        return file_name.split(".")[-1]


def split_filename_correctly(file_name):
    """正确拆分文件名和扩展名，处理双重扩展名"""
    if file_name.endswith(".tar.gz"):
        name_part = file_name[:-7]  # 去掉 .tar.gz
        ext_part = ".tar.gz"
    else:
        name_part, ext_part = os.path.splitext(file_name)
    return name_part, ext_part


def save_file_and_extract(file):
    # 临时修改：由于磁盘空间不足，将路径改为 /root/workspace/ch 下
    # 原代码（等磁盘空间足够后改回）：
    # upload_code_dir = 'upload_code'  # 相对于项目根目录
    # # 确保目录存在
    # if not os.path.exists(upload_code_dir):
    #     os.makedirs(upload_code_dir)

    # 临时路径
    upload_code_dir = UPLOAD_CODE_DIR
    # 确保目录存在
    if not os.path.exists(upload_code_dir):
        os.makedirs(upload_code_dir)

    file_name = file.filename

    # 使用新的文件类型检测函数
    file_type = get_file_type(file_name)
    if file_type not in ["tar", "zip", "7z", "tar.gz"]:
        raise ValueError(f"不支持的文件类型: {file_type}")

    # 生成时间字符串
    time_str = datetime.now().strftime("%Y%m%d%H%M%S")

    # 使用新的文件名拆分函数
    name_part, ext_part = split_filename_correctly(file_name)
    # 拼接新文件名
    new_file_name = f"{name_part}_{time_str}{ext_part}"

    file_path = os.path.join(upload_code_dir, new_file_name)

    # 保存到指定目录
    file.save(file_path)

    # 进行文件解压
    extract_dir = ""
    if file_type in ["tar", "tar.gz"]:
        extract_dir = extract_tar_file(file_path)
    elif file_type == "zip":
        extract_dir = extract_zip_file(file_path)
    elif file_type == "7z":
        extract_dir = extract_7z_file(file_path)

    return name_part, file_path, new_file_name, file_type, extract_dir


def analysis_code(extract_dir, source_name):
    # 创建OpenAI配置
    llm_config = RedKBSAnalyzer.create_llm_config(
        provider="openai",
        api_key=CHAT_MODEL_API_KEY,
        base_url=CHAT_URL,  # 可选
        model=CHAT_MODEL_NAME,
    )

    # 创建分析器实例
    analyzer = RedKBSAnalyzer(llm_config=llm_config)

    # 分析项目
    result = analyzer.analyze_project(
        project_path=extract_dir, project_name=source_name, metadata={}
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
            api_key="not-needed",
            base_url=OPENAI_URL,
        )

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_prompt},
        ]

        response = client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
            stream=False,
        )

        result = json.loads(response.choices[0].message.content)
        description = result.get("description", "")

        if description:
            logger.info(
                f"[generate_code_chunk_description] 成功生成description，长度={len(description)}"
            )
            return description
        else:
            logger.warning(f"[generate_code_chunk_description] description为空")
            return None

    except Exception as e:
        logger.error(f"[generate_code_chunk_description] 生成description失败: {e}")
        return None


def handle_json_file(data, insert_number,repo_url):
    behind_uuid = str(uuid.uuid4())
    software_uuid = f"software-{behind_uuid}"
    behind_file_uuid = "file-{}-{}"

    logger.info(f"[handle_json_file] 开始处理上传 JSON，生成软件 UUID={software_uuid}")
    # # 用户上传的和文件一样, 都是 0
    insert_number = 0

    # 先进行软件信息拼凑, embedding 信息后面再加入
    software_name = data["software_name"]
    software_description = data["software_summary"]
    logger.info(
        f"[handle_json_file] 软件名称={software_name}，描述长度={len(software_description) if software_description else 0}"
    )

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
    logger.info(
        f"[handle_json_file] 收到 {len(tactics_id_list2)} 个战术 ID: {tactics_id_list2}"
    )

    # 插入 mitre_attack_code_software 节点
    with driver.session(**SESSION_KWARGS) as session:
        merge_query = """
        MERGE (software:BaseEntity:MitreAttackCodeSoftware {software_uuid: $software_uuid})
        ON CREATE SET
            software.name = $software_name,
            software.software_uuid = $software_uuid,
            software.description = $software_description,
            software.tactic_id_list = $tactic_id_list,
            software.insert_number = $insert_number,
            software.repo_url = $repo_url
        RETURN elementId(software) AS software_element_id
        """
        result = session.run(
            merge_query,
            software_uuid=software_uuid,
            software_name=software_name,
            software_description=software_description,
            tactic_id_list=tactics_id_list2,
            insert_number=insert_number,
            repo_url=repo_url,
        )
        software_element_id = result.single()["software_element_id"]
    logger.info(
        f"[handle_json_file] 完成软件节点 MERGE，elementId={software_element_id}"
    )

    # 拿取 code_files 需要的数据
    # 获取所有 file 的 uuid
    all_file_ids = []
    # 获取所有 chunk element_id（仅 Neo4j 中的）
    all_chunk_element_id = []
    # 新增：保存所有代码块信息（用于 Milvus），包括没有 technique_id 的
    all_chunks_for_milvus = []

    software_files_data = data.get("software_files")
    if software_files_data:
        logger.info(f"[handle_json_file] 开始处理 {len(software_files_data)} 个文件")
        index = 0
        for single_file in software_files_data:
            file_name = single_file.get("file_name")
            file_uuid = behind_file_uuid.format(behind_uuid, index)
            all_file_ids.append(file_uuid)
            logger.info(
                f"[handle_json_file] 处理文件[{index}] name={file_name} uuid={file_uuid}"
            )
            with driver.session(**SESSION_KWARGS) as session:
                merge_file_query = """
                MERGE (file:MitreAttackCodeSoftwareFile {file_uuid: $file_uuid})
                ON CREATE SET
                    file.name = $file_name,
                    file.software_uuid = $software_uuid,
                    file.insert_number = $insert_number,
                    file.file_uuid = $file_uuid,
                    file.repo_url = $repo_url
                RETURN file
                """
                session.run(
                    merge_file_query,
                    file_uuid=file_uuid,
                    file_name=file_name,
                    software_uuid=software_uuid,
                    insert_number=insert_number,
                    repo_url=repo_url,
                )
            logger.info(f"[handle_json_file] 文件节点 MERGE 完成 uuid={file_uuid}")
            index += 1

            # 处理文件的所有代码块（用于筛选和 Milvus）
            all_chunks = single_file.get("chunks", [])
            code_data_total = single_file.get("file_technique")

            # 构建 chunk_number -> ttp 的映射，用于查找哪些代码块有技术
            ttp_map = {}
            if (
                code_data_total
                and code_data_total.get("status")
                and code_data_total.get("result")
            ):
                ttps = code_data_total.get("ttps", [])
                for ttp in ttps:
                    chunk_num = ttp.get("chunk_number")
                    if chunk_num is not None:
                        ttp_map[chunk_num] = ttp
                logger.info(
                    f"[handle_json_file] 文件[{file_name}] 有 {len(ttps)} 个技术，{len(all_chunks)} 个代码块"
                )

            if not all_chunks:
                logger.info(f"[handle_json_file] 文件[{file_name}] 没有代码块")
                continue

            # 第一步：准备所有代码块数据（用于后续筛选和 Milvus）
            all_chunks_data = []
            code_index = 0
            for chunk in all_chunks:
                chunk_number = chunk.get("chunk_number", code_index)
                code_data = chunk.get("code", "")

                # 跳过空代码块
                if not code_data or not str(code_data).strip():
                    logger.info(
                        f"[handle_json_file] 代码块[{chunk_number}] 跳过，原因: code 为空"
                    )
                    code_index += 1
                    continue

                # 从 ttp_map 中获取技术关联信息
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
                code_uuid = "code-{}-{}-{}-{}".format(
                    behind_uuid, index, chunk_number, code_index
                )

                chunk_info = {
                    "code_uuid": code_uuid,
                    "code_data": code_data,
                    "chunk_number": chunk_number,
                    "chunk_start_line": chunk_start_line,
                    "chunk_end_line": chunk_end_line,
                    "technique_id": technique_id,
                    "have_code": have_code,
                    "relevance": relevance,
                    "code_index": code_index,
                    "file_uuid": file_uuid,
                    "file_name": file_name,
                    # 新增：所属软件名称，用于写入 Milvus 的 soft_name 字段
                    "soft_name": software_name,
                }
                all_chunks_data.append(chunk_info)
                code_index += 1

            if not all_chunks_data:
                logger.info(
                    f"[handle_json_file] 文件[{file_name}] 没有有效代码块需要处理"
                )
                continue

            # 第二步：区分有/无技术的代码块（用于日志统计）
            # 只保留 have_code == true 且 relevance >= 0.9 的代码块用于生成 description
            chunks_with_technique = [
                c
                for c in all_chunks_data
                if c["technique_id"] is not None
                and c.get("have_code", False) == True
                and c.get("relevance") is not None
                and c.get("relevance", 0) >= 0.9
            ]
            chunks_without_technique = [
                c for c in all_chunks_data if c["technique_id"] is None
            ]
            chunks_with_low_relevance = [
                c
                for c in all_chunks_data
                if c["technique_id"] is not None
                and (c.get("have_code", False) != True or c.get("relevance", 0) < 0.9)
            ]
            logger.info(
                f"[handle_json_file] 文件[{file_name}] 有 {len(chunks_with_technique)} 个代码块满足条件（have_code=true, relevance>=0.9）将生成description，"
                f"{len(chunks_with_low_relevance)} 个代码块关联技术但相关性不足，"
                f"{len(chunks_without_technique)} 个代码块无技术，将全部插入 Neo4j"
            )

            # 第三步：并发生成 description（仅对满足条件的代码块：have_code=true 且 relevance>=0.9）
            if chunks_with_technique:
                logger.info(
                    f"[handle_json_file] 开始并发生成 {len(chunks_with_technique)} 个代码块的 description"
                )
                with ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_index = {
                        executor.submit(
                            generate_code_chunk_description,
                            chunk_info["code_data"],
                            file_name,
                        ): i
                        for i, chunk_info in enumerate(chunks_with_technique)
                    }

                    descriptions = [None] * len(chunks_with_technique)
                    for future in as_completed(future_to_index):
                        idx = future_to_index[future]
                        try:
                            descriptions[idx] = future.result()
                        except Exception as e:
                            logger.error(
                                f"[handle_json_file] 代码块[{chunks_with_technique[idx]['chunk_number']}] 生成description失败: {e}"
                            )
                            descriptions[idx] = None

                    for i, desc in enumerate(descriptions):
                        chunks_with_technique[i]["description"] = desc

                logger.info(f"[handle_json_file] description 生成完成")

                # 将已生成的 description 同步到 all_chunks_data 中对应的代码块
                description_map = {
                    c["code_uuid"]: c.get("description") for c in chunks_with_technique
                }
                for chunk_info in all_chunks_data:
                    code_uuid = chunk_info["code_uuid"]
                    if code_uuid in description_map:
                        chunk_info["description"] = description_map[code_uuid]
                    else:
                        # 没有技术的代码块，description 为 None（不生成描述）
                        chunk_info["description"] = None
            else:
                # 没有任何关联技术的代码块，全都没有 description
                for chunk_info in all_chunks_data:
                    chunk_info["description"] = None

            # 第四步：为所有代码块生成 embedding（有/无技术都生成）
            logger.info(
                f"[handle_json_file] 开始为 {len(all_chunks_data)} 个代码块生成 embedding"
            )
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_index = {
                    executor.submit(
                        send_request_embedding,
                        [chunk_info["code_uuid"], chunk_info["code_data"]],
                    ): i
                    for i, chunk_info in enumerate(all_chunks_data)
                }

                embeddings = [None] * len(all_chunks_data)
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        result = future.result()
                        if result:
                            texts_ids, embeddings_list = result
                            if embeddings_list:
                                embeddings[idx] = embeddings_list[0]
                    except Exception as e:
                        logger.error(
                            f"[handle_json_file] 代码块[{all_chunks_data[idx]['chunk_number']}] 生成embedding失败: {e}"
                        )
                        embeddings[idx] = None

                for i, emb in enumerate(embeddings):
                    all_chunks_data[i]["code_embedding"] = emb

            logger.info(f"[handle_json_file] embedding 生成完成")

            # 第五步：批量插入 Neo4j（插入所有代码块，包含 embedding）
            with driver.session(**SESSION_KWARGS) as session:
                batch_merge_query = """
                UNWIND $chunks AS chunk
                MERGE (code:BaseEntity:MitreAttackCodeSoftwareCodeChunk {code_uuid: chunk.code_uuid})
                ON CREATE SET
                    code.code_uuid = chunk.code_uuid,
                    code.file_uuid = $file_uuid,
                    code.insert_number = $insert_number,
                    code.code_data = chunk.code_data,
                    code.description = chunk.description,
                    code.technique_id = chunk.technique_id,
                    code.chunk_start_line = chunk.chunk_start_line,
                    code.chunk_end_line = chunk.chunk_end_line,
                    code.have_code = chunk.have_code,
                    code.relevance = chunk.relevance,
                    code.code_embedding = chunk.code_embedding,
                    code.repo_url = $repo_url
                RETURN elementId(code) as chunk_element_id, chunk.code_uuid as code_uuid
                """

                chunks_data = [
                    {
                        "code_uuid": c["code_uuid"],
                        "code_data": c["code_data"],
                        "description": c.get(
                            "description"
                        ),  # 有技术的为字符串，无技术为 None
                        "technique_id": c["technique_id"],  # 无技术为 None
                        "chunk_start_line": c["chunk_start_line"],
                        "chunk_end_line": c["chunk_end_line"],
                        "have_code": c["have_code"],
                        "relevance": c["relevance"],
                        "code_embedding": c.get(
                            "code_embedding"
                        ),  # 所有代码块都有 embedding（可能为 None）
                    }
                    for c in all_chunks_data
                ]

                result2 = session.run(
                    batch_merge_query,
                    chunks=chunks_data,
                    file_uuid=file_uuid,
                    insert_number=insert_number,
                    repo_url=repo_url,
                )

                # 创建 code_uuid -> elementId 的映射，用于同步到 all_chunks_data
                element_id_map = {}
                for record in result2:
                    chunk_element_id = record["chunk_element_id"]
                    code_uuid = record["code_uuid"]
                    element_id_map[code_uuid] = chunk_element_id
                    all_chunk_element_id.append(chunk_element_id)
                    logger.info(
                        f"[handle_json_file] 代码块节点 MERGE 成功 code_uuid={code_uuid}, "
                        f"elementId={chunk_element_id}"
                    )

                logger.info(
                    f"[handle_json_file] 批量插入 {len(all_chunks_data)} 个代码块到 Neo4j 完成"
                )

            # 为所有代码块同步 elementId，用于 Milvus
            for chunk_info in all_chunks_data:
                code_uuid = chunk_info["code_uuid"]
                chunk_info["element_id"] = element_id_map.get(code_uuid)

            # 保存所有代码块信息（用于 Milvus），描述、elementId 和 embedding 已同步
            all_chunks_for_milvus.extend(all_chunks_data)
    else:
        logger.info("[handle_json_file] 未提供 software_files 数据")

    all_chunk_element_id.append(software_element_id)
    logger.info(
        f"[handle_json_file] 总计文件UUID {len(all_file_ids)} 个，Neo4j代码块节点 {len(all_chunk_element_id) - 1} 个，Milvus代码块 {len(all_chunks_for_milvus)} 个"
    )

    # 返回 Neo4j 的 element_id 和所有代码块信息（用于 Milvus）
    return all_file_ids, software_uuid, all_chunk_element_id, all_chunks_for_milvus


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
            logger.info(
                f"[send_request_embedding] Stella 返回为空 elementId={texts_ids}"
            )
            return None
        logger.info(
            f"[send_request_embedding] Stella 请求失败 status={response.status_code}, body={response.text}"
        )
        return None
    except Exception as e:
        logger.info(f"[send_request_embedding] Stella 请求异常: {e}")
        return None


def add_embedding_data_to_neo4j():
    """
    获取 Neo4j 中的 code_data，生成 code_embedding，并写回节点。
    description 仅保存文本，不再生成 embedding。
    """
    with driver.session(**SESSION_KWARGS) as session:
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
            logger.info(
                f"[add_embedding_data_to_neo4j] code_data 为空，跳过 elementId={element_id}"
            )
            continue

        embedding_result = send_request_embedding([element_id, code_data])
        if not embedding_result:
            logger.info(
                f"[add_embedding_data_to_neo4j] code_data 向量化失败，跳过 elementId={element_id}"
            )
            continue

        texts_ids, embeddings_list = embedding_result
        if not texts_ids or not embeddings_list:
            logger.info(
                f"[add_embedding_data_to_neo4j] 向量结果为空，跳过 elementId={element_id}"
            )
            continue

        code_embedding = embeddings_list[0]
        with driver.session(**SESSION_KWARGS) as session:
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
        logger.info(
            f"[add_embedding_data_to_neo4j] 更新 code_embedding elementId={element_id}"
        )

    return processed_ids


def add_relateship(all_file_ids, software_uuid, insert_number):
    insert_number = 0
    """添加三种节点的关系：软件-文件、文件-代码片段、代码片段-技术"""
    with driver.session(**SESSION_KWARGS) as session:
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
            session.run(
                merge_software_file_query,
                software_uuid=software_uuid,
                file_uuid=file_uuid,
                insert_number=insert_number,
            )

            # 2. 文件节点和代码片段节点的关系
            merge_file_code_query = """
            MATCH (file:MitreAttackCodeSoftwareFile {file_uuid: $file_uuid}), (code:MitreAttackCodeSoftwareCodeChunk {file_uuid: $file_uuid})
            MERGE (file)-[r:CODE_SOFTWARE_FILE_HAS_CODE_SOFTWARE_CODE_CHUNK]->(code)
            ON CREATE SET r.insert_number = $insert_number
            MERGE (code)-[r2:CODE_SOFTWARE_CODE_CHUNK_BELONG_CODE_SOFTWARE_FILE]->(file)
            ON CREATE SET r2.insert_number = $insert_number
            """
            session.run(
                merge_file_code_query, file_uuid=file_uuid, insert_number=insert_number
            )
        # 3. 代码片段节点和技术节点的关系
        for file_uuid in all_file_ids:
            # 查询该文件下的所有代码片段及其技术 ID
            search_code_techniques_query = """
            MATCH (code:MitreAttackCodeSoftwareCodeChunk {file_uuid: $file_uuid})
            RETURN code.code_uuid AS code_uuid, code.technique_id AS technique_id
            """
            code_techniques = session.run(
                search_code_techniques_query, file_uuid=file_uuid
            )

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
                session.run(
                    merge_code_technique_query,
                    code_uuid=code_uuid,
                    technique_id=technique_id,
                    insert_number=insert_number,
                )
        # 4. 软件节点和战术的关系
        search_software_query = """
            MATCH (software:MitreAttackCodeSoftware {software_uuid: $software_uuid})
            RETURN software.tactic_id_list AS tactic_id_list
        """
        software_tactics = session.run(
            search_software_query, software_uuid=software_uuid
        )

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
                session.run(
                    merge_software_tactic_query,
                    software_uuid=software_uuid,
                    tactic_id=tactic_id,
                    insert_number=insert_number,
                )


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
        print(
            f"Milvus collection {collection_name} 不存在，开始创建 (dim={vector_dim})..."
        )

        try:
            # 定义字段：neo4j_id + code_data + description + code__embedding + soft_name + url
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
                # 新增：所属软件名称
                FieldSchema(
                    name="soft_name",
                    dtype=DataType.VARCHAR,
                    max_length=512,
                ),
                # 新增：软件仓库 URL（暂时为空，后续可更新）
                FieldSchema(
                    name="url",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
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
                if (
                    "already exist" not in str(exc).lower()
                    and "duplicate" not in str(exc).lower()
                ):
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
                if (
                    "already exist" not in str(exc).lower()
                    and "duplicate" not in str(exc).lower()
                ):
                    print(f"创建稀疏向量字段索引时出错: {exc}")
                    raise

            # 加载 collection
            collection.load()
            print(f"Milvus collection {collection_name} 创建并加载完成")

            # 验证 collection 是否真的存在
            if utility.has_collection(collection_name):
                print(f"✓ 验证成功: collection {collection_name} 已存在")
            else:
                raise RuntimeError(
                    f"Collection {collection_name} 创建失败，验证时不存在"
                )

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
        sparse_has_index = any(idx.field_name == "sparse_vector" for idx in index_info)

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
                if (
                    "already exist" not in str(exc).lower()
                    and "duplicate" not in str(exc).lower()
                ):
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
                if (
                    "already exist" not in str(exc).lower()
                    and "duplicate" not in str(exc).lower()
                ):
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
                print(
                    f"跳过记录 {neo4j_id}: 向量维度不正确 (期望 1024, 实际 {actual_dim})"
                )
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

    # 批量插入数据 - 分批处理以避免 gRPC 消息大小限制
    if neo4j_ids:
        try:
            # 设置每批插入的记录数（根据实际情况调整，建议 500-2000）
            BATCH_SIZE = 1000

            total_batches = (len(neo4j_ids) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"将分 {total_batches} 批插入数据，每批 {BATCH_SIZE} 条记录...")
            print(f"开始插入数据到 collection {MILVUS_COLLECTION}...")

            for batch_idx in range(0, len(neo4j_ids), BATCH_SIZE):
                batch_end = min(batch_idx + BATCH_SIZE, len(neo4j_ids))
                batch_neo4j_ids = neo4j_ids[batch_idx:batch_end]
                batch_code_datas = code_datas[batch_idx:batch_end]
                batch_descriptions = descriptions[batch_idx:batch_end]
                batch_embeddings = embeddings[batch_idx:batch_end]

                # 确保字段顺序与 schema 定义一致: neo4j_id, code_data, description, code__embedding
                batch_entities = [
                    batch_neo4j_ids,
                    batch_code_datas,
                    batch_descriptions,
                    batch_embeddings,
                ]

                current_batch = (batch_idx // BATCH_SIZE) + 1
                print(
                    f"正在插入第 {current_batch}/{total_batches} 批 ({len(batch_neo4j_ids)} 条记录)..."
                )

                try:
                    result = collection.upsert(batch_entities)
                    success_count += len(batch_neo4j_ids)
                    print(
                        f"第 {current_batch} 批插入成功，累计已导入 {success_count} 条记录..."
                    )
                except MilvusException as e:
                    print(f"第 {current_batch} 批插入失败: {str(e)}")
                    print(f"错误类型: {type(e).__name__}")
                    error_count += len(batch_neo4j_ids)
                    # 继续处理下一批
                except Exception as e:
                    print(f"第 {current_batch} 批插入时发生未知错误: {str(e)}")
                    print(f"错误类型: {type(e).__name__}")
                    error_count += len(batch_neo4j_ids)
                    # 继续处理下一批

            # 验证插入是否成功 - 查询 collection 中的记录数
            try:
                collection.flush()  # 确保数据被持久化
                num_entities = collection.num_entities
                print(f"Collection {MILVUS_COLLECTION} 当前包含 {num_entities} 条记录")
            except Exception as e:
                print(f"查询 collection 记录数时出错: {e}")

            print(f"导入完成！成功: {success_count}, 失败: {error_count}")
        except Exception as e:
            print(f"插入数据时发生严重错误: {str(e)}")
            print(f"错误类型: {type(e).__name__}")
            import traceback

            traceback.print_exc()
            error_count += len(neo4j_ids) - success_count
    else:
        print("没有有效数据需要导入")


def add_milvus_from_chunks(all_chunks_data, repo_url: str = ""):
    """直接从代码块数据添加到 Milvus 向量数据库（全量入库）

    Args:
        all_chunks_data: 代码块数据列表
        repo_url: Gitea 仓库的 web_url，将写入 Milvus 的 url 字段

    约定：
    - 每个 chunk_info 中如果包含 soft_name 字段，则写入 Milvus 的 soft_name 字段；
      否则 soft_name 置为空字符串。
    - url 字段将使用传入的 repo_url 参数。
    """
    if not milvus_connected:
        print("错误: Milvus 未连接，无法插入数据")
        return

    if not all_chunks_data:
        print("没有代码块数据需要导入")
        return

    print(f"准备将 {len(all_chunks_data)} 个代码块导入 Milvus（全量）")

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

    # 第一步：为所有代码块生成 embedding（使用已同步的 description，不再重新生成）
    logger.info(
        f"[add_milvus_from_chunks] 开始为 {len(all_chunks_data)} 个代码块生成 embedding（使用已同步的 description）"
    )

    def process_chunk(chunk_info):
        """处理单个代码块：使用已同步的 description（如果有），生成 embedding"""
        code_data = chunk_info["code_data"]
        file_name = chunk_info.get("file_name", "未知文件")

        # 使用已同步的 description（只对有技术的代码块有值，没有技术的为 None）
        description = chunk_info.get("description", None)
        if description is None:
            # 没有技术的代码块，description 为空字符串
            description = ""

        # 优先使用 elementId（Neo4j 的 elementId），如果没有则使用 code_uuid（不在 Neo4j 中的代码块）
        neo4j_element_id = chunk_info.get("element_id")
        if neo4j_element_id:
            # 有技术的代码块，使用 Neo4j 的 elementId
            neo4j_id = neo4j_element_id
        else:
            # 没有技术的代码块，使用 code_uuid（虽然不在 Neo4j 中，但可以作为 Milvus 的唯一标识）
            neo4j_id = chunk_info["code_uuid"]
            logger.debug(
                f"[add_milvus_from_chunks] 代码块 {chunk_info['code_uuid']} 不在 Neo4j 中，使用 code_uuid 作为 neo4j_id"
            )

        # 生成 embedding（所有代码块都需要）
        embedding_result = send_request_embedding([neo4j_id, code_data])

        if embedding_result:
            texts_ids, embeddings_list = embedding_result
            if embeddings_list:
                return {
                    "neo4j_id": neo4j_id,  # 使用 Neo4j 的 elementId（如果有），否则使用 code_uuid
                    "code_data": code_data,
                    "description": description,  # 有技术的使用已生成的描述，没有技术的为空字符串
                    "embedding": embeddings_list[0],
                    # 从原始 chunk_info 透传 soft_name（如果有）
                    "soft_name": chunk_info.get("soft_name", ""),
                }

        return None

    # 并发生成 embedding（description 已从 handle_json_file 同步）
    processed_chunks = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_chunk = {
            executor.submit(process_chunk, chunk_info): chunk_info
            for chunk_info in all_chunks_data
        }

        for future in as_completed(future_to_chunk):
            chunk_info = future_to_chunk[future]
            try:
                result = future.result()
                if result:
                    processed_chunks.append(result)
                else:
                    error_count += 1
                    logger.warning(
                        f"[add_milvus_from_chunks] 代码块 {chunk_info['code_uuid']} 处理失败"
                    )
            except Exception as e:
                error_count += 1
                logger.error(
                    f"[add_milvus_from_chunks] 代码块 {chunk_info['code_uuid']} 处理异常: {e}"
                )

    logger.info(
        f"[add_milvus_from_chunks] 完成处理，成功 {len(processed_chunks)} 个，失败 {error_count} 个"
    )

    # 准备批量插入数据
    neo4j_ids = []
    code_datas = []
    descriptions = []
    embeddings = []
    soft_names = []

    for chunk_result in processed_chunks:
        neo4j_id = chunk_result["neo4j_id"]
        code_data = chunk_result["code_data"]
        description = chunk_result["description"]
        embedding = chunk_result["embedding"]
        soft_name = chunk_result.get("soft_name", "")

        # 验证向量维度
        if not isinstance(embedding, list) or len(embedding) != 1024:
            error_count += 1
            logger.warning(f"[add_milvus_from_chunks] 代码块 {neo4j_id} 向量维度不正确")
            continue

        neo4j_ids.append(neo4j_id)
        code_datas.append(code_data)
        descriptions.append(description)
        embeddings.append(embedding)
        soft_names.append(soft_name)

    print(f"准备插入 {len(neo4j_ids)} 条有效记录到 Milvus")

    # 批量插入数据
    if neo4j_ids:
        try:
            BATCH_SIZE = 1000
            total_batches = (len(neo4j_ids) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"将分 {total_batches} 批插入数据，每批 {BATCH_SIZE} 条记录...")

            for batch_idx in range(0, len(neo4j_ids), BATCH_SIZE):
                batch_end = min(batch_idx + BATCH_SIZE, len(neo4j_ids))
                batch_neo4j_ids = neo4j_ids[batch_idx:batch_end]
                batch_code_datas = code_datas[batch_idx:batch_end]
                batch_descriptions = descriptions[batch_idx:batch_end]
                batch_embeddings = embeddings[batch_idx:batch_end]
                batch_soft_names = soft_names[batch_idx:batch_end]
                batch_urls = [repo_url] * len(batch_neo4j_ids)  # 使用传入的 repo_url

                # 字段顺序与 schema 定义一致:
                # neo4j_id, code_data, description, code__embedding, soft_name, url
                batch_entities = [
                    batch_neo4j_ids,
                    batch_code_datas,
                    batch_descriptions,
                    batch_embeddings,
                    batch_soft_names,
                    batch_urls,
                ]

                current_batch = (batch_idx // BATCH_SIZE) + 1
                print(
                    f"正在插入第 {current_batch}/{total_batches} 批 ({len(batch_neo4j_ids)} 条记录)..."
                )

                try:
                    result = collection.upsert(batch_entities)
                    success_count += len(batch_neo4j_ids)
                    print(
                        f"第 {current_batch} 批插入成功，累计已导入 {success_count} 条记录..."
                    )
                except MilvusException as e:
                    print(f"第 {current_batch} 批插入失败: {str(e)}")
                    error_count += len(batch_neo4j_ids)
                except Exception as e:
                    print(f"第 {current_batch} 批插入时发生未知错误: {str(e)}")
                    error_count += len(batch_neo4j_ids)

            # 验证插入是否成功 / 可删除
            try:
                collection.flush()
                num_entities = collection.num_entities
                print(f"Collection {MILVUS_COLLECTION} 当前包含 {num_entities} 条记录")
            except Exception as e:
                print(f"查询 collection 记录数时出错: {e}")

            print(f"Milvus 导入完成！成功: {success_count}, 失败: {error_count}")
        except Exception as e:
            print(f"插入数据时发生严重错误: {str(e)}")
            import traceback

            traceback.print_exc()
            error_count += len(neo4j_ids) - success_count
    else:
        print("没有有效数据需要导入")

def handle_code(source_name, file_path, file_name, file_type, extract_dir, insert_number):
    try:
    # 使用线程池并发执行：代码处理和 Gitea 上传
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 任务1：分析代码，处理 JSON 文件和建立关系（串行执行）
            def process_code_data():
                result = analysis_code(extract_dir, source_name)
                return result
            
            # 任务2：上传到 Gitea（并发执行）
            def upload_to_gitea_task():
                try:
                    logger.info(f"[handle_code] 开始上传项目到 Gitea: {source_name}")
                    repo_url = upload_to_gitea(
                        extract_dir=extract_dir,
                        repo_name=source_name,
                        description=f"项目: {source_name}"
                    )
                    if repo_url:
                        logger.info(f"[handle_code] Gitea 上传成功，仓库 URL: {repo_url}")
                    else:
                        logger.warning(f"[handle_code] Gitea 上传失败，将继续处理但不记录仓库 URL")
                    return repo_url or ""  # 确保返回字符串，不能是 None
                except Exception as e:
                    logger.error(f"[handle_code] Gitea 上传异常: {e}")
                    return ""  # 上传失败返回空字符串，不影响主流程
            
            # 提交并发任务
            future_result = executor.submit(process_code_data)
            future_gitea = executor.submit(upload_to_gitea_task)
            
            # 等待两个任务完成
            result = future_result.result()
            repo_url = future_gitea.result()
        logger.info(f"[handle_code] 开始处理代码数据: {source_name}")
        all_file_ids, software_uuid, all_embedding_element_id, all_chunks_for_milvus = handle_json_file(result.to_dict(), insert_number,repo_url)
        # 建立关系（只针对 Neo4j 中的代码块）
        add_relateship(all_file_ids, software_uuid, insert_number)
        logger.info(f"[handle_code] 代码数据处理完成: {source_name}")
        add_milvus_from_chunks(all_chunks_for_milvus, repo_url=repo_url)
        return {"status": "success"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}