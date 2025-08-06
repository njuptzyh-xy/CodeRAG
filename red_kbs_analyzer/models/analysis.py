"""
分析结果相关数据模型
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class TacticAnalysis(BaseModel):
    """战术分析结果"""
    tactic: str = Field(description="战术名称")
    tactic_id: str = Field(description="战术ID")
    evidence: str = Field(description="证据描述")


class TechniqueAnalysis(BaseModel):
    """技术分析结果"""
    technique_id: str = Field(description="技术ID")
    name: str = Field(description="技术名称")
    code_relevance: str = Field(description="代码相关性描述")
    chunk_number: int = Field(description="代码块编号")
    relevance: float = Field(description="相关度评分")
    have_code: bool = Field(description="是否包含代码")
    chunk_code: Optional[str] = Field(default=None, description="代码块内容")
    chunk_start_line: Optional[int] = Field(default=None, description="代码块起始行")
    chunk_end_line: Optional[int] = Field(default=None, description="代码块结束行")


class FileAnalysisResult(BaseModel):
    """文件分析结果"""
    file_name: str = Field(description="文件名")
    file_abs_path: str = Field(description="文件绝对路径")
    file_technique: Dict[str, Any] = Field(description="文件技术分析结果")


class CodeChunk(BaseModel):
    """代码块模型"""
    code: str = Field(description="代码内容")
    start_line: int = Field(description="起始行号")
    end_line: int = Field(description="结束行号")
    file_path: str = Field(description="文件路径")
    chunk_number: int = Field(description="代码块编号")
    language: Optional[str] = Field(default=None, description="编程语言")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "code": self.code,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "file_path": self.file_path,
            "chunk_number": self.chunk_number,
            "language": self.language
        }


class CodeFile(BaseModel):
    """代码文件模型"""
    file_path: str = Field(description="文件路径")
    file_abs_path: str = Field(description="文件绝对路径")
    file_name: str = Field(description="文件名")
    file_size: int = Field(description="文件大小")
    file_type: str = Field(description="文件类型")
    project_root: str = Field(description="项目根目录")
    project_name: str = Field(description="项目名称")
    chunks: List[CodeChunk] = Field(default=[], description="代码块列表")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "file_path": self.file_path,
            "file_abs_path": self.file_abs_path,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "project_root": self.project_root,
            "project_name": self.project_name,
            "chunks": [chunk.to_dict() for chunk in self.chunks]
        } 