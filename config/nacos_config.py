import os
from typing import Optional, Dict, Any

# 导入 Apollo 客户端
from config.apolloclient import apollo_client

# --- BATFISH 配置 ---
# 从 'BATFISH' namespace 获取配置
BATFISH_HOST = apollo_client.get_value('BATFISH_HOST', default='localhost')
BATFISH_PORT = int(apollo_client.get_value('BATFISH_PORT',  default='9996'))

# --- Nacos 配置 ---
# 从 'NACOS' namespace 获取配置
NACOS_SERVER = apollo_client.get_value('NACOS_SERVER', default='nacos.configcenter:8848')
NACOS_NAMESPACE = apollo_client.get_value('NACOS_NAMESPACE', default='public')
NACOS_SERVICE_NAME = apollo_client.get_value('NACOS_SERVICE_NAME',  default='network-topology')
NACOS_GROUP_NAME = apollo_client.get_value('NACOS_GROUP_NAME', default='DEFAULT_GROUP')
NACOS_SERVICE_PORT = int(apollo_client.get_value('NACOS_SERVICE_PORT',  default='8050'))
NACOS_USERNAME = apollo_client.get_value('NACOS_USERNAME', default='nacos')
NACOS_PASSWORD = apollo_client.get_value('NACOS_PASSWORD', default='nacos') 


# update_config 函数已被移除，因为配置现在应通过 Apollo UI 集中管理。
# 应用不应在运行时自行修改配置。

def get_nacos_config() -> Dict[str, Any]:
    """获取Nacos配置字典"""
    return {
        "server": NACOS_SERVER,
        "namespace": NACOS_NAMESPACE,
        "group_name": NACOS_GROUP_NAME,
        "service_name": NACOS_SERVICE_NAME,
        "service_port": NACOS_SERVICE_PORT,
        "username": NACOS_USERNAME,
        "password": NACOS_PASSWORD,
    }
