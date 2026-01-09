from copy import deepcopy
from typing import Any, Dict, List, Optional

from pymilvus import AnnSearchRequest, Collection, WeightedRanker, connections, utility
from pymilvus.exceptions import MilvusException

import setting

DEFAULT_TEXT_PARAM: Dict[str, Any] = {"metric_type": "BM25"}
DEFAULT_VECTOR_PARAM: Dict[str, Any] = {"metric_type": "COSINE", "params": {"ef": 128}}


class ESHelper:
    """
    Milvus 检索辅助类。

    之所以保留 ESHelper 名称，是为了兼容上层已经写死的依赖。
    """

    def __init__(self) -> None:
        self.fulltext_field = setting.MILVUS_FULLTEXT_INDEX_FILED
        self.vector_field = setting.MILVUS_VECTOR_FILED
        self.code_field = setting.MILVUS_CODE_INDEX_FILED
        # BM25 稀疏向量字段（由 BM25 函数自动生成）
        self.sparse_vector_field = "sparse_vector"
        self.partition_names = getattr(setting, "MILVUS_PARTITION_NAMES", None)

        self.text_search_param = deepcopy(
            getattr(setting, "MILVUS_TEXT_SEARCH_PARAM", DEFAULT_TEXT_PARAM)
        )
        self.vector_search_param = deepcopy(
            getattr(setting, "MILVUS_VECTOR_SEARCH_PARAM", DEFAULT_VECTOR_PARAM)
        )

        self.collection = self._init_collection()
        
        # 直接设置需要返回的字段：neo4j_id、code_data、description
        self.output_fields = ["neo4j_id", "code_data", "description"]

    def _init_collection(self) -> Optional[Collection]:
        """连接并加载指定的 Milvus collection。"""
        try:
            connections.connect(
                alias="default",
                host=setting.MILVUS_HOST,
                port=str(setting.MILVUS_PORT),
                user=getattr(setting, "MILVUS_USER", None),
                password=getattr(setting, "MILVUS_PASSWORD", None),
                db_name=getattr(setting, "MILVUS_DB_NAME", "default"),
                secure=getattr(setting, "MILVUS_SECURE", False),
            )

            if not utility.has_collection(setting.MILVUS_COLLECTION):
                raise RuntimeError(
                    f"Milvus collection {setting.MILVUS_COLLECTION} 不存在，请先创建或迁移数据。"
                )

            collection = Collection(name=setting.MILVUS_COLLECTION)
            collection.load(partition_names=self.partition_names)
            return collection
        except MilvusException as exc:
            print(f"Milvus 初始化失败: {exc}")
        except Exception as exc:  # noqa: BLE001 - 捕获初始化阶段的所有异常
            print(f"Milvus 初始化失败: {exc}")
        return None

    def _clone_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """返回参数的深拷贝，防止 pymilvus 内部写入修改。"""
        return deepcopy(params)

    def _execute_hybrid(
        self, reqs: List[AnnSearchRequest], weights: List[float], limit: int
    ):
        if not self.collection or not reqs:
            return []

        try:
            results = self.collection.hybrid_search(
                reqs=reqs,
                rerank=WeightedRanker(*weights),
                limit=limit,
                partition_names=self.partition_names,
                output_fields=self.output_fields,
            )
            # 修复：直接返回 Hits 对象，让 _format_hits 处理转换
            # 在 Python 3.13 中，Hits 对象可能不能直接转换为列表，需要在 _format_hits 中处理
            if results and len(results) > 0:
                return results[0]
            return []
        except MilvusException as exc:
            print(f"Milvus hybrid_search 失败: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"Milvus hybrid_search 失败: {exc}")
        return []


    def _format_hits(self, hits) -> List[Dict[str, Any]]:
        if not hits:
            return []

        # 修复：处理 pymilvus Hits 对象（兼容 Python 3.13）
        # 直接迭代 Hits 对象，不先转换为列表，避免 SequenceIterator 问题
        formatted = []
        hit_scores = []
        
        try:
            # 第一遍迭代：收集所有 hit 对象和分数
            for hit in hits:
                formatted.append({
                    "id": str(hit.id),
                    "source": self._extract_source(hit),
                    "raw_score": float(hit.score or 0.0),
                    "normalized_score": 0.0,  # 先设为0，后面再计算
                })
                hit_scores.append(float(hit.score or 0.0))
        except (TypeError, ValueError) as e:
            # 如果直接迭代失败，尝试其他方法
            print(f"直接迭代 hits 失败: {type(hits)}, 错误: {e}")
            try:
                # 尝试访问 Hits 对象的内部属性
                if hasattr(hits, 'hits'):
                    hits_iter = hits.hits
                elif hasattr(hits, '_hits'):
                    hits_iter = hits._hits
                else:
                    print(f"无法找到 hits 对象的可迭代属性: {type(hits)}")
                    return []
                
                # 迭代内部属性
                for hit in hits_iter:
                    formatted.append({
                        "id": str(hit.id),
                        "source": self._extract_source(hit),
                        "raw_score": float(hit.score or 0.0),
                        "normalized_score": 0.0,
                    })
                    hit_scores.append(float(hit.score or 0.0))
            except Exception as e2:
                print(f"所有迭代方法都失败: {type(hits)}, 错误: {e2}")
                return []
        
        if not formatted:
            return []
        
        # 计算归一化分数
        max_score = max(hit_scores) if hit_scores else 1.0
        for i, item in enumerate(formatted):
            item["normalized_score"] = item["raw_score"] / max_score if max_score else 0.0
        
        return formatted

    def _extract_source(self, hit) -> Dict[str, Any]:
        """从 hit 对象中提取字段数据。"""
        payload = {}
        
        # 首先尝试从 entity 获取数据
        entity = getattr(hit, "entity", None)
        # print("entity=================\n", entity)
        # print("hit=================\n", hit)
        try:
            if entity is not None:
                entity_dict = entity.to_dict()
                if isinstance(entity_dict, dict):
                    # 先平铺顶层
                    payload.update(entity_dict)

                    # 兜底嵌套的 entity
                    nested_entity = entity_dict.get("entity")
                    if isinstance(nested_entity, dict):
                        if nested_entity.get("description") is not None:
                            payload["description"] = nested_entity.get("description", "")
                        payload.setdefault("neo4j_id", nested_entity.get("neo4j_id", ""))

                    # 顶层已有 description 则写入（避免被前面的平铺覆盖为 None）
                    if entity_dict.get("description") is not None:
                        payload["description"] = entity_dict.get("description", "")

                    # 不需要把嵌套 entity 透传出去
                    payload.pop("entity", None)

            # 有些版本字段可能在 hit.fields 中
            fields = getattr(hit, "fields", None)
            if isinstance(fields, dict):
                if fields.get("description") is not None:
                    payload["description"] = fields.get("description", "")
                if fields.get("code_data") is not None:
                    payload["code_data"] = fields.get("code_data", "")
                payload.setdefault("neo4j_id", fields.get("neo4j_id", ""))

            # 调试查看最终返回的 payload
            # print("payload_extracted=================\n", payload)

        except Exception as e:  # noqa: BLE001
            print(f"从 entity 提取数据失败: {e}")
        
        # 确保至少包含 neo4j_id（优先使用 entity 中的，否则使用 hit.id）
        if "neo4j_id" not in payload:
            if hasattr(hit, "id"):
                payload["neo4j_id"] = str(hit.id)
            else:
                print(f"警告: hit 对象没有 id 属性，无法提取 neo4j_id")
                payload["neo4j_id"] = ""
        
        return payload

    def search_by_fulltext(self, query: str) -> List[Dict[str, Any]]:
        """
        在 Milvus 上执行 BM25 全文检索。
        
        注意：BM25 索引在稀疏向量字段上，但查询时仍使用文本。
        Milvus 的 BM25 函数会自动将文本转换为稀疏向量进行检索。
        """
        if not query or not self.collection:
            return []

        # 检查稀疏向量字段是否存在
        try:
            field_names = {field.name for field in self.collection.schema.fields}
            if self.sparse_vector_field not in field_names:
                print(f"BM25 稀疏向量字段 {self.sparse_vector_field} 在集合中不存在，跳过全文检索。")
                return []
        except Exception:
            pass  # 如果检查失败，继续尝试检索

        try:
            # 使用稀疏向量字段进行检索，但查询数据仍然是文本
            # Milvus 的 BM25 函数会自动将文本转换为稀疏向量
            request = AnnSearchRequest(
                data=[query],  # 查询数据仍然是文本
                anns_field=self.sparse_vector_field,  # 但检索字段是稀疏向量字段
                param=self._clone_params(self.text_search_param),
                limit=setting.ES_FULLTEXT_SIZE,
            )
            hits = self._execute_hybrid([request], [1.0], setting.ES_FULLTEXT_SIZE)
            return self._format_hits(hits)
        except MilvusException as exc:
            # 如果字段没有 BM25 索引，会抛出异常，此时返回空列表
            if "not of vector data type" in str(exc) or "BM25" in str(exc):
                print(f"字段 {self.sparse_vector_field} 不支持 BM25 全文检索，跳过全文检索。")
            else:
                print(f"全文检索失败: {exc}")
            return []
        except Exception as exc:  # noqa: BLE001
            print(f"全文检索失败: {exc}")
            return []

    def search_by_calculate_similarity(
        self, query_vector: List[float], filter: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        在 Milvus 向量字段上执行向量检索。

        filter 参数来自旧版 ES，Milvus 目前不支持在同一请求内传入任意 DSL，
        因此这里直接忽略。
        """
        if not query_vector or not self.collection:
            return []

        if filter:
            print("Milvus 向量搜索暂不支持 filter 参数，当前请求将忽略该条件。")

        request = AnnSearchRequest(
            data=[query_vector],
            anns_field=self.vector_field,
            param=self._clone_params(self.vector_search_param),
            limit=setting.ES_VECTOR_SIZE,
        )
        hits = self._execute_hybrid([request], [1.0], setting.ES_VECTOR_SIZE)
        return self._format_hits(hits)
    # 暂时对这个混合检索策略弃用
    def hybrid_search(self, text_query: str, vector: List[float]) -> List[Dict[str, Any]]:
        """
        混合检索：分别执行全文和向量检索，再按 ES_ALPHA 进行线性融合。
        """
        fulltext_results = self.search_by_fulltext(text_query)
        vector_results = self.search_by_calculate_similarity(vector)
        
        # 添加调试信息
        print(f"全文检索结果数量: {len(fulltext_results)}")
        print(f"向量检索结果数量: {len(vector_results)}")

        combined_results: Dict[str, Dict[str, Any]] = {}
        text_weight = 1 - setting.ES_ALPHA
        vector_weight = setting.ES_ALPHA

        for item in fulltext_results:
            doc_id = item["id"]
            combined_results[doc_id] = {
                "id": doc_id,
                "source": item["source"],
                "fulltext_score": item["normalized_score"] * text_weight,
                "vector_score": 0.0,
            }

        for item in vector_results:
            doc_id = item["id"]
            entry = combined_results.setdefault(
                doc_id,
                {
                    "id": doc_id,
                    "source": item["source"],
                    "fulltext_score": 0.0,
                    "vector_score": 0.0,
                },
            )
            entry["vector_score"] = item["normalized_score"] * vector_weight
            if not entry.get("source"):
                entry["source"] = item["source"]

        result_list = list(combined_results.values())
        for item in result_list:
            item["final_score"] = item["fulltext_score"] + item["vector_score"]

        final_results = sorted(
            result_list, key=lambda x: x["final_score"], reverse=True
        )[: setting.ES_RETURN_SIZE]
        
        print(f"混合检索最终结果数量: {len(final_results)}")
        return final_results
