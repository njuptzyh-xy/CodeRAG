"""
AST-based code splitter using tree-sitter
"""
from typing import List, Optional, Dict, Any
from tree_sitter import Parser
import tree_sitter_language_pack

from .base import Splitter, CodeChunk
from .langchain_splitter import LangChainCodeSplitter
from ..run_logs.logger import logger


class ASTCodeSplitter(Splitter):
    """
    AST-based code splitter using tree-sitter
    Automatically falls back to LangChain splitter for unsupported languages
    """
    
    # Node types that represent logical code units for different languages
    SPLITTABLE_NODE_TYPES = {
        'javascript': ['function_declaration', 'arrow_function', 'class_declaration', 
                      'method_definition', 'export_statement'],
        'typescript': ['function_declaration', 'arrow_function', 'class_declaration', 
                      'method_definition', 'export_statement', 'interface_declaration', 
                      'type_alias_declaration'],
        'python': ['function_definition', 'class_definition', 'decorated_definition', 
                  'async_function_definition'],
        'java': ['method_declaration', 'class_declaration', 'interface_declaration', 
                'constructor_declaration'],
        'cpp': ['function_definition', 'class_specifier', 'namespace_definition', 'declaration'],
        'go': ['function_declaration', 'method_declaration', 'type_declaration', 
              'var_declaration', 'const_declaration'],
        'rust': ['function_item', 'impl_item', 'struct_item', 'enum_item', 'trait_item', 'mod_item'],
        'csharp': ['method_declaration', 'class_declaration', 'interface_declaration', 
                  'struct_declaration', 'enum_declaration'],
        'scala': ['method_declaration', 'class_declaration', 'interface_declaration', 
                 'constructor_declaration'],
    }
    
    # Language name mapping
    LANGUAGE_MAP = {
        'js': 'javascript',
        'ts': 'typescript',
        'tsx': 'typescript',
        'jsx': 'javascript',
        'py': 'python',
        'c++': 'cpp',
        'c': 'cpp',
        'rs': 'rust',
        'cs': 'csharp',
    }
    
    def __init__(self, chunk_size: int = 2500, chunk_overlap: int = 300):
        """
        Initialize AST code splitter
        
        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Overlap size between chunks
        """
        super().__init__(chunk_size, chunk_overlap)
        
        # Initialize fallback splitter
        self.langchain_fallback = LangChainCodeSplitter(chunk_size, chunk_overlap)
    
    async def split(self, code: str, language: str, file_path: Optional[str] = None) -> List[CodeChunk]:
        """
        Split code using AST analysis
        
        Args:
            code: Code content
            language: Programming language
            file_path: Optional file path
            
        Returns:
            List of code chunks
        """
        # Normalize language name
        normalized_lang = self.LANGUAGE_MAP.get(language.lower(), language.lower())
        
        # Check if language is supported
        if not self._is_language_supported(normalized_lang):
            logger.info(f"[ASTCodeSplitter] Language {language} not supported, using LangChain fallback")
            return await self.langchain_fallback.split(code, language, file_path)
        
        try:
            logger.info(f"[ASTCodeSplitter] Using AST splitter for {language}")
            
            # Parse code with tree-sitter
            try:
                parser = tree_sitter_language_pack.get_parser(normalized_lang)
            except ImportError:
                raise ImportError(
                    "Please install tree_sitter_language_pack to use ASTCodeSplitter."
                )
            except Exception as e:
                logger.info(
                    f"Could not get parser for language {normalized_lang}. Check "
                    "https://github.com/Goldziher/tree-sitter-language-pack for valid languages. Error: {e}"
                )
                return await self.langchain_fallback.split(code, language, file_path)
            
            if not isinstance(parser, Parser):
                raise ValueError("Parser must be a tree-sitter Parser object.")
            
            tree = parser.parse(bytes(code, 'utf-8'))
            
            if not tree.root_node:
                logger.info(f"[ASTCodeSplitter] Failed to parse AST, falling back to LangChain")
                return await self.langchain_fallback.split(code, language, file_path)
            
            # Extract chunks based on AST nodes
            node_types = self.SPLITTABLE_NODE_TYPES.get(normalized_lang, [])
            chunks = self._extract_chunks(tree.root_node, code, node_types, language, file_path)
            
            # Refine chunks (split large chunks and add overlap)
            refined_chunks = self._refine_chunks(chunks, code)
            
            return refined_chunks
            
        except Exception as e:
            logger.info(f"[ASTCodeSplitter] Error in AST splitting: {e}, falling back to LangChain")
            return await self.langchain_fallback.split(code, language, file_path)
    
    def _is_language_supported(self, language: str) -> bool:
        """Check if language is supported by AST splitter"""
        return language in self.SPLITTABLE_NODE_TYPES
    
    def _extract_chunks(
        self, 
        node: Any, 
        code: str, 
        splittable_types: List[str],
        language: str,
        file_path: Optional[str]
    ) -> List[CodeChunk]:
        """Extract chunks by traversing AST"""
        chunks = []
        code_lines = code.split('\n')
        
        # 将代码编码为字节，以便正确使用字节索引
        # tree-sitter返回的是字节偏移量，不是字符偏移量
        code_bytes = code.encode('utf-8')
        
        # 使用栈来跟踪是否在函数内部
        function_stack = []
        
        def traverse(current_node: Any) -> None:
            # 检查是否是函数定义节点
            is_function = current_node.type == 'function_definition'
            
            # 如果是函数定义，入栈
            if is_function:
                function_stack.append(current_node)
            
            # Check if this node type should be split into a chunk
            if current_node.type in splittable_types:
                # 对于声明类型的节点，检查是否在函数内部
                # 如果在函数内部，不应该单独切块，应该作为函数的一部分
                if current_node.type == 'declaration' and len(function_stack) > 0:
                    # 跳过函数内部的声明，继续遍历子节点（但不创建chunk）
                    # 这样函数内部的声明会作为函数定义的一部分被包含
                    for child in current_node.children:
                        traverse(child)
                    # 如果是函数定义，出栈
                    if is_function:
                        function_stack.pop()
                    return
                
                start_line = current_node.start_point[0] + 1
                end_line = current_node.end_point[0] + 1
                
                # 使用字节索引从bytes中切分，然后解码
                # 这样可以正确处理多字节字符（中文、韩文等）
                try:
                    node_bytes = code_bytes[current_node.start_byte:current_node.end_byte + 1]
                    node_text = node_bytes.decode('utf-8')
                except (UnicodeDecodeError, IndexError) as e:
                    # 如果解码失败，尝试使用行号重新提取
                    node_text = '\n'.join(code_lines[start_line-1:end_line])
                
                # Only create chunk if it has meaningful content
                if node_text.strip():
                    chunks.append(CodeChunk(
                        content=node_text,
                        start_line=start_line,
                        end_line=end_line,
                        language=language,
                        file_path=file_path,
                    ))
            
            # Continue traversing child nodes
            for child in current_node.children:
                traverse(child)
            
            # 如果是函数定义，出栈（在遍历完所有子节点后）
            if is_function and len(function_stack) > 0 and function_stack[-1] == current_node:
                function_stack.pop()
        
        traverse(node)
        
        # If no meaningful chunks found, create a single chunk with entire code
        if not chunks:
            chunks.append(CodeChunk(
                content=code,
                start_line=1,
                end_line=len(code_lines),
                language=language,
                file_path=file_path,
            ))
        
        return chunks
    


    # TODO 收集被遗漏的顶层模块（如import、全局变量、主逻辑等）
    def _collect_uncovered_code(
        self,
        code_lines: List[str],
        covered_lines: set,
        language: str,
        file_path: Optional[str]
    ) -> List[CodeChunk]:
        """
        收集未被函数/类定义覆盖的顶层代码
        
        Args:
            code_lines: 代码行列表
            covered_lines: 已被覆盖的行号集合
            language: 编程语言
            file_path: 文件路径
            
        Returns:
            未覆盖代码的chunks列表
        """
        uncovered_chunks = []
        current_chunk_lines = []
        current_start_line = None
        
        for line_num, line in enumerate(code_lines, start=1):
            # 跳过空行和注释行（简单判断）
            stripped_line = line.strip()
            is_empty_or_comment = (
                not stripped_line or 
                stripped_line.startswith('#') or  # Python注释
                stripped_line.startswith('//') or  # C/Java/JS注释
                stripped_line.startswith('/*') or
                stripped_line.startswith('*')
            )
            
            if line_num not in covered_lines and not is_empty_or_comment:
                # 这是一个未覆盖的有效代码行
                if current_start_line is None:
                    current_start_line = line_num
                current_chunk_lines.append(line)
            else:
                # 遇到覆盖的行或空行/注释，结束当前chunk
                if current_chunk_lines:
                    content = '\n'.join(current_chunk_lines)
                    uncovered_chunks.append(CodeChunk(
                        content=content,
                        start_line=current_start_line,
                        end_line=line_num - 1,
                        language=language,
                        file_path=file_path,
                    ))
                    current_chunk_lines = []
                    current_start_line = None
        
        # 处理最后一个chunk
        if current_chunk_lines:
            content = '\n'.join(current_chunk_lines)
            uncovered_chunks.append(CodeChunk(
                content=content,
                start_line=current_start_line,
                end_line=len(code_lines),
                language=language,
                file_path=file_path,
            ))
        
        return uncovered_chunks
    
    def _refine_chunks(self, chunks: List[CodeChunk], original_code: str) -> List[CodeChunk]:
        """Refine chunks by splitting large ones and adding overlap"""
        refined_chunks = []
        
        for chunk in chunks:
            if len(chunk.content) <= self.chunk_size:
                # 小块不需要切分，直接保留
                refined_chunks.append(chunk)
            else:
                # 大块需要切分，并在切分后的子块之间添加 overlap
                sub_chunks = self._split_large_chunk(chunk)
                # 只对当前大块切分后的子块添加 overlap
                overlapped_sub_chunks = self._add_overlap(sub_chunks)
                refined_chunks.extend(overlapped_sub_chunks)
        
        # 不再对所有块统一添加 overlap，保持 AST 结构的独立性
        return refined_chunks
    
    def _split_large_chunk(self, chunk: CodeChunk) -> List[CodeChunk]:
        """Split a large chunk into smaller sub-chunks"""
        lines = chunk.content.split('\n')
        sub_chunks = []
        current_chunk = ''
        current_start_line = chunk.start_line
        current_line_count = 0
        
        for i, line in enumerate(lines):
            line_with_newline = line if i == len(lines) - 1 else line + '\n'
            
            # 处理超长单行(如嵌入的 shellcode、base64 数据等)
            if len(line_with_newline) > self.chunk_size:
                # 先保存当前累积的内容
                if current_chunk:
                    end_line = current_start_line + current_line_count - 1
                    sub_chunks.append(CodeChunk(
                        content=current_chunk,
                        start_line=current_start_line,
                        end_line=end_line,
                        language=chunk.language,
                        file_path=chunk.file_path,
                    ))
                    current_chunk = ''
                    current_line_count = 0
                
                # 将超长行按 chunk_size 分割成多个 chunk
                line_start = current_start_line + current_line_count
                for j in range(0, len(line_with_newline), self.chunk_size):
                    segment = line_with_newline[j:j + self.chunk_size]
                    sub_chunks.append(CodeChunk(
                        content=segment,
                        start_line=line_start,
                        end_line=line_start,  # 同一行
                        language=chunk.language,
                        file_path=chunk.file_path,
                    ))
                
                current_start_line = line_start + 1
                continue
            
            if len(current_chunk) + len(line_with_newline) > self.chunk_size and current_chunk:
                # Create a sub-chunk
                end_line = current_start_line + current_line_count - 1
                sub_chunks.append(CodeChunk(
                    #content=current_chunk.strip(),
                    content=current_chunk,
                    start_line=current_start_line,
                    end_line=end_line,
                    language=chunk.language,
                    file_path=chunk.file_path,
                ))
                
                # Start new chunk: the next line after the previous chunk ended
                current_start_line = end_line + 1
                current_chunk = line_with_newline
                current_line_count = 1
            else:
                current_chunk += line_with_newline
                current_line_count += 1
        
        # Add the last sub-chunk
        if current_chunk.strip():
            sub_chunks.append(CodeChunk(
                #content=current_chunk.strip(),
                content=current_chunk,
                start_line=current_start_line,
                end_line=current_start_line + current_line_count - 2,
                language=chunk.language,
                file_path=chunk.file_path,
            ))
        
        return sub_chunks
    
    def _add_overlap(self, chunks: List[CodeChunk]) -> List[CodeChunk]:
        """Add overlap between consecutive chunks"""
        if len(chunks) <= 1 or self.chunk_overlap <= 0:
            return chunks
        
        overlapped_chunks = []
        
        for i, chunk in enumerate(chunks):
            content = chunk.content
            start_line = chunk.start_line
            
            # Add overlap from previous chunk
            if i > 0 and self.chunk_overlap > 0:
                prev_chunk = chunks[i - 1]
                prev_chunk_end_line = prev_chunk.end_line
                overlap_text = prev_chunk.content[-self.chunk_overlap:]
                content = overlap_text + '\n' + content
                start_line = max(1, prev_chunk_end_line - len(overlap_text.split('\n')) + 2)

            
            overlapped_chunks.append(CodeChunk(
                content=content,
                start_line=start_line,
                end_line=chunk.end_line,
                language=chunk.language,
                file_path=chunk.file_path,
            ))
        
        return overlapped_chunks
    
    @staticmethod
    def is_language_supported(language: str) -> bool:
        """Check if AST splitting is supported for the given language"""
        normalized = ASTCodeSplitter.LANGUAGE_MAP.get(language.lower(), language.lower())
        return normalized in ASTCodeSplitter.SPLITTABLE_NODE_TYPES

