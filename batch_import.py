import os
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from tqdm import tqdm

# 将项目根目录添加到 Python 路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from service.upload_file_service import handle_file

PROCESSED_LOG_FILE = 'processed_files.log'
log_lock = threading.Lock()
thread_local = threading.local()

def get_thread_id():
    if not hasattr(thread_local, "id"):
        thread_local.id = threading.get_ident()
    return thread_local.id

def load_processed_files(log_file_path):
    """从日志文件中加载已处理的文件名列表。"""
    if not os.path.exists(log_file_path):
        return set()
    with open(log_file_path, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)

def log_processed_file(log_file_path, file_name):
    """将成功处理的文件名线程安全地记录到日志文件中。"""
    with log_lock:
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(file_name + '\n')

def process_single_file(original_file_path, batch_number, pbar):
    """
    处理单个文件，直接使用原始文件路径进行核心服务调用。
    返回一个元组 (文件名, 是否成功, 消息)。
    """
    file_name = os.path.basename(original_file_path)
    thread_id = get_thread_id()
    
    def update_pbar_description(step_message):
        pbar.set_description(f"[线程 {thread_id}] {file_name}: {step_message}")

    update_pbar_description("开始处理")

    # 1. 验证文件类型
    name_part, ext_part = os.path.splitext(file_name)
    file_type = ext_part.lstrip('.')
    allowed_types = ['pdf', 'docx', 'doc', 'txt', 'md']
    if file_type not in allowed_types:
        message = f"不支持的文件类型: '{file_type}'"
        update_pbar_description(f"跳过 ({message})")
        return file_name, False, message

    # 2. 调用核心处理函数，直接使用原始文件
    source_name = file_name
    
    update_pbar_description("调用核心服务...")
    
    try:
        # 注意：handle_file 现在直接处理原始路径
        result = handle_file(source_name, original_file_path, file_name, file_type, batch_number)
        if result.get("status") == "success":
            message = f"文件处理完成，批次号为: {batch_number}。"
            update_pbar_description("处理成功")
            return file_name, True, message
        else:
            # 确保即使 message 是 None 或其他类型，也能安全地打印
            error_reason = result.get('message', '未知错误')
            message = f"处理失败。原因: {error_reason}"
            update_pbar_description(f"处理失败")
            print(f"\n[详细错误] 文件 {file_name} 处理失败: {result}")
            return file_name, False, message
    except Exception as e:
        import traceback
        message = f"处理过程中发生严重异常: {e}"
        update_pbar_description("严重错误")
        # 打印完整的异常堆栈信息，以便调试
        print(f"\n[严重异常] 文件 {file_name} 处理时发生致命错误:")
        traceback.print_exc()
        return file_name, False, message

def main():
    """
    主函数，配置参数并使用线程池并发处理目录中的所有文件。
    """
    # --- 在这里配置参数 ---
    # 1. 设置要处理的文件夹路径
    target_directory = "/home/lyd/red-team-rag/upload_files/Tide安全团队"
    # 2. 设置数据导入的批次号
    batch_number = 3
    # 3. 设置并发处理的线程数
    max_workers = 5
    # --- 配置结束 ---

    print("开始批量导入任务...")
    print(f"目标目录: {target_directory}")
    print(f"批次号: {batch_number}")
    print(f"并发数: {max_workers}")
    print(f"进度日志: {PROCESSED_LOG_FILE}")

    processed_files = load_processed_files(PROCESSED_LOG_FILE)
    print(f"已加载 {len(processed_files)} 个已处理文件的记录。")

    if not os.path.isdir(target_directory):
        print(f"错误：目录 '{target_directory}' 不存在或不是一个目录。")
        return

    try:
        all_files = [f for f in os.listdir(target_directory) if os.path.isfile(os.path.join(target_directory, f))]
    except Exception as e:
        print(f"错误：无法读取目录 '{target_directory}' 中的文件: {e}")
        return
        
    files_to_process = [f for f in all_files if f not in processed_files]
    
    if not files_to_process:
        print("所有文件均已处理过，任务完成。")
        return

    print(f"准备并发处理 {len(files_to_process)} 个新文件。")
    
    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        with tqdm(total=len(files_to_process), desc="总体进度") as pbar:
            # 提交所有任务到线程池
            future_to_file = {executor.submit(process_single_file, os.path.join(target_directory, file_name), batch_number, pbar): file_name for file_name in files_to_process}
            
            for future in as_completed(future_to_file):
                file_name, is_success, message = future.result()
                
                if is_success:
                    log_processed_file(PROCESSED_LOG_FILE, file_name)
                    success_count += 1
                else:
                    fail_count += 1
                
                pbar.update(1)
                pbar.set_postfix_str(f"成功: {success_count}, 失败: {fail_count}")

    print("\n\n========== 任务总结 ==========")
    print("所有新文件处理完毕。")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")
    print("==============================")

if __name__ == "__main__":
    main()
