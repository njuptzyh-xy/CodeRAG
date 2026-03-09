"""
统计 Neo4j 中存在重名文件的代码项目。

查询逻辑：按 MitreAttackCodeSoftware 与文件 name 分组，
统计每个项目下同名文件数量，筛选 file_count > 1 的记录，
将结果写入 check/gitUpload 目录下的 CSV 文件。
"""

import sys
import os
import csv
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from database_helper.neo4j_helper import Neo4jHelper

# 输出目录与文件名（带时间戳）
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV_FILENAME = "duplicate_files_{}.csv".format(
    datetime.now().strftime("%Y%m%d_%H%M%S")
)

# 查询所有代码项目中存在重名文件的情况
QUERY_DUPLICATE_FILES = """
MATCH (software:MitreAttackCodeSoftware)
      -[:CODE_SOFTWARE_HAS_CODE_SOFTWARE_FILE]->(file:MitreAttackCodeSoftwareFile)
WITH software.name AS software_name, file.name AS file_name,
     COUNT(file) AS file_count, collect(file) AS files
WHERE file_count > 1
RETURN software_name, file_name, file_count, [f in files | id(f)] AS internal_ids
ORDER BY software_name, file_count DESC
"""


def run_duplicate_check(neo4j_helper: Neo4jHelper) -> list[dict]:
    """
    执行重名文件统计查询，返回所有存在重名文件的记录。

    Returns:
        列表，每项为 dict：software_name, file_name, file_count, internal_ids
    """
    rows = []
    with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
        result = session.run(QUERY_DUPLICATE_FILES)
        for record in result:
            rows.append(
                {
                    "software_name": record.get("software_name") or "",
                    "file_name": record.get("file_name") or "",
                    "file_count": record.get("file_count") or 0,
                    "internal_ids": record.get("internal_ids") or [],
                }
            )
    return rows


def write_csv(rows: list[dict], csv_path: str) -> None:
    """将统计结果写入 CSV。internal_ids 以逗号分隔的字符串写入。"""
    if not rows:
        print("无重名文件记录，未生成 CSV。")
        return

    fieldnames = ["software_name", "file_name", "file_count", "internal_ids"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {
                "software_name": row["software_name"],
                "file_name": row["file_name"],
                "file_count": row["file_count"],
                "internal_ids": ",".join(str(x) for x in row["internal_ids"]),
            }
            writer.writerow(out)
    print(f"已写入 {len(rows)} 条重名文件记录到: {csv_path}")


def main() -> None:
    neo4j_helper = Neo4jHelper()
    if not neo4j_helper or not getattr(neo4j_helper, "neo4j_driver", None):
        print("Neo4j 连接失败，退出。")
        sys.exit(1)

    rows = run_duplicate_check(neo4j_helper)
    csv_path = os.path.join(OUTPUT_DIR, OUTPUT_CSV_FILENAME)
    write_csv(rows, csv_path)

    if rows:
        print(
            f"共发现 {len(rows)} 组重名文件，涉及 {len({r['software_name'] for r in rows})} 个代码项目。"
        )
    else:
        print("未发现重名文件。")


if __name__ == "__main__":
    main()
