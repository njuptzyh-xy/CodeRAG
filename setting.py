"""应用配置：从环境变量读取，未设置时使用默认值。"""

import os


def _get(key: str, default: str = "") -> str:
    """从环境变量获取配置，未设置时返回默认值。"""
    return os.getenv(key, default)


# neo4j 数据库设置
NEO4J_URI = _get("NEO4J_URI", "bolt://10.7.7.200:17687")
NEO4J_USER = _get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = _get("NEO4J_PASSWORD", "D6gkdYMp3NrDzh")
NEO4J_DATABASE = _get("NEO4J_DATABASE", "neo4j")
INDEX_NAME = _get("INDEX_NAME", "mitre_acttack_index")

# Embedding 模型设置
EMBEDDING_URL = _get("EMBEDDING_URL", "http://10.1.1.125:14829/get_embeddings/stella")
EMBEDDING_API_KEY = _get(
    "EMBEDDING_API_KEY", "huaqing-embedding-key-9b677e7e-6694-11ef-83d7-ac162d803876"
)

# Chat 模型设置
CHAT_URL = _get("CHAT_URL", "https://api.deepseek.com")
CHAT_MODEL_NAME = _get("CHAT_MODEL_NAME", "deepseek-chat")
CHAT_MODEL_API_KEY = _get("CHAT_MODEL_API_KEY", "sk-53b49f7e5a9748a58ac7c1a44673c778")
CHAT_TEMPERATURE = float(_get("CHAT_TEMPERATURE", "0"))
CHAT_MAX_TOKENS = int(_get("CHAT_MAX_TOKENS", "25000"))

# OpenAI 模型设置
OPENAI_URL = _get("OPENAI_URL", "http://10.1.1.125:29000/v1")
OPENAI_MODEL_NAME = _get("OPENAI_MODEL_NAME", "qwen3-coder")
OPENAI_TEMPERATURE = float(_get("OPENAI_TEMPERATURE", "0"))
OPENAI_MAX_TOKENS = int(_get("OPENAI_MAX_TOKENS", "25000"))

# rerank 模型设置
RERANK_URL = _get("RERANK_URL", "http://10.7.7.200:8223/rerank")
# 上传文件切块请求 url
UPLOAD_FILE_CHUNK_URL = _get(
    "UPLOAD_FILE_CHUNK_URL", "http://10.7.7.200:8010/submit-parse-job-from-file"
)
DOWNLOAD_FILE_CHUNK_URL = _get(
    "DOWNLOAD_FILE_CHUNK_URL", "http://10.7.7.200:8010/task-status/"
)
# 图片识别 url
OCR_URL = _get("OCR_URL", "http://10.7.7.200/ocr-image")

# 图谱查询的节点字段（固定结构，一般不需按环境变更）
NODE_RETURN_FIELDS = {
    "MitreAttackArticleChunk": ["description", "source_url", "repo_url"],
    "MitreAttackArticleDocument": [
        "insert_type",
        "procedure_examples_id",
        "procedure_examples_name",
        "source_url",
        "title",
        "repo_url",
    ],
    "MitreAttackCampaign": [
        "description",
        "attack_id",
        "attack_first_seen_citation",
        "attack_last_seen_citation",
        "name",
        "ref_url",
    ],
    "MitreAttackCodeSoftware": ["description", "name", "repo_url"],
    "MitreAttackCodeSoftwareCodeChunk": [
        "description",
        "technique_id",
        "code_data",
        "repo_url",
    ],
    "MitreAttackDataComponent": ["description", "name"],
    "MitreAttackDataSource": ["attack_id", "description", "name", "ref_url"],
    "MitreAttackGroup": ["attack_id", "description", "name", "ref_url"],
    "MitreAttackMitigation": ["attack_id", "description", "name", "ref_url"],
    "MitreAttackTactic": [
        "attack_id",
        "attack_shortname",
        "description",
        "name",
        "ref_url",
    ],
    "MitreAttackTechnique": ["attack_id", "description", "name", "ref_url"],
}

# ====== Milvus 配置 ==================
MILVUS_HOST = _get("MILVUS_HOST", "10.7.7.200")
MILVUS_PORT = int(_get("MILVUS_PORT", "19534"))
MILVUS_USER = _get("MILVUS_USER", "root")
MILVUS_PASSWORD = _get("MILVUS_PASSWORD", "Milvus")
MILVUS_DB_NAME = _get("MILVUS_DB_NAME", "default")
MILVUS_COLLECTION = _get("MILVUS_COLLECTION", "es_migration_new")
MILVUS_CONSISTENCY_LEVEL = _get("MILVUS_CONSISTENCY_LEVEL", "Bounded")
MILVUS_SECURE = _get("MILVUS_SECURE", "false").lower() == "true"
MILVUS_FULLTEXT_INDEX_FILED = _get("MILVUS_FULLTEXT_INDEX_FILED", "code_data")
MILVUS_CODE_INDEX_FILED = _get("MILVUS_CODE_INDEX_FILED", "code_data")
MILVUS_VECTOR_FILED = _get("MILVUS_VECTOR_FILED", "code__embedding")
MILVUS_FULLTEXT_SIZE = int(_get("MILVUS_FULLTEXT_SIZE", "50"))
MILVUS_VECTOR_SIZE = int(_get("MILVUS_VECTOR_SIZE", "10"))
MILVUS_RETURN_SIZE = int(_get("MILVUS_RETURN_SIZE", "10"))
MILVUS_HYBRID_ALPHA = float(_get("MILVUS_HYBRID_ALPHA", "0.6"))

# ====== Claude Code API Keys 配置 ==================
CLAUDE_API_KEYS_STR = _get("CLAUDE_API_KEYS", "")
if CLAUDE_API_KEYS_STR:
    CLAUDE_API_KEYS = [k.strip() for k in CLAUDE_API_KEYS_STR.split(",") if k.strip()]
else:
    CLAUDE_API_KEYS = [
        "feb3a0948a184509bad92e479d255647.HNv6D8wSoml1Da5o",
        "31a5536a55114d2287e665a08c4f27e1.Ncmlk0cQ16RflsBz",
        "935ec0bffaa343c5a25ade89a4b96230.3N0NwmxiKwW6tMV3",
    ]

# ====== Claude Code 项目路径配置 ==================
PROJECT_ROOT = os.path.abspath(_get("CLAUDE_PROJECT_ROOT", "/root/workspace/ch"))
UPLOAD_CODE_DIR = os.path.join(PROJECT_ROOT, "upload_code")

# Gitea 配置
GITEA_URL = _get("GITEA_URL", "http://10.1.1.155:3000")
GITEA_ADMIN_USER = _get("GITEA_ADMIN_USER", "root")
GITEA_ADMIN_PASSWORD = _get("GITEA_ADMIN_PASSWORD", "Admin@1234")
GITEA_ORG_NAME = _get("GITEA_ORG_NAME", "red_team_rag")
