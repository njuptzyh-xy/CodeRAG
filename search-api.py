from flask import Flask, request, jsonify, Response, stream_with_context
from utils import query_graphrag
from api_tool import get_description_by_id, get_data_by_id, get_detail_by_ids
import json

# 创建 Flask 应用
app = Flask(__name__)


# 定义一个简单的 GET 接口
@app.route('/rag_api/query', methods=['GET'])
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
        
        
@app.route('/rag_api/get_description_by_id', methods=['GET'])
def get_description_by_id_route():
    # 获取技术或者战术 id
    mitre_attack_id = request.args.get('mitre_attack_id', None)
    if not mitre_attack_id:
        return jsonify({'code': '400', 'description': '', 'message': '请输入战术或者技术 id'})
    
    # 真正的执行逻辑
    description = get_description_by_id(mitre_attack_id)
    
    if description is None:
        return jsonify({'code': '400', 'description': '', 'message': '没找到对应的技术或者战术'})
    
    return jsonify({'code': '200', 'description': description, 'message': 'success'})


@app.route('/rag_api/get_data_by_id', methods=['GET'])
def get_data_by_id_route():
     # 获取技术或者战术 id
    mitre_attack_id = request.args.get('mitre_attack_id', None)
    if not mitre_attack_id:
        return jsonify({'code': '400', 'message': '请输入战术或者技术 id', 'data': ''})
    
    # 真正执行寻找
    data = get_data_by_id(mitre_attack_id)
    
    return jsonify({'code': '200', 'message': 'success', 'data': data})


@app.route('/rag_api/get_detail_by_ids', methods=['POST'])
def get_detail_by_ids_route():
    neo_ids = request.json
    if not neo_ids:
        return jsonify({'code': '400', 'message': '请输入图数据库 neo_id', 'data': ''})
    
    # 真正执行寻找
    data = get_detail_by_ids(neo_ids)
    
    return jsonify({'code': '200', 'message': 'success', 'data': data})
    

# 启动应用
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)