"""
检查指定路径下文件在 Neo4j 和 Milvus 数据库中的数据一致性脚本

功能：
1. 检索指定路径下的所有文件
2. 对每个文件，检查其在 Neo4j 和 Milvus 数据库中的数据是否一致
3. 生成 CSV 报告并保存到 check\timestamp 目录
"""

import sys
import os
import csv
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymilvus import Collection, connections, utility
from pymilvus.exceptions import MilvusException
from database_helper.neo4j_helper import Neo4jHelper
import setting

# 导入 check_consistency.py 中的函数
from check.check_consistency import (
    _remove_file_extension,
    check_node_type,
    query_code_chunks_by_software_name,
    query_article_chunks_by_document_title,
)


def get_files_from_directory(directory_path: str) -> List[str]:
    """
    检索指定目录下的所有文件

    Args:
        directory_path: 目录路径

    Returns:
        文件路径列表
    """
    files = []
    directory = Path(directory_path)

    if not directory.exists():
        print(f"[FAIL] 目录不存在: {directory_path}")
        return files

    if not directory.is_dir():
        print(f"[FAIL] 路径不是目录: {directory_path}")
        return files

    print(f"[INFO] 开始扫描目录: {directory_path}")

    # 递归扫描所有文件
    for file_path in directory.rglob("*"):
        if file_path.is_file():
            files.append(str(file_path))

    print(f"[INFO] 找到 {len(files)} 个文件")
    return files


def get_milvus_count_by_softname(soft_name: str, collection: Collection) -> int:
    """
    查询 Milvus 中指定 soft_name 的记录数量

    Args:
        soft_name: 软件名或文档名
        collection: Milvus collection 对象

    Returns:
        记录数量
    """
    try:
        # 查询指定 soft_name 的记录数量
        # 使用 expr 过滤条件，需要转义引号
        expr = f'soft_name == "{soft_name}"'
        result = collection.query(
            expr=expr,
            output_fields=["neo4j_id"],
            limit=2147483647,  # 最大限制
        )
        return len(result) if result else 0
    except Exception as e:
        print(f"[WARN] 查询 Milvus 失败 (soft_name={soft_name}): {e}")
        return 0


def check_file_consistency(
    file_path: str, collection: Collection, neo4j_helper: Neo4jHelper
) -> Dict[str, Any]:
    """
    检查单个文件在 Neo4j 和 Milvus 中的数据一致性

    Args:
        file_path: 文件路径
        collection: Milvus collection 对象
        neo4j_helper: Neo4j 连接助手

    Returns:
        检查结果字典
    """
    # 获取文件名（不含路径）
    file_name = os.path.basename(file_path)
    # 获取文件名（不含扩展名），用于查询 Neo4j
    file_name_without_ext = _remove_file_extension(file_name)

    print(f"\n[INFO] 检查文件: {file_name}")

    # 1. 查询 Milvus 中的记录数量（使用完整文件名）
    milvus_count = get_milvus_count_by_softname(file_name, collection)
    print(f"  [INFO] Milvus 记录数: {milvus_count} (soft_name={file_name})")

    # 2. 判断节点类型并查询 Neo4j 中的 chunk 数量
    # 先尝试用完整文件名查询（可能是 CodeSoftware）
    node_type = check_node_type(file_name, neo4j_helper)

    # 如果没找到，尝试用去掉扩展名的文件名查询（可能是 ArticleDocument）
    if not node_type:
        node_type = check_node_type(file_name_without_ext, neo4j_helper)
        if node_type:
            # 如果找到了，说明是 ArticleDocument，使用去掉扩展名的名称
            file_name_for_query = file_name_without_ext
        else:
            # 都没找到
            file_name_for_query = file_name
    else:
        # 找到了 CodeSoftware，使用完整文件名
        file_name_for_query = file_name

    if not node_type:
        print(f"  [WARN] 在 Neo4j 中未找到该文件（既不是 CodeSoftware 也不是 ArticleDocument）")
        neo4j_count = 0
    else:
        print(f"  [INFO] 节点类型: {node_type}")

        # 根据节点类型查询 chunk 数量
        if node_type == "CodeSoftware":
            neo4j_count = query_code_chunks_by_software_name(
                file_name_for_query, neo4j_helper
            )
        elif node_type == "ArticleDocument":
            neo4j_count = query_article_chunks_by_document_title(
                file_name, neo4j_helper  # 传入完整文件名，函数内部会去掉扩展名
            )
        else:
            neo4j_count = 0

        print(f"  [INFO] Neo4j chunk 数: {neo4j_count}")

    # 3. 比对结果
    is_consistent = milvus_count == neo4j_count
    difference = milvus_count - neo4j_count

    status = "一致" if is_consistent else "不一致"
    print(f"  [INFO] 一致性: {status} (差异: {difference})")

    return {
        "file_path": file_path,
        "file_name": file_name,
        "milvus_count": milvus_count,
        "neo4j_count": neo4j_count,
        "difference": difference,
        "is_consistent": status,
        "node_type": node_type or "NotFound",
    }


def check_all_files_consistency(
    directory_path: str,
) -> List[Dict[str, Any]]:
    """
    检查指定目录下所有文件的数据一致性

    Args:
        directory_path: 目录路径

    Returns:
        检查结果列表
    """
    # 1. 获取所有文件
    files = get_files_from_directory(directory_path)
    if not files:
        print("[FAIL] 未找到任何文件")
        return []

    # 2. 初始化数据库连接
    print("\n" + "=" * 80)
    print("初始化数据库连接")
    print("=" * 80)

    # 连接 Milvus
    try:
        connections.connect(
            alias="default",
            host=setting.MILVUS_HOST,
            port=str(setting.MILVUS_PORT),
            user=setting.MILVUS_USER,
            password=setting.MILVUS_PASSWORD,
            db_name=setting.MILVUS_DB_NAME,
            secure=setting.MILVUS_SECURE,
        )
        print(
            f"[INFO] Milvus 连接成功: {setting.MILVUS_HOST}:{setting.MILVUS_PORT}"
        )
    except Exception as e:
        if "already exists" not in str(e).lower():
            print(f"[WARN] Milvus 连接检查: {e}")

    if not utility.has_collection(setting.MILVUS_COLLECTION):
        print(f"[FAIL] Collection {setting.MILVUS_COLLECTION} 不存在")
        return []

    collection = Collection(setting.MILVUS_COLLECTION)
    collection.load()

    # 连接 Neo4j
    neo4j_helper = Neo4jHelper()
    if not neo4j_helper or not neo4j_helper.neo4j_driver:
        print("[FAIL] Neo4j 连接失败")
        return []

    print("[OK] Neo4j 连接成功")

    # 3. 检查每个文件
    print("\n" + "=" * 80)
    print(f"开始检查 {len(files)} 个文件")
    print("=" * 80)

    results = []
    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] 处理文件...")
        try:
            result = check_file_consistency(file_path, collection, neo4j_helper)
            results.append(result)
        except Exception as e:
            print(f"[FAIL] 检查文件失败 {file_path}: {e}")
            import traceback

            traceback.print_exc()
            results.append(
                {
                    "file_path": file_path,
                    "file_name": os.path.basename(file_path),
                    "milvus_count": 0,
                    "neo4j_count": 0,
                    "difference": 0,
                    "is_consistent": "错误",
                    "node_type": "Error",
                }
            )

    return results


def save_results(results: List[Dict[str, Any]], directory_path: str) -> str:
    """
    保存检查结果到 CSV 文件

    Args:
        results: 检查结果列表
        directory_path: 原始目录路径

    Returns:
        保存的文件路径
    """
    # 创建输出目录（使用时间戳）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(script_dir, timestamp)
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[INFO] 开始保存结果到: {output_dir}")

    # 保存检查结果到 CSV
    csv_file_path = os.path.join(output_dir, f"fail_file_check_{timestamp}.csv")
    try:
        with open(csv_file_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "file_path",
                "file_name",
                "milvus_count",
                "neo4j_count",
                "difference",
                "is_consistent",
                "node_type",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            # 按差异大小排序（不一致的排在前面）
            sorted_results = sorted(
                results,
                key=lambda x: (
                    0 if x["is_consistent"] == "一致" else 1,
                    abs(x["difference"]),
                ),
                reverse=True,
            )

            for row in sorted_results:
                writer.writerow(row)

        print(f"[OK] 已保存检查结果到: {os.path.basename(csv_file_path)}")
    except Exception as e:
        print(f"[FAIL] 保存检查结果失败: {e}")
        import traceback

        traceback.print_exc()

    # 打印统计摘要
    total_files = len(results)
    consistent_count = sum(1 for r in results if r["is_consistent"] == "一致")
    inconsistent_count = sum(1 for r in results if r["is_consistent"] == "不一致")
    not_found_count = sum(1 for r in results if r["node_type"] == "NotFound")
    error_count = sum(1 for r in results if r["is_consistent"] == "错误")

    print(f"\n[INFO] 检查结果统计:")
    print(f"  - 总文件数: {total_files}")
    print(f"  - 一致的数量: {consistent_count}")
    print(f"  - 不一致的数量: {inconsistent_count}")
    print(f"  - Neo4j 中未找到的数量: {not_found_count}")
    if error_count > 0:
        print(f"  - 检查出错的数量: {error_count}")

    if inconsistent_count > 0:
        print(f"\n[WARNING] 发现 {inconsistent_count} 个不一致的文件")
        print(f"[WARNING] 前10个不一致的文件:")
        for i, row in enumerate(results[:10], 1):
            if row["is_consistent"] == "不一致":
                print(
                    f"  {i}. {row['file_name']}: Milvus={row['milvus_count']}, Neo4j={row['neo4j_count']}, 差异={row['difference']}"
                )

    return csv_file_path


def main():
    """主函数"""
    print("=" * 80)
    print("检查指定路径下文件的数据一致性脚本")
    print("=" * 80)

    # 指定目录路径
    directory_path = r"D:\HuaQingWeiYang\RedTeamRAG上传脚本\uploadFileFail"

    print(f"\n[INFO] 目标目录: {directory_path}")

    # 检查所有文件
    results = check_all_files_consistency(directory_path)

    if not results:
        print("[FAIL] 未获取到任何检查结果")
        return

    # 保存结果
    print("\n" + "=" * 80)
    print("保存检查结果")
    print("=" * 80)

    csv_path = save_results(results, directory_path)

    print("\n" + "=" * 80)
    print("检查完成")
    print("=" * 80)
    print(f"结果已保存到: {csv_path}")


if __name__ == "__main__":
    main()