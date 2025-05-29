import json
from neo4j_driver import driver
from neo4j_graphrag.retrievers import VectorCypherRetriever
from neo4j_graphrag.llm import LLMInterface
# from neo4j_graphrag.generation import GraphRAG
from graphrag import GraphRAG
from typing import Any, Optional, List, Generator
from openai import OpenAI
from setting import (
    EMBEDDING_URL, INDEX_NAME, EMBEDDING_TOP_K, 
    CHAT_MODEL_NAME, CHAT_MODEL_API_KEY, CHAT_URL, 
    CHAT_TEMPERATURE, CHAT_MAX_TOKENS, RERANK_URL, NODE_RETURN_FIELDS
)
from transformers import PreTrainedTokenizerFast
import requests

# 集成 openai 接口
class OpenaiEmbeddingClient:
    """自定义嵌入模型客户端，使用 requests 调用"""
    def __init__(self, embedding_url):
        self.embedding_url = embedding_url

    def embed_query(self, text: str) -> list[float]:
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "texts": [text]
        }
        
        response = requests.post(self.embedding_url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["embeddings"][0]

# 自定义兼容 OpenAI 接口的嵌入模型类
class CustomOpenAIEmbeddings:
    def __init__(self, api_base=EMBEDDING_URL):
        self.api_base = api_base
        self.openai_client = OpenaiEmbeddingClient(embedding_url=self.api_base)
    
    def embed_query(self, text: str) -> list[float]:
        return self.openai_client.embed_query(text)

# 添加一个类表示 LLM 响应
class LLMResponse:
    def __init__(self, content):
        self.content = content

class CustomLLM(LLMInterface):
    """自定义LLM实现，符合LLMInterface接口"""
    
    def __init__(
        self,
        model_name: str = CHAT_MODEL_NAME,
        model_params: Optional[dict[str, Any]] = None,
    ):
        """初始化自定义LLM"""
        self.model_name = model_name
        self.model_params = model_params or {"temperature": 0}
        self.api_base = CHAT_URL
        # 使用OpenAI官方客户端
        self.client = OpenAI(
            api_key=CHAT_MODEL_API_KEY,
            base_url=self.api_base
        )
        self.tokenizer = PreTrainedTokenizerFast(tokenizer_file="qwen2.5-7B-Instruct.json")
        super().__init__(model_name, model_params)
        
    def __call__(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """调用LLM生成回答"""
        return self.invoke(prompt, stop)
    
    def cut_prompt(self, prompt: str) -> str:
        """裁剪 prompt，只保留前 MAX_PROMPT_TOKENS 个 token"""
        MAX_TOKENS = CHAT_MAX_TOKENS
        SYSTEM_TOKENS = 2000
        # 用户提示的最大token数
        MAX_PROMPT_TOKENS = MAX_TOKENS - SYSTEM_TOKENS
        
        # 使用 tokenizer 进行 token 计算
        tokens = self.tokenizer.encode(prompt)
        
        if len(tokens) > MAX_PROMPT_TOKENS:
            # 只保留前 MAX_PROMPT_TOKENS 个 token
            truncated_tokens = tokens[:MAX_PROMPT_TOKENS]
            
            # 将 token 转换回文本
            truncated_prompt = self.tokenizer.decode(truncated_tokens)
            
            print(f"原始token数: {len(tokens)}, 截断后token数: {len(truncated_tokens)}")
            prompt = truncated_prompt
        
        return prompt
    
    def invoke(self, prompt: str, message_history=None, system_instruction=None, stop: Optional[List[str]] = None):
        """同步调用LLM (必须实现的抽象方法)"""
        # 构建消息列表
        messages = []
        
        # 如果有系统指令，添加为系统消息
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        
        # 处理消息历史
        if message_history:
            print(f"Message history type: {type(message_history)}")
            if hasattr(message_history, '__iter__'):
                formatted_messages = []
                for msg in message_history:
                    if hasattr(msg, 'role') and hasattr(msg, 'content'):
                        formatted_messages.append({"role": msg.role, "content": msg.content})
                    elif isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                        formatted_messages.append(msg)
                
                if formatted_messages:
                    messages.extend(formatted_messages)
                else:
                    print("Warning: Could not format message history properly")
            else:
                print("Warning: message_history is not iterable")
        
        # 进行 prompt 剪裁
        prompt = self.cut_prompt(prompt)
        
        # 添加用户提示
        messages.append({"role": "user", "content": prompt})
        
        is_stream = self.model_params.get("stream", False)
        
        print(f"Sending request to LLM API: {self.api_base}")
        print(f"Messages count: {len(messages)}")
        print(f"Final message length: {len(messages[-1]['content'])} chars")
        
        try:
            # 使用 OpenAI 官方客户端API调用
            if is_stream:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                    temperature=self.model_params.get("temperature", 0),
                    stream=True,
                    stop=stop if stop else None
                )
                
                def generate() -> Generator[str, None, None]:
                    for chunk in response:
                        if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                
                return generate()
            else:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                    temperature=self.model_params.get("temperature", 0),
                    stream=False,
                    stop=stop if stop else None
                )
                
                content = response.choices[0].message.content
                print(f"LLM response received, length: {len(content)}")
                
                return LLMResponse(content)
        
        except Exception as e:
            print(f"Error in LLM call: {str(e)}")
            # 增强错误信息
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                print(f"Response content: {e.response.text}")
            elif hasattr(e, 'status_code'):
                print(f"Status code: {e.status_code}")
            raise

    def ainvoke(self, prompt: str, message_history=None, system_instruction=None, stop: Optional[List[str]] = None):
        """异步调用LLM"""
        pass

def query_extend(question: str, max_retries: int=3) -> list[str]:
    # 将问题给到模型，让模型进行扩写
    prompt = f"""
        请根据以下问题进行扩写,
        
        问题：{question}。
        
        扩写要求：
            我的数据库中有这些类型节点：
            
            1. MitreAttackCampaign           表示某次攻击战役
            2. MitreAttackCodeSoftware       表示攻击中使用的代码或软件
            3. MitreAttackGroup              表示攻击的组织
            4. MitreAttackMitigation         表示攻击的缓解措施
            5. MitreAttackSoftware           表示攻击的软件
            6. MitreAttackTactic             表示攻击的战术
            7. MitreAttackTechnique          表示攻击的技术
            
            分析输入的问题，梳理出这个问题想问的与哪些类型的数据相关，
            根据最相关的三个类型，分别给出三个和用户意思相关但是不完全一样的英文扩写问题，
            每个问题侧重一个类型。
            注意: 三个问题要使用英文返回。
            
            请以json格式返回，json格式如下：
            
            {{
                "question_list": ["question1", "question2", "question3"]
            }}
            
            请确保回复是严格有效的JSON格式，不要添加任何额外的文本。
            请确保回复是严格有效的JSON格式，不要添加任何额外的文本。
            请确保回复是严格有效的JSON格式，不要添加任何额外的文本。
            请确保回复是严格有效的JSON格式，不要添加任何额外的文本。
            请确保回复是严格有效的JSON格式，不要添加任何额外的文本。
    """
    # llm 请求怕返回结构出问题，所以进行重试
    retry_count = 0
    while retry_count < max_retries:
        try:         
            llm = CustomLLM(
                model_name=CHAT_MODEL_NAME, 
                model_params={"temperature": 0}
            )
            
            result_content = llm.invoke(prompt)
            result_json = json.loads(result_content.content)
            return result_json["question_list"]
        except json.JSONDecodeError as e:
            # JSON解析失败，记录错误并重试
            last_error = f"JSON解析错误: {str(e)}, 内容: {result_content[:100]}..."
            retry_count += 1
            print(f"尝试 {retry_count}/{max_retries} 失败: {last_error}")
        except KeyError as e:
            # JSON中缺少所需的键
            last_error = f"JSON缺少键 {str(e)}, 内容: {result_content[:100]}..."
            retry_count += 1
            print(f"尝试 {retry_count}/{max_retries} 失败: {last_error}")  
        except Exception as e:
            # 其他错误
            last_error = f"未预期的错误: {str(e)}"
            retry_count += 1
            print(f"尝试 {retry_count}/{max_retries} 失败: {last_error}")
    
    # 所有重试都失败了
    error_msg = f"在 {max_retries} 次尝试后仍然无法获取有效的JSON结果。最后错误: {last_error}"
    # 可以选择抛出异常
    raise Exception(error_msg)

def get_neo4j_files_by_id(id: str, return_fields=None):
    """
    根据element_id查询节点，并动态指定返回字段
    
    参数:
        id: 节点的element_id
        return_fields: 要返回的字段列表，如为空则返回整个节点
    
    返回:
        查询结果
    """
    # 默认返回整个节点
    if return_fields is None or not return_fields:
        return_clause = "RETURN n"
    else:
        # 构建动态返回字段
        field_expressions = []
        for field in return_fields:
            # 安全处理字段名，避免注入
            safe_field = field.replace("'", "").replace('"', "").replace(";", "")
            field_expressions.append(f"n.{safe_field} AS {safe_field}")
        
        # 将所有字段表达式连接成返回子句
        return_clause = f"RETURN {', '.join(field_expressions)}"
    
    # 完整的查询语句
    query = f"""
        MATCH (n)
        WHERE elementId(n) = $element_id
        {return_clause}
    """
    
    # 执行查询
    with driver.session() as session:
        result = session.run(query, element_id=id)
        # 返回单条记录或 None
        return result.single() if result.peek() else None

def get_rerank_result(query: str, documents: list[str], top_k: int):
    """
    调用重排序接口对文档进行排序
    
    参数:
        query: 查询文本
        documents: 待排序的文档列表
        top_k: 返回排序后的前k个结果
    
    返回:
        排序后的文档及其分数
    """
    url = RERANK_URL
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "query": query,
        "documents": documents,
        "top_k": top_k
    }
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()  # 如果请求失败则抛出异常
        
    result = response.json()
    return result

def get_one_hop_neighbors(node_id: str):
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
    with driver.session() as session:
        result = session.run(query, element_id=node_id)
        for record in result:
            neighbors.append({
                "id": record.get("id"),
                "nodeLabels": record.get("nodeLabels"),
                "relationshipType": record.get("relationshipType")
            })
    
    return neighbors

def query_graphrag(question, stream=False):
    custom_embedder = CustomOpenAIEmbeddings(
        api_base=EMBEDDING_URL
    )

    retrieval_query = """
        MATCH (node)-[rel1]->(related_node)
WITH node, node.description AS node_description, labels(node) AS node_labels,
     collect({
        description: related_node.description,
        labels: labels(related_node),
        rel_type: type(rel1)
     }) AS first_hop_data,
     collect(related_node) AS related_nodes

// 对每个一跳节点查找它的下一跳关系，但排除原始节点
UNWIND related_nodes AS related_node
OPTIONAL MATCH (related_node)-[rel2]->(second_level_node)
WHERE second_level_node <> node  // 排除原始节点
WITH node_description, node_labels, first_hop_data,
     collect({
        second_node: CASE
            WHEN second_level_node IS NOT NULL AND second_level_node.description IS NOT NULL
            THEN {
                description: second_level_node.description,
                labels: labels(second_level_node)
            }
            ELSE null
        END,
        rel_type: type(rel2)
     }) AS second_hop_data

// 过滤掉无效的二跳记录
RETURN node_description,
       node_labels,
       [x IN first_hop_data WHERE x.description IS NOT NULL] AS first_hop_nodes,
       [x IN second_hop_data WHERE x.second_node IS NOT NULL AND x.second_node.description IS NOT NULL] AS second_hop_nodes
    """
    
    
    # 初始化 retriever
    retriever = VectorCypherRetriever(driver, INDEX_NAME, retrieval_query, custom_embedder)

    # 创建自定义 LLM 并传递给 GraphRAG
    llm = CustomLLM(
        model_name=CHAT_MODEL_NAME, 
        model_params={"temperature": CHAT_TEMPERATURE, "stream": stream}
    )
    rag = GraphRAG(retriever=retriever, llm=llm)
    if stream:
        # 流式返回模式
        prompt, message_history, system_instruction = rag.search(
            query_text=question,
            retriever_config={"top_k": EMBEDDING_TOP_K}
        )
        # 直接调用LLM的流式接口
        return llm.invoke(
            prompt,
            message_history,
            system_instruction=system_instruction
        )
    else:
        # 非流式返回模式
        prompt, message_history, system_instruction = rag.search(
            query_text=question,
            retriever_config={"top_k": EMBEDDING_TOP_K}
        )
        # 调用LLM获取答案
        answer = llm.invoke(
            prompt,
            message_history,
            system_instruction=system_instruction
        )

        # 返回答案内容
        return answer.content if hasattr(answer, 'content') else answer
    
    # # 在这里进行 query 扩写
    # extend_questions = query_extend(question)

    # # 这是三个问题所有召回数据的汇总
    # all_retriever_result = []
    # all_retriever_result_description = []
    # for i, question in enumerate(extend_questions):
    #     retriever_result = rag.search(
    #         query_text=question, 
    #         retriever_config={"top_k": EMBEDDING_TOP_K}
    #     )
    #     for item in retriever_result.items:
    #         # 这里的 item.metadata 是一个字典，结构是这样的，
    #         # {
    #         #  'score': 0.8025574684143066, 
    #         #  'nodeLabels': ['MitreAttackSoftware', 'BaseEntity'], 
    #         #  'id': '4:608e2f15-7966-4b36-84b4-00ef46edf27f:251'
    #         # }
    #         item_node_data = item.metadata

    #         # 提取出 id 字段，去 neo4j 数据库中找到相应节点，拿出 description
    #         item_node_id = item_node_data["id"]

    #         # 拿到描述字段进行重排处理
    #         item_node_description = get_neo4j_files_by_id(item_node_id, ["description"])
    #         item_node_data["description"] = item_node_description.get("description", "")

    #         # 将处理后的节点数据添加到汇总列表中
    #         all_retriever_result.append(item_node_data)
    #         all_retriever_result_description.append(item_node_description.get("description", ""))

    # # 数据已经准备就绪，进行重排
    # rerank_result = get_rerank_result(question, all_retriever_result_description, 5)
    # rerank_result_list = rerank_result.get("ranked_results", [])

    # # 这是重排后的列表内数据
    # # {'score': 0.8025574684143066, 
    # #  'nodeLabels': ['MitreAttackSoftware', 'BaseEntity'], 
    # #  'id': '4:608e2f15-7966-4b36-84b4-00ef46edf27f:251',
    # #  'description': ''}
    # after_rerank_data = []
    # if rerank_result_list:
    #     for rerank_item in rerank_result_list:
    #         rerank_item_index = rerank_item.get("index")
    #         after_rerank_data.append(all_retriever_result[rerank_item_index])

    # # 对 5个重排后的召回结果，做图查询，延申 2 跳
    # # 分步做延伸数据，先来第一跳
    # result_data = []
    # for item in after_rerank_data:
    #     # 一共有五个大字典，因为有五个召回节点
    #     item_all_data = {}

    #     # 先提取出 id 和 nodeLabels
    #     item_id = item.get("id")
    #     item_node_labels = item.get("nodeLabels")

    #     # item_node_labels 里面有两个类型
    #     # 'nodeLabels': ['MitreAttackSoftware', 'BaseEntity'], ，我要不是 BaseEntity 那个类型
    #     for node_label in item_node_labels:
    #         if node_label == "BaseEntity":
    #             continue
    #         else:
    #             item_node_return_fields = NODE_RETURN_FIELDS.get(node_label, [])

    #     # 根据 id 查询节点, 这是根节点
    #     item_root_node_data = get_neo4j_files_by_id(item_id, item_node_return_fields)
    #     for field_a in item_node_return_fields:
    #         item_all_data[field_a] = item_root_node_data.get(field_a, "")
    #     item_all_data["id"] = item_id
    #     item_all_data["nodeLabels"] = item_node_labels
    #     item_all_data["next_level"] = []

    #     # 现在查询这个节点出发 1 跳的数据，返回 1 跳的节点 id、nodeLabels、relationshipType 列表
    #     # id 用于查询具体信息，nodeLabels 用于查询应该返回的字段，relationshipType 用于查询关系类型
    #     first_hop_neighbors = get_one_hop_neighbors(item_id)
    #     for neighbor_item in first_hop_neighbors:
    #         neighbor_item_all_data = {}
    #         neighbor_id = neighbor_item.get("id")
    #         neighbor_node_labels = neighbor_item.get("nodeLabels")
    #         neighbor_relationship_type = neighbor_item.get("relationshipType")

    #         for node_label_item in neighbor_node_labels:
    #             if node_label_item == "BaseEntity":
    #                 continue
    #             else:
    #                 item_node_return_fields = NODE_RETURN_FIELDS.get(node_label_item, [])
    #         # 根据 neighbor_id 查询节点, 这是第二层根节点
    #         neighbor_first_node_data = get_neo4j_files_by_id(neighbor_id, item_node_return_fields)
    #         for field_a in item_node_return_fields:
    #             neighbor_item_all_data[field_a] = neighbor_first_node_data.get(field_a, "")
    #         neighbor_item_all_data["id"] = neighbor_id
    #         neighbor_item_all_data["nodeLabels"] = neighbor_node_labels
    #         neighbor_item_all_data["relationshipType"] = neighbor_relationship_type
    #         neighbor_item_all_data["next_level"] = []

    #         # 根据这个第一跳结点进行第二条查询
    #         second_hop_neighbors = get_one_hop_neighbors(neighbor_id)
    #         for second_neighbor_item in second_hop_neighbors:
    #             second_neighbor_id = second_neighbor_item.get("id")
    #             if second_neighbor_id == item_id:
    #                 continue
    #             second_neighbor_node_labels = second_neighbor_item.get("nodeLabels")
    #             second_neighbor_relationship_type = second_neighbor_item.get("relationshipType")

    #             for node_label_item in second_neighbor_node_labels:
    #                 if node_label_item == "BaseEntity":
    #                     continue
    #                 else:
    #                     item_node_return_fields = NODE_RETURN_FIELDS.get(node_label_item, [])
    #             second_neighbor_node_data = get_neo4j_files_by_id(second_neighbor_id, item_node_return_fields)
    #             b = {}
    #             b["id"] = second_neighbor_id
    #             b["nodeLabels"] = second_neighbor_node_labels
    #             b["relationshipType"] = second_neighbor_relationship_type
    #             for field_a in item_node_return_fields:
    #                 b[field_a] = second_neighbor_node_data.get(field_a, "")
    #             neighbor_item_all_data["next_level"].append(b)
    #         item_all_data["next_level"].append(neighbor_item_all_data)
    #     result_data.append(item_all_data)


    # if stream:
    #     # 直接调用 LLM 的流式接口
    #     return llm.invoke(
    #         prompt,
    #         message_history,
    #         system_instruction=system_instruction
    #     )
    # else:
    #     # 调用LLM获取答案
    #     answer = llm.invoke(
    #         prompt,
    #         message_history,
    #         system_instruction=system_instruction
    #     )
    #     # 返回答案内容
    #     return answer.content if hasattr(answer, 'content') else answer