"""
根据文章标题同步删除 Neo4j 和 Milvus 中的相关数据

功能：
1. 根据文章标题找到 Neo4j 中的 MitreAttackArticleDocument 和 MitreAttackArticleChunk 节点
2. 从 Milvus 中删除对应的记录
3. 从 Neo4j 中删除 MitreAttackArticleChunk 和 MitreAttackArticleDocument 节点（按顺序删除）

使用方法:
    python Delete/deleteByArticleTitle.py

    或在代码中使用:
    from Delete.deleteByArticleTitle import delete_by_article_title

    result = delete_by_article_title("文章标题")
"""

import sys
import os
from typing import Dict, Any, List, Optional

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo4j import GraphDatabase
from pymilvus import Collection, connections, utility
from pymilvus.exceptions import MilvusException
from database_helper.neo4j_helper import Neo4jHelper
import setting


class ArticleDeleter:
    """文章数据删除器"""

    def __init__(self):
        """初始化连接"""
        self.neo4j_helper = None
        self.milvus_collection = None
        self._init_neo4j()
        self._init_milvus()

    def _init_neo4j(self):
        """初始化 Neo4j 连接"""
        try:
            self.neo4j_helper = Neo4jHelper()
            if not self.neo4j_helper or not self.neo4j_helper.neo4j_driver:
                print("[FAIL] Neo4j 连接失败")
                raise RuntimeError("Neo4j 连接失败")
            print("[OK] Neo4j 连接成功")
        except Exception as e:
            print(f"[FAIL] Neo4j 初始化失败: {e}")
            raise

    def _init_milvus(self):
        """初始化 Milvus 连接"""
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
                    f"[OK] Milvus 连接成功: {setting.MILVUS_HOST}:{setting.MILVUS_PORT}"
                )
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"[WARN] Milvus 连接检查: {e}")
                    raise

            # 检查 collection 是否存在
            if not utility.has_collection(setting.MILVUS_COLLECTION):
                print(f"[FAIL] Collection {setting.MILVUS_COLLECTION} 不存在")
                raise RuntimeError(f"Collection {setting.MILVUS_COLLECTION} 不存在")

            # 获取 collection 并加载
            self.milvus_collection = Collection(setting.MILVUS_COLLECTION)
            self.milvus_collection.load()
            print(f"[OK] Milvus Collection {setting.MILVUS_COLLECTION} 加载成功")
        except Exception as e:
            print(f"[FAIL] Milvus 初始化失败: {e}")
            raise

    def find_article_data(self, article_title: str) -> Dict[str, Any]:
        """
        根据文章标题查找所有相关的节点信息

        Args:
            article_title: 文章标题

        Returns:
            包含 document、chunks 信息的字典
        """
        query = """
        MATCH (document:MitreAttackArticleDocument)
        WHERE document.title = $article_title
        OPTIONAL MATCH (document)-[r:DOCUMENT_HAS_CHUNK]->
                      (chunk:MitreAttackArticleChunk)
        RETURN DISTINCT
            elementId(document) AS document_id,
            document.title AS document_title,
            document.article_uuid AS document_uuid,
            elementId(chunk) AS chunk_id,
            chunk.chunk_uuid AS chunk_uuid
        """

        document_ids = []
        document_title = None
        document_uuids = []
        chunk_ids = []
        chunk_uuids = []

        with self.neo4j_helper.neo4j_driver.session(
            **self.neo4j_helper.session_kwargs
        ) as session:
            result = session.run(query, article_title=article_title)

            for record in result:
                document_id = record.get("document_id")
                if document_id and document_id not in document_ids:
                    document_ids.append(document_id)
                    if not document_title:
                        document_title = record.get("document_title")
                    document_uuid = record.get("document_uuid")
                    if document_uuid and document_uuid not in document_uuids:
                        document_uuids.append(document_uuid)

                chunk_id = record.get("chunk_id")
                if chunk_id and chunk_id not in chunk_ids:
                    chunk_ids.append(chunk_id)
                    chunk_uuid = record.get("chunk_uuid")
                    if chunk_uuid and chunk_uuid not in chunk_uuids:
                        chunk_uuids.append(chunk_uuid)

        return {
            "document_ids": document_ids,
            "document_title": document_title,
            "document_uuids": document_uuids,
            "chunk_ids": chunk_ids,
            "chunk_uuids": chunk_uuids,
        }

    def delete_from_milvus(self, neo4j_ids: List[str]) -> Dict[str, Any]:
        """
        从 Milvus 中删除记录

        Args:
            neo4j_ids: Neo4j 节点的 elementId 列表

        Returns:
            删除结果统计
        """
        if not neo4j_ids:
            print("[INFO] 没有需要删除的 Milvus 记录")
            return {"deleted": 0, "not_found": 0}

        try:
            # 分批处理，避免表达式过长
            batch_size = 1000
            total_deleted = 0
            total_not_found = 0

            for i in range(0, len(neo4j_ids), batch_size):
                batch_ids = neo4j_ids[i : i + batch_size]
                escaped_ids = [f'"{nid}"' for nid in batch_ids]
                expr = f"neo4j_id in [{', '.join(escaped_ids)}]"

                # 查询匹配的记录
                existing_records = self.milvus_collection.query(
                    expr=expr, output_fields=["neo4j_id"]
                )

                existing_ids = [item["neo4j_id"] for item in existing_records]
                batch_not_found = len(batch_ids) - len(existing_ids)
                total_not_found += batch_not_found

                if existing_ids:
                    # 执行删除
                    print(
                        f"[INFO] 准备从 Milvus 删除批次 {i//batch_size + 1} 的 {len(existing_ids)} 条记录..."
                    )
                    delete_expr = f"neo4j_id in [{', '.join(escaped_ids)}]"
                    self.milvus_collection.delete(expr=delete_expr)
                    total_deleted += len(existing_ids)

            # 刷新 collection 使删除生效
            if total_deleted > 0:
                self.milvus_collection.flush()
                print(f"[OK] 已从 Milvus 删除 {total_deleted} 条记录")
            else:
                print(f"[WARN] 在 Milvus 中没有找到需要删除的记录")

            if total_not_found > 0:
                print(
                    f"[INFO] 有 {total_not_found} 条记录在 Milvus 中不存在（可能已删除）"
                )

            return {"deleted": total_deleted, "not_found": total_not_found}

        except MilvusException as e:
            print(f"[FAIL] Milvus 删除失败: {e}")
            import traceback

            traceback.print_exc()
            return {"deleted": 0, "not_found": 0, "error": str(e)}
        except Exception as e:
            print(f"[FAIL] Milvus 删除过程异常: {e}")
            import traceback

            traceback.print_exc()
            return {"deleted": 0, "not_found": 0, "error": str(e)}

    def delete_from_neo4j(
        self, chunk_ids: List[str], document_ids: List[str]
    ) -> Dict[str, Any]:
        """
        从 Neo4j 中删除节点（按顺序：chunk -> document）

        Args:
            chunk_ids: Chunk 节点的 elementId 列表
            document_ids: Document 节点的 elementId 列表

        Returns:
            删除结果统计
        """
        result = {
            "chunk_deleted": 0,
            "document_deleted": 0,
            "errors": [],
        }

        try:
            with self.neo4j_helper.neo4j_driver.session(
                **self.neo4j_helper.session_kwargs
            ) as session:
                # 1. 删除 chunk 节点
                if chunk_ids:
                    print(f"[INFO] 准备删除 {len(chunk_ids)} 个 chunk 节点...")
                    chunk_delete_query = """
                    UNWIND $chunk_ids AS chunk_id
                    MATCH (chunk:MitreAttackArticleChunk)
                    WHERE elementId(chunk) = chunk_id
                    DETACH DELETE chunk
                    RETURN count(chunk) AS deleted_count
                    """
                    try:
                        chunk_result = session.run(
                            chunk_delete_query, chunk_ids=chunk_ids
                        )
                        chunk_record = chunk_result.single()
                        result["chunk_deleted"] = (
                            chunk_record.get("deleted_count", 0) if chunk_record else 0
                        )
                        print(f"[OK] 已删除 {result['chunk_deleted']} 个 chunk 节点")
                    except Exception as e:
                        error_msg = f"删除 chunk 节点失败: {e}"
                        print(f"[FAIL] {error_msg}")
                        result["errors"].append(error_msg)

                # 2. 删除 document 节点
                if document_ids:
                    print(f"[INFO] 准备删除 {len(document_ids)} 个 document 节点...")
                    document_delete_query = """
                    UNWIND $document_ids AS document_id
                    MATCH (document:MitreAttackArticleDocument)
                    WHERE elementId(document) = document_id
                    DETACH DELETE document
                    RETURN count(document) AS deleted_count
                    """
                    try:
                        document_result = session.run(
                            document_delete_query, document_ids=document_ids
                        )
                        document_record = document_result.single()
                        result["document_deleted"] = (
                            document_record.get("deleted_count", 0)
                            if document_record
                            else 0
                        )
                        print(
                            f"[OK] 已删除 {result['document_deleted']} 个 document 节点"
                        )
                    except Exception as e:
                        error_msg = f"删除 document 节点失败: {e}"
                        print(f"[FAIL] {error_msg}")
                        result["errors"].append(error_msg)

        except Exception as e:
            error_msg = f"Neo4j 删除过程异常: {e}"
            print(f"[FAIL] {error_msg}")
            result["errors"].append(error_msg)
            import traceback

            traceback.print_exc()

        return result

    def delete_by_article_title(self, article_title: str) -> Dict[str, Any]:
        """
        根据文章标题删除所有相关数据

        Args:
            article_title: 文章标题

        Returns:
            删除结果统计
        """
        print("=" * 80)
        print(f"根据文章标题删除数据: {article_title}")
        print("=" * 80)

        # 1. 查找所有相关节点
        print(f"\n[步骤 1] 查找文章 '{article_title}' 的相关节点...")
        article_data = self.find_article_data(article_title)

        if not article_data["document_ids"]:
            print(f"[WARN] 未找到文章: {article_title}")
            return {
                "success": False,
                "reason": f"未找到文章: {article_title}",
                "article_data": article_data,
            }

        print(f"[INFO] 找到文章节点:")
        print(f"  - document 节点数: {len(article_data['document_ids'])}")
        print(f"  - document_ids: {article_data['document_ids']}")
        print(f"  - document_title: {article_data['document_title']}")
        print(f"  - document_uuid 数: {len(article_data['document_uuids'])}")
        print(f"  - chunk 节点数: {len(article_data['chunk_ids'])}")

        # 2. 从 Milvus 删除记录
        print(f"\n[步骤 2] 从 Milvus 删除 {len(article_data['chunk_ids'])} 条记录...")
        milvus_result = self.delete_from_milvus(article_data["chunk_ids"])

        # 3. 从 Neo4j 删除节点
        print(f"\n[步骤 3] 从 Neo4j 删除节点...")
        neo4j_result = self.delete_from_neo4j(
            article_data["chunk_ids"],
            article_data["document_ids"],
        )

        # 汇总结果
        total_deleted = {
            "milvus_records": milvus_result.get("deleted", 0),
            "neo4j_chunk_nodes": neo4j_result.get("chunk_deleted", 0),
            "neo4j_document_nodes": neo4j_result.get("document_deleted", 0),
        }

        success = (
            milvus_result.get("deleted", 0) > 0
            or neo4j_result.get("chunk_deleted", 0) > 0
            or neo4j_result.get("document_deleted", 0) > 0
        ) and len(neo4j_result.get("errors", [])) == 0

        print("\n" + "=" * 80)
        print("删除完成")
        print("=" * 80)
        print(f"Milvus 删除: {total_deleted['milvus_records']} 条记录")
        print(
            f"Neo4j 删除: {total_deleted['neo4j_chunk_nodes']} 个 chunk 节点, "
            f"{total_deleted['neo4j_document_nodes']} 个 document 节点"
        )

        if neo4j_result.get("errors"):
            print(f"\n[WARN] 删除过程中有错误:")
            for error in neo4j_result["errors"]:
                print(f"  - {error}")

        return {
            "success": success,
            "article_data": article_data,
            "milvus_result": milvus_result,
            "neo4j_result": neo4j_result,
            "total_deleted": total_deleted,
        }


def delete_by_article_title(article_title: str) -> Dict[str, Any]:
    """
    根据文章标题删除所有相关数据的便捷函数

    Args:
        article_title: 文章标题

    Returns:
        删除结果统计
    """
    deleter = ArticleDeleter()
    return deleter.delete_by_article_title(article_title)


if __name__ == "__main__":
    # 测试示例
    print("=" * 80)
    print("根据文章标题删除数据脚本")
    print("=" * 80)

    # 配置：设置要删除的文章标题
    # 注意：删除操作不可逆，请谨慎使用！
    article_title = "MITRE ATT&CK 框架全面解析文档"  # 替换为实际的文章标题

    # 执行删除操作
    delete_result = delete_by_article_title(article_title)

    if delete_result.get("success"):
        print("\n[OK] 删除操作完成")
    else:
        print("\n[FAIL] 删除操作失败或部分失败")
