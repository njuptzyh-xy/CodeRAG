from neo4j import GraphDatabase
from neo4j.time import Date, DateTime, Duration, Time
from setting import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NODE_RETURN_FIELDS, NEO4J_DATABASE


class Neo4jHelper:

    def __init__(self):
        """
        初始化 neo4j 客户端。
        """
        try:
            self.auth = (NEO4J_USER, NEO4J_PASSWORD)
            self.neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=self.auth)
            self.session_kwargs = {"database": NEO4J_DATABASE}
        except Exception as e:
            print(f"Authentication failed: {e}")
            return None
    
    def _serialize_value(self, value):
        """Recursively convert Neo4j temporal objects into JSON-safe values."""
        if isinstance(value, (DateTime, Date, Time)):
            return value.isoformat()
        if isinstance(value, Duration):
            return str(value)
        if isinstance(value, list):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._serialize_value(val) for key, val in value.items()}
        return value

    def get_single_point_data(self, neo_id, node_type=None):
        """
        根据element_id查询节点，并动态指定返回字段
        
        参数:
            id: 节点的 element_id
        返回:
            查询结果
        """
        # 先进行节点类型查询, 拿到要返回的字段
        if not node_type:
            node_type_query = f"""
                MATCH (n)
                WHERE elementId(n) = $element_id
                RETURN labels(n) AS nodeLabels
            """ 
            # 执行查询
            with self.neo4j_driver.session(**self.session_kwargs) as session:
                type_result = session.run(node_type_query, element_id=neo_id)
                # 只有一条数据，所以使用 single
                type_record = type_result.single()
                if type_record:
                    node_labels = type_record.get("nodeLabels")
                    for node_label_item in node_labels:
                        if node_label_item !=  "BaseEntity":
                            node_type = node_label_item
        if node_type:# "MitreAttackArticleChunk"
            return_fields = NODE_RETURN_FIELDS.get(node_type)
            if not return_fields:
                return_fields = "all" 
        else:
            return_fields = "all"
        
        # 构建动态返回字段
        field_expressions = []
        if return_fields != "all":
            for field in return_fields:
                # 安全处理字段名，避免注入
                safe_field = field.replace("'", "").replace('"', "").replace(";", "")
                field_expressions.append(f"n.{safe_field} AS {safe_field}")
            return_clause = f"RETURN {', '.join(field_expressions)}"
        # 将所有字段表达式连接成返回子句
        if return_fields == "all":
            return_clause = f"RETURN n"
        
        # 完整的查询语句
        node_data_query = f"""
            MATCH (n)
            WHERE elementId(n) = $element_id
            {return_clause}
        """
        
        return_dict = {}
        # 执行查询
        with self.neo4j_driver.session(**self.session_kwargs) as session:
            search_data_result = session.run(node_data_query, element_id=neo_id)
            search_data_record = search_data_result.single()
            if search_data_record:
                if return_fields != "all":
                    for field_item in return_fields:
                        field_value = search_data_record.get(field_item)
                        return_dict[field_item] = self._serialize_value(field_value)
                else:
                    node_data = dict(search_data_record.data()["n"])
                    return_dict.update(self._serialize_value(node_data))  # 核心修改
                return_dict["node_label"] = node_type
        
        return return_dict

    def get_node_by_description(self, description: str):
        """
        通过 description 精确查找节点，返回节点字段、标签及 elementId。
        """
        if not description:
            return {}
        
        query = """
            MATCH (n:BaseEntity)
            WHERE n.description = $description
            RETURN n, labels(n) AS nodeLabels, elementId(n) AS element_id
            LIMIT 1
        """
        
        with self.neo4j_driver.session(**self.session_kwargs) as session:
            result = session.run(query, description=description)
            record = result.single()
            if not record:
                return {}
            
            node = record.get("n")
            node_labels = record.get("nodeLabels") or []
            element_id = record.get("element_id")
            
            node_type = None
            for label in node_labels:
                if label != "BaseEntity":
                    node_type = label
                    break
            
            node_data = dict(node)
            serialized = self._serialize_value(node_data)
            serialized["node_label"] = node_type
            serialized["element_id"] = element_id
            return serialized
    
    def get_one_hop_neighbors(self, node_id: str):
        """
        查询节点向外一跳的所有节点，并返回关系名称
        
        参数:
            node_id: 起始节点的element_id
        
        返回:
            一跳邻居节点的列表，每个元素包含节点id、nodeLabels和关系类型
        """
        # Cypher查询，获取所有与起始节点有关系的节点，并包含关系类型
        query = """
            MATCH (n)-[r]->(neighbor)
            WHERE elementId(n) = $element_id
            RETURN
                elementId(neighbor) AS id,
                labels(neighbor) AS nodeLabels,
                type(r) AS relationshipType
        """
        
        # 执行查询
        neighbors = []
        with self.neo4j_driver.session(**self.session_kwargs) as session:
            result = session.run(query, element_id=node_id)
            for record in result:
                neighbors.append({
                    "id": record.get("id"),
                    "nodeLabels": record.get("nodeLabels"),
                    "relationshipType": record.get("relationshipType")
                })

        # 在这里进行代码文件的进一步查找，找到代码结点
        index = 0
        while index < len(neighbors):
            neighbors_item = neighbors[index]
            if "MitreAttackCodeSoftwareFile" in neighbors_item.get("nodeLabels"):
                code_element_id = neighbors_item.get("id")
                # 查询该文件节点下的所有代码节点
                query_find_code = """
                    MATCH (n)-[r:CODE_SOFTWARE_FILE_HAS_CODE_SOFTWARE_CODE_CHUNK]->(neighbor)
                    WHERE elementId(n) = $code_file_element_id
                    RETURN
                        elementId(neighbor) AS id,
                        labels(neighbor) AS nodeLabels,
                        type(r) AS relationshipType,
                        neighbor as node_data
                """
                code_nodes = []
                with self.neo4j_driver.session(**self.session_kwargs) as session:
                    code_result = session.run(query_find_code, code_file_element_id=code_element_id)
                    for code_record in code_result:
                        code_nodes.append({
                            "id": code_record.get("id"),
                            "nodeLabels": code_record.get("nodeLabels"),
                            "relationshipType": code_record.get("relationshipType")
                        })
                # 删除当前的文件节点
                neighbors.pop(index)
                # 在当前位置插入所有代码节点
                for code_node in code_nodes:
                    neighbors.insert(index, code_node)
                    # 关键修改：插入后立即移动索引
                    index += 1
            else:
                index += 1

        return neighbors
     
    def expansion_search(self, neo4j_id_list):
        # 对应召回模式中的延伸搜索
        # 循环每个 neo4j_id, 将所有结点的延伸进行收集返回。
        data_neo_id = [j for j in neo4j_id_list]         # 这个是为了做节点去重使用的
        
        # 这是最终返回数据
        total_result = []
        if neo4j_id_list:
            for neo_id in neo4j_id_list:
                single_total_data = {} 
                # 先拿到 这个父节点的信息,并更新 single_total_data
                parent_node_data = self.get_single_point_data(neo_id)
                single_total_data.update(parent_node_data)
                
                # 下一层级的数据
                next_level_data = []
                # 接下来拿取第一跳的所有数据
                children_data = self.get_one_hop_neighbors(neo_id)
                # 接下来给 children 结点补充数据
                for child_item in children_data:
                    # 循环每一个孩子节点，拿到孩子节点需要的字段的数据
                    child_neo_id = child_item.get("id")
                    
                    # 第一层要添加 neo_id 为了去重
                    data_neo_id.append(child_neo_id)
                    
                    child_node_types = child_item.get("nodeLabels")
                    child_node_type = "BaseEntity"
                    # 找到不是 BaseEntity 的那个标签
                    for type_item in child_node_types:
                        if type_item != "BaseEntity":
                            child_node_type = type_item
                    
                    children_complete_data = self.get_single_point_data(child_neo_id, child_node_type)
                    
                    # 接下来进行第二层寻找
                    next_level_data2 = []
                    children_children_data = self.get_one_hop_neighbors(child_neo_id)
                    # 接下来给 children 结点补充数据
                    for child_child_item in children_children_data:
                        # 循环每一个孩子节点，拿到孩子节点需要的字段的数据
                        child_child_neo_id = child_child_item.get("id")
                        
                        # 第一层要添加 neo_id 为了去重
                        if child_child_neo_id not in data_neo_id:
                            data_neo_id.append(child_child_neo_id)
                        else:
                            continue
                        
                        child_child_node_types = child_child_item.get("nodeLabels")
                        child_child_node_type = "BaseEntity"
                        # 找到不是 BaseEntity 的那个标签
                        for type_item2 in child_child_node_types:
                            if type_item2 != "BaseEntity":
                                child_child_node_type = type_item2
                        children_children_complete_data = self.get_single_point_data(child_child_neo_id, child_child_node_type)
                        next_level_data2.append(children_children_complete_data)
                    children_complete_data["next_level"] = next_level_data2
                    next_level_data.append(children_complete_data)
                
                single_total_data["next_level"] = next_level_data
                total_result.append(single_total_data)
        
        return total_result      
                
        
        
        
        