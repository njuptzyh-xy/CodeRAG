"""
LLM接口模块
支持多种大语言模型提供商
"""
import json
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from .prompts import PromptTemplates
from .utils import extract_json_content
from ..run_logs.logger import logger


class BaseLLMClient(ABC):
    """LLM客户端基类"""
    
    @abstractmethod
    def chat_completion(self, messages: list, **kwargs) -> str:
        """聊天完成接口"""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI客户端"""
    
    def __init__(self, api_key: str, base_url: Optional[str] = None, model: str = "gpt-3.5-turbo"):
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI library not installed. Run: pip install openai")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model = model
        self.logger = logger
    
    def chat_completion(self, messages: list, **kwargs) -> str:
        """OpenAI聊天完成"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            self.logger.error(f"OpenAI API调用失败: {e}")
            raise


class MockLLMClient(BaseLLMClient):
    """模拟LLM客户端，用于测试"""
    
    def __init__(self):
        self.logger = logger
    
    def chat_completion(self, messages: list, **kwargs) -> str:
        """返回模拟响应"""
        prompt = messages[-1]["content"] if messages else ""
        
        # 根据prompt内容返回不同的模拟响应
        if "summary" in prompt.lower() and "red tool" in prompt.lower():
            return '''```json
{
    "summary": "这是一个红队工具，主要用于网络安全测试和渗透测试。该工具具备多种攻击能力，包括远程代码执行、权限提升和数据收集等功能。",
    "files": ["main.py", "exploit.py", "payload.py"]
}
```'''
        
        elif "tactics" in prompt.lower():
            return '''```json
{
    "tactics": [
        {
            "tactic": "Command and Control",
            "tactic_id": "TA0011",
            "evidence": "检测到网络通信和远程控制相关代码"
        },
        {
            "tactic": "Execution",
            "tactic_id": "TA0002", 
            "evidence": "包含代码执行和进程创建功能"
        }
    ]
}
```'''
        
        elif "technique" in prompt.lower():
            return '''```json
{
    "result": true,
    "ttps": [
        {
            "technique_id": "T1059.004",
            "name": "Unix Shell",
            "code_relevance": "检测到Shell命令执行相关代码",
            "chunk_number": 1,
            "relevance": 0.9,
            "have_code": true
        }
    ]
}
```'''
        
        return '{"error": "Unknown request type"}'


class LLMInterface:
    """LLM接口管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化LLM接口
        
        Args:
            config: LLM配置字典
        """
        self.config = config
        self.logger = logger
        self.prompt_templates = PromptTemplates()
        
        # 初始化客户端
        self.primary_client = self._create_client(config.get("primary", {}))
        self.fallback_client = self._create_client(config.get("fallback", {}))
        
        if not self.primary_client and not self.fallback_client:
            self.logger.warning("未配置有效的LLM客户端，使用模拟客户端")
            self.primary_client = MockLLMClient()
    
    def _create_client(self, client_config: Dict[str, Any]) -> Optional[BaseLLMClient]:
        """创建LLM客户端"""
        if not client_config.get("enabled", False):
            return None
        
        provider = client_config.get("provider", "openai")
        
        if provider == "openai":
            try:
                return OpenAIClient(
                    api_key=client_config.get("api_key"),
                    base_url=client_config.get("base_url"),
                    model=client_config.get("model", "gpt-3.5-turbo")
                )
            except Exception as e:
                self.logger.error(f"创建OpenAI客户端失败: {e}")
                return None
        
        elif provider == "mock":
            return MockLLMClient()
        
        else:
            self.logger.error(f"不支持的LLM提供商: {provider}")
            return None
    
    def get_llm_response(self, task: str, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        获取LLM响应
        
        Args:
            task: 任务类型
            metadata: 元数据
            
        Returns:
            LLM响应结果
        """
        try:
            # 获取prompt
            prompt = self._get_prompt(task, metadata)
            if not prompt:
                self.logger.error(f"未找到任务类型的prompt: {task}")
                return None
            
            # 构建消息
            messages = [
                {"role": "system", "content": "you are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
            
            # 尝试主要客户端
            response_content = self._call_with_fallback(messages)
            
            if response_content:
                # 提取JSON内容
                result = extract_json_content(response_content)
                if result:
                    result["status"] = "success"
                    return result
                else:
                    self.logger.error("无法从响应中提取JSON内容")
            
            return None
            
        except Exception as e:
            self.logger.error(f"LLM调用失败: {e}")
            return None
    
    def _get_prompt(self, task: str, metadata: Dict[str, Any]) -> Optional[str]:
        """获取prompt模板"""
        if task == "get_summary_red_tool":
            return self.prompt_templates.get_summary_prompt(
                readme_content=metadata.get("readme_content", ""),
                file_tree=metadata.get("file_tree", "")
            )
        
        elif task == "analyze_software_tactics":
            return self.prompt_templates.get_tactics_prompt(
                summary=metadata.get("summary", ""),
                file_code=metadata.get("file_code", ""),
                software_name=metadata.get("software_name", ""),
                software_path=metadata.get("software_path", "")
            )
        
        elif task == "analyze_file_technique":
            return self.prompt_templates.get_technique_prompt(
                code_chunks=metadata.get("code_chunks", []),
                software_name=metadata.get("software_name", ""),
                software_tactics=metadata.get("software_tactics", {}),
                file_path=metadata.get("file_path", "")
            )
        
        else:
            self.logger.error(f"未知的任务类型: {task}")
            return None
    
    def _call_with_fallback(self, messages: list) -> Optional[str]:
        """带备用方案的LLM调用"""
        # 尝试主要客户端
        if self.primary_client:
            try:
                return self.primary_client.chat_completion(messages)
            except Exception as e:
                self.logger.warning(f"主要LLM客户端调用失败，尝试备用客户端: {e}")
        
        # 尝试备用客户端
        if self.fallback_client:
            try:
                return self.fallback_client.chat_completion(messages)
            except Exception as e:
                self.logger.error(f"备用LLM客户端调用失败: {e}")
        
        return None 