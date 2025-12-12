"""
Base splitter interface and types
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


@dataclass
class CodeChunk:
    """A chunk of code with metadata"""
    content: str
    start_line: int
    end_line: int
    language: str
    file_path: Optional[str] = None


class SplitterType(str, Enum):
    """Splitter type enumeration"""
    LANGCHAIN = 'langchain'
    AST = 'ast'


@dataclass
class SplitterConfig:
    """Splitter configuration"""
    type: SplitterType = SplitterType.AST
    chunk_size: int = 2500
    chunk_overlap: int = 300


class Splitter(ABC):
    """
    Abstract base class for code splitters
    """
    
    def __init__(self, chunk_size: int = 2500, chunk_overlap: int = 300):
        """
        Initialize splitter
        
        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Overlap size between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    @abstractmethod
    async def split(self, code: str, language: str, file_path: Optional[str] = None) -> List[CodeChunk]:
        """
        Split code into chunks
        
        Args:
            code: Code content
            language: Programming language
            file_path: Optional file path
            
        Returns:
            List of code chunks
        """
        pass
    
    def set_chunk_size(self, chunk_size: int) -> None:
        """Set chunk size"""
        self.chunk_size = chunk_size
    
    def set_chunk_overlap(self, chunk_overlap: int) -> None:
        """Set chunk overlap"""
        self.chunk_overlap = chunk_overlap

