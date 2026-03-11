"""
检查 duplicate_projects 中的代码项目在 Neo4j 中是否有 repo_url 且不为空。
结果输出到 CSV 文件。
"""

import csv
import os
import sys
from datetime import datetime

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from database_helper.neo4j_helper import Neo4jHelper

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_TXT = os.path.join(SCRIPT_DIR, "duplicate_projects_20260309_162536.txt")
OUTPUT_CSV = os.path.join(
    SCRIPT_DIR,
    f"duplicate_repo_url_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
)

QUERY_REPO_URL = """
MATCH (n:MitreAttackCodeSoftware)
WHERE n.name = $software_name
RETURN n.name AS name, n.repo_url AS repo_url
LIMIT 1
"""


def main():
    if not os.path.isfile(INPUT_TXT):
        print(f"文件不存在: {INPUT_TXT}")
        return

    with open(INPUT_TXT, "r", encoding="utf-8") as f:
        projects = [line.strip() for line in f if line.strip()]

    neo4j = Neo4jHelper()
    if not neo4j or not getattr(neo4j, "neo4j_driver", None):
        print("Neo4j 连接失败")
        return

    rows = []

    with neo4j.neo4j_driver.session(**neo4j.session_kwargs) as session:
        for name in projects:
            result = session.run(QUERY_REPO_URL, software_name=name)
            record = result.single()
            if not record:
                rows.append(
                    {"software_name": name, "status": "not_found", "repo_url": ""}
                )
                continue
            repo = record.get("repo_url")
            if repo and str(repo).strip():
                rows.append(
                    {
                        "software_name": name,
                        "status": "has_repo",
                        "repo_url": str(repo).strip(),
                    }
                )
            else:
                rows.append(
                    {
                        "software_name": name,
                        "status": "no_repo_or_empty",
                        "repo_url": "",
                    }
                )

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["software_name", "status", "repo_url"])
        writer.writeheader()
        writer.writerows(rows)

    has_repo = sum(1 for r in rows if r["status"] == "has_repo")
    no_repo = sum(1 for r in rows if r["status"] == "no_repo_or_empty")
    not_found = sum(1 for r in rows if r["status"] == "not_found")
    print(f"已写入 {len(rows)} 条记录到: {OUTPUT_CSV}")
    print(
        f"有 repo_url 且非空: {has_repo}，无 repo_url 或为空: {no_repo}，未找到节点: {not_found}"
    )


if __name__ == "__main__":
    main()
