import os
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from tqdm import tqdm

# 将项目根目录添加到 Python 路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from service.upload_code_service import handle_code

PROCESSED_LOG_FILE = 'processed_code_projects.log'
log_lock = threading.Lock()
thread_local = threading.local()

def get_thread_id():
    if not hasattr(thread_local, "id"):
        thread_local.id = threading.get_ident()
    return thread_local.id

def load_processed_files(log_file_path):
    """从日志文件中加载已处理的项目路径列表。"""
    if not os.path.exists(log_file_path):
        return set()
    with open(log_file_path, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)

def log_processed_file(log_file_path, project_path):
    """将成功处理的项目路径线程安全地记录到日志文件中。"""
    with log_lock:
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(project_path + '\n')

def find_git_projects(root_dir):
    """在根目录下递归查找所有包含 .git 目录的项目。"""
    project_paths = []
    print(f"开始在 '{root_dir}' 中搜索 Git 项目...")
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if '.git' in dirnames:
            project_paths.append(dirpath)
            print(f"  [发现项目] {dirpath}")
            # 找到了一个 .git 目录，我们假定这是一个项目的根目录，
            # 所以不再继续深入这个目录。
            dirnames[:] = []
    print(f"搜索完成，共发现 {len(project_paths)} 个项目。")
    return project_paths

def process_single_project(project_path, batch_number, pbar):
    """
    处理单个代码项目。
    返回一个元组 (项目路径, 是否成功, 消息)。
    """
    project_name = os.path.basename(project_path)
    thread_id = get_thread_id()
    
    def update_pbar_description(step_message):
        pbar.set_description(f"[线程 {thread_id}] {project_name}: {step_message}")

    update_pbar_description("开始处理")

    try:
        # 对于代码项目，source_name 和 file_name 都是项目目录名，
        # file_path 和 extract_dir 都是项目路径。
        # file_type 可以设为 'git' 以作区分。
        result = handle_code(
            source_name=project_name,
            file_path=project_path,
            file_name=project_name,
            file_type='git',
            extract_dir=project_path,
            insert_number=batch_number
        )
        
        if result.get("status") == "success":
            message = f"项目处理完成，批次号为: {batch_number}。"
            update_pbar_description("处理成功")
            return project_path, True, message
        else:
            error_reason = result.get('message', '未知错误')
            message = f"处理失败。原因: {error_reason}"
            update_pbar_description("处理失败")
            print(f"\n[详细错误] 项目 {project_name} 处理失败: {result}")
            return project_path, False, message
            
    except Exception as e:
        import traceback
        message = f"处理过程中发生严重异常: {e}"
        update_pbar_description("严重错误")
        print(f"\n[严重异常] 项目 {project_name} 处理时发生致命错误:")
        traceback.print_exc()
        return project_path, False, message

def main():
    """
    主函数，配置参数并使用线程池并发处理目录中的所有代码项目。
    """
    # --- 在这里配置参数 ---
    # 1. 设置要扫描的根目录
    target_directory = "/home/lyd/red-team-rag/upload_files/Ots安全"
    # 2. 设置数据导入的批次号 (对应 insert_number)
    batch_number = 3
    # 3. 设置并发处理的线程数
    max_workers = 3
    # --- 配置结束 ---

    print("开始批量导入代码项目任务...")
    print(f"目标根目录: {target_directory}")
    print(f"批次号: {batch_number}")
    print(f"并发数: {max_workers}")
    print(f"进度日志: {PROCESSED_LOG_FILE}")

    if not os.path.isdir(target_directory):
        print(f"错误：目录 '{target_directory}' 不存在或不是一个目录。")
        return

    processed_projects = load_processed_files(PROCESSED_LOG_FILE)
    print(f"已加载 {len(processed_projects)} 个已处理项目的记录。")

    all_projects = find_git_projects(target_directory)
    
    projects_to_process = [p for p in all_projects if p not in processed_projects]
    
    if not projects_to_process:
        print("所有发现的项目均已处理过，任务完成。")
        return

    print(f"准备并发处理 {len(projects_to_process)} 个新项目。")
    
    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        with tqdm(total=len(projects_to_process), desc="总体进度") as pbar:
            future_to_project = {executor.submit(process_single_project, project_path, batch_number, pbar): project_path for project_path in projects_to_process}
            
            for future in as_completed(future_to_project):
                project_path, is_success, message = future.result()
                
                if is_success:
                    log_processed_file(PROCESSED_LOG_FILE, project_path)
                    success_count += 1
                else:
                    fail_count += 1
                
                pbar.update(1)
                pbar.set_postfix_str(f"成功: {success_count}, 失败: {fail_count}")

    print("\n\n========== 任务总结 ==========")
    print("所有新项目处理完毕。")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")
    print("==============================")

if __name__ == "__main__":
    main()
