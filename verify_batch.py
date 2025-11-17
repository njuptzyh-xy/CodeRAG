import argparse
import os
import sys
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

# 将项目根目录添加到 Python 路径中，以便导入 'setting' 模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from setting import NEO4J_USER, NEO4J_PASSWORD, NEO4J_URI
except ImportError:
    print("错误：无法从 'setting.py' 文件中导入数据库配置。")
    print("请确保该文件存在，并且包含 NEO4J_USER, NEO4J_PASSWORD, 和 NEO4J_URI。")
    sys.exit(1)

def main():
    """
    主函数，用于连接 Neo4j 并验证指定批次号的文档数量。
    """
    parser = argparse.ArgumentParser(description="验证 Neo4j 数据库中指定批次的文档数量。")
    parser.add_argument("batch_number", type=int, help="要查询的批次号。")
    args = parser.parse_args()

    batch_number = args.batch_number
    uri = NEO4J_URI
    auth = (NEO4J_USER, NEO4J_PASSWORD)
    driver = None

    print(f"正在尝试连接到 Neo4j 数据库: {uri}...")

    try:
        # 1. 创建 Neo4j 驱动实例
        driver = GraphDatabase.driver(uri, auth=auth)
        driver.verify_connectivity()
        print("数据库连接成功！")

        # 2. 执行 Cypher 查询
        query = """
        MATCH (d:MitreAttackArticleDocument {insert_number: $batch_number})
        RETURN count(d) AS document_count
        """
        
        print(f"正在查询批次号为 {batch_number} 的文档数量...")
        
        with driver.session() as session:
            result = session.run(query, batch_number=batch_number)
            record = result.single()
            
            if record:
                count = record["document_count"]
                print("\n--- 查询结果 ---")
                print(f"在 Neo4j 数据库中，批次号为 {batch_number} 的文档共有: {count} 个。")
                print("------------------")
            else:
                print("查询未返回结果。")

    except ServiceUnavailable:
        print(f"错误：无法连接到 Neo4j 数据库，请检查 URI '{uri}' 是否正确以及数据库服务是否正在运行。")
    except Exception as e:
        print(f"查询过程中发生错误: {e}")
    finally:
        # 3. 关闭驱动连接
        if driver:
            driver.close()
            print("\n数据库连接已关闭。")

if __name__ == "__main__":
    main()
