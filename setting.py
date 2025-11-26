import os

# neo4j 数据库设置
NEO4J_URI = os.getenv('NEO4J_URI', "bolt://10.7.7.200:7687")
NEO4J_USER = os.getenv('NEO4J_USER', "neo4j")
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', "D6gkdYMp3NrDzh")
INDEX_NAME = os.getenv('INDEX_NAME', "mitre_acttack_index")

# Embedding 模型设置
EMBEDDING_URL = os.getenv('EMBEDDING_URL', "http://10.7.7.200:8222/embeddings/bgem3")
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', "BAAI/bge-m3")
EMBEDDING_API_KEY = os.getenv('EMBEDDING_API_KEY', "sk-bjgqeyesmvqkyoggvgnptzkshhjheomlwktszrdfkadwpyjl")
EMBEDDING_TOP_K = int(os.getenv('EMBEDDING_TOP_K', "5"))

# Chat 模型设置
CHAT_URL = os.getenv('CHAT_URL', "https://api.deepseek.com")
CHAT_MODEL_NAME = os.getenv('CHAT_MODEL_NAME', "deepseek-chat")
CHAT_MODEL_API_KEY = os.getenv('CHAT_MODEL_API_KEY', "sk-896ca4dae917485184a075dfb363759c")
CHAT_TEMPERATURE = float(os.getenv('CHAT_TEMPERATURE', "0"))
CHAT_MAX_TOKENS = int(os.getenv('CHAT_MAX_TOKENS', "25000"))

# rerank 模型设置
RERANK_URL = os.getenv('RERANK_URL', "http://10.7.7.200:8223/rerank")
# 上传文件切块请求 url
UPLOAD_FILE_CHUNK_URL = os.getenv('UPLOAD_FILE_CHUNK_URL', "http://10.7.7.200:8004/submit-parse-job-from-file")
DOWNLOAD_FILE_CHUNK_URL = os.getenv('DOWNLOAD_FILE_CHUNK_URL', "http://10.7.7.200:8004/task-status/")
# 图片识别 url
OCR_URL = os.getenv('OCR_URL', "http://10.7.7.200/ocr-image")




# ====== ES 配置==================
# ip、端口、身份验证设置
ES_HOST = os.getenv('ES_HOST', "10.1.1.149")
ES_PORT = int(os.getenv('ES_PORT', 9200))
ES_AUTH_NAME = os.getenv('ES_AUTH_NAME', "elastic")
ES_AUTH_PASSWORD =  os.getenv('ES_AUTH_PASSWORD', "42cTNIjZAAMqmVd-p=q1")
# es 这个项目使用的索引 
ES_INDEX = os.getenv('ES_INDEX', "qax_graph_rag")
# es 这两种索引方式返回的数据量 
ES_FULLTEXT_SIZE = int(os.getenv('ES_FULLTEXT_SIZE', 50))
ES_VECTOR_SIZE = int(os.getenv('ES_VECTOR_SIZE', 10))
# es 混合搜索的时候最终返回的数据条目
ES_RETURN_SIZE = int(os.getenv('ES_RETURN_SIZE', 10))
# es 全文索引、和向量索引字段
ES_FULLTEXT_INDEX_FILED =  os.getenv('ES_FULLTEXT_INDEX_FILED', "description")
ES_VECTOR_FILED = os.getenv('ES_VECTOR_FILED', "description_embedding")
# es 全文索引结果和向量搜索结果的权重数值
ES_ALPHA = float(os.getenv('ES_ALPHA', 0.6))

# 图谱查询的节点字段
NODE_RETURN_FIELDS = {
    "MitreAttackArticleChunk": ["description", "source_url"],
    "MitreAttackArticleDocument": ["insert_type", "procedure_examples_id", "procedure_examples_name", "source_url", "title"],
    "MitreAttackCampaign": ["description", "attack_id", "attack_first_seen_citation", "attack_last_seen_citation", "name", "ref_url"],
    "MitreAttackCodeSoftware": ["description", "name"],
    "MitreAttackCodeSoftwareCodeChunk": ["description", "technique_id", "code_data"],
    "MitreAttackDataComponent": ["description", "name"],
    "MitreAttackDataSource": ["attack_id", "description", "name", "ref_url"],
    "MitreAttackGroup": ["attack_id", "description", "name", "ref_url"],
    "MitreAttackMitigation": ["attack_id", "description", "name", "ref_url"],
    "MitreAttackTactic": ["attack_id", "attack_shortname", "description", "name", "ref_url"],
    "MitreAttackTechnique": ["attack_id", "description", "name", "ref_url"]
}
# ====== Milvus 配置 ==================
MILVUS_HOST = os.getenv("MILVUS_HOST", "10.1.1.140")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_USER = os.getenv("MILVUS_USER", "root")
MILVUS_PASSWORD = os.getenv("MILVUS_PASSWORD", "Milvus")
MILVUS_DB_NAME = os.getenv("MILVUS_DB_NAME", "default")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "es_migration")
MILVUS_CONSISTENCY_LEVEL = os.getenv("MILVUS_CONSISTENCY_LEVEL", "Bounded")
MILVUS_SECURE = os.getenv("MILVUS_SECURE", "false").lower() == "true"
