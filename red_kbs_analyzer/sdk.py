"""
Red KBS Analyzer SDK
提供红队知识库软件分析功能的SDK接口
"""
import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

from .core.analyzer import ProjectAnalyzer
from .models.project import ProjectAnalysisResult
from .llm.interface import LLMInterface


class RedKBSAnalyzer:
    """红队知识库软件分析器 SDK"""
    
    def __init__(self, 
                 llm_config: Optional[Dict[str, Any]] = None,
                 analyzer_config: Optional[Dict[str, Any]] = None):
        """
        初始化分析器SDK
        
        Args:
            llm_config: LLM配置字典，格式为：
                {
                    "primary": {
                        "enabled": True,
                        "provider": "openai",  # "openai", "mock"
                        "api_key": "your_api_key",
                        "base_url": "https://api.openai.com/v1",  # 可选
                        "model": "gpt-3.5-turbo",
                        "temperature": 0.1,
                        "max_tokens": 2000
                    },
                    "fallback": {
                        "enabled": True,
                        "provider": "mock"
                    }
                }
            analyzer_config: 分析器配置，包含文件处理参数等
        """
        # 设置默认配置
        self.default_analyzer_config = {
            "max_file_size": 1024 * 1024,  # 1MB
            "max_chunk_chars": 3000,
            "min_chunk_lines": 5,
            "max_workers": 30,
            "max_code_files": 100,
            "max_code_length": 25000,
            "max_file_analysis_workers": 30
        }
        
        # 合并用户配置
        self.analyzer_config = {**self.default_analyzer_config}
        if analyzer_config:
            self.analyzer_config.update(analyzer_config)
        
        # 设置默认LLM配置
        self.default_llm_config = {
            "primary": {
                "enabled": False,
                "provider": "mock"
            },
            "fallback": {
                "enabled": True,
                "provider": "mock"
            }
        }
        
        # 使用用户提供的LLM配置或默认配置
        self.llm_config = llm_config or self.default_llm_config
        
        # 初始化分析器
        self.analyzer = ProjectAnalyzer(
            max_file_size=self.analyzer_config["max_file_size"],
            max_chunk_chars=self.analyzer_config["max_chunk_chars"],
            min_chunk_lines=self.analyzer_config["min_chunk_lines"],
            max_workers=self.analyzer_config["max_workers"],
            max_code_files=self.analyzer_config["max_code_files"],
            max_code_length=self.analyzer_config["max_code_length"],
            max_file_analysis_workers=self.analyzer_config["max_file_analysis_workers"],
            llm_config=self.llm_config
        )
    
    def analyze_project(self, 
                       project_path: str, 
                       project_name: Optional[str] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> ProjectAnalysisResult:
        """
        分析项目
        
        Args:
            project_path: 项目路径（绝对路径或相对路径）
            project_name: 项目名称，如果不提供则从路径中提取
            metadata: 项目元数据，可包含：
                - summary: 项目摘要
                - author: 作者
                - description: 描述
                - tags: 标签列表
                - readme_content: README内容
                - 等等
        
        Returns:
            ProjectAnalysisResult: 项目分析结果
        """
        # 规范化路径
        project_path = os.path.abspath(project_path)
        
        # 检查路径是否存在
        if not os.path.exists(project_path):
            raise FileNotFoundError(f"项目路径不存在: {project_path}")
        
        # 如果没有提供项目名称，从路径中提取
        if not project_name:
            project_name = os.path.basename(project_path)
        
        # 执行分析
        return self.analyzer.analyze_project(
            project_path=project_path,
            project_name=project_name,
            metadata=metadata or {}
        )
    
    def analyze_project_to_file(self,
                               project_path: str,
                               output_file: str,
                               project_name: Optional[str] = None,
                               metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        分析项目并将结果保存到文件
        
        Args:
            project_path: 项目路径
            output_file: 输出文件路径
            project_name: 项目名称
            metadata: 项目元数据
        
        Returns:
            str: 输出文件的绝对路径
        """
        # 执行分析
        result = self.analyze_project(project_path, project_name, metadata)
        
        # 转换为字典格式
        result_dict = result.to_dict()
        
        # 确保输出目录存在
        output_path = os.path.abspath(output_file)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # 保存到文件
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2)
        
        return output_path
    
    def analyze_multiple_projects(self,
                                 projects: List[Dict[str, Any]],
                                 output_dir: Optional[str] = None) -> List[ProjectAnalysisResult]:
        """
        批量分析多个项目
        
        Args:
            projects: 项目列表，每个项目包含：
                - path: 项目路径 (必须)
                - name: 项目名称 (可选)
                - metadata: 项目元数据 (可选)
            output_dir: 输出目录，如果提供则保存结果到文件
        
        Returns:
            List[ProjectAnalysisResult]: 分析结果列表
        """
        results = []
        
        for project_info in projects:
            project_path = project_info.get("path")
            if not project_path:
                print(f"跳过项目：缺少路径信息")
                continue
            
            project_name = project_info.get("name")
            metadata = project_info.get("metadata", {})
            
            try:
                result = self.analyze_project(project_path, project_name, metadata)
                results.append(result)
                
                # 如果提供了输出目录，保存结果
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                    result_name = project_name or os.path.basename(project_path)
                    output_file = os.path.join(output_dir, f"{result_name}_analysis.json")
                    
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
                    
                    print(f"项目 {result_name} 分析完成，结果已保存到: {output_file}")
                
            except Exception as e:
                print(f"分析项目 {project_path} 时出错: {e}")
        
        return results
    
    def set_llm_config(self, llm_config: Dict[str, Any]):
        """
        更新LLM配置
        
        Args:
            llm_config: 新的LLM配置
        """
        self.llm_config = llm_config
        self.analyzer.update_llm_config(llm_config)
    
    def get_config(self) -> Dict[str, Any]:
        """
        获取当前配置
        
        Returns:
            包含分析器配置和LLM配置的字典
        """
        return {
            "analyzer_config": self.analyzer_config,
            "llm_config": self.llm_config
        }
    
    def validate_project_path(self, project_path: str) -> bool:
        """
        验证项目路径是否有效
        
        Args:
            project_path: 项目路径
            
        Returns:
            bool: 是否有效
        """
        try:
            path = os.path.abspath(project_path)
            return os.path.exists(path) and os.path.isdir(path)
        except Exception:
            return False
    
    @staticmethod
    def create_llm_config(provider: str = "openai",
                         api_key: Optional[str] = None,
                         base_url: Optional[str] = None,
                         model: str = "deepseek-chat") -> Dict[str, Any]:
        """
        创建LLM配置的辅助方法
        
        Args:
            provider: LLM提供商 ("openai", "mock")
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
            
        Returns:
            LLM配置字典
        """
        if provider == "mock":
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
        
        elif provider == "openai":
            if not api_key:
                raise ValueError("OpenAI provider requires api_key")
            
            return {
                "primary": {
                    "enabled": True,
                    "provider": "openai",
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                    "temperature": 0.1
                },
                "fallback": {
                    "enabled": True,
                    "provider": "mock"
                }
            }
        
        else:
            raise ValueError(f"不支持的provider: {provider}")


# 为了向后兼容，提供一些便捷的别名
AnalyzerSDK = RedKBSAnalyzer
RedTeamAnalyzer = RedKBSAnalyzer 