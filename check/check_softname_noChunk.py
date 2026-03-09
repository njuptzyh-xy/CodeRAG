"""
统计没有 CodeChunk 的 MitreAttackCodeSoftware 的 softname。

查询 Neo4j 中满足以下条件的软件节点：
不存在路径 software -> CodeSoftwareFile -> CodeSoftwareCodeChunk，
即该 software 下没有任何 code chunk。
结果追加到指定 consistency_check CSV 文件中。
"""

import sys
import os
import csv

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_helper.neo4j_helper import Neo4jHelper

# 结果要追加到的 CSV 路径（相对于本脚本所在目录）
OUTPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "20260304_145233",
    "consistency_check_20260304_145233.csv",
)


# 查询没有 code chunk 的 software，返回 name（softname）
QUERY_SOFTNAME_NO_CHUNK = """
MATCH (software:MitreAttackCodeSoftware)
WHERE NOT EXISTS {
    MATCH (software)-[:CODE_SOFTWARE_HAS_CODE_SOFTWARE_FILE]->(:MitreAttackCodeSoftwareFile)-[:CODE_SOFTWARE_FILE_HAS_CODE_SOFTWARE_CODE_CHUNK]->(:MitreAttackCodeSoftwareCodeChunk)
}
RETURN software.name AS softname
ORDER BY softname
"""


def get_softnames_without_code_chunk(neo4j_helper: Neo4jHelper) -> list[str]:
    """
    查询所有没有 CodeChunk 的 software 的 name 列表。

    Returns:
        没有 code chunk 的 software 的 name 列表
    """
    with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
        result = session.run(QUERY_SOFTNAME_NO_CHUNK)
        return [record["softname"] for record in result if record.get("softname")]


def append_no_chunk_to_csv(softnames: list[str], csv_path: str) -> None:
    """
    将没有 CodeChunk 的 softname 追加到 consistency_check CSV。
    若 soft_name 已存在则跳过。每行格式与现有 CSV 一致：
    soft_name, milvus_count=0, neo4j_count=0, difference=0, is_consistent=一致, node_type=CodeSoftware
    """
    if not softnames:
        print("无新增记录，未写入 CSV。")
        return

    # 读取已有行，获取已存在的 soft_name 集合
    existing_soft_names = set()
    rows = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
            existing_soft_names.add(row.get("soft_name", "").strip())

    # 只追加尚未出现在 CSV 中的 softname
    to_append = [name for name in softnames if name not in existing_soft_names]
    if not to_append:
        print("所有 softname 已存在于 CSV 中，未追加新行。")
        return

    for name in to_append:
        rows.append(
            {
                "soft_name": name,
                "milvus_count": 0,
                "neo4j_count": 0,
                "difference": 0,
                "is_consistent": "一致",
                "node_type": "CodeSoftware",
            }
        )

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"已向 {csv_path} 追加 {len(to_append)} 条无 CodeChunk 的 softname。")
    for name in to_append:
        print(f"  + {name}")


def main() -> None:
    neo4j_helper = Neo4jHelper()
    if not neo4j_helper or not neo4j_helper.neo4j_driver:
        print("[FAIL] Neo4j 连接失败")
        return

    softnames = get_softnames_without_code_chunk(neo4j_helper)
    count = len(softnames)

    print(f"没有 CodeChunk 的 Software 数量: {count}")
    print("-" * 40)
    for name in softnames:
        print(name)

    if not os.path.isfile(OUTPUT_CSV):
        print(f"[WARN] CSV 文件不存在: {OUTPUT_CSV}，跳过追加。")
        return
    append_no_chunk_to_csv(softnames, OUTPUT_CSV)


if __name__ == "__main__":
    main()
