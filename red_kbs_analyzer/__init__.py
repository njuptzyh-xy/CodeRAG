"""
红色知识库软件分析器 SDK
提供项目上传、分析和战术技术识别功能的SDK接口

使用示例:
    from red_kbs_analyzer import RedKBSAnalyzer
    
    # 创建分析器
    analyzer = RedKBSAnalyzer()
    
    # 分析项目
    result = analyzer.analyze_project("/path/to/project")
    
    # 使用自定义LLM配置
    llm_config = RedKBSAnalyzer.create_llm_config(
        provider="openai",
        api_key="your_api_key"
    )
    analyzer = RedKBSAnalyzer(llm_config=llm_config)
"""

__version__ = "1.0.0"
__author__ = "Red Team KBS"

# 主要SDK接口
from .sdk import RedKBSAnalyzer, AnalyzerSDK, RedTeamAnalyzer

# 核心模型和结果类
from .models.project import ProjectAnalysisResult, RedTool, ProjectAnalysisResultEncoder
from .models.analysis import CodeFile, CodeChunk

# LLM接口（用于高级用户）
from .llm.interface import LLMInterface

# 核心分析器（用于高级用户）
from .core.analyzer import ProjectAnalyzer

# 主要导出
__all__ = [
    # 主SDK接口
    "RedKBSAnalyzer",
    "AnalyzerSDK", 
    "RedTeamAnalyzer",
    
    # 结果模型
    "ProjectAnalysisResult",
    "ProjectAnalysisResultEncoder",
    "RedTool",
    "CodeFile", 
    "CodeChunk",
    
    # 高级接口
    "LLMInterface",
    "ProjectAnalyzer",
    
    # 版本信息
    "__version__",
    "__author__"
] 