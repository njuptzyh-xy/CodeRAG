"""
项目相关数据模型
"""
import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod


class Project(BaseModel, ABC):
    """项目基础模型"""
    project_name: str = Field(description="项目名称")
    project_path: str = Field(description="项目路径")
    readme_content: str = Field(default="", description="项目README内容")
    file_tree: str = Field(default="", description="项目文件树")

    def __init__(self, project_name: str, project_path: str, **kwargs):
        super().__init__(
            project_name=project_name,
            project_path=project_path,
            **kwargs
        )
        if not self.readme_content:
            self.readme_content = self.get_readme_content()
        if not self.file_tree:
            self.file_tree = self.get_file_tree()
    
    @abstractmethod
    def get_readme_content(self) -> str:
        """获取项目README内容"""
        pass
    
    @abstractmethod 
    def get_file_tree(self) -> str:
        """获取项目文件树"""
        pass


class RedTool(Project):
    """红队工具项目模型"""
    tactics: List[str] = Field(default=[], description="项目战术")
    main_files: List[str] = Field(default=[], description="项目主要文件")
    summary: str = Field(default="", description="项目摘要")
    project_type: str = Field(default="red_tool", description="项目类型")
    
    # 元信息字段
    author: str = Field(default="", description="作者")
    version: str = Field(default="", description="版本")
    language: str = Field(default="", description="主要编程语言")
    description: str = Field(default="", description="项目描述")
    tags: List[str] = Field(default=[], description="标签")
    
    def get_readme_content(self) -> str:
        """获取README内容"""
        readme_files = ["README.md", "readme.md", "README.txt", "readme.txt"]
        project_path = Path(self.project_path)
        
        for readme_file in readme_files:
            readme_path = project_path / readme_file
            if readme_path.exists() and readme_path.is_file():
                try:
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except UnicodeDecodeError:
                    try:
                        with open(readme_path, 'r', encoding='gbk') as f:
                            return f.read()
                    except:
                        continue
        return ""
    
    def get_file_tree(self) -> str:
        """获取项目文件树"""
        def build_tree(directory: Path, prefix: str = "", max_depth: int = 3, current_depth: int = 0) -> str:
            if current_depth >= max_depth:
                return ""
            
            tree_str = ""
            try:
                items = sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                for i, item in enumerate(items):
                    is_last = i == len(items) - 1
                    current_prefix = "└── " if is_last else "├── "
                    tree_str += f"{prefix}{current_prefix}{item.name}\n"
                    
                    if item.is_dir() and not item.name.startswith('.'):
                        next_prefix = prefix + ("    " if is_last else "│   ")
                        tree_str += build_tree(item, next_prefix, max_depth, current_depth + 1)
            except PermissionError:
                pass
            
            return tree_str
        
        project_path = Path(self.project_path)
        if project_path.exists():
            return f"{project_path.name}/\n" + build_tree(project_path)
        return ""


class ProjectAnalysisResult(BaseModel):
    """项目分析结果"""
    software_name: str = Field(description="软件名称")
    software_path: str = Field(description="软件路径")
    software_summary: str = Field(description="软件摘要")
    software_tree: str = Field(description="软件文件树")
    software_tactics: Dict[str, Any] = Field(description="软件战术分析")
    software_files: List[Dict[str, Any]] = Field(default=[], description="文件分析结果")
    analysis_timestamp: Optional[str] = Field(default=None, description="分析时间戳")
    analysis_version: str = Field(default="1.0.0", description="分析器版本")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，兼容原有输出格式"""
        return {
            "software_name": self.software_name,
            "software_path": self.software_path,
            "software_summary": self.software_summary,
            "software_tree": self.software_tree,
            "software_tactics": self.software_tactics,
            "software_files": self.software_files,
            "analysis_timestamp": self.analysis_timestamp,
            "analysis_version": self.analysis_version
        }
    
    def to_json(self, **kwargs) -> str:
        """转换为JSON字符串"""
        default_kwargs = {
            "ensure_ascii": False, 
            "indent": 2
        }
        default_kwargs.update(kwargs)
        return json.dumps(self.to_dict(), **default_kwargs)
    
    def __json__(self):
        """支持直接JSON序列化的魔术方法"""
        return self.to_dict()
    
    def model_dump_json(self, **kwargs) -> str:
        """Pydantic v2 兼容的JSON导出方法"""
        default_kwargs = {
            "ensure_ascii": False,
            "indent": 2
        }
        default_kwargs.update(kwargs)
        return json.dumps(self.to_dict(), **default_kwargs)
    
    def save_to_file(self, output_path: str) -> None:
        """保存结果到文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_json_encoder(cls):
        """获取自定义JSON编码器"""
        return ProjectAnalysisResultEncoder
    
    def model_dump(self, **kwargs) -> Dict[str, Any]:
        """Pydantic兼容的字典导出方法"""
        return self.to_dict()


class ProjectAnalysisResultEncoder(json.JSONEncoder):
    """ProjectAnalysisResult的JSON编码器类
    
    使用示例:
        result = ProjectAnalysisResult(...)
        with open("output.json", "w") as f:
            json.dump(result, f, cls=ProjectAnalysisResult.get_json_encoder(), 
                     ensure_ascii=False, indent=2)
    """
    def default(self, obj):
        if isinstance(obj, ProjectAnalysisResult):
            return obj.to_dict()
        elif hasattr(obj, 'to_dict'):
            return obj.to_dict()
        elif hasattr(obj, 'model_dump'):
            return obj.model_dump()
        elif hasattr(obj, 'dict'):
            return obj.dict()
        return super().default(obj) 