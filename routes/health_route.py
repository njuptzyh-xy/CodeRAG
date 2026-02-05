"""
健康检查接口：存活探针与就绪探针
供 K8s 配置 livenessProbe / readinessProbe 使用
"""

from flask import Blueprint, jsonify
from service.health_service import check_live, check_health

health_route = Blueprint("health_route", __name__)


@health_route.route("/actuator/health/liveness", methods=["GET"])
def check_live_route():
    """存活状态检查"""
    live_status = check_live()
    return jsonify(live_status), 200


@health_route.route("/actuator/health/readiness", methods=["GET"])
def check_health_route():
    """准备状态检查"""
    health_status = check_health()
    return jsonify(health_status), 200
