"""
日志记录器
"""
import logging
import os
import sys
from datetime import datetime
import traceback

# 确保日志目录存在
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'run_logs')
os.makedirs(log_dir, exist_ok=True)

# 配置日志记录器
_logger = logging.getLogger('rag')
_logger.setLevel(logging.DEBUG)

# 获取当前日期作为日志文件名
current_date = datetime.now().strftime('%Y-%m-%d')
log_file = os.path.join(log_dir, f'rag_{current_date}.log')
file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

# 创建控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# 定义颜色代码
class Colors:
    """日志颜色"""
    DEBUG = '\033[36m'  # 青色
    INFO = '\033[32m'   # 绿色
    WARNING = '\033[33m'  # 黄色
    ERROR = '\033[31m'    # 红色
    CRITICAL = '\033[35m' # 紫色
    RESET = '\033[0m'     # 重置颜色

# 创建详细的格式化器
class ColoredFormatter(logging.Formatter):
    """颜色格式"""
    def format(self, record):
        # 添加颜色
        if record.levelno >= logging.CRITICAL:
            color = Colors.CRITICAL
        elif record.levelno >= logging.ERROR:
            color = Colors.ERROR
        elif record.levelno >= logging.WARNING:
            color = Colors.WARNING
        elif record.levelno >= logging.INFO:
            color = Colors.INFO
        else:
            color = Colors.DEBUG

        # 格式化时间
        record.asctime = datetime.fromtimestamp(
            record.created
        ).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # 获取日志级别名称
        levelname = record.levelname

        # 构建日志消息
        if hasattr(record, 'stacklevel'):
            # 使用 stacklevel 来获取正确的调用位置
            caller = logging.getLogger().findCaller(record, record.stacklevel)
            if caller:
                filename, lineno, funcname, _ = caller
                record.filename = os.path.basename(filename)
                record.lineno = lineno
                record.funcname = funcname
        else:
            record.filename = os.path.basename(record.pathname)
            record.funcname = record.funcName

        # 构建格式化的消息
        message = (
            f"{record.asctime} | "
            f"{color}{levelname:<8}{Colors.RESET} | "
            f"{record.filename}:{record.lineno} - "
            f"{record.getMessage()}"
        )

        # 如果有异常信息，添加到消息中
        if record.exc_info:
            message += f"\n{''.join(traceback.format_exception(*record.exc_info))}"

        return message

# 创建文件格式化器（不带颜色）
class FileFormatter(logging.Formatter):
    """文件格式"""
    def format(self, record):
        # 格式化时间
        record.asctime = datetime.fromtimestamp(
            record.created
        ).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # 获取日志级别名称
        levelname = record.levelname

        # 构建日志消息
        if hasattr(record, 'stacklevel'):
            # 使用 stacklevel 来获取正确的调用位置
            caller = logging.getLogger().findCaller(record, record.stacklevel)
            if caller:
                filename, lineno, funcname, _ = caller
                record.filename = os.path.basename(filename)
                record.lineno = lineno
                record.funcname = funcname
        else:
            record.filename = os.path.basename(record.pathname)
            record.funcname = record.funcName

        # 构建格式化的消息
        message = (
            f"{record.asctime} | "
            f"{levelname:<8} | "
            f"{record.filename}:{record.lineno} - "
            f"{record.getMessage()}"
        )

        # 如果有异常信息，添加到消息中
        if record.exc_info:
            message += f"\n{''.join(traceback.format_exception(*record.exc_info))}"

        return message

# 设置格式化器
file_handler.setFormatter(FileFormatter())
console_handler.setFormatter(ColoredFormatter())

# 添加处理器到日志记录器
_logger.addHandler(file_handler)
_logger.addHandler(console_handler)

# 记录日志系统初始化
_logger.info("日志系统初始化完成")

class NexusLogger:
    """自定义日志记录器"""
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NexusLogger, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.logger = _logger
            self._initialized = True
            self._current_date = datetime.now().strftime('%Y-%m-%d')
            self._check_log_date()

    def _check_log_date(self):
        """检查日期是否变化,如果变化则更新日志文件"""
        current_date = datetime.now().strftime('%Y-%m-%d')
        if current_date != self._current_date:
            # 移除旧的文件处理器
            self.logger.removeHandler(file_handler)
            
            # 创建新的文件处理器
            new_log_file = os.path.join(log_dir, f'rag_{current_date}.log')
            new_file_handler = logging.FileHandler(new_log_file, mode='a', encoding='utf-8')
            new_file_handler.setLevel(logging.DEBUG)
            new_file_handler.setFormatter(FileFormatter())
            
            # 添加新的文件处理器
            self.logger.addHandler(new_file_handler)
            self._current_date = current_date

    def info(self, message):
        """记录信息"""
        self._check_log_date()
        self.logger.info(message, stacklevel=2)

    def error(self, message):
        """记录错误"""
        self._check_log_date()
        self.logger.error(message, stacklevel=2)

    def warning(self, message):
        """记录警告"""
        self._check_log_date()
        self.logger.warning(message, stacklevel=2)

    def debug(self, message):
        """记录调试信息"""
        self._check_log_date()
        self.logger.debug(message, stacklevel=2)

    def exception(self, message):
        """记录异常信息，包括堆栈跟踪"""
        self._check_log_date()
        self.logger.error("%s\n%s", message, traceback.format_exc(), stacklevel=2)

    def critical(self, message):
        """记录严重错误"""
        self._check_log_date()
        self.logger.critical(message, stacklevel=2)

# 创建单例实例
logger = NexusLogger()
