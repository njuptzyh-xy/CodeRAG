#!/usr/bin/env python
"""
批量迁移 Elasticsearch 向量数据到 Milvus。

用法示例：
    python utils/es_to_milvus_migrator.py --batch-size 100 --collection qax_graph_rag
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch8 import Elasticsearch, helpers
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

LOGGER = logging.getLogger("es_to_milvus")
DEFAULT_BATCH_SIZE = 100
PRIMARY_FIELD = "neo4j_id"
DESCRIPTION_FIELD = setting.ES_FULLTEXT_INDEX_FILED
VECTOR_FIELD = setting.ES_VECTOR_FILED
SPARSE_VECTOR_FIELD = "sparse_vector"  # BM25 生成的稀疏向量字段


class ESMilvusMigrator:
    """Simple utility that streams ES docs into Milvus in fixed-size batches."""

    def __init__(
        self,
        batch_size: int,
        collection_name: str,
        mode: str = "upsert",
        metric_type: str = "COSINE",
        index_type: str = "IVF_FLAT",
        nlist: int = 1024,
        dry_run: bool = False,
        skipped_output: Optional[str] = None,
        recreate_collection: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.collection_name = collection_name
        self.mode = mode
        self.metric_type = metric_type
        self.index_type = index_type
        self.nlist = nlist
        self.dry_run = dry_run
        self.skipped_output = skipped_output
        self.skipped_ids: List[str] = []
        self.recreate_collection = recreate_collection

        self.es = self._build_es_client()
        self._connect_milvus()
        self.collection = self._ensure_collection()

    def _build_es_client(self) -> Elasticsearch:
        scheme = getattr(setting, "ES_SCHEME", "http")
        hosts = [{"host": setting.ES_HOST, "port": setting.ES_PORT, "scheme": scheme}]
        auth = (
            (setting.ES_AUTH_NAME, setting.ES_AUTH_PASSWORD)
            if getattr(setting, "ES_AUTH_NAME", None)
            else None
        )
        return Elasticsearch(
            hosts=hosts,
            basic_auth=auth,
            request_timeout=getattr(setting, "ES_REQUEST_TIMEOUT", 60),
            verify_certs=getattr(setting, "ES_VERIFY_CERTS", False),
            ssl_show_warn=getattr(setting, "ES_SSL_SHOW_WARN", False),
            max_retries=getattr(setting, "ES_MAX_RETRIES", 3),
            retry_on_timeout=True,
        )

    def _connect_milvus(self) -> None:
        LOGGER.info(
            "Connecting to Milvus %s:%s (db=%s)",
            setting.MILVUS_HOST,
            setting.MILVUS_PORT,
            setting.MILVUS_DB_NAME,
        )
        connections.connect(
            alias="default",
            host=setting.MILVUS_HOST,
            port=str(setting.MILVUS_PORT),
            user=setting.MILVUS_USER,
            password=setting.MILVUS_PASSWORD,
            db_name=setting.MILVUS_DB_NAME,
            secure=setting.MILVUS_SECURE,
        )

    def _ensure_collection(self) -> Collection:
        vector_dim = self._infer_vector_dim()
        if vector_dim is None:
            raise RuntimeError(
                f"无法推断向量维度，请确认 ES 中字段 {setting.ES_VECTOR_FILED} 存在且包含向量。"
            )

        has_collection = utility.has_collection(self.collection_name)
        if has_collection and self.recreate_collection:
            LOGGER.warning(
                "检测到 collection %s 已存在，根据 --recreate-collection 选项将其删除后重建。",
                self.collection_name,
            )
            utility.drop_collection(self.collection_name)
            has_collection = False

        created_new = False
        if not has_collection:
            LOGGER.info(
                "Milvus collection %s 不存在，开始创建 (dim=%s)...",
                self.collection_name,
                vector_dim,
            )
            # 创建字段列表
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
                    # 启用 analyzer 以支持 BM25 全文检索
                    enable_analyzer=True,
                    analyzer_params={
                        "tokenizer": "jieba",  # 字符级拆（中英通用）
                        "filter": [
                            "lowercase"
                        ],
                    },
                ),
                FieldSchema(
                    name=VECTOR_FIELD,
                    dtype=DataType.FLOAT_VECTOR,
                    dim=vector_dim,
                ),
                # 添加稀疏向量字段用于 BM25
                FieldSchema(
                    name=SPARSE_VECTOR_FIELD,
                    dtype=DataType.SPARSE_FLOAT_VECTOR,
                ),
            ]
            
            # 创建 BM25 函数，将文本字段转换为稀疏向量
            bm25_function = Function(
                name=f"{DESCRIPTION_FIELD}_bm25",
                input_field_names=[DESCRIPTION_FIELD],
                output_field_names=[SPARSE_VECTOR_FIELD],
                function_type=FunctionType.BM25,
            )
            
            schema = CollectionSchema(
                fields=fields,
                functions=[bm25_function],
                description="Migrated from Elasticsearch index "
                f"{setting.ES_INDEX}",
            )
            collection = Collection(
                name=self.collection_name,
                schema=schema,
                consistency_level=setting.MILVUS_CONSISTENCY_LEVEL,
            )
            created_new = True
        else:
            collection = Collection(name=self.collection_name)

        self._ensure_sparse_pipeline(collection, vector_dim, skip_validation=created_new)
        self._ensure_indexes(collection)

        collection.load()
        return collection

    def _ensure_sparse_pipeline(
        self, collection: Collection, vector_dim: int, skip_validation: bool = False
    ) -> None:
        """
        确保 collection 中包含全文检索所需的字段、函数配置，否则提示用户重新创建。
        """
        if skip_validation:
            # 我们刚刚使用正确的 schema 新建了 collection，无需重复检查
            return
        schema_fields = {field.name: field for field in collection.schema.fields}

        def _raise_missing(message: str) -> None:
            raise RuntimeError(
                f"{message}。可以重新运行脚本并添加 --recreate-collection 选项来自动创建。"
            )

        desc_field = schema_fields.get(DESCRIPTION_FIELD)
        if not desc_field:
            _raise_missing(f"集合 {self.collection_name} 缺少字段 {DESCRIPTION_FIELD}")

        vector_field = schema_fields.get(VECTOR_FIELD)
        if not vector_field:
            _raise_missing(f"集合 {self.collection_name} 缺少字段 {VECTOR_FIELD}")
        vector_params = getattr(vector_field, "params", {}) or {}
        dim_value = vector_params.get("dim")
        if dim_value not in (None, vector_dim):
            LOGGER.warning(
                "检测到集合 %s 的向量维度(%s)与 ES 推断的维度(%s)不一致。",
                self.collection_name,
                dim_value or "unknown",
                vector_dim,
            )

        if SPARSE_VECTOR_FIELD not in schema_fields:
            _raise_missing(
                f"集合 {self.collection_name} 缺少稀疏向量字段 {SPARSE_VECTOR_FIELD}"
            )

        functions = getattr(collection.schema, "functions", []) or []
        has_bm25 = False
        for func in functions:
            func_type = None
            input_fields = []
            output_fields = []
            if isinstance(func, dict):
                func_type = func.get("type")
                input_fields = func.get("input_field_names", [])
                output_fields = func.get("output_field_names", [])
            else:  # 兼容旧版 pymilvus Function 对象
                func_type = getattr(func, "function_type", None)
                input_fields = getattr(func, "input_field_names", [])
                output_fields = getattr(func, "output_field_names", [])

            if (
                func_type == FunctionType.BM25
                and DESCRIPTION_FIELD in input_fields
                and SPARSE_VECTOR_FIELD in output_fields
            ):
                has_bm25 = True
                break

        if not has_bm25:
            _raise_missing(
                f"集合 {self.collection_name} 未配置 BM25 函数从 {DESCRIPTION_FIELD} 生成 {SPARSE_VECTOR_FIELD}"
            )

    def _ensure_indexes(self, collection: Collection) -> None:
        """为向量字段和稀疏向量字段创建所需索引。"""
        try:
            # 检查向量字段是否已有索引
            index_info = collection.indexes
            vector_has_index = any(
                idx.field_name == VECTOR_FIELD for idx in index_info
            )
            if not vector_has_index:
                LOGGER.info(
                    "为 collection %s 的向量字段 %s 创建索引 (%s/%s)...",
                    self.collection_name,
                    VECTOR_FIELD,
                    self.index_type,
                    self.metric_type,
                )
                collection.create_index(
                    field_name=VECTOR_FIELD,
                    index_params={
                        "index_type": self.index_type,
                        "metric_type": self.metric_type,
                        "params": {"nlist": self.nlist},
                    },
                )
        except MilvusException as exc:
            if "already exist" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                LOGGER.warning("创建向量字段索引时出错: %s", exc)
        except Exception:
            # 如果检查失败，尝试直接创建（如果已存在会抛出异常，我们忽略）
            try:
                LOGGER.info(
                    "为 collection %s 的向量字段 %s 创建索引 (%s/%s)...",
                    self.collection_name,
                    VECTOR_FIELD,
                    self.index_type,
                    self.metric_type,
                )
                collection.create_index(
                    field_name=VECTOR_FIELD,
                    index_params={
                        "index_type": self.index_type,
                        "metric_type": self.metric_type,
                        "params": {"nlist": self.nlist},
                    },
                )
            except MilvusException as idx_exc:
                if "already exist" not in str(idx_exc).lower() and "duplicate" not in str(idx_exc).lower():
                    LOGGER.warning("创建向量字段索引时出错: %s", idx_exc)

        # 创建稀疏向量字段的 BM25 索引（用于全文检索）
        # SPARSE_INVERTED_INDEX 只能用于向量字段，所以需要为稀疏向量字段创建索引
        try:
            # 检查稀疏向量字段是否已有索引
            index_info = collection.indexes
            sparse_has_index = any(
                idx.field_name == SPARSE_VECTOR_FIELD for idx in index_info
            )
            if not sparse_has_index:
                LOGGER.info(
                    "为 collection %s 的稀疏向量字段 %s 创建 BM25 索引...",
                    self.collection_name,
                    SPARSE_VECTOR_FIELD,
                )
                collection.create_index(
                    field_name=SPARSE_VECTOR_FIELD,
                    index_params={
                        "index_type": "SPARSE_INVERTED_INDEX",
                        "metric_type": "BM25",
                    },
                )
        except MilvusException as exc:
            if "already exist" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                LOGGER.warning(
                    "为字段 %s 创建 BM25 索引失败: %s。全文检索可能无法使用。",
                    SPARSE_VECTOR_FIELD,
                    exc,
                )
        except Exception:
            # 如果检查失败，尝试直接创建（如果已存在会抛出异常，我们忽略）
            try:
                LOGGER.info(
                    "为 collection %s 的稀疏向量字段 %s 创建 BM25 索引...",
                    self.collection_name,
                    SPARSE_VECTOR_FIELD,
                )
                collection.create_index(
                    field_name=SPARSE_VECTOR_FIELD,
                    index_params={
                        "index_type": "SPARSE_INVERTED_INDEX",
                        "metric_type": "BM25",
                    },
                )
            except MilvusException as idx_exc:
                if "already exist" not in str(idx_exc).lower() and "duplicate" not in str(idx_exc).lower():
                    LOGGER.warning(
                        "为字段 %s 创建 BM25 索引失败: %s。全文检索可能无法使用。",
                        SPARSE_VECTOR_FIELD,
                        idx_exc,
                    )

    def _infer_vector_dim(self) -> Optional[int]:
        response = self.es.search(
            index=setting.ES_INDEX,
            body={
                "size": 1,
                "query": {"exists": {"field": setting.ES_VECTOR_FILED}},
                "_source": [setting.ES_VECTOR_FILED],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        vector = hits[0]["_source"].get(setting.ES_VECTOR_FILED)
        return len(vector) if isinstance(vector, list) else None

    def migrate(self) -> None:
        total = self._count_es_docs()
        LOGGER.info(
            "开始迁移，索引 %s 总计 %s 条，批大小 %s",
            setting.ES_INDEX,
            total,
            self.batch_size,
        )

        batch: List[Dict[str, Any]] = []
        migrated = 0
        for doc in self._iter_es_docs():
            batch.append(doc)
            if len(batch) >= self.batch_size:
                migrated += self._process_batch(batch)
                batch = []

        if batch:
            migrated += self._process_batch(batch)

        LOGGER.info("迁移完成，共写入 %s 条。", migrated)
        self._write_skipped_ids()

    def _count_es_docs(self) -> int:
        resp = self.es.count(index=setting.ES_INDEX, body={"query": {"match_all": {}}})
        return resp.get("count", 0)

    def _iter_es_docs(self) -> Iterable[Dict[str, Any]]:
        for doc in helpers.scan(
            self.es,
            index=setting.ES_INDEX,
            query={"query": {"match_all": {}}},
            size=self.batch_size,
            preserve_order=True,
        ):
            yield doc

    def _process_batch(self, batch: List[Dict[str, Any]]) -> int:
        entities = self._prepare_entities(batch)
        if not entities:
            return 0

        if self.dry_run:
            LOGGER.info("Dry-run: 跳过插入 %s 条数据。", len(entities[0]))
            return len(entities[0])

        try:
            if self.mode == "insert":
                self.collection.insert(entities)
            else:
                self.collection.upsert(entities)
        except MilvusException as exc:
            LOGGER.error("Milvus 写入失败: %s", exc)
            raise

        return len(entities[0])

    def _prepare_entities(
        self, docs: List[Dict[str, Any]]
    ) -> Optional[List[List[Any]]]:
        ids: List[str] = []
        descriptions: List[str] = []
        vectors: List[List[float]] = []

        for doc in docs:
            source = doc.get("_source", {})
            vector = source.get(VECTOR_FIELD)
            if not isinstance(vector, list):
                self.skipped_ids.append(str(doc["_id"]))
                continue

            primary_id = str(source.get(PRIMARY_FIELD) or doc.get("_id"))
            if not primary_id:
                self.skipped_ids.append(str(doc.get("_id", "unknown")))
                continue

            description = source.get(DESCRIPTION_FIELD)
            if not isinstance(description, str):
                description = "" if description is None else str(description)

            ids.append(primary_id)
            descriptions.append(description)
            vectors.append(vector)

        if not ids:
            return None

        return [ids, descriptions, vectors]

    def _write_skipped_ids(self) -> None:
        if not self.skipped_output:
            if self.skipped_ids:
                LOGGER.warning(
                    "检测到 %s 条因缺失向量被跳过，但未指定输出文件。", len(self.skipped_ids)
                )
            return

        if not self.skipped_ids:
            LOGGER.info("没有文档因缺失向量被跳过，跳过写入 %s。", self.skipped_output)
            return

        with open(self.skipped_output, "w", encoding="utf-8") as fh:
            fh.write("\n".join(self.skipped_ids))
        LOGGER.info(
            "共有 %s 条文档缺失向量，已写入 %s。",
            len(self.skipped_ids),
            self.skipped_output,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 ES 数据批量迁移至 Milvus。"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="单次迁移的文档数量，默认 100。",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=setting.MILVUS_COLLECTION,
        help="Milvus collection 名称，默认读取 setting.MILVUS_COLLECTION。",
    )
    parser.add_argument(
        "--mode",
        choices=["insert", "upsert"],
        default="upsert",
        help="Milvus 写入模式，默认为 upsert，方便重复迁移。",
    )
    parser.add_argument(
        "--metric-type",
        default="COSINE",
        help="Milvus 索引 metric_type，默认 COSINE。",
    )
    parser.add_argument(
        "--index-type",
        default="IVF_FLAT",
        help="Milvus 索引类型，默认 IVF_FLAT。",
    )
    parser.add_argument(
        "--nlist",
        type=int,
        default=1024,
        help="Milvus IVF 索引的 nlist，默认 1024。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计可迁移数量，不真正写入 Milvus。",
    )
    parser.add_argument(
        "--skipped-output",
        type=str,
        default="skipped_ids.txt",
        help="记录因缺失向量被跳过的文档 _id，默认写入 skipped_ids.txt。",
    )
    parser.add_argument(
        "--recreate-collection",
        action="store_true",
        help="如果 collection 已存在则先删除再重建，以确保 BM25 配置完整。",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args()
    migrator = ESMilvusMigrator(
        batch_size=args.batch_size,
        collection_name=args.collection,
        mode=args.mode,
        metric_type=args.metric_type,
        index_type=args.index_type,
        nlist=args.nlist,
        dry_run=args.dry_run,
        skipped_output=args.skipped_output,
        recreate_collection=args.recreate_collection,
    )
    migrator.migrate()


if __name__ == "__main__":
    main()

