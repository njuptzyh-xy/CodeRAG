import json
import requests
from database_helper.neo4j_helper import Neo4jHelper
from openai import OpenAI
from setting import (
    CHAT_MODEL_NAME, CHAT_MODEL_API_KEY, CHAT_URL, 
    CHAT_TEMPERATURE, CHAT_MAX_TOKENS, RERANK_URL, EMBEDDING_URL,EMBEDDING_API_KEY
)
from database_helper.es_helper import ESHelper
from utils.prompts import get_prompts


def query_graphrag(question):
    retrieval = RetrievalRoute(question)
    # 进行处理
    print("00000000000000000000000000\n")
    result = retrieval.handle_question()
    
    return result


class OpenaiEmbeddingClient:
    """自定义嵌入模型客户端，使用 requests 调用，集成 openai 接口"""
    def __init__(self, embedding_url):
        self.embedding_url = embedding_url

    def embed_query(self, text: str) -> list[float]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": EMBEDDING_API_KEY,  # 复用现有 key 变量
        }
        payload = {"texts": [text]}
        
        try:
            response = requests.post(self.embedding_url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                embeddings = data.get("embeddings")
                if embeddings:
                    return embeddings[0]
                print("[embed_query] Stella 返回为空")
                return None
            print(f"[embed_query] Stella 请求失败 status={response.status_code}, body={response.text}")
            return None
        except Exception as e:
            print(f"[embed_query] Stella 请求异常: {e}")
            return None


class CustomOpenAIEmbeddings:
    # 自定义兼容 OpenAI 接口的嵌入模型类
    def __init__(self, api_base=EMBEDDING_URL):
        self.api_base = api_base
        self.openai_client = OpenaiEmbeddingClient(embedding_url=self.api_base)
    
    def embed_query(self, text: str) -> list[float]:
        return self.openai_client.embed_query(text)


class RetrievalRoute:

    def __init__(self, question):
        """初始化，将使用的模型参数放在这里面"""
        self.model_url = CHAT_URL                                              # 模型地址
        self.model_name = CHAT_MODEL_NAME                                      # 模型名称
        self.model_api_key = CHAT_MODEL_API_KEY                                # 模型 api key
        self.model_temperature = CHAT_TEMPERATURE                              # 模型温度
        self.model_max_tokens = CHAT_MAX_TOKENS                                # 模型最大 token
        self.return_results_json = True                                        # 是否返回 json 格式
        self.es = ESHelper()                                                   # es 初始化
        self.neo4j_drive = Neo4jHelper()                                       # neo4j 初始化
        self.question = question                                               # 问题
        self.question_embedding = self._get_question_embedding()               # 问题向量
        self.strategy_dict = {                                                 # 策略字典
            "hybrid_search": self.hybrid_search, # 混合检索  全文+向量融合检索  适合问题里含具体实体、需要语义理解的场景
            "graph_search": self.graph_search, # 图谱检索  通过图谱查询  暂时未实现
            "vector_expansion": self.vector_expansion_search # 向量扩展  通过向量扩展查询  适合问题里没有具体实体、需要语义理解的场景 兜底策略
        }
        
    def _get_question_embedding(self):
         embedding_data = CustomOpenAIEmbeddings().embed_query(self.question)
         return embedding_data
    
    def send_general_request(self, prompt: str, return_results_json: bool):
        client = OpenAI(
            api_key=self.model_api_key,
            base_url=self.model_url
        )
        
        if return_results_json:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.model_temperature,
                response_format={"type": "json_object"}
            )
            response_data = json.loads(response.choices[0].message.content)
        else:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.model_temperature
            )
            response_data = response.choices[0].message.content
        
        return response_data
    
    def send_rerank_request(self, documents: list[str], top_k: int):
        # 发送重排请求
        """
        调用重排序接口对文档进行排序
        
        参数:
            query: 查询文本
            documents: 待排序的文档列表
            top_k: 返回排序后的前 k 个结果
        
        返回:
            排序后的文档及其分数
        """
        url = RERANK_URL
        headers = {
            "Content-Type": "application/json"
        }
        
        # print("=================\n", self.question)
        # print("=================\n", documents)
        # print("=================\n", top_k)
        payload = {
            "query": self.question,
            "documents": documents,
            "top_k": top_k
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # 如果请求失败则抛出异常
        response_data = response.json()
        ranked_results = response_data.get("ranked_results")
        
        # 直接处理成 index 列表
        ranked_index_list = []
        if len(ranked_results) > 1:
            for ranked_item in ranked_results:
                ranked_index_list.append(ranked_item.get("index"))
        
        return ranked_index_list
    
    def query_extend(self):
        # 将问题给到模型，让模型进行扩写
        prompt = get_prompts("query_extend")
        prompt = prompt.format(self.question)
        result = self.send_general_request(prompt, self.return_results_json)
        extend_question = result.get("question_list")
        
        return extend_question
        
    def judge_retrieval_route(self):
        """
        判断使用哪种检索方式函数，就是检索分策略函数
        """
        judge_prompt = get_prompts("judge_prompt")
        judge_prompt = judge_prompt.format(self.question)
        response_data = self.send_general_request(judge_prompt, self.return_results_json)
        
        return response_data["retrieval_strategy"]
    
    def hybrid_search(self):
        final_result= [] 
        
        # 调用 es 混合搜索
        es_data = self.es.hybrid_search(self.question, self.question_embedding) 
        
        # 接下来进行 neo4j 的数据收集和返回
        for es_item in es_data:
            es_item_neo4j_id = es_item["source"].get("neo4j_id")
            if not es_item_neo4j_id:
                print(f"警告: 跳过缺失 neo4j_id 的结果: {es_item}")
                continue
            node_data = self.neo4j_drive.get_single_point_data(es_item_neo4j_id)
            if node_data:  # 添加空值检查
                final_result.append(node_data)
        print("============================\n", final_result)
        return final_result

    def vector_expansion_search(self):
        # 先进行问题扩写并且将问题向量化
        question = self.query_extend()
        question_embedding_data = CustomOpenAIEmbeddings().embed_query(question)
        
        # 这里是之前的逻辑，就是查两跳的逻辑
        es_data = self.es.search_by_calculate_similarity(question_embedding_data)
        if len(es_data) > 0:
            # 进行重排模型重排
            # print("es_data=================\n", es_data)
            neo4j_description_list = [es_data_item.get("source").get("description") for es_data_item in es_data]
            # print("neo4j_description_list=================\n", neo4j_description_list)
            rank_index_result_list = self.send_rerank_request(neo4j_description_list, top_k=3)
            
            # 重排结果进行梳理，将这几个结点 id 进行整理
            neo4j_id_list = []
            for rank_index in rank_index_result_list:
                # neo4j_id_list.append(es_data[rank_index].get("id"))
                neo4j_id_list.append(es_data[rank_index].get("source", {}).get("neo4j_id"))
            
            # 整理好的 id 进行 延伸查询
            neo4j_search_result = self.neo4j_drive.expansion_search(neo4j_id_list)
            return neo4j_search_result
        else:
            return None

    def graph_search(self):
        print("待后续补充这中召回检索办法\n", self.question)
        pass
    
    
    def handle_question(self):
        # 先判断应该使用那个策略
        search_strategy = self.judge_retrieval_route()
        
        print("=================\n", search_strategy)
        # 有了策略之后进行分函数处理, 
        # hybrid_search 混合检索， graph_query 生成语句检索， vector_expansion 向量比对两跳查询
        result = self.strategy_dict.get(search_strategy)()
        
        return result


if __name__ == "__main__":
    question = "什么是 discovery, 他有哪些子技术？"
    retrieval_route = RetrievalRoute(question)
    retrieval_strategy = retrieval_route.vector_expansion_search()