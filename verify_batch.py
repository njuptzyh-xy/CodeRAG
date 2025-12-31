import os
import sys
from pathlib import Path

# 需要统计的代码文件扩展名
CODE_EXTENSIONS = {
    '.py', '.java', '.c', '.cpp', '.h', '.hpp', '.go', '.rs', 
    '.cs', '.js', '.ts', '.sh', '.ps1', '.rb', '.php', '.swift',
    '.kt', '.scala', '.r', '.pl', '.lua', '.m', '.mm'
}

# 忽略的目录
IGNORE_DIRS = {
    '.git', '.svn', '.hg', '__pycache__', 'node_modules', 
    '.vscode', '.idea', 'build', 'dist', 'target', 'bin', 'obj',
    '.pytest_cache', '.mypy_cache', 'venv', 'env', '.env'
}

# 忽略的文件
IGNORE_FILES = {
    '.gitignore', '.gitattributes', '.DS_Store', 'Thumbs.db',
    '.pylintrc', '.flake8', 'pytest.ini', 'setup.cfg', 'tox.ini'
}

def should_ignore_dir(dir_name, count_hidden=False):
    """检查目录是否应该被忽略"""
    # 如果不统计隐藏文件，忽略所有以.开头的目录
    if not count_hidden and dir_name.startswith('.'):
        return True
    
    # 检查是否在忽略列表中
    if dir_name in IGNORE_DIRS:
        return True
    
    return False

def should_ignore_file(file_name, count_hidden=False):
    """检查文件是否应该被忽略"""
    # 如果不统计隐藏文件，忽略所有以.开头的文件
    if not count_hidden and file_name.startswith('.'):
        return True
    
    # 检查是否在忽略列表中
    if file_name in IGNORE_FILES:
        return True
    
    return False

def count_code_files_in_directory(directory, count_hidden=False, recursive=True):
    """
    统计指定路径下的代码文件数量（忽略特定目录和文件）
    
    参数:
    directory: 要统计的目录路径
    count_hidden: 是否统计隐藏文件（默认False）
    recursive: 是否递归统计子目录（默认True）
    
    返回:
    代码文件数量
    """
    try:
        # 确保目录存在
        if not os.path.exists(directory):
            print(f"错误：目录 '{directory}' 不存在")
            return 0
            
        if not os.path.isdir(directory):
            print(f"错误：'{directory}' 不是目录")
            return 0
            
        code_file_count = 0
        
        if recursive:
            # 递归统计所有子目录
            for root, dirs, files in os.walk(directory, topdown=True):
                # 过滤需要忽略的目录
                dirs[:] = [d for d in dirs if not should_ignore_dir(d, count_hidden)]
                
                # 如果不统计隐藏文件，过滤隐藏文件
                if not count_hidden:
                    files = [f for f in files if not f.startswith('.')]
                
                # 过滤需要忽略的文件
                files = [f for f in files if not should_ignore_file(f, count_hidden)]
                
                # 统计代码文件
                for file in files:
                    # 获取文件扩展名
                    _, ext = os.path.splitext(file)
                    ext = ext.lower()
                    
                    # 检查是否是代码文件扩展名
                    if ext in CODE_EXTENSIONS:
                        code_file_count += 1
                        
                        # 调试信息（可选）
                        # file_path = os.path.join(root, file)
                        # print(f"找到代码文件: {os.path.relpath(file_path, directory)}")
        else:
            # 仅统计当前目录
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_file():
                        # 检查是否忽略该文件
                        if should_ignore_file(entry.name, count_hidden):
                            continue
                            
                        # 获取文件扩展名
                        _, ext = os.path.splitext(entry.name)
                        ext = ext.lower()
                        
                        # 检查是否是代码文件扩展名
                        if ext in CODE_EXTENSIONS:
                            code_file_count += 1
        
        return code_file_count
        
    except PermissionError:
        print(f"错误：没有权限访问目录 '{directory}'")
        return 0
    except Exception as e:
        print(f"发生错误：{e}")
        return 0

def get_detailed_stats(directory, count_hidden=False):
    """
    获取详细的统计信息
    """
    stats = {
        'total_files': 0,
        'ignored_dirs': 0,
        'ignored_files': 0,
        'extension_count': {},
        'ignored_extensions': {}
    }
    
    try:
        for root, dirs, files in os.walk(directory, topdown=True):
            # 统计忽略的目录
            ignored_in_this_dir = [d for d in dirs if should_ignore_dir(d, count_hidden)]
            stats['ignored_dirs'] += len(ignored_in_this_dir)
            
            # 过滤目录
            dirs[:] = [d for d in dirs if not should_ignore_dir(d, count_hidden)]
            
            # 过滤隐藏文件（如果需要）
            if not count_hidden:
                files = [f for f in files if not f.startswith('.')]
            
            # 统计代码文件
            for file in files:
                # 检查是否忽略该文件
                if should_ignore_file(file, count_hidden):
                    stats['ignored_files'] += 1
                    continue
                
                # 获取文件扩展名
                _, ext = os.path.splitext(file)
                ext = ext.lower()
                
                # 检查是否是代码文件扩展名
                if ext in CODE_EXTENSIONS:
                    stats['total_files'] += 1
                    stats['extension_count'][ext] = stats['extension_count'].get(ext, 0) + 1
                else:
                    # 统计非代码文件扩展名
                    stats['ignored_extensions'][ext] = stats['ignored_extensions'].get(ext, 0) + 1
        
        # 对统计结果排序
        stats['extension_count'] = dict(sorted(stats['extension_count'].items(), 
                                              key=lambda x: x[1], reverse=True))
        stats['ignored_extensions'] = dict(sorted(stats['ignored_extensions'].items(),
                                                 key=lambda x: x[1], reverse=True))
        
        return stats
    except Exception as e:
        print(f"获取详细统计时出错：{e}")
        return stats

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='统计指定路径下的代码文件数量（自动忽略常见无关目录）')
    parser.add_argument('directory', nargs='?', default='.', 
                       help='要统计的目录路径（默认当前目录）')
    parser.add_argument('-a', '--all', action='store_true',
                       help='统计所有文件，包括隐藏文件（但仍会忽略IGNORE列表中的项）')
    parser.add_argument('-d', '--details', action='store_true',
                       help='显示详细统计信息')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='显示调试信息')
    parser.add_argument('--no-recursive', action='store_true',
                       help='不递归统计，仅统计当前目录')
    
    args = parser.parse_args()
    
    # 获取目录路径
    target_dir = os.path.abspath(args.directory)
    
    print(f"正在统计目录：{target_dir}")
    print("-" * 70)
    
    # 显示配置信息
    print("配置信息：")
    print(f"  - 统计的文件类型：{len(CODE_EXTENSIONS)} 种代码文件")
    print(f"  - 忽略的目录：{len(IGNORE_DIRS)} 种常见开发目录")
    print(f"  - 忽略的文件：{len(IGNORE_FILES)} 种常见配置文件")
    
    if args.all:
        print("  - 包含隐藏文件：是（但仍会忽略IGNORE列表中的项）")
    else:
        print("  - 包含隐藏文件：否")
    
    print("-" * 70)
    
    # 统计代码文件数量
    recursive = not args.no_recursive
    code_file_count = count_code_files_in_directory(
        target_dir, 
        count_hidden=args.all,
        recursive=recursive
    )
    
    if recursive:
        print(f"✓ 代码文件总数（递归统计，已过滤无关目录）：{code_file_count}")
    else:
        print(f"✓ 代码文件总数（仅当前目录）：{code_file_count}")
    
    # 如果需要显示详细信息
    if args.details:
        print("-" * 70)
        print("详细统计信息：")
        
        stats = get_detailed_stats(target_dir, count_hidden=args.all)
        
        if stats['total_files'] > 0:
            print(f"\n找到的代码文件：{stats['total_files']} 个")
            
            if stats['extension_count']:
                print("\n按扩展名统计：")
                total_code = sum(stats['extension_count'].values())
                for ext, count in stats['extension_count'].items():
                    percentage = (count / total_code * 100) if total_code > 0 else 0
                    print(f"  {ext:<8}: {count:>6} 个 ({percentage:.1f}%)")
            
            # 显示忽略的信息
            if stats['ignored_dirs'] > 0 or stats['ignored_files'] > 0:
                print(f"\n忽略统计：")
                print(f"  - 跳过的目录：{stats['ignored_dirs']} 个")
                print(f"  - 跳过的文件：{stats['ignored_files']} 个")
                
                if args.verbose and stats['ignored_extensions']:
                    print(f"  - 非代码文件类型：")
                    for ext, count in list(stats['ignored_extensions'].items())[:10]:
                        print(f"    {ext:<8}: {count:>4} 个")
                    if len(stats['ignored_extensions']) > 10:
                        print(f"    ... 还有 {len(stats['ignored_extensions']) - 10} 种其他类型")
            
            # 显示未找到的扩展名
            found_extensions = set(stats['extension_count'].keys())
            not_found = CODE_EXTENSIONS - found_extensions
            if not_found:
                print(f"\n未找到的文件类型：{', '.join(sorted(not_found))}")
        else:
            print("未找到代码文件")
    
    print("-" * 70)

if __name__ == "__main__":
    main()