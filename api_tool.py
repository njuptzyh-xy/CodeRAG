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
                RETURN article.full_text as full_text
            """
            with driver.session() as session:
                result = session.run(query)
                result_data = result.single() if result.peek() else None
            
            if result_data:
                item_full_text = result_data.get('full_text', None)
            else:
                item_full_text = ""
            
            document_and_code_data.append({
                'document_data': item_full_text,
                'type': "document"
            })
        elif neo_data.get('type') == 'software':
            element_id = neo_data.get('neo_id')
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
            
            document_and_code_data.append(code_data) 
                
    return document_and_code_data
        
        
                
                
                
            