"""
健康检查服务：存活探针与就绪探针
用于 K8s liveness / readiness 配置
"""

import time


def check_live() -> dict:
    """检查存活状态"""
    return {
        "status": "UP",
        "message": "API is running",
        "timestamp": time.time(),
    }


def check_health() -> dict:
    """检查准备状态（是否可接收流量）"""
    return {
        "status": "UP",
        "message": "API is ready to serve",
        "timestamp": time.time(),
    }
