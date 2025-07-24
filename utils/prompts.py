prompts_dict = {
    "query_extend": """
        你是一名安全知识专家，精通 mitre-attack 攻击阶段，现在需按规则扩写用户问题：  
        1. 补充缺失属性特征。 
        2. 术语标准化：比如技术就是指mitre-attack战术下的技术或者技术下的子技术， 
        注意：不是所有的技术都是子技术。战术就是指mitre-attack框架中的战术。  
        
        要扩写的问题：{}
        如果觉得没有什么需要修改的那就原问题输出。注意输出英文！
        
        请以json格式返回，json格式如下：
                
        {{
            "question_list": "question_result"
        }}
                
            请确保回复是严格有效的JSON格式，不要添加任何额外的文本。
    """,
    "judge_prompt": """
            根据查询特性选择最佳检索方式：

            hybrid_search：含具体实体且需语义理解。

            vector_expansion：非 hybrid_search 类型的问题也就是兜底方案。

            查询：{}
            只输出两种类型之一，不加解释。
            输出 json 格式 {{"retrieval_strategy": "hybrid_search" | "vector_expansion"}}
        """
        # "judge_prompt": """
        #     根据查询特性选择最佳检索方式：

        #     hybrid_search：含具体实体且需语义理解。

        #     graph_query：明确关系或路径查询。

        #     vector_expansion：开放型探索问题。

        #     查询：{}
        #     只输出三种类型之一，不加解释。
        #     输出格式 {{"retrieval_strategy": "hybrid_search" | "graph_query" | "vector_expansion"}}
        # """
}

def get_prompts(prompt_key):
    return prompts_dict.get(prompt_key)