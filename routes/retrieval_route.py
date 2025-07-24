from flask import Blueprint, request, jsonify
from service.retrieval_service import query_graphrag

retrieval_route = Blueprint('retrieval_route', __name__)

@retrieval_route.route('/query', methods=['GET'])
def query():
    # 获取问题和流式参数
    question = request.args.get('question', None)
    
    if question is None:
        return jsonify({'code': '400', 'data': [], 'message': '请输入问题'})
    
    # 非流式响应处理
    try:
        answer = query_graphrag(question)
        return jsonify({'code': '200', 'data': answer, 'message': "success"})
    except Exception as e:
        return jsonify({'code': '500', 'data': [], 'message': f'处理请求时出错: {str(e)}'})