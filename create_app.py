from flask import Flask
from routes.upload_code_route import upload_code_route
from routes.retrieval_route import retrieval_route
from routes.neo4j_route import neo4j_route
from routes.upload_file_route import upload_file_route
from routes.health_route import health_route
from prometheus import setup_metrics


def create_app():
    app = Flask(__name__)
    register_routes(app)
    setup_metrics(app)
    return app


def register_routes(app):
    # 注册蓝图
    app.register_blueprint(health_route, url_prefix="/rag_api")
    app.register_blueprint(retrieval_route, url_prefix="/rag_api")
    app.register_blueprint(neo4j_route, url_prefix="/rag_api")
    app.register_blueprint(upload_file_route, url_prefix="/rag_api")
    app.register_blueprint(upload_code_route, url_prefix="/rag_api")


if __name__ == "__main__":
    # 本地运行代码
    app = create_app()
    config = dict(
        host="0.0.0.0",
        port=5010,
    )
    app.run(**config)
