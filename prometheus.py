"""
Prometheus 指标服务：请求计数与延迟
在应用启动时调用 setup_metrics(app) 即可集成。
"""

import time
from flask import Flask, g, request
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from red_kbs_analyzer.run_logs.logger import logger


# 定义指标
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP Requests",
    ["method", "endpoint", "http_status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.1, 0.5, 1, 2.5, 5, 10],
)


def setup_metrics(app: Flask) -> None:
    """为 Flask 应用设置 Prometheus 指标"""
    logger.info("prometheus----------开始----------")

    @app.before_request
    def _store_start_time():
        """请求开始前记录时间"""
        g._prometheus_start_time = time.time()

    @app.after_request
    def _dispatch_metrics(response):
        """中间件，用于在每次请求后记录指标"""
        if not hasattr(g, "_prometheus_start_time"):
            return response

        # 计算延迟
        latency = time.time() - g._prometheus_start_time

        # 使用路由端点作为 endpoint，以避免指标基数爆炸
        # 例如：request.endpoint 为视图名，无匹配时用 path
        endpoint = request.endpoint if request.endpoint else request.path

        # 记录延迟
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(latency)

        # 记录请求总数
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            http_status=response.status_code,
        ).inc()

        return response

    # 添加 Prometheus 指标端点（Flask 使用路由返回 generate_latest）
    @app.route("/rag_api/actuator/prometheus", methods=["GET"])
    def _metrics_route():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    logger.info("prometheus----------完成----------")
