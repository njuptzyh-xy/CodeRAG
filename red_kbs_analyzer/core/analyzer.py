"""
项目分析器模块
负责整合所有分析功能，提供完整的项目分析流程
"""
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..models.project import RedTool, ProjectAnalysisResult
from ..models.analysis import CodeFile, CodeChunk
from .file_processor import FileProcessor
from .code_splitter import CodeSplitter
from ..llm.interface import LLMInterface
from ..llm.utils import format_code_chunks_for_llm
from ..run_logs.logger import logger


class ProjectAnalyzer:
    """项目分析器"""
    
    def __init__(self, 
                 max_file_size: int = 1024 * 1024,  # 1MB
                 max_chunk_chars: int = 3000,
                 min_chunk_lines: int = 5,
                 max_workers: int = 30,
                 max_code_files: int = 100,  # 最大代码文件数量限制
                 max_code_length: int = 25000,  # 单个文件最大代码长度
                 max_file_analysis_workers: int = 30,  # 文件分析并发数
                 llm_config: Optional[Dict[str, Any]] = None):
        """
        初始化项目分析器
        
        Args:
            max_file_size: 最大文件大小限制
            max_chunk_chars: 代码块最大字符数
            min_chunk_lines: 代码块最小行数
            max_workers: 并发处理线程数
            max_code_files: 最大代码文件数量限制
            max_code_length: 单个文件最大代码长度
            max_file_analysis_workers: 文件分析并发数
            llm_config: LLM配置
        """
        self.file_processor = FileProcessor(max_file_size=max_file_size)
        self.code_splitter = CodeSplitter(max_chars=max_chunk_chars, min_lines=min_chunk_lines)
        self.max_workers = max_workers
        self.max_code_files = max_code_files
        self.max_code_length = max_code_length
        self.max_file_analysis_workers = max_file_analysis_workers
        
        # 初始化LLM接口
        if llm_config:
            self.llm_interface = LLMInterface(llm_config)
        else:
            # 使用默认配置（模拟模式）
            default_config = {
                "primary": {
                    "enabled": True,
                    "provider": "mock"
                }
            }
            self.llm_interface = LLMInterface(default_config)
    
    def analyze_project(self, 
                       project_path: str, 
                       project_name: str,
                       metadata: Optional[Dict[str, Any]] = None) -> ProjectAnalysisResult:
        """
        分析项目
        
        Args:
            project_path: 项目路径
            project_name: 项目名称
            metadata: 项目元数据
            
        Returns:
            项目分析结果
        """
        print(f"开始分析项目: {project_name}")
        
        # 1. 创建项目对象
        project = RedTool(project_name=project_name, project_path=project_path)
        if metadata:
            for key, value in metadata.items():
                if hasattr(project, key):
                    setattr(project, key, value)
        
        # 2. 扫描文件
        logger.info("扫描项目文件...")
        code_files = self.file_processor.scan_project(project_path, project_name)
        logger.info(f"发现 {len(code_files)} 个代码文件")
        
        # 3. 检查文件数量限制
        if len(code_files) == 0:
            logger.info(f"项目 {project_name} 没有文件,跳过")
            return self._create_empty_result(project_name, project_path)
        
        # 过滤代码文件
        code_files_only = [f for f in code_files if f.file_type == "code"]
        if len(code_files_only) > self.max_code_files:
            logger.info(f"项目 {project_name} 代码文件数量超过{self.max_code_files},跳过")
            return self._create_empty_result(project_name, project_path)
        
        # 4. 处理文件和分割代码
        logger.info("处理文件并分割代码块...")
        processed_files = self._process_files(code_files)
        
        # 5. 生成项目摘要（如果未提供）
        logger.info("生成项目摘要...")
        if not project.summary:
            project.summary = self._generate_project_summary(project, processed_files)
        
        # 6. 分析项目战术
        logger.info("分析项目战术...")
        tactics_analysis = self._analyze_project_tactics(project, processed_files)
        
        # 7. 分析文件技术（使用并发）
        logger.info("分析文件技术...")
        file_analysis_results = self._analyze_file_techniques_concurrent(processed_files, project, tactics_analysis)
        
        # 8. 构建结果
        result = ProjectAnalysisResult(
            software_name=project_name,
            software_path=project_path,
            software_summary=project.summary,
            software_tree=project.file_tree,
            software_tactics=tactics_analysis,
            software_files=file_analysis_results,
            analysis_timestamp=datetime.now().isoformat(),
            analysis_version="1.0.0"
        )
        
        logger.info(f"项目分析完成: {project_name}")
        return result
    
    def _create_empty_result(self, project_name: str, project_path: str) -> ProjectAnalysisResult:
        """创建空的分析结果"""
        return ProjectAnalysisResult(
            software_name=project_name,
            software_path=project_path,
            software_summary="",
            software_tree="",
            software_tactics={"tactics": [], "status": "skipped"},
            software_files=[],
            analysis_timestamp=datetime.now().isoformat(),
            analysis_version="1.0.0"
        )
    
    def _process_files(self, code_files: List[CodeFile]) -> List[Dict[str, Any]]:
        """处理文件列表，分割代码块"""
        processed_files = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(self._process_single_file, file): file 
                for file in code_files
            }
            
            for future in as_completed(future_to_file):
                file = future_to_file[future]
                try:
                    result = future.result()
                    if result:
                        processed_files.append(result)
                except Exception as e:
                    logger.error(f"处理文件 {file.file_name} 时出错: {e}")
        
        return processed_files
    
    def _process_single_file(self, code_file: CodeFile) -> Optional[Dict[str, Any]]:
        """处理单个文件"""
        try:
            # 读取文件内容
            content = self.file_processor.read_file_content(code_file.file_abs_path)
            if not content.strip():
                return None
            
            # 分割代码块
            chunks = self.code_splitter.split_file(code_file, content)
            
            # 更新文件对象
            code_file.chunks = chunks
            
            # 转换为字典格式
            file_dict = code_file.to_dict()
            
            return file_dict
            
        except Exception as e:
            logger.error(f"处理文件 {code_file.file_name} 时出错: {e}")
            return None
    
    def _generate_project_summary(self, project: RedTool, processed_files: List[Dict[str, Any]]) -> str:
        """生成项目摘要"""
        # 调用LLM生成摘要
        if self.llm_interface:
            summary_result = self._call_llm_for_summary(project, processed_files)
            if summary_result and "summary" in summary_result:
                # 同时更新项目的主要文件列表
                if "files" in summary_result:
                    project.main_files = summary_result["files"]
                return summary_result["summary"]
        
        # 备用方案：生成简单摘要
        main_files = self._identify_main_files(processed_files)
        summary_parts = []
        
        if project.readme_content:
            summary_parts.append(f"项目README内容: {project.readme_content[:200]}...")
        
        if main_files:
            summary_parts.append(f"主要文件: {', '.join(main_files[:5])}")
            project.main_files = main_files[:5]
        
        summary_parts.append(f"包含 {len(processed_files)} 个代码文件")
        
        return "; ".join(summary_parts)
    
    def _identify_main_files(self, processed_files: List[Dict[str, Any]]) -> List[str]:
        """识别主要文件"""
        main_patterns = [
            "main", "index", "app", "server", "client", "core", 
            "init", "setup", "config", "start", "run"
        ]
        
        main_files = []
        for file_dict in processed_files:
            file_name = file_dict.get("file_name", "").lower()
            if any(pattern in file_name for pattern in main_patterns):
                main_files.append(file_dict.get("file_name", ""))
        
        return main_files
    
    def _analyze_project_tactics(self, project: RedTool, processed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析项目战术"""
        # 调用LLM分析战术
        if self.llm_interface:
            tactics_result = self._call_llm_for_tactics(project, processed_files)
            if tactics_result:
                return tactics_result
        
        # 备用方案：返回模拟结果
        return {
            "tactics": [
                {
                    "tactic": "Command and Control",
                    "tactic_id": "TA0011",
                    "evidence": "检测到网络通信相关代码，可能用于远程控制"
                }
            ],
            "status": "success"
        }
    
    def _analyze_file_techniques_concurrent(self, 
                                          processed_files: List[Dict[str, Any]], 
                                          project: RedTool,
                                          tactics_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """使用并发分析文件技术"""
        # 过滤有效文件：只处理有代码块且为代码类型的文件
        valid_files = [
            file_dict for file_dict in processed_files 
            if len(file_dict.get("chunks", [])) > 0 and file_dict.get("file_type", "") == "code"
        ]
        
        if not valid_files:
            return []
        
        logger.info(f"开始并发处理 {len(valid_files)} 个有效文件...")
        file_results = []
        
        # 使用并发处理文件
        with ThreadPoolExecutor(max_workers=self.max_file_analysis_workers) as executor:
            future_to_file = {
                executor.submit(self._analyze_single_file_technique, file_dict, project, tactics_analysis): file_dict
                for file_dict in valid_files
            }
            
            for future in as_completed(future_to_file):
                file_dict = future_to_file[future]
                try:
                    result = future.result()
                    if result:
                        file_results.append(result)
                except Exception as e:
                    logger.error(f"分析文件 {file_dict.get('file_name', '')} 技术时出错: {e}")
                    # 即使出错也添加一个失败的结果
                    file_results.append({
                        "file_name": file_dict.get("file_name", ""),
                        "file_abs_path": file_dict.get("file_abs_path", ""),
                        "file_technique": {
                            "result": False,
                            "ttps": [],
                            "status": "failed",
                            "error": str(e)
                        }
                    })
        
        return file_results
    
    def _analyze_single_file_technique(self, 
                                     file_dict: Dict[str, Any], 
                                     project: RedTool,
                                     tactics_analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """分析单个文件的技术"""
        chunks = file_dict.get("chunks", [])
        if not chunks:
            return None
        
        file_name = file_dict.get("file_name", "")
        file_abs_path = file_dict.get("file_abs_path", "")
        
        # 过滤代码块并限制长度（参考main_flow_llm.py的逻辑）
        filtered_chunks = []
        len_code = 0
        
        for chunk in chunks:
            chunk_code = chunk.get("code", "")
            len_code += len(chunk_code)
            if len_code > self.max_code_length:
                break
            filtered_chunks.append({
                "code": chunk_code,
                "chunk_number": chunk.get("chunk_number", 0)
            })
        
        if not filtered_chunks:
            return None
        
        # 调用LLM分析文件技术
        technique_result = self._call_llm_for_file_techniques_filtered(
            filtered_chunks, file_dict, project, tactics_analysis
        )
        
        # 如果LLM分析成功，补充原始chunk信息
        if technique_result and technique_result.get("status") == "success":
            for ttp in technique_result.get("ttps", []):
                chunk_num = ttp.get("chunk_number", 0)
                # 从原始chunks中找到对应编号的chunk
                for chunk in chunks:
                    if chunk.get("chunk_number", 0) == chunk_num:
                        ttp["chunk_code"] = chunk.get("code", "")
                        ttp["chunk_start_line"] = chunk.get("start_line", 0)
                        ttp["chunk_end_line"] = chunk.get("end_line", 0)
                        break
        
        return {
            "file_name": file_name,
            "file_abs_path": file_abs_path,
            "file_technique": technique_result or {
                "result": False,
                "ttps": [],
                "status": "failed"
            }
        }
    
    def _analyze_file_techniques(self, 
                                processed_files: List[Dict[str, Any]], 
                                project: RedTool,
                                tactics_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析文件技术（保留原有方法以兼容）"""
        return self._analyze_file_techniques_concurrent(processed_files, project, tactics_analysis)
    
    def _call_llm_for_summary(self, project: RedTool, processed_files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """调用LLM生成项目摘要"""
        try:
            metadata = {
                "readme_content": project.readme_content,
                "file_tree": project.file_tree,
                "software_name": project.project_name,
                "software_path": project.project_path
            }
            
            result = self.llm_interface.get_llm_response("get_summary_red_tool", metadata)
            return result
            
        except Exception as e:
            logger.error(f"LLM摘要生成失败: {e}")
            return None
    
    def _call_llm_for_tactics(self, project: RedTool, processed_files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """调用LLM分析项目战术"""
        try:
            # 获取主要文件的代码内容
            main_files_content = self._get_main_files_content(project, processed_files)
            
            # 应用备用逻辑（参考main_flow_llm.py的逻辑）
            project_summary = project.summary
            if project_summary == "":
                project_summary = project.readme_content
            
            if len(project.main_files or []) == 0:
                main_files_content = project.file_tree
            
            metadata = {
                "summary": project_summary,
                "file_code": main_files_content,
                "software_name": project.project_name,
                "software_path": project.project_path
            }
            
            result = self.llm_interface.get_llm_response("analyze_software_tactics", metadata)
            return result
            
        except Exception as e:
            logger.error(f"LLM战术分析失败: {e}")
            return None
    
    def _call_llm_for_file_techniques(self, 
                                     file_dict: Dict[str, Any], 
                                     project: RedTool,
                                     tactics_analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """调用LLM分析文件技术（原方法，保留兼容性）"""
        try:
            chunks = file_dict.get("chunks", [])
            if not chunks:
                return None
            
            # 格式化代码块以供LLM分析
            formatted_chunks = format_code_chunks_for_llm(chunks)
            
            # 限制代码块数量和长度
            if len(formatted_chunks) > 10:
                formatted_chunks = formatted_chunks[:10]
            
            # 计算总代码长度，如果超过25000字符则截断
            total_code_length = sum(len(chunk.get("code", "")) for chunk in formatted_chunks)
            if total_code_length > 25000:
                # 按比例截断每个代码块
                ratio = 25000 / total_code_length
                for chunk in formatted_chunks:
                    code = chunk.get("code", "")
                    max_length = int(len(code) * ratio)
                    if len(code) > max_length:
                        chunk["code"] = code[:max_length] + "\n... (truncated)"
            
            metadata = {
                "code_chunks": formatted_chunks,
                "software_name": project.project_name,
                "software_tactics": tactics_analysis,
                "file_path": file_dict.get("file_abs_path", "")
            }
            
            result = self.llm_interface.get_llm_response("analyze_file_technique", metadata)
            return result
            
        except Exception as e:
            logger.error(f"LLM文件技术分析失败: {e}")
            return None
    
    def _call_llm_for_file_techniques_filtered(self, 
                                             filtered_chunks: List[Dict[str, Any]],
                                             file_dict: Dict[str, Any], 
                                             project: RedTool,
                                             tactics_analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """调用LLM分析文件技术（使用过滤后的代码块）"""
        try:
            if not filtered_chunks:
                return None
            
            metadata = {
                "code_chunks": filtered_chunks,
                "software_name": project.project_name,
                "software_tactics": tactics_analysis,
                "file_path": file_dict.get("file_abs_path", "")
            }
            
            result = self.llm_interface.get_llm_response("analyze_file_technique", metadata)
            return result
            
        except Exception as e:
            logger.error(f"LLM文件技术分析失败: {e}")
            return None
    
    def _get_main_files_content(self, project: RedTool, processed_files: List[Dict[str, Any]]) -> str:
        """获取主要文件的代码内容"""
        main_files = project.main_files or self._identify_main_files(processed_files)
        
        all_content = ""
        content_length = 0
        max_content_length = 50000  # 限制总内容长度
        
        for file_dict in processed_files:
            file_name = file_dict.get("file_name", "")
            
            # 检查是否为主要文件
            if file_name in main_files:
                # 读取文件内容
                file_path = file_dict.get("file_abs_path", "")
                if file_path:
                    try:
                        content = self.file_processor.read_file_content(file_path)
                        if content and content_length + len(content) <= max_content_length:
                            all_content += f"\n=== {file_name} ===\n{content}\n"
                            content_length += len(content)
                        elif content:
                            # 截断内容
                            remaining_length = max_content_length - content_length
                            if remaining_length > 500:  # 至少保留500字符
                                all_content += f"\n=== {file_name} ===\n{content[:remaining_length]}...\n"
                            break
                    except Exception as e:
                        logger.error(f"读取文件内容失败 {file_path}: {e}")
        
        return all_content if all_content else project.file_tree
    
    def set_llm_interface(self, llm_interface):
        """设置LLM接口"""
        self.llm_interface = llm_interface
    
    def update_llm_config(self, llm_config: Dict[str, Any]):
        """更新LLM配置"""
        self.llm_interface = LLMInterface(llm_config) 