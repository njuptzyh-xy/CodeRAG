"""
根据软件名同步删除 Neo4j 和 Milvus 中的相关数据

功能：
1. 根据软件名找到 Neo4j 中的 software、file、code 节点
2. 从 Milvus 中删除对应的记录
3. 从 Neo4j 中删除 code、file、software 节点（按顺序删除）

使用方法:
    python Delete/deleteBySoftname.py

    或在代码中使用:
    from Delete.deleteBySoftname import delete_by_software_name

    result = delete_by_software_name("panda-re_lava")
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


class SoftwareDeleter:
    """软件数据删除器"""

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

    def find_software_data(self, soft_name: str) -> Dict[str, Any]:
        """
        根据软件名查找所有相关的节点信息

        Args:
            soft_name: 软件名

        Returns:
            包含 software、files、codes 信息的字典
        """
        query = """
        MATCH (software:MitreAttackCodeSoftware)
        WHERE software.name = $soft_name
        OPTIONAL MATCH (software)-[r1:CODE_SOFTWARE_HAS_CODE_SOFTWARE_FILE]->
                      (file:MitreAttackCodeSoftwareFile)
        OPTIONAL MATCH (file)-[r2:CODE_SOFTWARE_FILE_BELONG_CODE_SOFTWARE]->(software)
        OPTIONAL MATCH (file)-[r3:CODE_SOFTWARE_FILE_HAS_CODE_SOFTWARE_CODE_CHUNK]->
                      (code:MitreAttackCodeSoftwareCodeChunk)
        RETURN DISTINCT
            elementId(software) AS software_id,
            software.name AS software_name,
            software.software_uuid AS software_uuid,
            elementId(file) AS file_id,
            file.file_uuid AS file_uuid,
            elementId(code) AS code_id
        """

        software_ids = []
        software_name = None
        software_uuids = []
        file_ids = []
        file_uuids = []
        code_ids = []

        with self.neo4j_helper.neo4j_driver.session(
            **self.neo4j_helper.session_kwargs
        ) as session:
            result = session.run(query, soft_name=soft_name)

            for record in result:
                software_id = record.get("software_id")
                if software_id and software_id not in software_ids:
                    software_ids.append(software_id)
                    if not software_name:
                        software_name = record.get("software_name")
                    software_uuid = record.get("software_uuid")
                    if software_uuid and software_uuid not in software_uuids:
                        software_uuids.append(software_uuid)

                file_id = record.get("file_id")
                if file_id and file_id not in file_ids:
                    file_ids.append(file_id)
                    file_uuid = record.get("file_uuid")
                    if file_uuid and file_uuid not in file_uuids:
                        file_uuids.append(file_uuid)

                code_id = record.get("code_id")
                if code_id and code_id not in code_ids:
                    code_ids.append(code_id)

        return {
            "software_ids": software_ids,
            "software_name": software_name,
            "software_uuids": software_uuids,
            "file_ids": file_ids,
            "file_uuids": file_uuids,
            "code_ids": code_ids,
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
        self, code_ids: List[str], file_ids: List[str], software_ids: List[str]
    ) -> Dict[str, Any]:
        """
        从 Neo4j 中删除节点（按顺序：code -> file -> software）

        Args:
            code_ids: Code 节点的 elementId 列表
            file_ids: File 节点的 elementId 列表
            software_ids: Software 节点的 elementId 列表

        Returns:
            删除结果统计
        """
        result = {
            "code_deleted": 0,
            "file_deleted": 0,
            "software_deleted": 0,
            "errors": [],
        }

        try:
            with self.neo4j_helper.neo4j_driver.session(
                **self.neo4j_helper.session_kwargs
            ) as session:
                # 1. 删除 code 节点
                if code_ids:
                    print(f"[INFO] 准备删除 {len(code_ids)} 个 code 节点...")
                    code_delete_query = """
                    UNWIND $code_ids AS code_id
                    MATCH (code:MitreAttackCodeSoftwareCodeChunk)
                    WHERE elementId(code) = code_id
                    DETACH DELETE code
                    RETURN count(code) AS deleted_count
                    """
                    try:
                        code_result = session.run(code_delete_query, code_ids=code_ids)
                        code_record = code_result.single()
                        result["code_deleted"] = (
                            code_record.get("deleted_count", 0) if code_record else 0
                        )
                        print(f"[OK] 已删除 {result['code_deleted']} 个 code 节点")
                    except Exception as e:
                        error_msg = f"删除 code 节点失败: {e}"
                        print(f"[FAIL] {error_msg}")
                        result["errors"].append(error_msg)

                # 2. 删除 file 节点
                if file_ids:
                    print(f"[INFO] 准备删除 {len(file_ids)} 个 file 节点...")
                    file_delete_query = """
                    UNWIND $file_ids AS file_id
                    MATCH (file:MitreAttackCodeSoftwareFile)
                    WHERE elementId(file) = file_id
                    DETACH DELETE file
                    RETURN count(file) AS deleted_count
                    """
                    try:
                        file_result = session.run(file_delete_query, file_ids=file_ids)
                        file_record = file_result.single()
                        result["file_deleted"] = (
                            file_record.get("deleted_count", 0) if file_record else 0
                        )
                        print(f"[OK] 已删除 {result['file_deleted']} 个 file 节点")
                    except Exception as e:
                        error_msg = f"删除 file 节点失败: {e}"
                        print(f"[FAIL] {error_msg}")
                        result["errors"].append(error_msg)

                # 3. 删除 software 节点（支持多个）
                if software_ids:
                    print(f"[INFO] 准备删除 {len(software_ids)} 个 software 节点...")
                    software_delete_query = """
                    UNWIND $software_ids AS software_id
                    MATCH (software:MitreAttackCodeSoftware)
                    WHERE elementId(software) = software_id
                    DETACH DELETE software
                    RETURN count(software) AS deleted_count
                    """
                    try:
                        software_result = session.run(
                            software_delete_query, software_ids=software_ids
                        )
                        software_record = software_result.single()
                        result["software_deleted"] = (
                            software_record.get("deleted_count", 0)
                            if software_record
                            else 0
                        )
                        if result["software_deleted"] > 0:
                            print(
                                f"[OK] 已删除 {result['software_deleted']} 个 software 节点"
                            )
                        else:
                            print(f"[WARN] 未找到或已删除 software 节点")
                    except Exception as e:
                        error_msg = f"删除 software 节点失败: {e}"
                        print(f"[FAIL] {error_msg}")
                        result["errors"].append(error_msg)

        except Exception as e:
            error_msg = f"Neo4j 删除过程异常: {e}"
            print(f"[FAIL] {error_msg}")
            result["errors"].append(error_msg)
            import traceback

            traceback.print_exc()

        return result

    def delete_by_software_name(self, soft_name: str) -> Dict[str, Any]:
        """
        根据软件名删除所有相关数据

        Args:
            soft_name: 软件名

        Returns:
            删除结果统计
        """
        print("=" * 80)
        print(f"根据软件名删除数据: {soft_name}")
        print("=" * 80)

        # 1. 查找所有相关节点
        print(f"\n[步骤 1] 查找软件 '{soft_name}' 的相关节点...")
        software_data = self.find_software_data(soft_name)

        if not software_data["software_ids"]:
            print(f"[WARN] 未找到软件: {soft_name}")
            return {
                "success": False,
                "reason": f"未找到软件: {soft_name}",
                "software_data": software_data,
            }

        print(f"[INFO] 找到软件节点:")
        print(f"  - software 节点数: {len(software_data['software_ids'])}")
        print(f"  - software_ids: {software_data['software_ids']}")
        print(f"  - software_name: {software_data['software_name']}")
        print(f"  - software_uuid 数: {len(software_data['software_uuids'])}")
        print(f"  - file 节点数: {len(software_data['file_ids'])}")
        print(f"  - code 节点数: {len(software_data['code_ids'])}")

        # 2. 从 Milvus 删除记录
        print(f"\n[步骤 2] 从 Milvus 删除 {len(software_data['code_ids'])} 条记录...")
        milvus_result = self.delete_from_milvus(software_data["code_ids"])

        # 3. 从 Neo4j 删除节点
        print(f"\n[步骤 3] 从 Neo4j 删除节点...")
        neo4j_result = self.delete_from_neo4j(
            software_data["code_ids"],
            software_data["file_ids"],
            software_data["software_ids"],
        )

        # 汇总结果
        total_deleted = {
            "milvus_records": milvus_result.get("deleted", 0),
            "neo4j_code_nodes": neo4j_result.get("code_deleted", 0),
            "neo4j_file_nodes": neo4j_result.get("file_deleted", 0),
            "neo4j_software_nodes": neo4j_result.get("software_deleted", 0),
        }

        success = (
            milvus_result.get("deleted", 0) > 0
            or neo4j_result.get("code_deleted", 0) > 0
            or neo4j_result.get("file_deleted", 0) > 0
            or neo4j_result.get("software_deleted", 0) > 0
        ) and len(neo4j_result.get("errors", [])) == 0

        print("\n" + "=" * 80)
        print("删除完成")
        print("=" * 80)
        print(f"Milvus 删除: {total_deleted['milvus_records']} 条记录")
        print(
            f"Neo4j 删除: {total_deleted['neo4j_code_nodes']} 个 code 节点, "
            f"{total_deleted['neo4j_file_nodes']} 个 file 节点, "
            f"{total_deleted['neo4j_software_nodes']} 个 software 节点"
        )

        if neo4j_result.get("errors"):
            print(f"\n[WARN] 删除过程中有错误:")
            for error in neo4j_result["errors"]:
                print(f"  - {error}")

        return {
            "success": success,
            "software_data": software_data,
            "milvus_result": milvus_result,
            "neo4j_result": neo4j_result,
            "total_deleted": total_deleted,
        }


def delete_by_software_name(soft_name: str) -> Dict[str, Any]:
    """
    根据软件名删除所有相关数据的便捷函数

    Args:
        soft_name: 软件名

    Returns:
        删除结果统计
    """
    deleter = SoftwareDeleter()
    return deleter.delete_by_software_name(soft_name)


if __name__ == "__main__":
    # 测试示例
    print("=" * 80)
    print("根据软件名删除数据脚本")
    print("=" * 80)

    # 配置：设置要删除的软件名
    # 注意：删除操作不可逆，请谨慎使用！
    software_name = "MitreAttackProject"  # 替换为实际的软件名

    # 执行删除操作
    delete_result = delete_by_software_name(software_name)

    if delete_result.get("success"):
        print("\n[OK] 删除操作完成")
    else:
        print("\n[FAIL] 删除操作失败或部分失败")
