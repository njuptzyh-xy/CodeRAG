from flask import Blueprint, request, jsonify
from service.neo4j_service import get_description_by_id, get_data_by_id, get_detail_by_ids, get_article_and_software_count, get_articles_by_attack_id, get_all_articles, get_all_software, get_software_techniques_tactics

neo4j_route = Blueprint('neo4j_route', __name__)


@neo4j_route.route('/get_description_by_id', methods=['GET'])
def get_description_by_id_route():
    """
    功能：根据MITRE ATT&CK ID获取技术或战术的描述信息
    参数：mitre_attack_id - 技术或战术ID（如 T1001, TA0011）
    返回：描述文本
    """
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
    """
    功能：根据MITRE ATT&CK ID获取技术或战术的完整数据（包括相关文章、子技术等）
    参数：mitre_attack_id - 技术或战术ID（如 T1001, TA0011）
    返回：完整节点数据
    """
     # 获取技术或者战术 id
    mitre_attack_id = request.args.get('mitre_attack_id', None)
    if not mitre_attack_id:
        return jsonify({'code': '400', 'message': '请输入战术或者技术 id', 'data': ''})
    
    # 真正执行寻找
    data = get_data_by_id(mitre_attack_id)
    
    return jsonify({'code': '200', 'message': 'success', 'data': data})


@neo4j_route.route('/get_detail_by_ids', methods=['POST'])
def get_detail_by_ids_route():
    """
    功能：根据文章/软件ID批量获取节点详细信息（支持文章和代码块节点）
    参数：neo_ids - JSON数组，包含节点ID和类型信息
    返回：节点详细信息列表
    """
    neo_ids = request.json
    if not neo_ids:
        return jsonify({'code': '400', 'message': '请输入图数据库 neo_id', 'data': ''})
    
    # 真正执行寻找
    data = get_detail_by_ids(neo_ids)
    
    return jsonify({'code': '200', 'message': 'success', 'data': data})

@neo4j_route.route('/count', methods=['GET'])
def get_neo4j_node_count():
    """
    功能：获取Neo4j中文章和软件节点的数量统计
    返回：文章数量和软件数量
    """
    result = get_article_and_software_count()
    return jsonify(result)

@neo4j_route.route('/get_articles_by_attack_id', methods=['GET'])
def get_articles_by_attack_id_route():
    """
    功能：根据attack_id获取文章统计
    参数：attack_id - 技术或战术ID（如 T1001, TA0011）
    返回：相关文章列表
    """
    # 获取ATT&CK ID
    attack_id = request.args.get('attack_id', None)
    if not attack_id:
        return jsonify({'code': '400', 'message': '请输入ATT&CK ID', 'data': ''})

    # 执行查询
    data = get_articles_by_attack_id(attack_id)

    return jsonify({'code': '200', 'message': 'success', 'data': data})


@neo4j_route.route('/get_all_articles', methods=['GET'])
def get_all_articles_route():
    """
    功能：获取所有文章列表（支持分页）
    参数：page - 页码（默认1），per_page - 每页数量（默认50）
    返回：分页后的文章列表
    """
    # 获取分页参数（可选）
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # 执行查询
    data = get_all_articles()

    # 简单分页处理
    total_articles = data['article_count']
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    articles_page = data['articles'][start_idx:end_idx]

    # 计算分页信息
    total_pages = (total_articles + per_page - 1) // per_page

    result = {
        'article_count': total_articles,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_next': page < total_pages,
        'has_prev': page > 1,
        'articles': articles_page
    }

    return jsonify({'code': '200', 'message': 'success', 'data': result})


@neo4j_route.route('/get_all_software', methods=['GET'])
def get_all_software_route():
    """
    功能：获取所有软件列表（支持分页）
    参数：page - 页码（默认1），per_page - 每页数量（默认50）
    返回：分页后的软件列表
    """
    # 获取分页参数（可选）
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # 执行查询
    data = get_all_software()

    # 简单分页处理
    total_software = data['software_count']
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    software_page = data['software'][start_idx:end_idx]

    # 计算分页信息
    total_pages = (total_software + per_page - 1) // per_page

    result = {
        'software_count': total_software,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_next': page < total_pages,
        'has_prev': page > 1,
        'software': software_page
    }

    return jsonify({'code': '200', 'message': 'success', 'data': result})


@neo4j_route.route('/get_software_techniques_tactics', methods=['GET'])
def get_software_techniques_tactics_route():
    """
    功能：根据软件id获取软件相关的战术和技术信息
    参数：software_id - 软件ID（software_uuid）
    返回：软件涉及的战术列表和技术列表
    """
    # 获取软件ID
    software_id = request.args.get('software_id', None)
    if not software_id:
        return jsonify({'code': '400', 'message': '请输入软件ID', 'data': ''})

    # 执行查询
    data = get_software_techniques_tactics(software_id)
    

    if data['tactics_count'] == 0:
        return jsonify({'code': '200', 'message': '未找到相关战术和技术信息', 'data': data})

    return jsonify({'code': '200', 'message': 'success', 'data': data})