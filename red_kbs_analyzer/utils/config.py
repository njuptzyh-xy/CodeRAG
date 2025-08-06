"""
配置管理模块 - SDK版本
仅保留分析器相关配置，移除web服务器配置
"""
import os
from typing import Optional, Dict, Any


class AnalyzerConfig:
    """分析器配置类"""
    
    def __init__(self, 
                 max_file_size: int = 1024 * 1024,  # 1MB
                 max_chunk_chars: int = 3000,
                 min_chunk_lines: int = 5,
                 max_workers: int = 30,
                 max_code_files: int = 100,
                 max_code_length: int = 25000,
                 max_file_analysis_workers: int = 30):
        """
        初始化分析器配置
        
        Args:
            max_file_size: 最大文件大小限制
            max_chunk_chars: 代码块最大字符数
            min_chunk_lines: 代码块最小行数
            max_workers: 并发处理线程数
            max_code_files: 最大代码文件数量限制
            max_code_length: 单个文件最大代码长度
            max_file_analysis_workers: 文件分析并发数
        """
        self.max_file_size = max_file_size
        self.max_chunk_chars = max_chunk_chars
        self.min_chunk_lines = min_chunk_lines
        self.max_workers = max_workers
        self.max_code_files = max_code_files
        self.max_code_length = max_code_length
        self.max_file_analysis_workers = max_file_analysis_workers
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "max_file_size": self.max_file_size,
            "max_chunk_chars": self.max_chunk_chars,
            "min_chunk_lines": self.min_chunk_lines,
            "max_workers": self.max_workers,
            "max_code_files": self.max_code_files,
            "max_code_length": self.max_code_length,
            "max_file_analysis_workers": self.max_file_analysis_workers
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'AnalyzerConfig':
        """从字典创建配置"""
        return cls(**{k: v for k, v in config_dict.items() if hasattr(cls, k)})


class LLMConfig:
    """LLM配置类"""
    
    def __init__(self,
                 provider: str = "mock",
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 model: str = "gpt-3.5-turbo",
                 temperature: float = 0.1,
                 max_tokens: int = 2000):
        """
        初始化LLM配置
        
        Args:
            provider: LLM提供商 ("openai", "mock")
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
        """
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'LLMConfig':
        """从字典创建配置"""
        return cls(**{k: v for k, v in config_dict.items() if hasattr(cls, k)})
    
    def is_enabled(self) -> bool:
        """检查配置是否启用"""
        if self.provider == "mock":
            return True
        return bool(self.api_key)


def create_default_analyzer_config() -> AnalyzerConfig:
    """创建默认分析器配置"""
    return AnalyzerConfig()


def create_default_llm_config() -> Dict[str, Any]:
    """创建默认LLM配置"""
    return {
        "primary": {
            "enabled": True,
            "provider": "mock"
        },
        "fallback": {
            "enabled": True,
            "provider": "mock"
        }
    }


def create_openai_llm_config(api_key: str,
                            base_url: Optional[str] = None,
                            model: str = "gpt-3.5-turbo") -> Dict[str, Any]:
    """创建OpenAI LLM配置"""
    return {
        "primary": {
            "enabled": True,
            "provider": "openai",
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "temperature": 0.1,
            "max_tokens": 2000
        },
        "fallback": {
            "enabled": True,
            "provider": "mock"
        }
    }


def load_config_from_env() -> Dict[str, Any]:
    """从环境变量加载配置"""
    config = {
        "analyzer": create_default_analyzer_config().to_dict(),
        "llm": create_default_llm_config()
    }
    
    # 从环境变量读取LLM配置
    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
    provider = os.getenv("LLM_PROVIDER", "mock")
    
    if provider == "openai" and api_key:
        config["llm"] = create_openai_llm_config(api_key, base_url, model)
    
    # 从环境变量读取分析器配置
    if os.getenv("MAX_FILE_SIZE"):
        config["analyzer"]["max_file_size"] = int(os.getenv("MAX_FILE_SIZE"))
    
    if os.getenv("MAX_WORKERS"):
        config["analyzer"]["max_workers"] = int(os.getenv("MAX_WORKERS"))
    
    if os.getenv("MAX_CODE_FILES"):
        config["analyzer"]["max_code_files"] = int(os.getenv("MAX_CODE_FILES"))
    
    return config


# 保持向后兼容的Settings类（简化版）
class Settings:
    """简化的设置类，用于向后兼容"""
    
    def __init__(self):
        self.app_name = "红队工具分析器 SDK"
        self.app_version = "1.0.0"
        
        # 文件处理配置
        self.max_file_size = int(os.getenv("MAX_FILE_SIZE", 1024 * 1024))
        self.max_chunk_chars = int(os.getenv("MAX_CHUNK_CHARS", 3000))
        self.min_chunk_lines = int(os.getenv("MIN_CHUNK_LINES", 5))
        self.max_workers = int(os.getenv("MAX_WORKERS", 30))
        
        # LLM配置
        self.enable_llm = True
        self.llm_primary_provider = os.getenv("LLM_PROVIDER", "mock")
        self.llm_primary_api_key = os.getenv("LLM_API_KEY")
        self.llm_primary_base_url = os.getenv("LLM_BASE_URL")
        self.llm_primary_model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", 0.1))
        self.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", 2000))
    
    def get_llm_config(self) -> Dict[str, Any]:
        """获取LLM配置"""
        if self.llm_primary_provider == "openai" and self.llm_primary_api_key:
            return create_openai_llm_config(
                api_key=self.llm_primary_api_key,
                base_url=self.llm_primary_base_url,
                model=self.llm_primary_model
            )
        else:
            return create_default_llm_config()


def get_settings() -> Settings:
    """获取配置实例（向后兼容）"""
    return Settings() 