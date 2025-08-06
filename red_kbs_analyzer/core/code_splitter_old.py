"""
代码切片的核心功能实现，基于llama_index的CodeSplitter
"""
from typing import List, Dict, Optional, Any
from llama_index.core.node_parser.text import CodeSplitter
from models import CodeChunk
# 默认参数
DEFAULT_CHUNK_LINES = 40
DEFAULT_LINES_OVERLAP = 15
DEFAULT_MAX_CHARS = 1500

class CodeSplitterCustom(CodeSplitter):
    """继承自llama_index的CodeSplitter，重写核心方法"""
    
    def __init__(
        self,
        language: str,
        chunk_lines: int = DEFAULT_CHUNK_LINES,
        chunk_lines_overlap: int = DEFAULT_LINES_OVERLAP,
        max_chars: int = DEFAULT_MAX_CHARS,
        parser: Any = None,
    ):
        """初始化代码切片器"""
        super().__init__(
            language=language,
            chunk_lines=chunk_lines,
            chunk_lines_overlap=chunk_lines_overlap,
            max_chars=max_chars,
            parser=parser
        )

    def _chunk_node(self, node: Any, text_bytes: bytes, last_end_byte_offset: int = 0, path_info: Optional[Dict] = None) -> List[Dict]:
        """
        递归地将AST节点切分为多个块。
        此方法优化了行号计算，并保持原有切分逻辑。
        """
        new_chunks = []
        current_chunk_text = "" # 存储当前累积的非语义单元文本
        current_chunk_start_byte = last_end_byte_offset # 当前累积块的起始字节
        current_chunk_start_line = text_bytes[:current_chunk_start_byte].count(b'\n') + 1

        # 获取当前节点的类型和名称 (如果适用)
        # 注意：这里的 node_type 和 node_name 是指当前 _chunk_node 正在处理的这个 'node'，
        # 它可能是一个父节点，其子节点将被迭代。
        # 我们通常对叶子块或完整语义单元块的类型和名称更感兴趣，这在 _create_chunk_info 中处理。
        parent_node_type_for_fallback = node.type # 当 current_chunk 保存时，用父节点类型作为 fallback
        parent_node_name_for_fallback = self._get_node_name(node, text_bytes)


        if self._is_complete_semantic_unit(node.type):
            # 如果当前节点本身就是完整的语义单元，即使超过max_chars也保持完整
            node_content = text_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
            node_start_line = node.start_point[0] + 1  # tree-sitter 行号是0-indexed
            node_end_line = node.end_point[0] + 1
            node_name = self._get_node_name(node, text_bytes)

            chunk_info = self._create_chunk_info(
                node_content,
                node_start_line,
                node_end_line,
                path_info,
                node.type, # 使用该语义单元节点的实际类型
                node_name
            )
            return [chunk_info]
"""
代码切片的核心功能实现，基于llama_index的CodeSplitter
"""
from typing import List, Dict, Optional, Any
from llama_index.core.node_parser.text import CodeSplitter
from models import CodeChunk
# 默认参数
DEFAULT_CHUNK_LINES = 40
DEFAULT_LINES_OVERLAP = 15
DEFAULT_MAX_CHARS = 1500

class CodeSplitterCustom(CodeSplitter):
    """继承自llama_index的CodeSplitter，重写核心方法"""

    def __init__(
        self,
        language: str,
        chunk_lines: int = DEFAULT_CHUNK_LINES,
        chunk_lines_overlap: int = DEFAULT_LINES_OVERLAP,
        max_chars: int = DEFAULT_MAX_CHARS,
        parser: Any = None,
    ):
        """初始化代码切片器"""
        super().__init__(
            language=language,
            chunk_lines=chunk_lines,
            chunk_lines_overlap=chunk_lines_overlap,
            max_chars=max_chars,
            parser=parser
        )

    def _chunk_node(self, node: Any, text_bytes: bytes, last_end_byte_offset: int = 0, path_info: Optional[Dict] = None) -> List[Dict]:
        """
        递归地将AST节点切分为多个块。
        此方法优化了行号计算，直接使用tree-sitter节点位置信息。
        """
        new_chunks = []
        current_chunk_text = "" # 存储当前累积的非语义单元文本
        current_chunk_start_byte = last_end_byte_offset # 当前累积块的起始字节
        
        # 跟踪当前累积块的第一个和最后一个节点，用于准确计算行号
        current_chunk_first_node = None
        current_chunk_last_node = None
        
        # 获取当前节点的类型和名称 (如果适用)
        parent_node_type_for_fallback = node.type # 当 current_chunk 保存时，用父节点类型作为 fallback
        parent_node_name_for_fallback = self._get_node_name(node, text_bytes)

        if self._is_complete_semantic_unit(node.type):
            # 如果当前节点本身就是完整的语义单元，即使超过max_chars也保持完整
            node_content = text_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
            node_start_line = node.start_point[0] + 1  # tree-sitter 行号是0-indexed
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
                # 重新计算 end_line
                node_end_line = node_start_line + node_content.count('\n')

            chunk_info = self._create_chunk_info(
                node_content,
                node_start_line,
                node_end_line,
                path_info,
                node.type, # 使用该语义单元节点的实际类型
                node_name
            )
            return [chunk_info]
        processed_child_end_byte = node.start_byte # 跟踪最后一个处理的子节点的结束位置，用于拼接

        for child in node.children:
            # 跳过空节点或错误节点（如果有）
            if child.type == "ERROR" or child.start_byte == child.end_byte: # Skip error or empty nodes
                # Update processed_child_end_byte even if skipping, to correctly capture inter-node text
                if child.end_byte > processed_child_end_byte : # Ensure forward progress
                     # Add text between last processed child and this skippable child to current_chunk_text
                    inter_text_bytes = text_bytes[processed_child_end_byte:child.start_byte]
                    if inter_text_bytes:
                        current_chunk_text += inter_text_bytes.decode("utf-8", errors="ignore")
                processed_child_end_byte = max(processed_child_end_byte, child.end_byte)
                continue

            # 先将上一个子节点到当前子节点之间的文本（通常是空格、注释等）加入 current_chunk_text
            # 注释节点通常会被tree-sitter解析为单独的节点类型，这里需要考虑是否跳过或如何处理
            # 假设这里的目标是主要基于非注释代码结构切分+

            if child.start_byte > processed_child_end_byte:
                inter_text_bytes = text_bytes[processed_child_end_byte:child.start_byte]
                current_chunk_text += inter_text_bytes.decode("utf-8", errors="ignore")

            if self._is_complete_semantic_unit(child.type):
                # 遇到完整语义单元子节点：
                # 1. 保存当前累积的 current_chunk_text (如果非空)
                if current_chunk_text.strip(): # 只有当累积块有实际内容时才保存
                    # 计算 current_chunk_text 的 دقیق行号
                    # current_chunk_start_line 已经有了
                    current_chunk_end_line = current_chunk_start_line + current_chunk_text.count('\n')
                    chunk_info = self._create_chunk_info(
                        current_chunk_text,
                        current_chunk_start_line,
                        current_chunk_end_line,
                        path_info,
                        parent_node_type_for_fallback, # 使用父节点的类型
                        parent_node_name_for_fallback  # 使用父节点的名称
                    )
                    new_chunks.append(chunk_info)

                # 2. 递归处理这个语义单元子节点
                # 注意：传递 child.start_byte 作为 last_end_byte_offset 给递归调用是不必要的，
                # 因为 _is_complete_semantic_unit case 会直接处理 child。
                child_chunks = self._chunk_node(child, text_bytes, child.start_byte, path_info) # last_end_byte_offset for child context start
                new_chunks.extend(child_chunks)

                # 3. 重置 current_chunk_text
                current_chunk_text = ""
                current_chunk_start_byte = child.end_byte
                # 更新下一块的起始行号，要精确计算
                current_chunk_start_line = text_bytes[:current_chunk_start_byte].count(b'\n') + 1

            else: # 非语义单元子节点：
                child_content_bytes = text_bytes[child.start_byte:child.end_byte]
                child_content_str = child_content_bytes.decode("utf-8", errors="ignore")

                # 检查如果添加这个子节点是否会超过 max_chars
                # 注意：这里的长度计算应该针对解码后的字符串
                if len(current_chunk_text.encode('utf-8')) + len(child_content_bytes) > self.max_chars and current_chunk_text.strip():
                    # 如果会超长，并且 current_chunk_text 有内容，则先保存 current_chunk_text
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

                    # 新的 current_chunk_text 从这个子节点开始
                    current_chunk_text = child_content_str
                    current_chunk_start_byte = child.start_byte
                    current_chunk_start_line = text_bytes[:current_chunk_start_byte].count(b'\n') + 1
                else:
                    # 如果未超长，或 current_chunk_text 为空，则累加
                    current_chunk_text += child_content_str
                    # 如果 current_chunk_text 之前为空，这是它的第一个内容，更新起始字节和行号
                    if len(current_chunk_text) == len(child_content_str): #
                        current_chunk_start_byte = child.start_byte
                        current_chunk_start_line = text_bytes[:current_chunk_start_byte].count(b'\n') + 1


            processed_child_end_byte = child.end_byte

        # 处理循环结束后剩余的 current_chunk_text
        # 以及从最后一个子节点到父节点结束之间的文本
        if node.end_byte > processed_child_end_byte:
             remaining_text_bytes = text_bytes[processed_child_end_byte:node.end_byte]
             current_chunk_text += remaining_text_bytes.decode("utf-8", errors="ignore")

        if current_chunk_text.strip(): # 确保不添加纯空格或空块
            # current_chunk_start_line 应该已经是正确的
            current_chunk_end_line = current_chunk_start_line + current_chunk_text.count('\n')
            chunk_info = self._create_chunk_info(
                current_chunk_text,
                current_chunk_start_line,
                current_chunk_end_line,
                path_info,
                parent_node_type_for_fallback, # 使用父节点类型作为此剩余块的类型
                parent_node_name_for_fallback
            )
            new_chunks.append(chunk_info)

        return new_chunks

    
    def _create_chunk_info(
        self, 
        content: str, 
        start_line: int, 
        end_line: int, 
        path_info: Optional[Dict],
        node_type: str,
        node_name: Optional[str]
    ) -> Dict:
        """创建代码块信息字典"""
        # 确定块类型
        chunk_type = "unknown"
        # Python
        if node_type == "function_definition": chunk_type = "function"
        elif node_type == "class_definition": chunk_type = "class"
        elif node_type == "module": chunk_type = "module"
        # JavaScript/TypeScript
        elif node_type in ["function_declaration", "method_definition"]: chunk_type = "function"
        elif node_type in ["class_declaration"]: chunk_type = "class"
        elif node_type in ["interface_declaration"]: chunk_type = "interface"
        elif node_type in ["enum_declaration"]: chunk_type = "enum"
        elif node_type in ["module_declaration", "program", "namespace_definition"]: chunk_type = "module" # 'program' is the root for JS/TS files
        elif node_type == "lexical_declaration": chunk_type = "variable_declaration" # const/let/var
        # Java
        elif node_type == "method_declaration": chunk_type = "method"
        elif node_type == "constructor_declaration": chunk_type = "constructor"
        elif node_type == "class_declaration": chunk_type = "class"
        elif node_type == "interface_declaration": chunk_type = "interface"
        elif node_type == "enum_declaration": chunk_type = "enum"
        # C/C++
        elif node_type == "function_definition": chunk_type = "function"
        elif node_type == "class_specifier": chunk_type = "class" # C++
        elif node_type == "struct_specifier": chunk_type = "struct"
        elif node_type == "union_specifier": chunk_type = "union"
        elif node_type == "enum_specifier": chunk_type = "enum"
        elif node_type == "namespace_definition": chunk_type = "namespace" # C++
        elif node_type == "translation_unit": chunk_type = "file" # Root for C/C++
        # Go
        elif node_type == "function_declaration": chunk_type = "function"
        elif node_type == "method_declaration": chunk_type = "method"
        elif node_type == "type_declaration": chunk_type = "type_definition" # e.g. struct, interface
        elif node_type == "source_file": chunk_type = "package_file" # Root for Go
        # Rust
        elif node_type == "function_item": chunk_type = "function"
        elif node_type == "struct_item": chunk_type = "struct"
        elif node_type == "enum_item": chunk_type = "enum"
        elif node_type == "trait_item": chunk_type = "trait"
        elif node_type == "impl_item": chunk_type = "implementation"
        elif node_type == "mod_item": chunk_type = "module"
        elif node_type == "source_file": chunk_type = "crate_file" # Root for Rust
        elif node_type in ["const_item", "static_item"]: chunk_type = "constant_or_static"
        elif node_type == "macro_definition": chunk_type = "macro"

        else: # 如果没有特定映射，使用原始节点类型
            chunk_type = node_type

        return {
            "content": content.strip(),
            "language": self.language,
            "type": chunk_type,
            "start_line": start_line,
            "end_line": end_line,
            "file_path": path_info.get("file_path") if path_info else None,
            "node_name": node_name,
        }
    
    """
    【普通分类】
    类别：Text Processing
    描述：将代码文本切分为多个代码块
    """
    def split_text(self, text_bytes: bytes, file_path: Optional[str] = None) -> List[Dict]:
        """
        将代码文本切分为多个代码块

        Args:
            text_bytes: 要切分的代码文本（字节格式）
            file_path: 源文件路径（可选）

        Returns:
            包含代码块信息的字典列表
        """
        if self._parser is None:
            raise ValueError("Parser not initialized. Please ensure the language is supported and tree-sitter grammars are installed.")
        # 解析代码生成AST
        tree = self._parser.parse(text_bytes)
        # 解析AST节点
        path_info = {"file_path": file_path} if file_path else None
        chunks = self._chunk_node(tree.root_node, text_bytes, 0, path_info)
        return chunks

    def _get_node_name(self, node: Any, text_bytes: bytes) -> Optional[str]:
        """获取节点名称。
        Tree-sitter AST 结构因语言而异，需要为每种语言适配。
        通常名称节点是 'identifier' 类型。
        """
        if node.type in ["ERROR", "comment"]: # 忽略错误节点和注释
            return None

        name_node = None
        if self.language == "python":
            if node.type in ["function_definition", "class_definition"]:
                # 通常第一个 'identifier' 子节点是名称
                name_node = next((child for child in node.children if child.type == "identifier"), None)
        elif self.language == "javascript" or self.language == "typescript":
            if node.type in ["function_declaration", "class_declaration", "method_definition", "lexical_declaration"]:
                # function foo() {}, class Foo {}, const foo = ...
                # 对于箭头函数赋值给变量: lexical_declaration -> variable_declarator -> identifier
                if node.type == "lexical_declaration": # const foo = () => {}
                    var_declarator = next((child for child in node.children if child.type == "variable_declarator"), None)
                    if var_declarator:
                        name_node = next((child for child in var_declarator.children if child.type == "identifier"), None)
                else: # function foo() or class Foo
                    name_node = next((child for child in node.children if child.type == "identifier"), None)
            elif node.type == "variable_declarator" and node.parent and node.parent.type == "export_statement":
                 # export const foo = ...
                 name_node = next((child for child in node.children if child.type == "identifier"), None)


        elif self.language == "java":
            if node.type in ["class_declaration", "interface_declaration", "enum_declaration", "method_declaration", "constructor_declaration"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)
        elif self.language in ["c", "cpp"]:
            if node.type == "function_definition":
                # 查找 function_declarator -> identifier
                declarator = next((child for child in node.children if child.type == "function_declarator"), None)
                if declarator:
                    name_node = next((child for child in declarator.children if child.type == "identifier"), None)
            elif node.type in ["class_specifier", "struct_specifier", "union_specifier", "enum_specifier"]:
                 # class Name, struct Name, etc.
                name_node = next((child for child in node.children if child.type == "type_identifier" or child.type == "identifier"), None)
            elif node.type == "namespace_definition": # C++
                name_node = next((child for child in node.children if child.type == "identifier" or child.type == "namespace_identifier"), None)

        elif self.language == "go":
            if node.type in ["function_declaration", "method_declaration"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)
            elif node.type == "type_spec": # type MyType struct {}
                 type_identifier_node = next((child for child in node.children if child.type == "identifier"), None)
                 if type_identifier_node: # Check if it's not an interface or other complex type without a simple name here
                     name_node = type_identifier_node


        elif self.language == "rust":
            if node.type in ["function_item", "struct_item", "enum_item", "trait_item", "impl_item", "mod_item"]:
                name_node = next((child for child in node.children if child.type == "identifier"), None)
            # const and static items
            elif node.type in ["const_item", "static_item"]:
                 name_node = next((child for child in node.children if child.type == "identifier"), None)


        # 可以继续为其他语言添加规则
        # ...

        if name_node:
            return text_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
        return None

    def _is_complete_semantic_unit(self, node_type: str) -> bool:
        """
        判断是否是完整的语义单元。
        文件级根节点（如 module, program）通常应被允许分解为其内部的主要声明，
        除非文件本身非常小（此逻辑暂未添加，当前总是允许分解文件根节点）。
        """
        
        # 定义哪些节点类型代表文件本身的根，这些通常应该被允许分解
        file_root_node_types = {
            "python": ["module"],
            "javascript": ["program"], 
            "typescript": ["program"], # TypeScript AST 的根节点也是 'program'
            "java": ["compilation_unit"], # Java 文件的根节点通常是 'compilation_unit'
            "c": ["translation_unit"],
            "cpp": ["translation_unit"],
            "go": ["source_file"],
            "rust": ["source_file"]
            # 可以为其他语言添加相应的文件级根节点类型
        }
        
        # 如果当前节点类型是指定语言的文件级根节点，则不将其视为"必须完整"的单元，
        # 而是允许 _chunk_node 方法迭代其子节点进行切分。
        if self.language in file_root_node_types and \
           node_type == file_root_node_types[self.language]:
            return False # 表明此文件级节点可以被进一步细分

        # 其他更细粒度的语义单元（如函数、类等）应尽可能保持完整
        # （除非它们自身也过长，但这部分逻辑在当前 _chunk_node 中是：语义单元优先于 max_chars）
        semantic_units = {
            "python": ["function_definition", "class_definition"],
            "javascript": ["function_declaration", "class_declaration", "lexical_declaration", "method_definition"],
            "typescript": ["function_declaration", "class_declaration", "interface_declaration", "enum_declaration", "module_declaration", "lexical_declaration", "method_definition"], # module_declaration 是指 TS 的 namespace 或内部 module
            "java": ["class_declaration", "interface_declaration", "enum_declaration", "method_declaration", "constructor_declaration" ,"module_declaration", "compact_constructor_declaration"], # module_declaration 是 Java 9+ 模块
            "c": ["function_definition", "struct_specifier", "union_specifier", "enum_specifier"],
            "cpp": ["function_definition", "class_specifier", "struct_specifier", "union_specifier", "enum_specifier", "namespace_definition", "concept_definition", "template_declaration"],
            "go": ["function_declaration", "method_declaration", "type_declaration"], # type_declaration for structs, interfaces etc.
            "rust": ["function_item", "struct_item", "enum_item", "trait_item", "impl_item", "mod_item", "macro_definition", "const_item", "static_item"],
            # 可以继续添加其他语言的内部语义单元
        }
        return node_type in semantic_units.get(self.language, [])



# 公共接口函数
def split_code_string(code_bytes: bytes, language: str, 
                     chunk_lines: int = DEFAULT_CHUNK_LINES,
                     chunk_lines_overlap: int = DEFAULT_LINES_OVERLAP, 
                     max_chars: int = DEFAULT_MAX_CHARS,
                     file_path: Optional[str] = None,
                     remove_comments_flag: bool = True) -> List[CodeChunk]:
    """
    将代码字节切分为多个代码块
    
    Args:
        code_bytes: 代码内容（字节格式）
        language: 编程语言
        chunk_lines: 每个块的行数
        chunk_lines_overlap: 块之间重叠的行数
        max_chars: 每个块的最大字符数
        file_path: 源文件路径（可选，用于生成更好的块信息）
        remove_comments_flag: 是否删除代码中的注释，默认为True
        
    Returns:
        包含代码块的列表
    """
    # 如果需要删除注释，先解码为字符串
    if remove_comments_flag:
        code_str = code_bytes.decode("utf-8")
        code_str = remove_comments(code_str, language)
        code_bytes = code_str.encode("utf-8")
    
    # 使用自定义的CodeSplitter
    splitter = CodeSplitterCustom(
        language=language,
        chunk_lines=chunk_lines,
        chunk_lines_overlap=chunk_lines_overlap,
        max_chars=max_chars
    )
    
    # 切分代码
    chunk_dicts = splitter.split_text(code_bytes, file_path)
    
    # 将字典转换为CodeChunk对象
    chunks = [
        CodeChunk(
            code=chunk_dict["content"],
            #language=chunk_dict["language"],
            #file_type=chunk_dict["type"],
            start_line=chunk_dict["start_line"],
            end_line=chunk_dict["end_line"],
            file_path=chunk_dict["file_path"],
            #file_id="33",
            #project_id="1",
            #project_name="default",
            chunk_number=idx
        )
        for idx, chunk_dict in enumerate(chunk_dicts)
    ]
    return chunks


def remove_comments(code_content, language):
    """
    移除代码中的注释
    
    Args:
        code_content: 源代码
        language: 编程语言
        
    Returns:
        移除注释后的代码
    """
    import re
    
    if language == 'python':
        # 移除Python注释：# 和三引号
        # 先移除块注释（三引号）
        code_without_block = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', ' ', code_content)
        # 然后移除行注释
        lines = code_without_block.splitlines()
        result = []
        for line in lines:
            comment_pos = line.find('#')
            if comment_pos >= 0:
                result.append(line[:comment_pos] + ' ' * (len(line) - comment_pos))
            else:
                result.append(line)
        return '\n'.join(result)
        
    elif language in ['java', 'cpp', 'c', 'javascript', 'typescript']:
        # 移除C风格注释：// 和 /* */
        # 先移除块注释
        code_without_block = re.sub(r'/\*[\s\S]*?\*/', lambda m: ' ' * len(m.group()), code_content)
        # 然后移除行注释
        lines = code_without_block.splitlines()
        result = []
        for line in lines:
            comment_pos = line.find('//')
            if comment_pos >= 0:
                result.append(line[:comment_pos] + ' ' * (len(line) - comment_pos))
            else:
                result.append(line)
        return '\n'.join(result)
        
    elif language == 'go':
        # Go使用C风格注释
        code_without_block = re.sub(r'/\*[\s\S]*?\*/', '', code_content)
        return re.sub(r'//.*', '\n', code_without_block)
        
    elif language == 'rust':
        # Rust有C风格注释加上文档注释
        code_without_block = re.sub(r'/\*[\s\S]*?\*/', '', code_content) 
        return re.sub(r'//.*|///.*|//!.*', '\n', code_without_block)
        
    else:
        # 如果没有专门处理的语言，返回原始内容
        return code_content
    

if __name__ == "__main__":
    file_path = "/root/ccq/code_search/red_tools/twelvesec_passcat/passcat/libpasscat.cpp"
    with open(file_path, "r") as f:
        code_content = f.read()
    chunks = split_code_string(code_content.encode("utf-8"), "cpp",file_path=file_path,remove_comments_flag=True)
    # for chunk in chunks:
    #     print(chunk.code)
    #     print(chunk.start_line,chunk.end_line)
    #     print(chunk.file_path)
    #     print(len(chunk.code))
    #     print("-"*100)

    with open("chunks.json", "w") as f:
        import json
        json.dump([chunk.to_dict() for chunk in chunks], f)