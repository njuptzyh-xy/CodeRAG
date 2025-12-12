"""
LangChain-based code splitter
"""
from typing import List, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

from .base import Splitter, CodeChunk
from ..run_logs.logger import logger

class LangChainCodeSplitter(Splitter):
    """
    LangChain-based code splitter using RecursiveCharacterTextSplitter
    """
    
    # Language mapping
    LANGUAGE_MAP = {
        'javascript': Language.JS,
        'typescript': Language.JS,
        'js': Language.JS,
        'ts': Language.JS,
        'python': Language.PYTHON,
        'py': Language.PYTHON,
        'java': Language.JAVA,
        'cpp': Language.CPP,
        'c++': Language.CPP,
        'c': Language.CPP,
        'go': Language.GO,
        'rust': Language.RUST,
        'rs': Language.RUST,
        'php': Language.PHP,
        'ruby': Language.RUBY,
        'rb': Language.RUBY,
        'swift': Language.SWIFT,
        'scala': Language.SCALA,
        'html': Language.HTML,
        'markdown': Language.MARKDOWN,
        'md': Language.MARKDOWN,
        'latex': Language.LATEX,
        'tex': Language.LATEX,
    }
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Initialize LangChain code splitter
        
        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Overlap size between chunks
        """
        super().__init__(chunk_size, chunk_overlap)
    
    async def split(self, code: str, language: str, file_path: Optional[str] = None) -> List[CodeChunk]:
        """
        Split code using LangChain RecursiveCharacterTextSplitter
        
        Args:
            code: Code content
            language: Programming language
            file_path: Optional file path
            
        Returns:
            List of code chunks
        """
        try:
            # Map language to LangChain format
            mapped_language = self._map_language(language)
            
            if mapped_language:
                # Use language-specific splitter
                splitter = RecursiveCharacterTextSplitter.from_language(
                    language=mapped_language,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
            else:
                # Use generic splitter
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
            
            # Split the code
            documents = splitter.create_documents([code])
            
            # Convert to CodeChunk format
            chunks = []
            for doc in documents:
                lines = self._estimate_lines(doc.page_content, code)
                chunk = CodeChunk(
                    content=doc.page_content,
                    start_line=lines['start'],
                    end_line=lines['end'],
                    language=language,
                    file_path=file_path,
                )
                chunks.append(chunk)
            
            return chunks
            
        except Exception as e:
            logger.info(f"[LangChainCodeSplitter] Error splitting code: {e}")
            raise
    
    def _map_language(self, language: str) -> Optional[Language]:
        """Map language name to LangChain Language enum"""
        return self.LANGUAGE_MAP.get(language.lower())
    
    def _estimate_lines(self, chunk: str, original_code: str) -> dict:
        """
        Estimate line numbers for a chunk
        
        Args:
            chunk: Chunk content
            original_code: Original code
            
        Returns:
            Dictionary with 'start' and 'end' line numbers
        """
        chunk_lines = chunk.split('\n')
        
        # Find chunk position in original code
        chunk_start = original_code.find(chunk)
        if chunk_start == -1:
            return {'start': 1, 'end': len(chunk_lines)}
        
        before_chunk = original_code[:chunk_start]
        start_line = len(before_chunk.split('\n'))
        end_line = start_line + len(chunk_lines) - 1
        
        return {'start': start_line, 'end': end_line}

