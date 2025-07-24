import os
from flask import Blueprint, request, jsonify
from service.upload_file_service import handle_file

upload_file_route = Blueprint('upload_file_route', __name__)


@upload_file_route.route('/upload_file', methods=['POST'])
def upload():
    file = request.files['file']
    if file:
        upload_file_dir = 'upload_file'  # 相对于项目根目录
        # 确保目录存在
        if not os.path.exists(upload_file_dir):
            os.makedirs(upload_file_dir)
        
        # 安全处理文件名
        filename = file.filename
        file_path = os.path.join(upload_file_dir, filename)
        
        # 保存到指定目录
        file.save(file_path)
        
        # 接下来进行文件处理
        handle_file(filename)
        
        return jsonify({'code': '200', 'data': '文件上传成功', 'message': "success"})
    else:
        return jsonify({'code': '400', 'data': [], 'message': '请上传文件'})