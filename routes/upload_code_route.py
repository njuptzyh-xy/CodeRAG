from flask import Blueprint, request, jsonify
from service.upload_code_service import save_file_and_extract, handle_code

upload_code_route = Blueprint('upload_code_route', __name__)


@upload_code_route.route('/upload_code', methods=['POST'])
def upload_code():
    code_file = request.files['file']
    if code_file:
        # distsat308 
        # upload_code/distsat308_20250804185904.7z 
        # distsat308_20250804185904.7z 
        # 7z 
        # upload_code/distsat308_20250804185904
        source_name, file_path, file_name, file_type, extract_dir = save_file_and_extract(code_file)
        # 接下来进行代码处理
        result_dict = handle_code(source_name, file_path, file_name, file_type, extract_dir)
        if result_dict["status"] == "error":
            return jsonify({'code': '500', 'data': [], 'message': result_dict["message"]})
        return jsonify({'code': '200', 'data': '文件上传成功', 'message': "success"})
    else:
        return jsonify({'code': '400', 'data': [], 'message': '请上传文件'})