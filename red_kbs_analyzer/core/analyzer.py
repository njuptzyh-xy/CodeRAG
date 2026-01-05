"""
项目分析器模块
负责整合所有分析功能，提供完整的项目分析流程
"""
import os
import json
import asyncio
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED, TimeoutError as FutureTimeoutError
from pathlib import Path

from ..models.project import RedTool, ProjectAnalysisResult
from ..models.analysis import CodeFile, CodeChunk
from .file_processor import FileProcessor
from .ast_splitter import ASTCodeSplitter
from .claude_code import (
    generate_project_summary_with_claude,
    identify_main_files_with_claude,
    analyze_file_technique_with_claude,
)
from ..llm.interface import LLMInterface
from ..llm.utils import format_code_chunks_for_llm
from ..run_logs.logger import logger


class ProjectAnalyzer:
    """项目分析器"""
    
    def __init__(self, 
                 max_file_size: int = 1024 * 1024,  # 1MB
                 max_chunk_chars: int = 3000,
                 min_chunk_lines: int = 5,
                 max_workers: int = 20,
                 max_code_files: int = 100,  # 最大代码文件数量限制
                 max_code_length: int = 25000,  # 单个文件最大代码长度
                 max_file_analysis_workers: int = 5,  # 文件分析并发数
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
        self.max_chunk_chars = max_chunk_chars
        self.min_chunk_lines = min_chunk_lines
        # 使用 AST 分割器替代原行分割器
        self.ast_splitter = ASTCodeSplitter(chunk_size=2500, chunk_overlap=300)
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
        # 移除文件数量限制，允许处理所有文件
        # 如果文件数量较多，记录警告信息但继续处理
        # if len(code_files_only) > self.max_code_files:
        #     logger.warning(f"项目 {project_name} 代码文件数量({len(code_files_only)})超过建议值({self.max_code_files})，将继续处理（可能耗时较长）")
        
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
            
            # 基于 AST 的代码分割（异步接口同步调用）
            # 使用线程安全的方式，避免在 ThreadPoolExecutor 中使用 asyncio.run() 导致的死锁
            language = Path(code_file.file_name).suffix.lstrip(".").lower() or "text"
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                raw_chunks = loop.run_until_complete(
                    self.ast_splitter.split(
                        code=content,
                        language=language,
                        file_path=code_file.file_abs_path,
                    )
                )
            finally:
                loop.close()

            # 适配为内部的 CodeChunk 模型
            chunks = [
                CodeChunk(
                    code=chunk.content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    file_path=chunk.file_path or code_file.file_path,
                    chunk_number=idx,
                    language=language,
                )
                for idx, chunk in enumerate(raw_chunks)
            ]
            
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
        # 优先使用 Claude Code 生成摘要
        try:
            summary_result = asyncio.run(
                generate_project_summary_with_claude(project, processed_files)
            )
            logger.info(f"project_name: {project.project_name}")
            logger.info(f"summary: {summary_result.get('summary') if summary_result else ''}")
            logger.info(f"main_files: {summary_result.get('files') if summary_result else ''}")

            summary = (summary_result or {}).get("summary") or ""
            files = (summary_result or {}).get("files") or []

            # 情况 1：有 summary 且有重要文件 -> 直接使用
            if summary and files:
                project.main_files = files
                return summary

            # 情况 2：有 summary 但没有 important_files -> 用规则识别主要文件
            if summary and not files:
                logger.warning("Claude 返回了摘要但没有重要文件，使用规则识别主要文件")
                # 直接使用文件名模式匹配，避免再次调用 Claude Code（可能同样被拒绝）
                main_files = self._identify_main_files_by_pattern(processed_files)
                project.main_files = main_files
                return summary

            # 情况 3：summary 也为空 -> 视为失败，走后面的 LLM / 规则兜底
            logger.warning("Claude 未返回有效摘要，尝试使用 LLM 接口或规则兜底")
        except Exception as e:
            logger.error(f"Claude Code 生成摘要失败: {e}，尝试使用 LLM 接口")
        
        # 备用：调用LLM接口（保持原有兼容）
        if self.llm_interface:
            summary_result = self._call_llm_for_summary(project, processed_files)
            if summary_result and "summary" in summary_result:
                summary_text = summary_result.get("summary", "")
                logger.info(f"llm生成摘要内容: {summary_text}")
                if "files" in summary_result:
                    project.main_files = summary_result["files"]
                return summary_text
        
        # 备用方案：生成简单摘要
        logger.info("备用方案生成摘要")
        # 直接使用文件名模式匹配，避免再次调用 Claude Code
        main_files = self._identify_main_files_by_pattern(processed_files)
        summary_parts = []
        
        if project.readme_content:
            summary_parts.append(f"项目README内容: {project.readme_content[:200]}...")
        
        if main_files:
            summary_parts.append(f"主要文件: {', '.join(main_files[:5])}")
            project.main_files = main_files[:5]
        
        summary_parts.append(f"包含 {len(processed_files)} 个代码文件")
        
        return "; ".join(summary_parts)
    
    def _identify_main_files(self, processed_files: List[Dict[str, Any]], project: Optional[RedTool] = None) -> List[str]:
        """
        识别主要文件（使用 Claude Code 或备用模式匹配）
        
        Args:
            processed_files: 处理后的文件列表
            project: 项目对象，用于获取项目路径和名称
            
        Returns:
            主要文件名列表
        """
        logger.info(f"项目信息:{project}")
        # 如果提供了项目信息，使用 Claude Code 识别
        if project:
            logger.info("开始使用 Claude Code 识别主要文件...")
            try:
                main_files_abs_paths = asyncio.run(
                    identify_main_files_with_claude(project, processed_files)
                )
                # 将绝对路径转换为文件名列表
                main_files = []
                for abs_path in main_files_abs_paths:
                    file_name = os.path.basename(abs_path)
                    # 验证该文件名是否在 processed_files 中
                    for file_dict in processed_files:
                        if file_dict.get("file_abs_path") == abs_path or file_dict.get("file_name") == file_name:
                            main_files.append(file_dict.get("file_name", file_name))
                            break
                if main_files:
                    logger.info(f"使用 Claude Code 识别出 {len(main_files)} 个主要文件")
                    return main_files[:10]  # 最多返回10个
                else:
                    logger.info("Claude Code 未识别出主要文件，将使用备用规则")
            except Exception as e:
                logger.error(f"Claude Code 识别主要文件失败: {e}，使用备用方案")
        
        # 备用方案：基于文件名模式匹配
        return self._identify_main_files_by_pattern(processed_files)
    
    def _identify_main_files_by_pattern(self, processed_files: List[Dict[str, Any]]) -> List[str]:
        """
        基于文件名模式匹配识别主要文件
        
        Args:
            processed_files: 处理后的文件列表
            
        Returns:
            主要文件名列表
        """
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
        
        # 记录所有要处理的文件名
        file_names = [f.get('file_name', '') for f in valid_files]
        logger.info(f"[文件技术分析] 待处理文件列表: {file_names}")
        
        # 使用并发处理文件
        with ThreadPoolExecutor(max_workers=self.max_file_analysis_workers) as executor:
            future_to_file = {
                executor.submit(self._analyze_single_file_technique, file_dict, project, tactics_analysis): file_dict
                for file_dict in valid_files
            }
            
            total_files = len(future_to_file)
            completed_count = 0
            
            logger.info(f"[文件技术分析] 已提交 {total_files} 个文件分析任务，开始等待完成...")
            
            # 设置超时时间（每个文件最多处理 30 分钟）
            timeout_per_file = 30 * 60  # 30 分钟
            
            import time
            # 记录每个 future 的提交时间
            future_start_times = {future: time.time() for future in future_to_file.keys()}
            remaining_futures = set(future_to_file.keys())
            
            # 使用较短的检查间隔，更快检测卡住的 future
            check_interval = 30  # 每 30 秒检查一次
            
            while remaining_futures:
                # 检查是否有 future 运行时间超过超时时间
                current_time = time.time()
                timed_out_futures = []
                
                for future in remaining_futures:
                    elapsed_time = current_time - future_start_times[future]
                    if elapsed_time > timeout_per_file:
                        timed_out_futures.append(future)
                        file_dict = future_to_file[future]
                        logger.warning(
                            f"[文件技术分析] 检测到文件 {file_dict.get('file_name', '')} "
                            f"运行时间过长（{elapsed_time:.1f}秒），超过 {timeout_per_file} 秒，标记为超时"
                        )
                
                # 处理超时的 future
                for future in timed_out_futures:
                    file_dict = future_to_file[future]
                    completed_count += 1
                    logger.error(
                        f"[文件技术分析] 文件 {file_dict.get('file_name', '')} "
                        f"处理超时（超过 {timeout_per_file} 秒），跳过该文件 ({completed_count}/{total_files})"
                    )
                    file_results.append({
                        "file_name": file_dict.get("file_name", ""),
                        "file_abs_path": file_dict.get("file_abs_path", ""),
                        "file_technique": {
                            "result": False,
                            "ttps": [],
                            "status": "failed",
                            "error": f"处理超时（超过 {timeout_per_file} 秒）"
                        }
                    })
                    remaining_futures.remove(future)
                
                if not remaining_futures:
                    break
                
                # 等待至少一个 future 完成，使用较短的超时时间以便定期检查
                done, not_done = wait(remaining_futures, timeout=check_interval, return_when=FIRST_COMPLETED)
                
                # 处理已完成的 future
                for future in done:
                    file_dict = future_to_file[future]
                    completed_count += 1
                    try:
                        logger.info(f"[文件技术分析] 收到文件 {file_dict.get('file_name', '')} 的分析结果 ({completed_count}/{total_files})")
                        # 已完成的任务应该很快返回结果，设置较短的超时时间（5秒）
                        result = future.result(timeout=5)
                        if result:
                            file_results.append(result)
                            logger.info(f"[文件技术分析] 文件 {file_dict.get('file_name', '')} 分析完成并添加到结果列表 ({completed_count}/{total_files})")
                        else:
                            logger.warning(f"[文件技术分析] 文件 {file_dict.get('file_name', '')} 分析返回空结果 ({completed_count}/{total_files})")
                            # 空结果也添加，避免丢失
                            file_results.append({
                                "file_name": file_dict.get("file_name", ""),
                                "file_abs_path": file_dict.get("file_abs_path", ""),
                                "file_technique": {
                                    "result": False,
                                    "ttps": [],
                                    "status": "failed",
                                    "error": "分析返回空结果"
                                }
                            })
                    except FutureTimeoutError:
                        logger.error(f"[文件技术分析] 文件 {file_dict.get('file_name', '')} 获取结果超时，跳过该文件 ({completed_count}/{total_files})")
                        file_results.append({
                            "file_name": file_dict.get("file_name", ""),
                            "file_abs_path": file_dict.get("file_abs_path", ""),
                            "file_technique": {
                                "result": False,
                                "ttps": [],
                                "status": "failed",
                                "error": "获取结果超时"
                            }
                        })
                    except Exception as e:
                        logger.error(f"分析文件 {file_dict.get('file_name', '')} 技术时出错: {e}", exc_info=True)
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
                        logger.info(f"[文件技术分析] 文件 {file_dict.get('file_name', '')} 分析失败但已添加到结果列表 ({completed_count}/{total_files})")
                
                # 更新剩余 future
                remaining_futures = not_done
                
                # 定期记录进度
                if completed_count % 10 == 0 or len(remaining_futures) == 0:
                    elapsed_time = time.time() - min(future_start_times.values()) if future_start_times else 0
                    logger.info(
                        f"[文件技术分析] 进度: {completed_count}/{total_files} 完成，"
                        f"剩余 {len(remaining_futures)} 个，已用时 {elapsed_time:.1f} 秒"
                    )
        
        logger.info(f"[文件技术分析] 所有文件分析完成，共处理 {len(file_results)} 个文件")
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
        
        # 将代码块分成多个批次（每批不超过max_code_length）
        batch_chunks_list = []
        current_batch = []
        current_length = 0
        
        for chunk in chunks:
            chunk_code = chunk.get("code", "")
            chunk_length = len(chunk_code)
            
            # 如果当前批次加上这个chunk会超过限制，且当前批次不为空，则保存当前批次
            if current_length + chunk_length > self.max_code_length and current_batch:
                batch_chunks_list.append(current_batch)
                current_batch = []
                current_length = 0
            
            # 如果单个chunk就超过限制，仍然添加（避免完全跳过）
            current_batch.append({
                "code": chunk_code,
                "chunk_number": chunk.get("chunk_number", 0)
            })
            current_length += chunk_length
        
        # 添加最后一个批次
        if current_batch:
            batch_chunks_list.append(current_batch)
        
        if not batch_chunks_list:
            return None
        
        # 记录分批信息
        total_code_length = sum(len(c.get("code", "")) for batch in batch_chunks_list for c in batch)
        if len(batch_chunks_list) > 1:
            logger.info(f"[文件技术分析] 文件 {file_name} 代码过长({total_code_length} 字符)，分成 {len(batch_chunks_list)} 批进行分析")
        
        # 对每个批次进行分析
        all_ttps = []
        all_success = False
        
        for batch_idx, batch_chunks in enumerate(batch_chunks_list):
            batch_code_length = sum(len(c.get("code", "")) for c in batch_chunks)
            logger.info(f"[文件技术分析] 分析第 {batch_idx + 1}/{len(batch_chunks_list)} 批，包含 {len(batch_chunks)} 个代码块，总长度 {batch_code_length} 字符")
            
            technique_result = self._call_llm_for_file_techniques_filtered(
                batch_chunks, file_dict, project, tactics_analysis
            )
            
            if technique_result and technique_result.get("status") == "success":
                all_success = True
                batch_ttps = technique_result.get("ttps", [])
                
                # 过滤：只保留 have_code == true 且 relevance >= 0.9 的结果
                filtered_ttps = [
                    ttp for ttp in batch_ttps
                    if ttp.get("have_code", False) == True
                    and ttp.get("relevance") is not None
                    and ttp.get("relevance", 0) >= 0.9
                ]
                
                if len(batch_ttps) != len(filtered_ttps):
                    logger.info(
                        f"[文件技术分析] 第 {batch_idx + 1} 批分析完成，"
                        f"发现 {len(batch_ttps)} 个技术，"
                        f"过滤后保留 {len(filtered_ttps)} 个高相关性技术（have_code=true, relevance>=0.9）"
                    )
                else:
                    logger.info(f"[文件技术分析] 第 {batch_idx + 1} 批分析完成，发现 {len(filtered_ttps)} 个技术")
                
                all_ttps.extend(filtered_ttps)
            else:
                logger.warning(f"[文件技术分析] 第 {batch_idx + 1} 批分析失败")
        
        logger.info(f"[文件技术分析] 所有批次分析完成，共 {len(batch_chunks_list)} 批，累计 {len(all_ttps)} 个技术")
        
        # 合并所有批次的结果
        merged_result = {
            "result": all_success,
            "ttps": all_ttps,
            "status": "success" if all_success else "failed"
        }
        
        logger.info(f"[文件技术分析] 合并结果完成，状态: {merged_result.get('status')}")
        
        # 补充原始chunk信息
        if merged_result.get("status") == "success":
            logger.info(f"[文件技术分析] 开始补充 chunk 信息，ttps 数量: {len(merged_result.get('ttps', []))}, chunks 数量: {len(chunks)}")
            
            # 优化：使用字典索引，避免 O(n*m) 复杂度
            chunk_dict = {chunk.get("chunk_number", 0): chunk for chunk in chunks}
            
            for ttp_idx, ttp in enumerate(merged_result.get("ttps", [])):
                chunk_num = ttp.get("chunk_number", 0)
                chunk = chunk_dict.get(chunk_num)
                if chunk:
                    ttp["chunk_code"] = chunk.get("code", "")
                    ttp["chunk_start_line"] = chunk.get("start_line", 0)
                    ttp["chunk_end_line"] = chunk.get("end_line", 0)
                else:
                    logger.warning(f"[文件技术分析] 未找到 chunk_number={chunk_num} 对应的 chunk")
            
            logger.info(f"[文件技术分析] chunk 信息补充完成")
        
        logger.info(f"[文件技术分析] 文件 {file_name} 分析完成，准备返回结果")
        
        return {
            "file_name": file_name,
            "file_abs_path": file_abs_path,
            "chunks": chunks,  # 包含所有原始代码块，用于全量入库
            "file_technique": merged_result
        }
    
    def _analyze_file_techniques(self, 
                                processed_files: List[Dict[str, Any]], 
                                project: RedTool,
                                tactics_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析文件技术（保留原有方法以兼容）"""
        return self._analyze_file_techniques_concurrent(processed_files, project, tactics_analysis)
    #暂时搁置，使用claude-code生成项目摘要和主要文件
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
            
            # 优先使用 Claude Code 分析
            try:
                from ..llm.prompts import PromptTemplates
                
                logger.info(f"[文件技术分析] 使用 Claude Code 分析文件: {file_dict.get('file_abs_path', '')}")
                
                # 使用相同的 prompt 模板
                prompt_templates = PromptTemplates()
                prompt = prompt_templates.get_technique_prompt(
                    code_chunks=filtered_chunks,
                    software_name=project.project_name,
                    software_tactics=tactics_analysis,
                    file_path=file_dict.get("file_abs_path", "")
                )
                
                # 调用 Claude Code - 使用线程安全的方式
                # 为当前线程创建独立的事件循环，避免在 ThreadPoolExecutor 中使用 asyncio.run() 导致的死锁
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    # 添加超时机制，避免无限等待（30分钟）
                    timeout_seconds = 30 * 60
                    result = loop.run_until_complete(
                        asyncio.wait_for(
                            analyze_file_technique_with_claude(
                                prompt=prompt,
                                file_path=file_dict.get("file_abs_path", ""),
                                project=project
                            ),
                            timeout=timeout_seconds
                        )
                    )
                except asyncio.TimeoutError:
                    logger.error(f"[文件技术分析] Claude Code 分析超时（超过 {timeout_seconds} 秒）")
                    result = None
                finally:
                    loop.close()
                
                if result and result.get("status") == "success":
                    logger.info(f"[文件技术分析] Claude Code 分析成功")
                    return result
                else:
                    logger.warning(f"[文件技术分析] Claude Code 分析失败，回退到 LLM 分析")
            except Exception as e:
                logger.warning(f"[文件技术分析] Claude Code 分析异常: {e}，回退到 LLM 分析")
            
            # 备用方案：使用原有的 LLM 接口
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
        logger.info("获取主要文件。。。")
        main_files_raw = project.main_files or self._identify_main_files(processed_files, project)
        
        logger.info(f"获取主要文件 raw 列表: {main_files_raw}")
        
        # 统一转换为绝对路径集合，避免重名问题
        main_files_set = set()
        matched_count = 0
        for item in main_files_raw:
            # 1. 如果是绝对路径，直接使用绝对路径
            if os.path.isabs(item):
                abs_item = os.path.abspath(item)
                main_files_set.add(abs_item)
                matched_count += 1
                logger.debug(f"主要文件匹配（绝对路径）: {item} -> {abs_item}")
                continue

            # 2. 非绝对路径（可能是相对路径或纯文件名），在 processed_files 中查找对应文件
            item_normalized = item.replace('\\', '/').lstrip('./')
            found = False

            for file_dict in processed_files:
                file_name = file_dict.get("file_name")
                file_path = file_dict.get("file_path", "")
                file_abs_path = file_dict.get("file_abs_path")

                if not file_abs_path:
                    continue

                file_path_normalized = file_path.replace('\\', '/').lstrip('./') if file_path else ""

                # 2.1 相对路径或后缀匹配（例如 file_path='proj/auth/login.php', item='auth/login.php'）
                if (
                    file_path_normalized == item_normalized
                    or file_path_normalized.endswith("/" + item_normalized)
                ):
                    main_files_set.add(file_abs_path)
                    matched_count += 1
                    found = True
                    logger.debug(
                        f"主要文件匹配（相对路径/后缀）: {item} -> {file_abs_path} (file_path={file_path_normalized})"
                    )
                    break

                # 2.2 仅文件名匹配（如 'user_edit.php'）
                if file_name == item:
                    main_files_set.add(file_abs_path)
                    matched_count += 1
                    found = True
                    logger.debug(f"主要文件匹配（文件名）: {item} -> {file_abs_path}")
                    break  # 找到第一个匹配的就停止（如果有重名，只取第一个）

            if not found:
                logger.warning(f"主要文件未匹配到绝对路径: {item} (在 {len(processed_files)} 个文件中查找)")

        logger.info(f"主要文件匹配结果: 输入 {len(main_files_raw)} 个，成功匹配 {matched_count} 个，绝对路径集合 {len(main_files_set)} 个")
        logger.info(f"主要文件列表（绝对路径，共{len(main_files_set)}个）: {list(main_files_set)[:5]}...")  # 只显示前5个
        
        all_content = ""
        content_length = 0
        max_file_length = 20000  # 每个文件最大字符数
        max_total_length = 80000  # 总内容最大字符数（可以包含多个文件）
        
        for file_dict in processed_files:
            file_abs_path = file_dict.get("file_abs_path", "")
            file_name = file_dict.get("file_name", "")
            
            # 使用绝对路径匹配，避免重名问题
            if file_abs_path in main_files_set:
                # 检查总长度是否超过限制
                if content_length >= max_total_length:
                    logger.warning(f"总内容长度已达到限制({max_total_length})，停止添加更多文件")
                    break
                
                # 读取文件内容
                if file_abs_path:
                    try:
                        content = self.file_processor.read_file_content(file_abs_path)
                        if not content:
                            logger.warning(f"文件 {file_name} 内容为空，跳过")
                            continue
                        
                        # 截断单个文件内容到最大长度
                        original_length = len(content)
                        if len(content) > max_file_length:
                            content = content[:max_file_length] + "\n... (文件内容已截断)"
                            logger.info(f"文件 {file_name} 内容过长({original_length}字符)，已截断到{max_file_length}字符")
                        
                        # 检查添加后是否会超过总长度限制
                        file_content_with_header = f"\n=== {file_name} ===\n{content}\n"
                        if content_length + len(file_content_with_header) > max_total_length:
                            # 如果会超过，只添加剩余空间的部分
                            remaining = max_total_length - content_length - len(f"\n=== {file_name} ===\n")
                            if remaining > 500:  # 至少保留500字符
                                all_content += f"\n=== {file_name} ===\n{content[:remaining]}...\n"
                                logger.warning(f"总长度限制，文件 {file_name} 只添加了部分内容")
                            break
                        else:
                            all_content += file_content_with_header
                            content_length += len(file_content_with_header)
                            logger.debug(f"已添加文件 {file_name}，当前总长度: {content_length}")
                            
                    except Exception as e:
                        logger.error(f"读取文件内容失败 {file_abs_path}: {e}")
        
        file_count = all_content.count("===") // 2 if all_content else 0
        logger.info(f"主要文件内容获取完成，总长度: {content_length}字符，包含文件数: {file_count}")
        return all_content if all_content else project.file_tree
    
    def set_llm_interface(self, llm_interface):
        """设置LLM接口"""
        self.llm_interface = llm_interface
    
    def update_llm_config(self, llm_config: Dict[str, Any]):
        """更新LLM配置"""
        self.llm_interface = LLMInterface(llm_config) 