#!/usr/bin/env python
"""
在两个 Milvus 集群之间迁移数据（仅迁移主键/描述/稠密向量）。

稀疏向量字段 `sparse_vector` 不会迁移也不会创建，后续可在目标端独立处理。
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, Iterable, List, Optional

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    connections,
    utility,
)
from pymilvus.exceptions import MilvusException

import setting

# 源/目标默认配置，可用命令行覆盖
SOURCE_MILVUS_HOST = "10.1.1.140"
SOURCE_MILVUS_PORT = 19530
SOURCE_MILVUS_USER = "root"
SOURCE_MILVUS_PASSWORD = "Milvus"
SOURCE_MILVUS_DB_NAME = "default"
SOURCE_MILVUS_SECURE = False

TARGET_MILVUS_HOST = "10.1.1.140"
TARGET_MILVUS_PORT = 19532
TARGET_MILVUS_USER = "root"
TARGET_MILVUS_PASSWORD = "Milvus"
TARGET_MILVUS_DB_NAME = "default"
TARGET_MILVUS_SECURE = False

LOGGER = logging.getLogger("milvus_to_milvus")

# 字段名称沿用 ES→Milvus 迁移脚本
PRIMARY_FIELD = "neo4j_id"
DESCRIPTION_FIELD = setting.ES_FULLTEXT_INDEX_FILED
VECTOR_FIELD = setting.ES_VECTOR_FILED
SPARSE_VECTOR_FIELD = "sparse_vector"

DEFAULT_BATCH_SIZE = 1000


class MilvusToMilvusMigrator:
    """Stream data from a source Milvus collection to a target Milvus collection."""

    def __init__(
        self,
        source_collection: str,
        target_collection: str,
        batch_size: int,
        mode: str = "upsert",
        metric_type: str = "COSINE",
        index_type: str = "IVF_FLAT",
        nlist: int = 1024,
        recreate_target: bool = False,
        dry_run: bool = False,
        source_conf: Optional[Dict[str, Any]] = None,
        target_conf: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.source_collection_name = source_collection
        self.target_collection_name = target_collection
        self.batch_size = batch_size
        self.mode = mode
        self.metric_type = metric_type
        self.index_type = index_type
        self.nlist = nlist
        self.recreate_target = recreate_target
        self.dry_run = dry_run

        self.source_conf = source_conf or {}
        self.target_conf = target_conf or {}

        self._connect_source()
        self._connect_target()

        self.source_collection = Collection(
            name=self.source_collection_name, using="source"
        )
        self.source_collection.load()

        self.vector_dim = self._get_vector_dim(self.source_collection)
        self.target_collection = self._ensure_target_collection()

    def _connect_source(self) -> None:
        conf = {
            "alias": "source",
            "host": self.source_conf.get("host", SOURCE_MILVUS_HOST),
            "port": str(self.source_conf.get("port", SOURCE_MILVUS_PORT)),
            "user": self.source_conf.get("user", SOURCE_MILVUS_USER),
            "password": self.source_conf.get("password", SOURCE_MILVUS_PASSWORD),
            "db_name": self.source_conf.get("db_name", SOURCE_MILVUS_DB_NAME),
            "secure": self.source_conf.get("secure", SOURCE_MILVUS_SECURE),
        }
        LOGGER.info(
            "Connecting to source Milvus %s:%s (db=%s)",
            conf["host"],
            conf["port"],
            conf["db_name"],
        )
        connections.connect(**conf)

    def _connect_target(self) -> None:
        conf = {
            "alias": "target",
            "host": self.target_conf.get("host", TARGET_MILVUS_HOST),
            "port": str(self.target_conf.get("port", TARGET_MILVUS_PORT)),
            "user": self.target_conf.get("user", TARGET_MILVUS_USER),
            "password": self.target_conf.get("password", TARGET_MILVUS_PASSWORD),
            "db_name": self.target_conf.get("db_name", TARGET_MILVUS_DB_NAME),
            "secure": self.target_conf.get("secure", TARGET_MILVUS_SECURE),
        }
        LOGGER.info(
            "Connecting to target Milvus %s:%s (db=%s)",
            conf["host"],
            conf["port"],
            conf["db_name"],
        )
        connections.connect(**conf)

    def _get_vector_dim(self, collection: Collection) -> int:
        for field in collection.schema.fields:
            if field.name == VECTOR_FIELD:
                params = getattr(field, "params", {}) or {}
                dim_value = params.get("dim")
                if dim_value:
                    return int(dim_value)
        raise RuntimeError(f"源集合缺少向量字段 {VECTOR_FIELD} 或未包含 dim 参数。")

    def _ensure_target_collection(self) -> Collection:
        has_collection = utility.has_collection(
            self.target_collection_name, using="target"
        )

        if has_collection and self.recreate_target:
            LOGGER.warning(
                "检测到目标 collection %s 已存在，根据 --recreate-target 选项将其删除后重建。",
                self.target_collection_name,
            )
            utility.drop_collection(self.target_collection_name, using="target")
            has_collection = False

        created_new = False
        if not has_collection:
            LOGGER.info(
                "目标 collection %s 不存在，开始创建 (dim=%s, 含 BM25 稀疏向量)...",
                self.target_collection_name,
                self.vector_dim,
            )
            fields = [
                FieldSchema(
                    name=PRIMARY_FIELD,
                    dtype=DataType.VARCHAR,
                    is_primary=True,
                    auto_id=False,
                    max_length=128,
                ),
                FieldSchema(
                    name=DESCRIPTION_FIELD,
                    dtype=DataType.VARCHAR,
                    max_length=65535,
                    enable_analyzer=True,
                    analyzer_params={
                        "tokenizer": "jieba",
                        "filter": ["lowercase"],
                    },
                ),
                FieldSchema(
                    name=VECTOR_FIELD,
                    dtype=DataType.FLOAT_VECTOR,
                    dim=self.vector_dim,
                ),
                FieldSchema(
                    name=SPARSE_VECTOR_FIELD,
                    dtype=DataType.SPARSE_FLOAT_VECTOR,
                ),
            ]

            bm25_function = Function(
                name=f"{DESCRIPTION_FIELD}_bm25",
                input_field_names=[DESCRIPTION_FIELD],
                output_field_names=[SPARSE_VECTOR_FIELD],
                function_type=FunctionType.BM25,
            )

            schema = CollectionSchema(
                fields=fields,
                functions=[bm25_function],
                description=f"Migrated from collection {self.source_collection_name}",
            )

            collection = Collection(
                name=self.target_collection_name,
                schema=schema,
                using="target",
                consistency_level=setting.MILVUS_CONSISTENCY_LEVEL,
            )
            created_new = True
        else:
            collection = Collection(
                name=self.target_collection_name,
                using="target",
            )

        self._ensure_indexes(collection, created_new)
        collection.load()
        return collection

    def _ensure_indexes(self, collection: Collection, created_new: bool) -> None:
        # 稠密向量索引
        try:
            vector_has_index = any(
                idx.field_name == VECTOR_FIELD for idx in collection.indexes
            )
        except Exception:
            vector_has_index = False

        if not vector_has_index:
            LOGGER.info(
                "为目标 collection %s 的向量字段 %s 创建索引 (%s/%s)...",
                self.target_collection_name,
                VECTOR_FIELD,
                self.index_type,
                self.metric_type,
            )
            try:
                collection.create_index(
                    field_name=VECTOR_FIELD,
                    index_params={
                        "index_type": self.index_type,
                        "metric_type": self.metric_type,
                        "params": {"nlist": self.nlist},
                    },
                )
            except MilvusException as exc:
                if "already exist" not in str(exc).lower() and "duplicate" not in str(
                    exc
                ).lower():
                    LOGGER.warning("创建向量索引失败: %s", exc)

        # 稀疏向量索引（BM25）
        try:
            sparse_has_index = any(
                idx.field_name == SPARSE_VECTOR_FIELD for idx in collection.indexes
            )
        except Exception:
            sparse_has_index = False

        if not sparse_has_index:
            LOGGER.info(
                "为目标 collection %s 的稀疏向量字段 %s 创建 BM25 索引...",
                self.target_collection_name,
                SPARSE_VECTOR_FIELD,
            )
            try:
                collection.create_index(
                    field_name=SPARSE_VECTOR_FIELD,
                    index_params={
                        "index_type": "SPARSE_INVERTED_INDEX",
                        "metric_type": "BM25",
                    },
                )
            except MilvusException as exc:
                if "already exist" not in str(exc).lower() and "duplicate" not in str(
                    exc
                ).lower():
                    LOGGER.warning("创建稀疏向量索引失败: %s", exc)

        if created_new:
            # 刚建完索引可能需重新 load
            collection.load()

    def migrate(self) -> None:
        total = self.source_collection.num_entities
        LOGGER.info(
            "开始迁移，源集合 %s 总计 %s 条，批大小 %s",
            self.source_collection_name,
            total,
            self.batch_size,
        )

        migrated = 0
        for batch in self._iter_source_docs():
            entities = self._prepare_entities(batch)
            if not entities:
                continue

            if self.dry_run:
                migrated += len(entities[0])
                LOGGER.info("Dry-run: 跳过写入 %s 条数据。", len(entities[0]))
                continue

            if self.mode == "insert":
                self.target_collection.insert(entities)
            else:
                self.target_collection.upsert(entities)

            migrated += len(entities[0])

        LOGGER.info("迁移完成，共写入 %s 条。", migrated)
    def _iter_source_docs(self) -> Iterable[List[Dict[str, Any]]]:
        output_fields = [PRIMARY_FIELD, DESCRIPTION_FIELD, VECTOR_FIELD]

        try:
            iterator = self.source_collection.query_iterator(
                batch_size=self.batch_size,
                filter="",                     # 全量
                output_fields=output_fields,
                limit=2147483647,              # 超大数，防止默认只返回 16384
            )
            LOGGER.info("成功启用 query_iterator，迁移速度将大幅提升！")

            while True:
                batch = iterator.next()        # 正确方式：调用 .next()
                if not batch:                  # 返回空 list 表示结束
                    break
                yield batch

            iterator.close()                   # 必须显式关闭
            return                             # 成功直接返回，不走 offset

        except Exception as e:
            LOGGER.warning("query_iterator 失败 (%s)，回退到传统 offset 分页", e)

        # ────── 以下是回退方案（老版本兼容） ──────
        offset = 0
        while True:
            res = self.source_collection.query(
                expr="",
                output_fields=output_fields,
                limit=self.batch_size,
                offset=offset,
            )
            if not res:
                break
            yield res
            offset += len(res)

    def _prepare_entities(
        self, docs: List[Dict[str, Any]]
    ) -> Optional[List[List[Any]]]:
        ids: List[str] = []
        descriptions: List[str] = []
        vectors: List[List[float]] = []

        for doc in docs:
            primary_id = doc.get(PRIMARY_FIELD)
            vector = doc.get(VECTOR_FIELD)
            description = doc.get(DESCRIPTION_FIELD)

            if not primary_id or not isinstance(vector, list):
                continue

            if not isinstance(description, str):
                description = "" if description is None else str(description)

            ids.append(str(primary_id))
            descriptions.append(description)
            vectors.append(vector)

        if not ids:
            return None
        return [ids, descriptions, vectors]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将数据从源 Milvus 集群迁移到目标 Milvus 集群（自动生成 BM25 稀疏向量）。"
    )
    parser.add_argument(
        "--source-collection",
        type=str,
        default=setting.MILVUS_COLLECTION,
        help="源 collection 名称，默认读取 setting.MILVUS_COLLECTION。",
    )
    parser.add_argument(
        "--target-collection",
        type=str,
        default=setting.MILVUS_COLLECTION,
        help="目标 collection 名称，默认与源相同。",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="单次迁移的行数，默认 1000。",
    )
    parser.add_argument(
        "--mode",
        choices=["insert", "upsert"],
        default="upsert",
        help="写入模式，默认 upsert（推荐）。",
    )
    parser.add_argument(
        "--metric-type",
        default="COSINE",
        help="目标向量索引 metric_type，默认 COSINE。",
    )
    parser.add_argument(
        "--index-type",
        default="IVF_FLAT",
        help="目标向量索引类型，默认 IVF_FLAT。",
    )
    parser.add_argument(
        "--nlist",
        type=int,
        default=1024,
        help="IVF 索引 nlist，默认 1024。",
    )
    parser.add_argument(
        "--recreate-target",
        action="store_true",
        help="若目标 collection 已存在则先删除再重建。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计可迁移数量，不写入目标。",
    )
    # 源配置
    parser.add_argument("--source-host", type=str, default=SOURCE_MILVUS_HOST)
    parser.add_argument("--source-port", type=int, default=SOURCE_MILVUS_PORT)
    parser.add_argument("--source-user", type=str, default=SOURCE_MILVUS_USER)
    parser.add_argument("--source-password", type=str, default=SOURCE_MILVUS_PASSWORD)
    parser.add_argument("--source-db", type=str, default=SOURCE_MILVUS_DB_NAME)
    parser.add_argument(
        "--source-secure",
        action="store_true",
        default=SOURCE_MILVUS_SECURE,
        help="源端开启 TLS。",
    )
    # 目标配置
    parser.add_argument("--target-host", type=str, default=TARGET_MILVUS_HOST)
    parser.add_argument("--target-port", type=int, default=TARGET_MILVUS_PORT)
    parser.add_argument("--target-user", type=str, default=TARGET_MILVUS_USER)
    parser.add_argument("--target-password", type=str, default=TARGET_MILVUS_PASSWORD)
    parser.add_argument("--target-db", type=str, default=TARGET_MILVUS_DB_NAME)
    parser.add_argument(
        "--target-secure",
        action="store_true",
        default=TARGET_MILVUS_SECURE,
        help="目标端开启 TLS。",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args()

    source_conf = {
        "host": args.source_host,
        "port": args.source_port,
        "user": args.source_user,
        "password": args.source_password,
        "db_name": args.source_db,
        "secure": args.source_secure,
    }
    target_conf = {
        "host": args.target_host,
        "port": args.target_port,
        "user": args.target_user,
        "password": args.target_password,
        "db_name": args.target_db,
        "secure": args.target_secure,
    }

    migrator = MilvusToMilvusMigrator(
        source_collection=args.source_collection,
        target_collection=args.target_collection,
        batch_size=args.batch_size,
        mode=args.mode,
        metric_type=args.metric_type,
        index_type=args.index_type,
        nlist=args.nlist,
        recreate_target=args.recreate_target,
        dry_run=args.dry_run,
        source_conf=source_conf,
        target_conf=target_conf,
    )
    migrator.migrate()


if __name__ == "__main__":
    main()
