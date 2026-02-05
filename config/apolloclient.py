"""
Apollo 配置中心客户端
从 Apollo 配置中心读取配置
"""
import os
import logging
from pyapollos import ApolloClient

# 配置日志
logger = logging.getLogger(__name__)

# 抑制 pyapollo 库的调试日志，避免输出 JSON 解析错误
logging.getLogger('pyapollo').setLevel(logging.CRITICAL)

# 修复pyapollo缓存目录问题
# 捕获FileExistsError以处理已存在的缓存目录
original_mkdir = os.mkdir

def fixed_mkdir(path, mode=0o777):
    """修复pyapollo中os.mkdir不处理已存在目录的问题"""
    try:
        return original_mkdir(path, mode)
    except FileExistsError:
        # 如果目录已存在，忽略错误
        if os.path.isdir(path):
            return  
        else:
            # 如果是文件存在而不是目录，重新抛出异常
            raise

# 临时替换os.mkdir以修复pyapollo的问题
os.mkdir = fixed_mkdir


class ApolloConfigClient:
    """Apollo 配置客户端 - 单例模式"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ApolloConfigClient, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):  # 防止重复初始化
            self.app_id = os.getenv("APOLLO_APP_ID", "ai-hq-redTeamRag")
            self.cluster = os.getenv("APOLLO_CLUSTER", "default")
            # Apollo 配置服务器地址
            self.meta_server = os.getenv("APOLLO_META_SERVER", "http://10.1.1.143:8080")

            if not self.meta_server:
                raise ValueError("APOLLO_META_SERVER environment variable not set.")

            try:
                self.client = ApolloClient(
                    app_id=self.app_id,
                    cluster=self.cluster,
                    config_server_url=self.meta_server,
                    namespaces=['application']
                )
                # 启动客户端，它会同步配置并开始长轮询更新
                self.client.start()
                logger.info(f"Apollo client started for AppId: {self.app_id} on Cluster: {self.cluster}")
            except Exception as e:
                logger.error(f"Failed to initialize/start Apollo client: {e}")
                raise

            self.initialized = True

    def get_value(self, key, default="", namespace='application'):
        """
        从指定的 namespace 获取配置值

        Args:
            key: 配置键
            default: 默认值
            namespace: 命名空间

        Returns:
            配置值
        """
        try:
            return self.client.get_value(key, default_val=default, namespace=namespace)
        except Exception as e:
            # 获取配置失败时静默返回默认值，避免输出错误日志
            return default


# 创建全局客户端实例
try:
    apollo_client = ApolloConfigClient()
except ValueError as e:
    logger.error(f"Could not initialize Apollo client: {e}. Running without Apollo configuration.")
    apollo_client = None
except Exception as e:
    logger.error(f"Failed to initialize Apollo client: {e}. Running without Apollo configuration.")
    apollo_client = None


if __name__ == "__main__":
    # 测试 Apollo 配置获取
    if apollo_client:
        test_key = "test"
        value = apollo_client.get_value(test_key, default="default_value", namespace='application')
        logger.info(f"Value for '{test_key}': {value}")
