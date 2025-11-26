import os
from flask import Blueprint, request, jsonify
from service.upload_file_service import handle_file, save_file

upload_file_route = Blueprint('upload_file_route', __name__)


@upload_file_route.route('/upload_file', methods=['POST'])
def upload_file():
    file = request.files['file']
    if file:
        # source_name: 上传批次或来源标识; file_path: 服务器上临时保存的完整路径;
        # file_name: 原始文件名; file_type: 文件扩展名/类型，用于后续切分流程
        source_name, file_path, file_name, file_type = save_file(file)
        
        # 接下来进行文件处理
        result_dict = handle_file(source_name, file_path, file_name, file_type)
        if result_dict["status"] == "error":
            return jsonify({'code': '500', 'data': [], 'message': result_dict["message"]})
        return jsonify({'code': '200', 'data': '文件上传成功', 'message': "success"})
    else:
        return jsonify({'code': '400', 'data': [], 'message': '请上传文件'})