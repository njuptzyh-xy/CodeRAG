"""
代码分割器模块
负责将代码文件分割成语义相关的代码块
基于AST解析的智能语义分割
"""
import re
from typing import List, Dict, Any, Optional
from ..models.analysis import CodeChunk, CodeFile


from llama_index.core.node_parser.text import CodeSplitter as LlamaCodeSplitter
HAS_LLAMA_INDEX = True



class CodeSplitter:
    """代码分割器 - 基于AST的语义分割"""
    
    # 语言到扩展名的映射
    LANG_EXTENSIONS = {
        "python": [".py"],
        "java": [".java"],
        "c": [".c", ".h"],
        "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".hxx"],
        "go": [".go"],
        "rust": [".rs"],
        "csharp": [".cs"],
        "javascript": [".js"],
        "typescript": [".ts"],
        "bash": [".sh"],
        "powershell": [".ps1"],
        "ruby": [".rb"],
        "php": [".php"],
        "swift": [".swift"],
        "kotlin": [".kt"],
        "scala": [".scala"],
        "r": [".r", ".R"],
        "perl": [".pl"],
        "lua": [".lua"]
    }
    
    def __init__(self, max_chars: int = 3000, min_lines: int = 5):
        """
        初始化代码分割器
        
        Args:
            max_chars: 每个代码块的最大字符数
            min_lines: 代码块的最小行数
        """
        self.max_chars = max_chars
        self.min_lines = min_lines
        
        # 如果有llama_index，使用AST分割器
        if HAS_LLAMA_INDEX:
            self._use_ast_splitter = True
        else:
            self._use_ast_splitter = False
    
    def split_file(self, code_file: CodeFile, content: str) -> List[CodeChunk]:
        """
        分割代码文件
        
        Args:
            code_file: 代码文件对象
            content: 文件内容
            
        Returns:
            代码块列表
        """
        if not content.strip():
            return []
        
        language = self._detect_language(code_file.file_name)
        
        # 如果支持AST分割且是支持的语言，使用AST分割
        if self._use_ast_splitter and self._is_ast_supported_language(language):
            try:
                return self._split_with_ast(content, code_file.file_path, language)
            except Exception as e:
                # AST分割失败时回退到基础分割
                pass
        
        # 回退到基础行分割
        return self._split_with_lines(content, code_file.file_path, language)
    
    def _is_ast_supported_language(self, language: str) -> bool:
        """检查是否支持AST分割的语言"""
        supported_languages = {
            "python", "java", "javascript", "typescript", 
            "c", "cpp", "go", "rust"
        }
        return language in supported_languages
    
    def _split_with_ast(self, content: str, file_path: str, language: str) -> List[CodeChunk]:
        """使用AST进行智能分割"""
        try:
            # 创建自定义AST分割器
            ast_splitter = CustomASTSplitter(
                language=language,
                max_chars=self.max_chars,
                min_lines=self.min_lines
            )
            
            content_bytes = content.encode('utf-8')
            chunk_dicts = ast_splitter.split_text(content_bytes, file_path)
            
            # 转换为CodeChunk对象
            chunks = []
            for idx, chunk_dict in enumerate(chunk_dicts):
                chunk = CodeChunk(
                    code=chunk_dict["content"],
                    start_line=chunk_dict["start_line"],
                    end_line=chunk_dict["end_line"],
                    file_path=file_path,
                    chunk_number=idx,
                    language=language
                )
                chunks.append(chunk)
            
            # 过滤短代码块
            chunks = [chunk for chunk in chunks 
                     if chunk.end_line - chunk.start_line >= self.min_lines]
            
            return chunks
            
        except Exception as e:
            # AST分割失败，回退到行分割
            return self._split_with_lines(content, file_path, language)
    
    def _split_with_lines(self, content: str, file_path: str, language: str) -> List[CodeChunk]:
        """基于行的基础分割"""
        lines = content.split('\n')
        
        # 移除注释（可选）
        lines = self._remove_comments(lines, language)
        
        # 分割成代码块
        chunks = self._split_into_chunks(lines, file_path, language)
        
        # 过滤短代码块
        chunks = [chunk for chunk in chunks if chunk.end_line - chunk.start_line >= self.min_lines]
        
        return chunks
    
    def _detect_language(self, filename: str) -> str:
        """检测编程语言"""
        extension = '.' + filename.split('.')[-1].lower()
        
        for lang, exts in self.LANG_EXTENSIONS.items():
            if extension in exts:
                return lang
        
        return "text"
    
    def _remove_comments(self, lines: List[str], language: str) -> List[str]:
        """移除注释行"""
        comment_patterns = {
            "python": [r'^\s*#'],
            "java": [r'^\s*//', r'^\s*/\*', r'^\s*\*'],
            "c": [r'^\s*//', r'^\s*/\*', r'^\s*\*'],
            "cpp": [r'^\s*//', r'^\s*/\*', r'^\s*\*'],
            "go": [r'^\s*//'],
            "rust": [r'^\s*//', r'^\s*/\*'],
            "csharp": [r'^\s*//', r'^\s*/\*'],
            "javascript": [r'^\s*//', r'^\s*/\*'],
            "typescript": [r'^\s*//', r'^\s*/\*'],
            "bash": [r'^\s*#'],
            "powershell": [r'^\s*#'],
            "ruby": [r'^\s*#'],
            "php": [r'^\s*//', r'^\s*#'],
        }
        
        patterns = comment_patterns.get(language, [])
        if not patterns:
            return lines
        
        filtered_lines = []
        for line in lines:
            is_comment = any(re.match(pattern, line) for pattern in patterns)
            if not is_comment:
                filtered_lines.append(line)
            else:
                # 保留空行以维持行号
                filtered_lines.append("")
        
        return filtered_lines
    
    def _split_into_chunks(self, lines: List[str], file_path: str, language: str) -> List[CodeChunk]:
        """将行分割成代码块"""
        chunks = []
        current_chunk_lines = []
        current_start_line = 1
        chunk_number = 0
        
        for i, line in enumerate(lines, 1):
            current_chunk_lines.append(line)
            current_content = '\n'.join(current_chunk_lines)
            
            # 检查是否需要分割
            if (len(current_content) >= self.max_chars or 
                self._is_logical_break(line, language) and len(current_chunk_lines) >= self.min_lines):
                
                # 创建代码块
                chunk_content = current_content.strip()
                if chunk_content:
                    chunk = CodeChunk(
                        code=chunk_content,
                        start_line=current_start_line,
                        end_line=i,
                        file_path=file_path,
                        chunk_number=chunk_number,
                        language=language
                    )
                    chunks.append(chunk)
                    chunk_number += 1
                
                # 重置
                current_chunk_lines = []
                current_start_line = i + 1
        
        # 处理最后一个代码块
        if current_chunk_lines:
            chunk_content = '\n'.join(current_chunk_lines).strip()
            if chunk_content:
                chunk = CodeChunk(
                    code=chunk_content,
                    start_line=current_start_line,
                    end_line=len(lines),
                    file_path=file_path,
                    chunk_number=chunk_number,
                    language=language
                )
                chunks.append(chunk)
        
        return chunks
    
    def _is_logical_break(self, line: str, language: str) -> bool:
        """判断是否为逻辑分割点"""
        line = line.strip()
        
        # 空行
        if not line:
            return True
        
        # 函数定义
        function_patterns = {
            "python": [r'^def\s+\w+', r'^class\s+\w+', r'^async\s+def\s+\w+'],
            "java": [r'^(public|private|protected)?\s*(static\s+)?[\w<>\[\]]+\s+\w+\s*\(', r'^(public|private|protected)?\s*class\s+\w+'],
            "c": [r'^\w+\s+\w+\s*\(', r'^struct\s+\w+', r'^typedef\s+'],
            "cpp": [r'^\w+\s+\w+\s*\(', r'^class\s+\w+', r'^struct\s+\w+'],
            "go": [r'^func\s+\w+', r'^type\s+\w+', r'^var\s+\w+'],
            "rust": [r'^fn\s+\w+', r'^struct\s+\w+', r'^enum\s+\w+', r'^impl\s+'],
            "javascript": [r'^function\s+\w+', r'^const\s+\w+\s*=\s*function', r'^class\s+\w+'],
            "typescript": [r'^function\s+\w+', r'^const\s+\w+\s*=\s*function', r'^class\s+\w+', r'^interface\s+\w+'],
        }
        
        patterns = function_patterns.get(language, [])
        return any(re.match(pattern, line) for pattern in patterns)


class CustomASTSplitter:
    """自定义AST分割器，基于llama_index的CodeSplitter"""
    
    def __init__(self, language: str, max_chars: int = 3000, min_lines: int = 5):
        self.language = language
        self.max_chars = max_chars
        self.min_lines = min_lines
        
        if HAS_LLAMA_INDEX:
            try:
                self._splitter = LlamaCodeSplitter(
                    language=language,
                    chunk_lines=40,
                    chunk_lines_overlap=15,
                    max_chars=max_chars
                )
                self._parser = getattr(self._splitter, '_parser', None)
            except Exception:
                self._splitter = None
                self._parser = None
        else:
            self._splitter = None
            self._parser = None
    
    def split_text(self, text_bytes: bytes, file_path: Optional[str] = None) -> List[Dict]:
        """分割文本为代码块"""
        if self._parser is None:
            # 回退到简单分割
            return self._fallback_split(text_bytes, file_path)
        
        try:
            # 解析代码生成AST
            tree = self._parser.parse(text_bytes)
            
            # 解析AST节点
            path_info = {"file_path": file_path} if file_path else None
            chunks = self._chunk_node(tree.root_node, text_bytes, 0, path_info)
            
            return chunks
        except Exception:
            return self._fallback_split(text_bytes, file_path)
    
    def _fallback_split(self, text_bytes: bytes, file_path: Optional[str] = None) -> List[Dict]:
        """回退分割方法"""
        text = text_bytes.decode('utf-8', errors='ignore')
        lines = text.split('\n')
        
        chunks = []
        chunk_lines = []
        start_line = 1
        chunk_num = 0
        
        for i, line in enumerate(lines, 1):
            chunk_lines.append(line)
            content = '\n'.join(chunk_lines)
            
            if len(content) >= self.max_chars and len(chunk_lines) >= self.min_lines:
                chunks.append({
                    "content": content.strip(),
                    "start_line": start_line,
                    "end_line": i,
                    "file_path": file_path,
                    "language": self.language,
                    "type": "code_block",
                    "node_name": None
                })
                chunk_lines = []
                start_line = i + 1
                chunk_num += 1
        
        if chunk_lines:
            content = '\n'.join(chunk_lines).strip()
            if content:
                chunks.append({
                    "content": content,
                    "start_line": start_line,
                    "end_line": len(lines),
                    "file_path": file_path,
                    "language": self.language,
                    "type": "code_block",
                    "node_name": None
                })
        
        return chunks
    
    def _chunk_node(self, node, text_bytes: bytes, last_end_byte_offset: int = 0, path_info: Optional[Dict] = None) -> List[Dict]:
        """递归地将AST节点切分为多个块"""
        new_chunks = []
        current_chunk_text = ""
        current_chunk_start_byte = last_end_byte_offset
        
        parent_node_type_for_fallback = node.type
        parent_node_name_for_fallback = self._get_node_name(node, text_bytes)

        if self._is_complete_semantic_unit(node.type):
            # 完整语义单元，保持完整
            node_content = text_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            node_name = self._get_node_name(node, text_bytes)

            # 跳过开头空白行
            lines = node_content.splitlines(keepends=True)
            non_blank_idx = 0
            for i, line in enumerate(lines):
                if line.strip() != "":
                    non_blank_idx = i
                    break
            else:
                non_blank_idx = len(lines)
            
            if non_blank_idx > 0:
                node_start_line += non_blank_idx
                node_content = "".join(lines[non_blank_idx:])
                node_end_line = node_start_line + node_content.count('\n')

            chunk_info = self._create_chunk_info(
                node_content,
                node_start_line,
                node_end_line,
                path_info,
                node.type,
                node_name
            )
            return [chunk_info]

        processed_child_end_byte = node.start_byte

        for child in node.children:
            # 跳过错误节点
            if child.type == "ERROR" or child.start_byte == child.end_byte:
                if child.end_byte > processed_child_end_byte:
                    inter_text_bytes = text_bytes[processed_child_end_byte:child.start_byte]
                    if inter_text_bytes:
                        current_chunk_text += inter_text_bytes.decode("utf-8", errors="ignore")
                processed_child_end_byte = max(processed_child_end_byte, child.end_byte)
                continue

            # 添加节点间文本
            if child.start_byte > processed_child_end_byte:
                inter_text_bytes = text_bytes[processed_child_end_byte:child.start_byte]
                current_chunk_text += inter_text_bytes.decode("utf-8", errors="ignore")

            if self._is_complete_semantic_unit(child.type):
                # 保存当前累积的块
                if current_chunk_text.strip():
                    current_chunk_start_line = text_bytes[:current_chunk_start_byte].count(b'\n') + 1
                    current_chunk_end_line = current_chunk_start_line + current_chunk_text.count('\n')
                    chunk_info = self._create_chunk_info(
                        current_chunk_text,
                        current_chunk_start_line,
                        current_chunk_end_line,
                        path_info,
                        parent_node_type_for_fallback,
                        parent_node_name_for_fallback
                    )
                    new_chunks.append(chunk_info)

                # 递归处理语义单元
                child_chunks = self._chunk_node(child, text_bytes, child.start_byte, path_info)
                new_chunks.extend(child_chunks)

                # 重置
                current_chunk_text = ""
                current_chunk_start_byte = child.end_byte

            else:
                # 非语义单元节点
                child_content_bytes = text_bytes[child.start_byte:child.end_byte]
                child_content_str = child_content_bytes.decode("utf-8", errors="ignore")

                # 检查长度限制
                if len(current_chunk_text.encode('utf-8')) + len(child_content_bytes) > self.max_chars and current_chunk_text.strip():
                    current_chunk_start_line = text_bytes[:current_chunk_start_byte].count(b'\n') + 1
                    current_chunk_end_line = current_chunk_start_line + current_chunk_text.count('\n')
                    chunk_info = self._create_chunk_info(
                        current_chunk_text,
                        current_chunk_start_line,
                        current_chunk_end_line,
                        path_info,
                        parent_node_type_for_fallback,
                        parent_node_name_for_fallback
                    )
                    new_chunks.append(chunk_info)

                    # 新块从这个子节点开始
                    current_chunk_text = child_content_str
                    current_chunk_start_byte = child.start_byte
                else:
                    # 累加到当前块
                    current_chunk_text += child_content_str
                    if len(current_chunk_text) == len(child_content_str):
                        current_chunk_start_byte = child.start_byte

            processed_child_end_byte = child.end_byte

        # 处理剩余文本
        if node.end_byte > processed_child_end_byte:
            remaining_text_bytes = text_bytes[processed_child_end_byte:node.end_byte]
            current_chunk_text += remaining_text_bytes.decode("utf-8", errors="ignore")

        if current_chunk_text.strip():
            current_chunk_start_line = text_bytes[:current_chunk_start_byte].count(b'\n') + 1
            current_chunk_end_line = current_chunk_start_line + current_chunk_text.count('\n')
            chunk_info = self._create_chunk_info(
                current_chunk_text,
                current_chunk_start_line,
                current_chunk_end_line,
                path_info,
                parent_node_type_for_fallback,
                parent_node_name_for_fallback
            )
            new_chunks.append(chunk_info)

        return new_chunks
    
    def _create_chunk_info(self, content: str, start_line: int, end_line: int, 
                          path_info: Optional[Dict], node_type: str, node_name: Optional[str]) -> Dict:
        """创建代码块信息字典"""
        # 确定块类型
        chunk_type = self._map_node_type_to_chunk_type(node_type)
        
        return {
            "content": content.strip(),
            "language": self.language,
            "type": chunk_type,
            "start_line": start_line,
            "end_line": end_line,
            "file_path": path_info.get("file_path") if path_info else None,
            "node_name": node_name,
        }
    
    def _map_node_type_to_chunk_type(self, node_type: str) -> str:
        """将AST节点类型映射为块类型"""
        type_mapping = {
            # Python
            "function_definition": "function",
            "class_definition": "class",
            "module": "module",
            # JavaScript/TypeScript
            "function_declaration": "function",
            "method_definition": "function",
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "program": "module",
            # Java
            "method_declaration": "method",
            "constructor_declaration": "constructor",
            # C/C++
            "class_specifier": "class",
            "struct_specifier": "struct",
            "union_specifier": "union",
            "enum_specifier": "enum",
            "namespace_definition": "namespace",
            "translation_unit": "file",
            # Go
            "type_declaration": "type_definition",
            "source_file": "package_file",
            # Rust
            "function_item": "function",
            "struct_item": "struct",
            "enum_item": "enum",
            "trait_item": "trait",
            "impl_item": "implementation",
            "mod_item": "module",
            "const_item": "constant",
            "static_item": "static",
            "macro_definition": "macro",
        }
        
        return type_mapping.get(node_type, node_type)
    
    def _get_node_name(self, node, text_bytes: bytes) -> Optional[str]:
        """获取节点名称"""
        if node.type in ["ERROR", "comment"]:
            return None

        name_node = None
        if self.language == "python":
            if node.type in ["function_definition", "class_definition"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)
        elif self.language in ["javascript", "typescript"]:
            if node.type in ["function_declaration", "class_declaration", "method_definition"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)
        elif self.language == "java":
            if node.type in ["class_declaration", "interface_declaration", "method_declaration"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)
        elif self.language in ["c", "cpp"]:
            if node.type == "function_definition":
                declarator = next((child for child in node.children if child.type == "function_declarator"), None)
                if declarator:
                    name_node = next((child for child in declarator.children if child.type == "identifier"), None)
        elif self.language == "go":
            if node.type in ["function_declaration", "method_declaration"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)
        elif self.language == "rust":
            if node.type in ["function_item", "struct_item", "enum_item"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)

        if name_node:
            return text_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
        return None
    
    def _is_complete_semantic_unit(self, node_type: str) -> bool:
        """判断是否是完整的语义单元"""
        # 文件级根节点，允许分解
        file_root_nodes = {
            "python": ["module"],
            "javascript": ["program"],
            "typescript": ["program"],
            "java": ["compilation_unit"],
            "c": ["translation_unit"],
            "cpp": ["translation_unit"],
            "go": ["source_file"],
            "rust": ["source_file"]
        }
        
        if self.language in file_root_nodes and node_type == file_root_nodes[self.language]:
            return False
        
        # 语义单元，保持完整
        semantic_units = {
            "python": ["function_definition", "class_definition"],
            "javascript": ["function_declaration", "class_declaration", "method_definition"],
            "typescript": ["function_declaration", "class_declaration", "interface_declaration", "enum_declaration", "method_definition"],
            "java": ["class_declaration", "interface_declaration", "method_declaration", "constructor_declaration"],
            "c": ["function_definition", "struct_specifier", "union_specifier", "enum_specifier"],
            "cpp": ["function_definition", "class_specifier", "struct_specifier", "union_specifier", "enum_specifier", "namespace_definition"],
            "go": ["function_declaration", "method_declaration", "type_declaration"],
            "rust": ["function_item", "struct_item", "enum_item", "trait_item", "impl_item", "mod_item", "const_item", "static_item"],
        }
        
        return node_type in semantic_units.get(self.language, []) 