import os

# neo4j 数据库设置
NEO4J_URI = os.getenv('NEO4J_URI', "bolt://10.7.7.200:7687")
NEO4J_USER = os.getenv('NEO4J_USER', "neo4j")
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', "D6gkdYMp3NrDzh")
NEO4J_DATABASE = os.getenv('NEO4J_DATABASE', "neo4j")  # 数据库名称，默认使用已有的 test 库
INDEX_NAME = os.getenv('INDEX_NAME', "mitre_acttack_index")

# Embedding 模型设置
EMBEDDING_URL = os.getenv('EMBEDDING_URL', "http://10.1.1.125:14829/get_embeddings/stella")
# EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', "BAAI/bge-m3")
EMBEDDING_API_KEY = os.getenv('EMBEDDING_API_KEY', "huaqing-embedding-key-9b677e7e-6694-11ef-83d7-ac162d803876")
# EMBEDDING_TOP_K = int(os.getenv('EMBEDDING_TOP_K', "5"))

# Chat 模型设置
CHAT_URL = os.getenv('CHAT_URL', "https://api.deepseek.com")
CHAT_MODEL_NAME = os.getenv('CHAT_MODEL_NAME', "deepseek-chat")
CHAT_MODEL_API_KEY = os.getenv('CHAT_MODEL_API_KEY', "sk-6584e56ad0ac47e58a222b1cc6b01627")
CHAT_TEMPERATURE = float(os.getenv('CHAT_TEMPERATURE', "0"))
CHAT_MAX_TOKENS = int(os.getenv('CHAT_MAX_TOKENS', "25000"))

# OpenAI 模型设置
OPENAI_URL = os.getenv('OPENAI_URL', "http://10.1.1.125:29000/v1")
OPENAI_MODEL_NAME = os.getenv('OPENAI_MODEL_NAME', "qwen3-coder")
OPENAI_TEMPERATURE = float(os.getenv('OPENAI_TEMPERATURE', "0"))
OPENAI_MAX_TOKENS = int(os.getenv('OPENAI_MAX_TOKENS', "25000"))

# rerank 模型设置
RERANK_URL = os.getenv('RERANK_URL', "http://10.7.7.200:8223/rerank")
# 上传文件切块请求 url
UPLOAD_FILE_CHUNK_URL = os.getenv('UPLOAD_FILE_CHUNK_URL', "http://10.7.7.200:8010/submit-parse-job-from-file")
DOWNLOAD_FILE_CHUNK_URL = os.getenv('DOWNLOAD_FILE_CHUNK_URL', "http://10.7.7.200:8010/task-status/")
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
MILVUS_HOST = os.getenv("MILVUS_HOST", "10.7.7.200")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_USER = os.getenv("MILVUS_USER", "root")
MILVUS_PASSWORD = os.getenv("MILVUS_PASSWORD", "Milvus")
MILVUS_DB_NAME = os.getenv("MILVUS_DB_NAME", "default")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "es_migration_new")
MILVUS_CONSISTENCY_LEVEL = os.getenv("MILVUS_CONSISTENCY_LEVEL", "Bounded")
MILVUS_SECURE = os.getenv("MILVUS_SECURE", "false").lower() == "true"
MILVUS_FULLTEXT_INDEX_FILED = os.getenv("MILVUS_FULLTEXT_INDEX_FILED", "code_data")
MILVUS_CODE_INDEX_FILED = os.getenv("MILVUS_CODE_INDEX_FILED", "code_data")
MILVUS_VECTOR_FILED = os.getenv("MILVUS_VECTOR_FILED", "code__embedding")

# ====== Claude Code API Keys 配置 ==================
# Claude API Keys (号池)，多个 key 用逗号分隔
CLAUDE_API_KEYS_STR = os.getenv('CLAUDE_API_KEYS', '')
if CLAUDE_API_KEYS_STR:
    CLAUDE_API_KEYS = [k.strip() for k in CLAUDE_API_KEYS_STR.split(',') if k.strip()]
else:
    # 默认 keys
    CLAUDE_API_KEYS = [
        "feb3a0948a184509bad92e479d255647.HNv6D8wSoml1Da5o",
        "31a5536a55114d2287e665a08c4f27e1.Ncmlk0cQ16RflsBz",
        "935ec0bffaa343c5a25ade89a4b96230.3N0NwmxiKwW6tMV3",
    ]


# Gitea 配置
GITEA_URL = os.getenv('GITEA_URL', 'http://10.1.1.155:3000')
GITEA_ADMIN_USER = os.getenv('GITEA_ADMIN_USER', 'root')
GITEA_ADMIN_PASSWORD = os.getenv('GITEA_ADMIN_PASSWORD', 'Admin@1234')
GITEA_ORG_NAME = os.getenv('GITEA_ORG_NAME', 'red_team_rag')