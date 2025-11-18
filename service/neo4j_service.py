# from neo4j_driver import driver
from neo4j import GraphDatabase
from setting import NEO4J_USER, NEO4J_PASSWORD, NEO4J_URI

AUTH = (NEO4J_USER, NEO4J_PASSWORD)

driver = GraphDatabase.driver(NEO4J_URI, auth=AUTH)

def get_description_by_id(mitre_attack_id):
    query = f"""
    MATCH (n:BaseEntity)
    WHERE n.attack_id = "{mitre_attack_id}"
    RETURN n.description as description
    """
    with driver.session() as session:
        result = session.run(query)
        result_data = result.single() if result.peek() else None
    
    if result_data:
        return result_data.get('description', None)
    else:
        return None


def get_data_by_id(mitre_attack_id):
   # 拼凑文章数据结果
    document_list = [] # 获取相关连的文章
    
    query = f"""
    MATCH (n)-[r]->(article:MitreAttackArticleDocument)
    WHERE n.attack_id = "{mitre_attack_id}"
    RETURN elementId(article) as document_neo_id, article.title as title, article.article_summary as summary
    """
    with driver.session() as session:
        result = session.run(query)
        for record in result:
            document_list.append({
                'document_neo_id': record.get('document_neo_id'),
                'title': record.get('title'),
                'summary': record.get('summary')
            })
    
    # 获取软件数据
    code_file_uuid_list = []
    software_list = []
    code_file_query = f"""
    MATCH (n)-[r]->(code:MitreAttackCodeSoftwareCodeChunk)
    WHERE n.attack_id = "{mitre_attack_id}"
    RETURN code.file_uuid as file_uuid
    """
    with driver.session() as session:
        code_file_uuid_result = session.run(code_file_query)
        for code_file_record in code_file_uuid_result:
            code_file_uuid_list.append(code_file_record.get("file_uuid"))
    
    # 接下来进行文件去重
    code_file_uuid_list = list(set(code_file_uuid_list))
    
    #这是软件查重的列表 
    check_id_list = []
    
    # 接下来通过文件找到软件
    for file_uuid_item in code_file_uuid_list:
        code_software_query = f"""
        MATCH (software:MitreAttackCodeSoftware)-[r]->(file:MitreAttackCodeSoftwareFile)
        WHERE file.file_uuid = "{file_uuid_item}"
        RETURN software.name as software_name, software.description as software_description, elementId(software) as software_element_id
        """
        with driver.session() as session:
            code_software_result = session.run(code_software_query)
            for code_software_record in code_software_result:
                single_software_name = code_software_record.get("software_name")
                single_software_description = code_software_record.get("software_description")
                single_software_neo_id = code_software_record.get("software_element_id")
                if single_software_neo_id not in check_id_list:
                    check_id_list.append(single_software_neo_id)
                    software_list.append({
                        "software_neo_id": single_software_neo_id,
                        "software_description": single_software_description,
                        "software_name": single_software_name
                    })
    result_data = {
        'document': document_list,
        'software': software_list
    }
    
    return result_data


def get_detail_by_ids(neo_ids):
    document_and_code_data = []
    for neo_data in neo_ids:
        if neo_data.get('type') == 'document':
            element_id = neo_data.get('neo_id')
            query = f"""
                MATCH (article:MitreAttackArticleDocument)
                WHERE elementId(article) = "{element_id}"
                RETURN article.title as title,
                       article.article_summary as summary,
                       article.full_text as full_text,
                       article.source_url as source_url,
                       article.insert_type as insert_type,
                       article.mitre_attack_id_list as mitre_attack_id_list,
                       elementId(article) as article_id
            """
            with driver.session() as session:
                result = session.run(query)
                result_data = result.single() if result.peek() else None

            if result_data:
                item_full_text = result_data.get('full_text', None)
                item_title = result_data.get('title', '无标题')
                item_summary = result_data.get('summary', '无摘要')
                item_source_url = result_data.get('source_url', '无URL')
                item_insert_type = result_data.get('insert_type', '未知')
                item_attack_ids = result_data.get('mitre_attack_id_list', [])
                item_article_id = result_data.get('article_id', '')
            else:
                item_full_text = ""
                item_title = "无标题"
                item_summary = "无摘要"
                item_source_url = "无URL"
                item_insert_type = "未知"
                item_attack_ids = []
                item_article_id = element_id

            document_and_code_data.append({
                'document_data': item_full_text,
                'type': "document",
                'title': item_title,
                'summary': item_summary,
                'source_url': item_source_url,
                'insert_type': item_insert_type,
                'mitre_attack_ids': item_attack_ids,
                'article_id': item_article_id
            })
        elif neo_data.get('type') == 'software':
            element_id = neo_data.get('neo_id')

            # 首先获取软件的基本信息
            software_info_query = f"""
                MATCH (software:MitreAttackCodeSoftware)
                WHERE elementId(software) = "{element_id}"
                RETURN software.name as software_name,
                       software.description as software_description,
                       elementId(software) as software_id
            """

            software_name = "无名称"
            software_description = "无描述"
            software_id = element_id

            with driver.session() as session:
                software_result = session.run(software_info_query)
                software_data = software_result.single() if software_result.peek() else None

                if software_data:
                    software_name = software_data.get('software_name', '无名称')
                    software_description = software_data.get('software_description', '无描述')
                    software_id = software_data.get('software_id', element_id)

            # 这是为了去重
            file_id_list = []
            file_id_name_dict = {}
            # 这是 software_id, 接下来要通过 software 找文章
            query = f"""
                MATCH (software:MitreAttackCodeSoftware)-[r]->(file:MitreAttackCodeSoftwareFile)
                WHERE elementId(software) = "{element_id}"
                RETURN file.file_uuid as file_uuid, file.name as file_name
            """
            with driver.session() as session:
                file_result = session.run(query)
                for file_record in file_result:
                    file_id_list.append(file_record.get("file_uuid"))
                    file_id_name_dict[file_record.get("file_uuid")] = file_record.get("file_name")

            file_id_list = list(set(file_id_list))

            code_data = {}
            for file_item in file_id_list:
                code_str_list = []
                code_query = f"""
                MATCH (file:MitreAttackCodeSoftwareFile)-[r]->(code:MitreAttackCodeSoftwareCodeChunk)
                WHERE file.file_uuid = "{file_item}"
                RETURN code.chunk_start_line as start_line, code.code_data as code_data
                """
                with driver.session() as session:
                    code_result = session.run(code_query)
                    for code_record in code_result:
                        code_str_list.append([code_record.get("start_line"), code_record.get("code_data")])

                code_str_list = sorted(code_str_list, key=lambda x: (x[0] is None, x[0] if x[0] is not None else 0))
                code_str = "\n\n".join([item[1] if item[1] is not None else "" for item in code_str_list])
                if code_str.strip() != "":
                    file_name = file_id_name_dict[file_item]
                    code_data[file_name] = code_str

            # 构造软件数据结构
            software_result = {
                'type': "software",
                'software_name': software_name,
                'software_description': software_description,
                'software_id': software_id,
                'code_files': code_data
            }

            document_and_code_data.append(software_result) 
                
    return document_and_code_data
        
def get_article_and_software_count():
    article_count_query = """
        MATCH (n:MitreAttackArticleDocument)
        RETURN count(n) AS article_count
    """
    software_count_query = """
        MATCH (n:MitreAttackCodeSoftware)
        RETURN count(n) AS software_count
    """
    
    with driver.session() as session:
        article_result = session.run(article_count_query)
        article_count = article_result.single()["article_count"]

        software_result = session.run(software_count_query)
        software_count = software_result.single()["software_count"]
        
    return {
        "article_count": article_count,
        "software_count": software_count
    }
        
def get_articles_by_attack_id(attack_id):
    """
    根据ATT&CK ID获取相关文章统计信息
    返回文章数量、标题、描述（50字）和来源URL
    """
    query = """
    MATCH (article:MitreAttackArticleDocument)
    WHERE $attack_id IN article.mitre_attack_id_list
    RETURN article.title as title,
           article.article_summary as summary,
           article.source_url as source_url
    """

    articles = []
    with driver.session() as session:
        result = session.run(query, attack_id=attack_id)
        for record in result:
            # 处理描述，截取前50个字
            summary = record.get('summary', '')
            if summary:
                # 简单截取前50个字符作为描述
                short_description = summary[:50] + '...' if len(summary) > 50 else summary
            else:
                short_description = "无描述"

            articles.append({
                'title': record.get('title', '无标题'),
                'description': short_description,
                'source_url': record.get('source_url', '无URL')
            })

    return {
        'attack_id': attack_id,
        'article_count': len(articles),
        'articles': articles
    }


def get_all_articles():
    """
    获取所有文章列表
    返回文章数量、标题、描述（100字）和来源URL
    """
    query = """
    MATCH (article:MitreAttackArticleDocument)
    RETURN elementId(article) as article_id,
           article.title as title,
           article.article_summary as summary,
           article.source_url as source_url,
           article.insert_type as insert_type,
           article.mitre_attack_id_list as mitre_attack_id_list
    ORDER BY article.title
    """

    articles = []
    with driver.session() as session:
        result = session.run(query)
        for record in result:
            # 处理描述，截取前100个字
            summary = record.get('summary', '')
            if summary:
                # 简单截取前100个字符作为描述
                short_description = summary[:100] + '...' if len(summary) > 100 else summary
            else:
                short_description = "无描述"

            # 获取MITRE ATT&CK ID列表
            attack_ids = record.get('mitre_attack_id_list', [])
            if not attack_ids:
                attack_ids = []

            articles.append({
                'article_id': record.get('article_id', ''),
                'title': record.get('title', '无标题'),
                'description': short_description,
                'source_url': record.get('source_url', '无URL'),
                'insert_type': record.get('insert_type', '未知'),
                'mitre_attack_ids': attack_ids
            })

    return {
        'article_count': len(articles),
        'articles': articles
    }


def get_all_software():
    """
    获取所有软件列表
    返回软件数量、名称、描述和相关信息
    """
    query = """
    MATCH (software:MitreAttackCodeSoftware)
    RETURN elementId(software) as software_id,
           software.name as name,
           software.description as description
    ORDER BY software.name
    """

    software_list = []
    with driver.session() as session:
        result = session.run(query)
        for record in result:
            # 处理描述，截取前200个字
            description = record.get('description', '')
            if description:
                # 简单截取前200个字符作为描述
                short_description = description[:200] + '...' if len(description) > 200 else description
            else:
                short_description = "无描述"

            software_list.append({
                'software_id': record.get('software_id', ''),
                'name': record.get('name', '无名称'),
                'description': short_description
            })

    return {
        'software_count': len(software_list),
        'software': software_list
    }


def get_software_techniques_tactics(software_id):
    """
    获取软件相关的战术和技术信息
    返回软件使用的ATT&CK技术和所属战术
    """
    query = """
    MATCH (software:MitreAttackCodeSoftware)-[r1*1..2]->(tech:MitreAttackTechnique)
    WHERE elementId(software) = $software_id
    OPTIONAL MATCH (tech)-[r2:MitreAttackTechniqueSubtechniqueOf]->(tactic:MitreAttackTactic)
    RETURN DISTINCT
           elementId(tech) as technique_id,
           tech.name as technique_name,
           tech.description as technique_description,
           tech.attack_id as technique_attack_id,
           elementId(tactic) as tactic_id,
           tactic.name as tactic_name,
           tactic.description as tactic_description,
           tactic.attack_id as tactic_attack_id,
           tactic.attack_shortname as tactic_shortname
    ORDER BY tactic_name, technique_name
    """

    tactics_dict = {}
    with driver.session() as session:
        result = session.run(query, software_id=software_id)
        for record in result:
            tactic_id = record.get('tactic_id', '')
            tactic_name = record.get('tactic_name', '未知战术')
            tactic_description = record.get('tactic_description', '无描述')
            tactic_attack_id = record.get('tactic_attack_id', '')
            tactic_shortname = record.get('tactic_shortname', '')

            technique_info = {
                'technique_id': record.get('technique_id', ''),
                'technique_name': record.get('technique_name', '未知技术'),
                'technique_description': record.get('technique_description', '无描述'),
                'technique_attack_id': record.get('technique_attack_id', '')
            }

            # 如果战术不存在，创建新战术
            if tactic_id not in tactics_dict:
                tactics_dict[tactic_id] = {
                    'tactic_id': tactic_id,
                    'tactic_name': tactic_name,
                    'tactic_description': tactic_description,
                    'tactic_attack_id': tactic_attack_id,
                    'tactic_shortname': tactic_shortname,
                    'techniques': []
                }

            # 添加技术到战术中（避免重复）
            technique_exists = any(
                tech['technique_id'] == technique_info['technique_id']
                for tech in tactics_dict[tactic_id]['techniques']
            )
            if not technique_exists:
                tactics_dict[tactic_id]['techniques'].append(technique_info)

    # 转换为列表格式
    tactics_list = list(tactics_dict.values())

    return {
        'software_id': software_id,
        'tactics_count': len(tactics_list),
        'tactics': tactics_list
    }