import os

# neo4j 数据库设置
NEO4J_URI = os.getenv('NEO4J_URI', "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv('NEO4J_USER', "neo4j")
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', "D6gkdYMp3NrDzh")
INDEX_NAME = os.getenv('INDEX_NAME', "mitre_acttack_index")

# Embedding 模型设置
EMBEDDING_URL = os.getenv('EMBEDDING_URL', "http://202.112.238.121:24520/embeddings/bgem3")
EMBEDDING_TOP_K = int(os.getenv('EMBEDDING_TOP_K', "5"))

# Chat 模型设置
CHAT_URL = os.getenv('CHAT_URL', "https://api.siliconflow.cn/v1")
CHAT_MODEL_NAME = os.getenv('CHAT_MODEL_NAME', "Qwen/Qwen2.5-7B-Instruct")
CHAT_MODEL_API_KEY = os.getenv('CHAT_MODEL_API_KEY', "sk-xixodpzlalrfxhgmhxrmyykbcedfgcbmzlwhcbggcsrxzmho")
CHAT_TEMPERATURE = float(os.getenv('CHAT_TEMPERATURE', "0"))
CHAT_MAX_TOKENS = int(os.getenv('CHAT_MAX_TOKENS', "25000"))

# rerank 模型设置
RERANK_URL = os.getenv('RERANK_URL', "http://10.1.1.125:5205/rerank")

# 图谱查询的节点字段
NODE_RETURN_FIELDS = {
    "MitreAttackArticleChunk": ["description", "insert_type", "source_url"],
    "MitreAttackArticleDocument": ["insert_type", "mitre_attack_id_list", 
                                   "procedure_examples_id", "procedure_examples_name", "source_url"],
    "MitreAttackCampaign": ["description", "attack_id", "attack_first_seen_citation", 
                            "attack_last_seen_citation", "name", "ref_url", "stix_id"],
    "MitreAttackCodeSoftware": ["description", "insert_type", "software_name", "tactic_id_list"],
    "MitreAttackDataComponent": ["description", "name", "stix_id", "stix_type"],
    "MitreAttackDataSource": ["attack_id", "description", "name", "ref_url", "stix_id", "stix_type"],
    "MitreAttackGroup": ["attack_id", "description", "name", "ref_url", "stix_id", "stix_type"],
    "MitreAttackMitigation": ["attack_id", "description", "name", "ref_url", "stix_id", "stix_type"],
    "MitreAttackSoftware": ["attack_id", "description", "name", "ref_url", "stix_id", "stix_type"],
    "MitreAttackSoftwareFile": ["description", "file_name", "file_path", "insert_type", "software_name", "technique_id"],
    "MitreAttackTactic": ["attack_id", "attack_shortname", "description", "name", "ref_url", "stix_type", "stix_id"],
    "MitreAttackTechnique": ["attack_id", "description", "name", "ref_url", "stix_type", "stix_id"]
}
