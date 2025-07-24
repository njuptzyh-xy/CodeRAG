from flask import Blueprint, request, jsonify
from service.neo4j_service import get_description_by_id, get_data_by_id, get_detail_by_ids

neo4j_route = Blueprint('neo4j_route', __name__)


@neo4j_route.route('/get_description_by_id', methods=['GET'])
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


@neo4j_route.route('/get_data_by_id', methods=['GET'])
def get_data_by_id_route():
     # 获取技术或者战术 id
    mitre_attack_id = request.args.get('mitre_attack_id', None)
    if not mitre_attack_id:
        return jsonify({'code': '400', 'message': '请输入战术或者技术 id', 'data': ''})
    
    # 真正执行寻找
    data = get_data_by_id(mitre_attack_id)
    
    return jsonify({'code': '200', 'message': 'success', 'data': data})


@neo4j_route.route('/get_detail_by_ids', methods=['POST'])
def get_detail_by_ids_route():
    neo_ids = request.json
    if not neo_ids:
        return jsonify({'code': '400', 'message': '请输入图数据库 neo_id', 'data': ''})
    
    # 真正执行寻找
    data = get_detail_by_ids(neo_ids)
    
    return jsonify({'code': '200', 'message': 'success', 'data': data})