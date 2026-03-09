"""
检查本地目录与 consistency_check CSV 的一致性。

- D:\\HuaQingWeiYang\\RedTeamData\\code：代码项目压缩包（.zip, .tar.gz, .tar, .7z），对应 CSV 中 CodeSoftware
- D:\\HuaQingWeiYang\\RedTeamData\\File：上传的所有文件，对应 CSV 中 ArticleDocument

检查内容：
1. CSV 中的 CodeSoftware 是否在 code 目录存在对应压缩包（文件名去掉扩展名 = soft_name）
2. CSV 中的 ArticleDocument 是否在 File 目录存在对应文件（文件名 = soft_name）
3. code 目录中的压缩包是否在 CSV 中有对应 CodeSoftware 记录
4. File 目录中的文件是否在 CSV 中有对应 ArticleDocument 记录
"""

import sys
import os
import csv
from pathlib import Path
from typing import Dict, List, Set, Tuple

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 本地目录配置
CODE_DIR = r"D:\HuaQingWeiYang\RedTeamData\code"  # 代码项目压缩包
FILE_DIR = r"D:\HuaQingWeiYang\RedTeamData\File"  # 上传的文件

# 一致性检查 CSV 路径
CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "20260304_145233",
    "consistency_check_20260304_145233.csv",
)

# code 目录支持的压缩包扩展名
CODE_ARCHIVE_EXTENSIONS = (".zip", ".tar.gz", ".tar", ".7z")


def _archive_base_name(file_name: str) -> str:
    """获取压缩包 basename（去掉扩展名），正确处理 .tar.gz"""
    if file_name.endswith(".tar.gz"):
        return file_name[:-7]
    return Path(file_name).stem


def load_csv_records(csv_path: str) -> Tuple[Set[str], Set[str], List[dict]]:
    """
    加载 CSV，返回 (CodeSoftware 的 soft_name 集合, ArticleDocument 的 soft_name 集合, 原始行列表)
    """
    code_soft_names: Set[str] = set()
    article_soft_names: Set[str] = set()
    rows: List[dict] = []

    if not os.path.isfile(csv_path):
        return code_soft_names, article_soft_names, rows

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            sn = (row.get("soft_name") or "").strip()
            nt = (row.get("node_type") or "").strip()
            if nt == "CodeSoftware":
                code_soft_names.add(sn)
            elif nt == "ArticleDocument":
                article_soft_names.add(sn)

    return code_soft_names, article_soft_names, rows


def get_code_dir_archives() -> Dict[str, str]:
    """
    扫描 code 目录，返回 {base_name: full_file_path}
    """
    result: Dict[str, str] = {}
    code_path = Path(CODE_DIR)
    if not code_path.exists() or not code_path.is_dir():
        return result

    for f in code_path.rglob("*"):
        if not f.is_file():
            continue
        name = f.name
        if any(name.endswith(ext) for ext in CODE_ARCHIVE_EXTENSIONS):
            base = _archive_base_name(name)
            result[base] = str(f)
    return result


def get_file_dir_files() -> Set[str]:
    """
    扫描 File 目录，返回所有文件名的集合
    """
    result: Set[str] = set()
    file_path = Path(FILE_DIR)
    if not file_path.exists() or not file_path.is_dir():
        return result

    for f in file_path.rglob("*"):
        if f.is_file():
            result.add(f.name)
    return result


def run_consistency_check() -> None:
    """执行本地文件与 CSV 的一致性检查"""
    print("=" * 60)
    print("本地文件与 consistency_check CSV 一致性检查")
    print("=" * 60)
    print(f"code 目录: {CODE_DIR}")
    print(f"File 目录: {FILE_DIR}")
    print(f"CSV 文件: {CSV_PATH}")
    print()

    # 1. 加载 CSV
    code_soft_names, article_soft_names, _ = load_csv_records(CSV_PATH)
    if not code_soft_names and not article_soft_names:
        print("[WARN] CSV 文件不存在或未包含有效记录")
        return
    print(
        f"[INFO] CSV: CodeSoftware {len(code_soft_names)} 条, ArticleDocument {len(article_soft_names)} 条"
    )
    print()

    # 2. 扫描本地目录
    code_archives = get_code_dir_archives()
    file_names = get_file_dir_files()
    print(f"[INFO] code 目录: {len(code_archives)} 个压缩包")
    print(f"[INFO] File 目录: {len(file_names)} 个文件")
    print()

    # 3. 检查
    issues: List[str] = []
    ok_count = 0

    # 3.1 CSV CodeSoftware -> code 目录
    for sn in sorted(code_soft_names):
        if sn in code_archives:
            ok_count += 1
        else:
            issues.append(
                f"[缺失压缩包] CodeSoftware '{sn}' 在 code 目录中无对应压缩包"
            )

    # 3.2 CSV ArticleDocument -> File 目录
    for sn in sorted(article_soft_names):
        if sn in file_names:
            ok_count += 1
        else:
            issues.append(f"[缺失文件] ArticleDocument '{sn}' 在 File 目录中无对应文件")

    # 3.3 code 目录 -> CSV CodeSoftware
    for base in sorted(code_archives.keys()):
        if base not in code_soft_names:
            issues.append(
                f"[多余压缩包] code 目录中的 '{base}' 在 CSV 中无对应 CodeSoftware 记录"
            )

    # 3.4 File 目录 -> CSV ArticleDocument
    for fn in sorted(file_names):
        if fn not in article_soft_names:
            issues.append(
                f"[多余文件] File 目录中的 '{fn}' 在 CSV 中无对应 ArticleDocument 记录"
            )

    # 4. 输出结果
    if not issues:
        print("[OK] 全部一致，本地目录与 CSV 记录匹配。")
        return

    print(f"[RESULT] 发现 {len(issues)} 处不一致:\n")
    for s in issues:
        print(s)
    print()
    print(f"[SUMMARY] 一致项: {ok_count}, 不一致项: {len(issues)}")


if __name__ == "__main__":
    run_consistency_check()
