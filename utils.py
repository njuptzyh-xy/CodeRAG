from retrieval_route import RetrievalRoute

def query_graphrag(question):
    retrieval = RetrievalRoute(question)
    # 进行处理
    result = retrieval.handle_question()
    
    return result
    