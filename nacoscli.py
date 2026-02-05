import os
import nacos
import atexit
from red_kbs_analyzer.run_logs.logger import logger
from config.nacos_config import get_nacos_config

# 获取配置
nacos_config = get_nacos_config()

logger.info(f"=======nacos_config配置项:{nacos_config}")

# 从环境变量或配置获取认证信息（优先使用环境变量）
nacos_username = os.getenv('NACOS_USERNAME', nacos_config.get("username"))
nacos_password = os.getenv('NACOS_PASSWORD', nacos_config.get("password"))


def get_pod_ip():
    """获取当前Pod的IP地址"""
    pod_ip = os.getenv('POD_IP')
    if pod_ip:
        return pod_ip
    else:
        return "127.0.0.1"


# 初始化客户端（支持认证和非认证两种模式）
def create_nacos_client():
    try:
        client_kwargs = {
            'server_addresses': nacos_config['server'],
            'namespace': nacos_config["namespace"]
        }

        # 只有同时配置了用户名和密码时才启用认证
        if nacos_username and nacos_password:
            client_kwargs.update({
                'username': nacos_username,
                'password': nacos_password
            })
            logger.info("Nacos客户端将使用认证连接")
        else:
            logger.info("Nacos连接未配置认证信息，将使用非认证模式")

        return nacos.NacosClient(**client_kwargs)
    except Exception as e:
        logger.error(f"创建nacos客户端时失败: {str(e)}")


client = create_nacos_client()
logger.info(f"Nacos客户端client:{client}")


def register_service(ip, port):
    """注册服务到 Nacos"""
    try:
        client.add_naming_instance(
            service_name=nacos_config["service_name"],
            ip=ip,
            port=port,
            group_name=nacos_config["group_name"],
            ephemeral=True,
            metadata={
                'version': '1.0',
                'protocol': 'http',
                'healthCheckPath': '/actuator/health/liveness',
                'healthCheckUrl': '/actuator/health/liveness'
            },
            heartbeat_interval=15
        )
        logger.info(f"成功注册服务到Nacos: {ip}:{port}")
    except Exception as e:
        logger.error(f"服务注册失败: {str(e)}")


def deregister_service(ip, port):
    """从 Nacos 注销服务"""
    try:
        client.remove_naming_instance(
            service_name=nacos_config["service_name"],
            ip=ip,
            port=port,
            group_name=nacos_config["group_name"]
        )
        logger.info(f"成功从Nacos注销服务: {ip}:{port}")
    except Exception as e:
        logger.error(f"服务注销失败: {str(e)}")


def nacos_register():
    """服务注册入口函数"""
    try:
        logger.info("nacos注册服务----------开始----------")
        pod_ip = get_pod_ip()

        service_port = nacos_config["service_port"]
        logger.info(f"使用get_pod_ip注册服务，IP: {pod_ip}、PORT:{service_port}")
        register_service(pod_ip, service_port)

        # 注册退出处理
        atexit.register(
            deregister_service,
            pod_ip,
            nacos_config["service_port"]
        )
        logger.info("nacos注册服务----------完成----------")
    except Exception as e:
        logger.error(f"nacos注册过程出错: {str(e)}")