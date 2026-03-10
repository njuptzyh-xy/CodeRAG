"""
从 duplicate_files CSV 中提取存在重名文件的项目名，每行一个项目（去重）。
"""

import csv
import os

# 输入与输出路径（相对于脚本所在目录）
INPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "duplicate_files_20260309_162536.csv",
)
OUTPUT_TXT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "duplicate_projects_20260309_162536.txt",
)


def extract_project_names(csv_path: str) -> list[str]:
    """从 CSV 中读取 software_name 并去重，返回按出现顺序的项目名列表。"""
    seen = set()
    projects = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("software_name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                projects.append(name)
    return projects


def write_one_per_line(projects: list[str], output_path: str) -> None:
    """将项目名写入文件，一行一个。"""
    with open(output_path, "w", encoding="utf-8") as f:
        for name in projects:
            f.write(name + "\n")
    print(f"已写入 {len(projects)} 个项目到: {output_path}")


def main() -> None:
    if not os.path.isfile(INPUT_CSV):
        print(f"输入文件不存在: {INPUT_CSV}")
        return

    projects = extract_project_names(INPUT_CSV)
    write_one_per_line(projects, OUTPUT_TXT)


if __name__ == "__main__":
    main()
