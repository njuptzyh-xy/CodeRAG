"""
检查 Neo4j 和 Milvus 数据库一致性脚本

功能：
1. 统计 Milvus 数据库中所有的 soft_name 及其记录数量
2. 对于没有 soft_name 的记录，提示 warning 并单独记录相关 neo4j_id
3. 根据第一步统计的 soft_name，查询 Neo4j 中每个 soft_name 关联的 CodeChunk 或 ArticleChunk 数量
4. 比对两种统计数量是否一致，生成 CSV 报告并保存到 check\timestamp 目录
"""

import sys
import os
import csv
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymilvus import Collection, connections, utility
from pymilvus.exceptions import MilvusException
from database_helper.neo4j_helper import Neo4jHelper
import setting


def _remove_file_extension(name: str) -> str:
    """
    去除文件名后缀。

    由于 ArticleDocument 类型节点的 title 属性在 Neo4j 中肯定不带文件后缀，
    这里可以直接去掉最后一个点号及其之后的内容（如果存在）。
    """
    if "." not in name:
        return name
    # 直接截取最后一个点号之前的部分
    return name.rsplit(".", 1)[0]


def check_node_type(soft_name: str, neo4j_helper: Neo4jHelper) -> Optional[str]:
    """
    检查 soft_name 对应的是 CodeSoftware 还是 ArticleDocument 节点

    Args:
        soft_name: 软件名或文档名
        neo4j_helper: Neo4j 连接助手

    Returns:
        "CodeSoftware" 或 "ArticleDocument" 或 None（未找到）
    """
    # 先查询 CodeSoftware
    code_query = """
    MATCH (software:MitreAttackCodeSoftware)
    WHERE software.name = $soft_name
    RETURN elementId(software) AS element_id
    LIMIT 1
    """

    with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
        result = session.run(code_query, soft_name=soft_name)
        if result.single():
            return "CodeSoftware"

    # 再查询 ArticleDocument
    article_query = """
    MATCH (document:MitreAttackArticleDocument)
    WHERE document.title = $soft_name
    RETURN elementId(document) AS element_id
    LIMIT 1
    """

    # 去除文件后缀后再查询（因为 Neo4j 中的 title 不包含文件后缀）
    title_without_ext = _remove_file_extension(soft_name)
    with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
        result = session.run(article_query, soft_name=title_without_ext)
        if result.single():
            return "ArticleDocument"

    return None


def query_code_chunks_by_software_name(
    soft_name: str, neo4j_helper: Neo4jHelper
) -> int:
    """
    查询 CodeSoftware 关联的所有 CodeChunk 的数量

    Args:
        soft_name: 软件名
        neo4j_helper: Neo4j 连接助手

    Returns:
        CodeChunk 的数量
    """
    query = """
    MATCH (software:MitreAttackCodeSoftware)
    WHERE software.name = $soft_name
    OPTIONAL MATCH (software)-[:CODE_SOFTWARE_HAS_CODE_SOFTWARE_FILE]->
                  (file:MitreAttackCodeSoftwareFile)
    OPTIONAL MATCH (file)-[:CODE_SOFTWARE_FILE_HAS_CODE_SOFTWARE_CODE_CHUNK]->
                  (code:MitreAttackCodeSoftwareCodeChunk)
    RETURN COUNT(DISTINCT code) AS chunk_count
    """

    with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
        result = session.run(query, soft_name=soft_name)
        record = result.single()
        if record:
            return record.get("chunk_count", 0) or 0
    return 0


def query_article_chunks_by_document_title(
    soft_name: str, neo4j_helper: Neo4jHelper
) -> int:
    """
    查询 ArticleDocument 关联的所有 ArticleChunk 的数量

    Args:
        soft_name: 文档标题（可能包含文件后缀，但 Neo4j 中的 title 不包含后缀）
        neo4j_helper: Neo4j 连接助手

    Returns:
        ArticleChunk 的数量
    """
    query = """
    MATCH (document:MitreAttackArticleDocument)
    WHERE document.title = $soft_name
    OPTIONAL MATCH (document)-[:DOCUMENT_HAS_CHUNK]->
                  (chunk:MitreAttackArticleChunk)
    RETURN COUNT(DISTINCT chunk) AS chunk_count
    """

    # 去除文件后缀后再查询（因为 Neo4j 中的 title 不包含文件后缀）
    title_without_ext = _remove_file_extension(soft_name)
    with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
        result = session.run(query, soft_name=title_without_ext)
        record = result.single()
        if record:
            return record.get("chunk_count", 0) or 0
    return 0


def get_milvus_softname_stats() -> Dict[str, Any]:
    """
    统计 Milvus 数据库中所有的 soft_name 及其记录数量

    Returns:
        返回字典，包含:
        - softname_stats: 每个 soft_name 的统计信息 {soft_name: count}
        - no_softname_count: 没有 soft_name 的记录数量
        - no_softname_records: 没有 soft_name 的记录列表（neo4j_id）
        - total_count: 总记录数
    """
    try:
        # 检查 Milvus 连接
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

        # 检查 collection 是否存在
        if not utility.has_collection(setting.MILVUS_COLLECTION):
            print(f"[FAIL] Collection {setting.MILVUS_COLLECTION} 不存在")
            return {
                "softname_stats": {},
                "no_softname_count": 0,
                "no_softname_records": [],
                "total_count": 0,
            }

        # 获取 collection 并加载
        collection = Collection(setting.MILVUS_COLLECTION)
        collection.load()

        print(f"[INFO] 开始查询所有记录...")

        # 按 soft_name 分组存储记录数量
        softname_counts = defaultdict(int)  # {soft_name: count}
        no_softname_records = []  # 没有 soft_name 的记录

        # 使用迭代器查询所有记录（避免内存问题）
        try:
            # 尝试使用 query_iterator（更高效）
            iterator = collection.query_iterator(
                batch_size=1000,
                filter="",  # 查询所有记录
                output_fields=["neo4j_id", "soft_name"],
                limit=2147483647,  # 最大限制
            )

            print("[INFO] 使用 query_iterator 查询...")
            batch_count = 0
            total_records = 0

            while True:
                batch = iterator.next()
                if not batch:
                    break

                batch_count += 1
                total_records += len(batch)

                # 处理当前批次
                for item in batch:
                    soft_name = item.get("soft_name")
                    neo4j_id = item.get("neo4j_id")

                    if not soft_name or soft_name == "" or soft_name.strip() == "":
                        # 没有 soft_name 的记录
                        if neo4j_id:
                            no_softname_records.append(neo4j_id)
                    else:
                        # 有 soft_name 的记录
                        softname_counts[soft_name] += 1

                if batch_count % 10 == 0:
                    print(f"[INFO] 已处理 {total_records} 条记录...")

            iterator.close()
            print(f"[INFO] 使用 query_iterator 完成，共处理 {total_records} 条记录")

        except Exception as e:
            print(f"[WARN] query_iterator 不可用，回退到传统查询方式: {e}")

            # 回退方案：使用 offset 分页查询
            offset = 0
            batch_size = 1000
            total_records = 0

            while True:
                result = collection.query(
                    expr="",  # 查询所有记录
                    output_fields=["neo4j_id", "soft_name"],
                    limit=batch_size,
                    offset=offset,
                )

                if not result:
                    break

                total_records += len(result)

                # 处理当前批次
                for item in result:
                    soft_name = item.get("soft_name")
                    neo4j_id = item.get("neo4j_id")

                    if not soft_name or soft_name == "" or soft_name.strip() == "":
                        # 没有 soft_name 的记录
                        if neo4j_id:
                            no_softname_records.append(neo4j_id)
                    else:
                        # 有 soft_name 的记录
                        softname_counts[soft_name] += 1

                offset += len(result)

                if offset % 5000 == 0:
                    print(f"[INFO] 已处理 {offset} 条记录...")

            print(f"[INFO] 传统查询完成，共处理 {total_records} 条记录")

        # 转换为普通字典
        softname_stats = dict(softname_counts)
        total_count = sum(softname_counts.values()) + len(no_softname_records)

        print(f"\n[INFO] Milvus 统计完成:")
        print(f"  - 总记录数: {total_count}")
        print(f"  - 有 soft_name 的记录数: {sum(softname_counts.values())}")
        print(f"  - 没有 soft_name 的记录数: {len(no_softname_records)}")
        print(f"  - 不同的 soft_name 数量: {len(softname_stats)}")

        # 如果有没有 soft_name 的记录，提示 warning
        if no_softname_records:
            print(
                f"\n[WARNING] 发现 {len(no_softname_records)} 条没有 soft_name 的记录"
            )
            print(f"[WARNING] 前10个无 soft_name 的记录 neo4j_id:")
            for i, nid in enumerate(no_softname_records[:10], 1):
                print(f"  {i}. {nid}")
            if len(no_softname_records) > 10:
                print(f"  ... 还有 {len(no_softname_records) - 10} 个记录")

        return {
            "softname_stats": softname_stats,
            "no_softname_count": len(no_softname_records),
            "no_softname_records": no_softname_records,
            "total_count": total_count,
        }

    except MilvusException as e:
        print(f"[FAIL] Milvus 查询失败: {e}")
        import traceback

        traceback.print_exc()
        return {
            "softname_stats": {},
            "no_softname_count": 0,
            "no_softname_records": [],
            "total_count": 0,
        }
    except Exception as e:
        print(f"[FAIL] 查询过程异常: {e}")
        import traceback

        traceback.print_exc()
        return {
            "softname_stats": {},
            "no_softname_count": 0,
            "no_softname_records": [],
            "total_count": 0,
        }


def get_neo4j_chunk_counts(
    softnames: List[str], neo4j_helper: Neo4jHelper
) -> Dict[str, Dict[str, Any]]:
    """
    查询 Neo4j 中每个 soft_name 关联的 chunk 数量

    Args:
        softnames: soft_name 列表
        neo4j_helper: Neo4j 连接助手

    Returns:
        返回字典，格式: {soft_name: {"count": N, "type": "CodeSoftware"/"ArticleDocument"/"NotFound"}}
    """
    results = {}

    print(f"\n[INFO] 开始查询 {len(softnames)} 个 soft_name 的 chunk 信息")

    for i, soft_name in enumerate(softnames, 1):
        if i % 100 == 0:
            print(f"[INFO] 已处理 {i}/{len(softnames)} 个 soft_name...")

        # 判断节点类型
        node_type = check_node_type(soft_name, neo4j_helper)

        if not node_type:
            results[soft_name] = {
                "type": "NotFound",
                "count": 0,
            }
            continue

        # 根据节点类型查询 chunk 数量
        if node_type == "CodeSoftware":
            chunk_count = query_code_chunks_by_software_name(soft_name, neo4j_helper)
        elif node_type == "ArticleDocument":
            chunk_count = query_article_chunks_by_document_title(
                soft_name, neo4j_helper
            )
        else:
            chunk_count = 0

        results[soft_name] = {
            "type": node_type,
            "count": chunk_count,
        }

    print(f"[INFO] Neo4j 查询完成")
    return results


def compare_and_save_results(
    milvus_stats: Dict[str, Any],
    neo4j_stats: Dict[str, Dict[str, Any]],
    no_softname_records: List[str],
) -> str:
    """
    比对两种统计数量并保存结果到 CSV 文件

    Args:
        milvus_stats: Milvus 统计结果 {soft_name: count}
        neo4j_stats: Neo4j 统计结果 {soft_name: {"count": N, "type": ...}}
        no_softname_records: 没有 soft_name 的记录列表

    Returns:
        保存的文件路径
    """
    # 创建输出目录（使用时间戳）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(script_dir, timestamp)
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[INFO] 开始比对并保存结果到: {output_dir}")

    # 准备比对数据
    comparison_data = []
    consistent_count = 0
    inconsistent_count = 0
    not_found_count = 0

    # 比对有 soft_name 的记录
    for soft_name, milvus_count in milvus_stats.items():
        neo4j_data = neo4j_stats.get(soft_name, {})
        neo4j_count = neo4j_data.get("count", 0)
        node_type = neo4j_data.get("type", "NotFound")

        is_consistent = milvus_count == neo4j_count
        if is_consistent:
            consistent_count += 1
        else:
            inconsistent_count += 1

        if node_type == "NotFound":
            not_found_count += 1

        comparison_data.append(
            {
                "soft_name": soft_name,
                "milvus_count": milvus_count,
                "neo4j_count": neo4j_count,
                "difference": milvus_count - neo4j_count,
                "is_consistent": "一致" if is_consistent else "不一致",
                "node_type": node_type,
            }
        )

    # 按差异大小排序（不一致的排在前面）
    comparison_data.sort(
        key=lambda x: (
            0 if x["is_consistent"] == "一致" else 1,
            abs(x["difference"]),
        ),
        reverse=True,
    )

    # 保存比对结果到 CSV
    csv_file_path = os.path.join(output_dir, f"consistency_check_{timestamp}.csv")
    try:
        with open(csv_file_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "soft_name",
                "milvus_count",
                "neo4j_count",
                "difference",
                "is_consistent",
                "node_type",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in comparison_data:
                writer.writerow(row)

        print(f"[OK] 已保存比对结果到: {os.path.basename(csv_file_path)}")
    except Exception as e:
        print(f"[FAIL] 保存比对结果失败: {e}")
        import traceback

        traceback.print_exc()

    # 保存没有 soft_name 的记录
    if no_softname_records:
        no_softname_file = os.path.join(output_dir, "no_softname_records.csv")
        try:
            with open(no_softname_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["neo4j_id"])
                for neo4j_id in no_softname_records:
                    writer.writerow([neo4j_id])

            print(
                f"[OK] 已保存 {len(no_softname_records)} 个无 soft_name 的记录到: no_softname_records.csv"
            )
        except Exception as e:
            print(f"[FAIL] 保存无 soft_name 记录失败: {e}")

    # 打印统计摘要
    print(f"\n[INFO] 比对结果统计:")
    print(f"  - 总 soft_name 数: {len(milvus_stats)}")
    print(f"  - 一致的数量: {consistent_count}")
    print(f"  - 不一致的数量: {inconsistent_count}")
    print(f"  - Neo4j 中未找到的数量: {not_found_count}")
    print(f"  - 没有 soft_name 的记录数: {len(no_softname_records)}")

    if inconsistent_count > 0:
        print(f"\n[WARNING] 发现 {inconsistent_count} 个不一致的 soft_name")
        print(f"[WARNING] 前10个不一致的记录:")
        for i, row in enumerate(comparison_data[:10], 1):
            if row["is_consistent"] == "不一致":
                print(
                    f"  {i}. {row['soft_name']}: Milvus={row['milvus_count']}, Neo4j={row['neo4j_count']}, 差异={row['difference']}"
                )

    return csv_file_path


def main():
    """主函数"""
    print("=" * 80)
    print("Neo4j 和 Milvus 数据库一致性检查脚本")
    print("=" * 80)

    # 第一步：统计 Milvus 中的 soft_name
    print("\n" + "=" * 80)
    print("第一步：统计 Milvus 数据库中的 soft_name")
    print("=" * 80)
    milvus_result = get_milvus_softname_stats()

    if not milvus_result["softname_stats"]:
        print("[FAIL] 未能从 Milvus 获取 soft_name 统计信息")
        return

    # 第二步：查询 Neo4j 中的 chunk 数量
    print("\n" + "=" * 80)
    print("第二步：查询 Neo4j 中每个 soft_name 的 chunk 数量")
    print("=" * 80)

    # 初始化 Neo4j 连接
    neo4j_helper = Neo4jHelper()
    if not neo4j_helper or not neo4j_helper.neo4j_driver:
        print("[FAIL] Neo4j 连接失败")
        return

    print("[OK] Neo4j 连接成功")

    # 获取所有 soft_name
    softnames = list(milvus_result["softname_stats"].keys())
    neo4j_result = get_neo4j_chunk_counts(softnames, neo4j_helper)

    # 第三步：比对并保存结果
    print("\n" + "=" * 80)
    print("第三步：比对统计结果并保存")
    print("=" * 80)

    csv_path = compare_and_save_results(
        milvus_result["softname_stats"],
        neo4j_result,
        milvus_result["no_softname_records"],
    )

    print("\n" + "=" * 80)
    print("检查完成")
    print("=" * 80)
    print(f"结果已保存到: {csv_path}")


if __name__ == "__main__":
    main()
