import os
import json
import re
import asyncio
import random
from typing import Dict, List, Any, Callable, Awaitable

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from ..run_logs.logger import logger
from ..models.project import RedTool
from .key_pool import ClaudeKeyPool

# 导入配置
try:
    from setting import CLAUDE_API_KEYS
except ImportError:
    # 如果无法导入，使用默认值
    CLAUDE_API_KEYS = [
        "feb3a0948a184509bad92e479d255647.HNv6D8wSoml1Da5o",
        "31a5536a55114d2287e665a08c4f27e1.Ncmlk0cQ16RflsBz",
        "935ec0bffaa343c5a25ade89a4b96230.3N0NwmxiKwW6tMV3",
    ]

# 创建全局号池实例
key_pool = ClaudeKeyPool(CLAUDE_API_KEYS)


PROJECT_ROOT = os.path.abspath("/root/workspace/ch")
UPLOAD_CODE_DIR = os.path.join(PROJECT_ROOT, "upload_code")
MAX_FILES = 5

# Token 限制配置（粗略估算：1 token ≈ 4 字符，保留安全余量）
MAX_FILE_TREE_LENGTH = 15000  # 文件树最大字符数（约 3750 tokens）
MAX_PROMPT_LENGTH = 30000  # Prompt 最大字符数（约 7500 tokens）
MAX_FILE_PROMPT_LENGTH = 100000  # Prompt 最大字符数（约 25000 tokens）

async def _call_with_key_pool(func: Callable[[str], Awaitable[Any]]) -> Any:
    """
    使用号池调用 Claude API，支持失败重试
    第一次随机选择一个 key，失败后按顺序尝试剩余的 key
    
    Args:
        func: 接受 key 作为参数的异步函数，返回结果
    
    Returns:
        函数返回值
    
    Raises:
        最后一次尝试的异常
    """
    # 获取所有可用的 key（排除临时失效的）
    with key_pool.lock:
        available_keys = [k for k in key_pool.keys if k not in key_pool.failed_keys]
        
        if not available_keys:
            # 所有 key 都失效了，重置并使用所有 key
            logger.warning("[Claude Code] 所有 key 都失效，重置失败列表")
            key_pool.failed_keys.clear()
            available_keys = key_pool.keys.copy()
    
    # 随机打乱可用 key 列表（第一次随机选择）
    keys_to_try = available_keys.copy()
    random.shuffle(keys_to_try)
    
    max_retries = len(keys_to_try)
    last_error = None
    
    logger.info(f"[Claude Code] 随机选择 key 顺序，共 {max_retries} 个 key")
    
    for attempt in range(max_retries):
        key = keys_to_try[attempt]
        logger.info(f"[Claude Code] 使用 Key {attempt + 1}/{max_retries} (key: {key[:20]}...)")
        
        try:
            result = await func(key)
            key_pool.mark_success(key)
            return result
        except Exception as e:
            error_msg = str(e)
            last_error = e
            key_pool.mark_failed(key, error_msg)
            
            # 判断是否应该重试
            # Token 限制错误不应该重试（换 key 也没用）
            is_token_error = (
                "maximum context length" in error_msg.lower() or
                "context length" in error_msg.lower() or
                "131072" in error_msg
            )
            
            should_retry = not is_token_error and attempt < max_retries - 1
            
            if should_retry:
                logger.warning(f"[Claude Code] Key 失败，尝试下一个 key: {error_msg[:100]}")
                continue
            else:
                # 不应该重试的错误或最后一次尝试，直接抛出
                if is_token_error:
                    logger.error(f"[Claude Code] Token 限制错误，不重试: {error_msg}")
                raise
    
    # 所有 key 都失败了
    logger.error(f"[Claude Code] 所有 key 都失败，最后一次错误: {last_error}")
    raise last_error

def _resolve_target_dir(project_path: str) -> str:
    project_path_abs = os.path.abspath(project_path)
    if project_path_abs.startswith(UPLOAD_CODE_DIR):
        target_dir = project_path_abs
    elif project_path_abs.startswith(PROJECT_ROOT):
        target_dir = project_path_abs
    else:
        target_dir = os.path.join(UPLOAD_CODE_DIR, os.path.basename(project_path_abs))

    if not os.path.exists(target_dir):
        logger.warning(f"目录不存在: {target_dir}，使用项目路径: {project_path_abs}")
        target_dir = project_path_abs

    return os.path.abspath(target_dir)


async def generate_project_summary_with_claude(project: RedTool, processed_files: List[Dict[str, any]]) -> Dict[str, any]:
    """使用 Claude Code 生成项目摘要和主要文件列表"""
    target_dir = _resolve_target_dir(project.project_path)
    logger.info(f"target_dir: {target_dir}")
    project_name = project.project_name
    file_tree = project.file_tree
    
    # 截断过长的文件树
    original_tree_length = len(file_tree)
    if len(file_tree) > MAX_FILE_TREE_LENGTH:
        logger.warning(f"[Claude Code] 文件树过长 ({original_tree_length} 字符)，截断到 {MAX_FILE_TREE_LENGTH} 字符")
        file_tree = file_tree[:MAX_FILE_TREE_LENGTH] + "\n... (文件树已截断，仅显示部分内容)"
    
    prompt = f"""你是一个熟悉红队视角和 MITRE ATT&CK 框架的代码分析助手。

项目信息：
- 项目名称: {project_name}
- 项目目录: {target_dir}

下面是该项目的文件目录结构（可能已被截断，仅供参考）：
{file_tree}

你的任务：
1. 从红队视角，并结合 MITRE ATT&CK 攻击框架，分析该软件最有可能涉及的战术，以及大致的数据流向。
2. 用不超过 300 字的中文，对该项目做一个整体摘要（summary）。
3. 使用 ListDir / Read / Glob 等工具，在项目目录中查找并阅读关键文件（不需要阅读所有文件），选出最多 5 个最能代表该软件主要战术活动的典型文件：
   - 核心业务逻辑代码文件；
   - 重要配置文件（如数据库、网络、认证相关配置）；
   - 关键的工具类或库文件；
   - 文档类文件（如 README 等）最多不能超过 2 个。

重要要求：
- 你返回的文件路径必须是真实存在的文件（不是目录），并且使用完整的绝对路径。
- 只需要在回复中给出一个 JSON 对象，不要输出任何额外说明文字，也不要加 Markdown 代码块标记（不要输出 之类的标记）。

输出格式如下：
```json
{{
    "summary": "项目摘要", #摘要必须用中文
    "important_files": [
        "/absolute/path/file1",
        "/absolute/path/file2"
    ]
}}
```


注意：只返回 JSON，不要输出其他内容。"""
    
    # 检查并截断 prompt（如果过长）
    original_prompt_length = len(prompt)
    if len(prompt) > MAX_PROMPT_LENGTH:
        logger.warning(f"[Claude Code] Prompt 过长 ({original_prompt_length} 字符)，截断到 {MAX_PROMPT_LENGTH} 字符")
        # 保留开头和结尾的重要部分
        header = prompt[:2000]  # 保留前2000字符
        footer = prompt[-2000:] if len(prompt) > 2000 else prompt  # 保留后2000字符
        prompt = header + "\n... (提示内容已截断) ...\n" + footer

    # 定义内部函数，使用号池调用
    async def _call_with_key(key: str) -> Dict[str, any]:
        options = ClaudeAgentOptions(
            cwd=PROJECT_ROOT,
            add_dirs=[PROJECT_ROOT, target_dir],
            allowed_tools=["Read", "ListDir", "Glob"],
            system_prompt="You are a helpful coding assistant specialized in summarizing projects and identifying key files.",
            env={
                "ANTHROPIC_AUTH_TOKEN": key,
                "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
                "ANTHROPIC_MODEL": "glm-4.7",
                "API_TIMEOUT_MS": "3000000",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
        )

        full_response = ""
        found_end_marker = False
        found_aup_error = False  # 添加 AUP 错误标志
        message_count = 0
        
        # AUP 检测关键词
        aup_keywords = [
            "Usage Policy",
            "unable to respond to this request",
            "violate our Usage Policy",
            "API Error",
            "aup"
        ]

        logger.info(f"[Claude Code] 初始化 Claude SDK 客户端，工作目录: {PROJECT_ROOT}, 添加目录: {[PROJECT_ROOT, target_dir]}")
        logger.info(f"[Claude Code] Prompt 长度: {len(prompt)} 字符，文件树长度: {len(file_tree)} 字符")
        async with ClaudeSDKClient(options=options) as client:
            logger.info(f"[Claude Code] 发送 prompt 到 Claude，prompt 长度: {len(prompt)} 字符")
            try:
                await client.query(prompt=prompt)
            except Exception as exc:
                error_msg = str(exc)
                if "maximum context length" in error_msg.lower() or "context length" in error_msg.lower() or "131072" in error_msg:
                    logger.error(f"[Claude Code] Token 限制错误: {error_msg}")
                    logger.error(f"[Claude Code] Prompt 长度: {len(prompt)} 字符，文件树原始长度: {original_tree_length} 字符")
                    raise ValueError(f"请求内容过长，超出模型 token 限制。请减少文件树或 prompt 长度。原始错误: {error_msg}")
                raise
            logger.info(f"[Claude Code] 开始接收 Claude 响应消息...")
            async for message in client.receive_messages():
                message_count += 1
                logger.debug(f"[Claude Code] 收到第 {message_count} 条消息")
                if hasattr(message, "content"):
                    for block in message.content:
                        if hasattr(block, "text"):
                            text = block.text
                            # 调试：打印 text 的实际值和类型
                            logger.debug(f"[Claude Code] block.text 类型: {type(text)}, 值: {repr(text)}, 长度: {len(text) if text else 0}")
                            
                            # 检查 text 是否为 None、空字符串或 "(no content)"
                            if text is None:
                                logger.warning(f"[Claude Code] block.text 为 None，跳过")
                                continue
                            if text == "(no content)":
                                logger.warning(f"[Claude Code] 收到 '(no content)' 字符串，跳过")
                                continue
                            if not text.strip():
                                logger.debug(f"[Claude Code] block.text 为空字符串，跳过")
                                continue
                                
                            full_response += text
                            print(text, end="", flush=True)
                            logger.debug(f"[Claude Code] 累积响应长度: {len(full_response)} 字符")
                            
                            # 实时检测 AUP 拒绝错误
                            if any(keyword.lower() in full_response.lower() for keyword in aup_keywords):
                                logger.warning(f"[Claude Code] 在接收消息时检测到 AUP 拒绝响应，立即退出循环")
                                found_aup_error = True
                                break
                            
                            # 原有的 JSON 结束标记检测
                            if '}' in text and '"summary"' in full_response:
                                if full_response.count('{') > 0 and full_response.count('}') >= full_response.count('{'):
                                    found_end_marker = True
                                    logger.info(f"[Claude Code] 检测到 JSON 结束标记，总响应长度: {len(full_response)} 字符")
                                    await asyncio.sleep(0.3)
                                    break
                    if found_end_marker or found_aup_error:
                        break
            print()  # 换行
            logger.info(f"[Claude Code] 完成接收消息，共接收 {message_count} 条消息，总响应长度: {len(full_response)} 字符")

        # 检测 AUP 拒绝情况（保留作为双重检查）
        if found_aup_error or any(keyword.lower() in full_response.lower() for keyword in aup_keywords):
            logger.warning(f"[Claude Code] 检测到 AUP 拒绝响应，响应内容前500字符: {full_response[:500]}")
            return {
                "summary": "",
                "files": []
            }

        # 解析 JSON
        logger.info(f"[Claude Code] 开始解析 JSON 响应...")
        json_str = None
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', full_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            logger.info(f"[Claude Code] 使用第一种模式匹配到 JSON（```json 格式），长度: {len(json_str)} 字符")
        else:
            json_match = re.search(r'```\s*(\{.*?"summary".*?\})\s*```', full_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                logger.info(f"[Claude Code] 使用第二种模式匹配到 JSON（``` 格式），长度: {len(json_str)} 字符")
            else:
                start_pos = full_response.find('"summary"')
                if start_pos != -1:
                    logger.info(f"[Claude Code] 使用第三种模式查找 JSON，找到 'summary' 位置: {start_pos}")
                    brace_start = full_response.rfind('{', 0, start_pos)
                    if brace_start != -1:
                        brace_count = 0
                        brace_end = -1
                        for i in range(brace_start, len(full_response)):
                            if full_response[i] == '{':
                                brace_count += 1
                            elif full_response[i] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    brace_end = i
                                    break
                        if brace_end != -1:
                            json_str = full_response[brace_start:brace_end + 1]
                            logger.info(f"[Claude Code] 使用第三种模式提取到 JSON，位置: {brace_start}-{brace_end}，长度: {len(json_str)} 字符")

        if not json_str:
            logger.warning(f"[Claude Code] 未找到 JSON 格式的摘要返回，响应内容前500字符: {full_response[:500]}")
            # 不再抛异常，返回空结果交给上层保底
            return {
                "summary": "",
                "files": []
            }

        logger.info(f"[Claude Code] 开始解析 JSON 字符串...")
        try:
            data = json.loads(json_str)
        except Exception as e:
            logger.error(f"[Claude Code] JSON 解析失败: {e}，json_str 前 500 字符: {json_str[:500]}")
            # 不再抛异常，返回空结果交给上层保底
            return {
                "summary": "",
                "files": []
            }

        if not isinstance(data, dict):
            logger.error(f"[Claude Code] JSON 根节点不是对象类型，实际类型: {type(data)}")
            return {
                "summary": "",
                "files": []
            }

        summary = data.get("summary", "") or ""
        files = data.get("important_files", []) or []
        logger.info(f"[Claude Code] JSON 解析成功，摘要长度: {len(summary)} 字符，重要文件数量: {len(files)}")

        validated_files = []
        logger.info(f"[Claude Code] 开始验证文件路径，待验证文件数: {len(files) if files else 0}")
        for idx, file_path in enumerate(files or [], 1):
            logger.debug(f"[Claude Code] 验证文件 {idx}/{len(files) if files else 0}: {file_path}")
            if isinstance(file_path, str):
                if os.path.isabs(file_path) and os.path.exists(file_path):
                    validated_files.append(os.path.abspath(file_path))
                    logger.info(f"[Claude Code] 文件验证成功（绝对路径）: {os.path.abspath(file_path)}")
                else:
                    potential_path = os.path.join(target_dir, file_path.lstrip('/'))
                    if os.path.exists(potential_path):
                        validated_files.append(os.path.abspath(potential_path))
                        logger.info(f"[Claude Code] 文件验证成功（相对目标目录）: {os.path.abspath(potential_path)}")
                    else:
                        potential_path = os.path.join(PROJECT_ROOT, file_path.lstrip('/'))
                        if os.path.exists(potential_path):
                            validated_files.append(os.path.abspath(potential_path))
                            logger.info(f"[Claude Code] 文件验证成功（相对项目根目录）: {os.path.abspath(potential_path)}")
                        else:
                            logger.warning(f"[Claude Code] 文件验证失败，未找到文件: {file_path}")
            if len(validated_files) >= MAX_FILES:
                logger.info(f"[Claude Code] 已达到最大文件数限制 ({MAX_FILES})，停止验证")
                break

        logger.info(f"[Claude Code] 文件验证完成，有效文件数: {len(validated_files)}/{len(files) if files else 0}")
        result = {
            "summary": summary or "",
            "files": validated_files
        }
        logger.info(f"[Claude Code] 生成项目摘要完成，返回结果包含 {len(validated_files)} 个文件")
        return result
    
    # 使用号池调用
    return await _call_with_key_pool(_call_with_key)


async def identify_main_files_with_claude(project: RedTool, processed_files: List[Dict[str, any]]) -> List[str]:
    """使用 Claude Code 识别主要文件"""
    target_dir = _resolve_target_dir(project.project_path)
    project_name = project.project_name

    prompt = f"""请分析目录 {target_dir} 中的所有文件。

要求：
1. 使用 ListDir 工具递归列出该目录下的所有文件（包含子目录）
2. 根据文件类型和名称，选择有代表性的文件使用 Read 工具阅读（不需要读所有文件）
3. 分析这些文件在项目中的作用和重要性
4. 根据以下标准选出最重要的文件（最多5个）：
- 核心业务逻辑文件
- 代码文件
- 配置文件
- 主要入口文件
- 关键的工具类或库文件
- 重要的数据模型或接口定义文件

5. 最终在回复的最后，必须以以下 JSON 格式返回选出的重要文件列表（必须是文件的完整绝对路径）：
```json
{{
    "important_files": [
        "/absolute/path/file1",
        "/absolute/path/file2",
        ...
    ]
}}
```

注意：
- 软件名称: {project_name}
- 必须返回有效的 JSON 格式，文件路径必须是完整的绝对路径，最多返回5个文件。

请开始分析。"""
    
    # 检查并截断 prompt（如果过长）
    original_prompt_length = len(prompt)
    if len(prompt) > MAX_PROMPT_LENGTH:
        logger.warning(f"[Claude Code] Prompt 过长 ({original_prompt_length} 字符)，截断到 {MAX_PROMPT_LENGTH} 字符")
        # 保留开头和结尾的重要部分
        header = prompt[:2000]  # 保留前2000字符
        footer = prompt[-1000:] if len(prompt) > 1000 else prompt  # 保留后1000字符
        prompt = header + "\n... (提示内容已截断) ...\n" + footer

    # 定义内部函数，使用号池调用
    async def _call_with_key(key: str) -> List[str]:
        options = ClaudeAgentOptions(
            cwd=PROJECT_ROOT,
            add_dirs=[PROJECT_ROOT, target_dir],
            allowed_tools=["Read", "ListDir", "Glob"],
            system_prompt="You are a helpful coding assistant specialized in analyzing codebases and identifying important files.",
            env={
                "ANTHROPIC_AUTH_TOKEN": key,
                "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
                "ANTHROPIC_MODEL": "glm-4.7",
                "API_TIMEOUT_MS": "3000000",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
        )

        important_files: List[str] = []
        full_response = ""
        found_end_marker = False
        found_aup_error = False  # 添加 AUP 错误标志
        
        # AUP 检测关键词
        aup_keywords = [
            "Usage Policy",
            "unable to respond to this request",
            "violate our Usage Policy",
            "API Error",
            "aup"
        ]

        logger.info(f"[Claude Code] Prompt 长度: {len(prompt)} 字符")
        async with ClaudeSDKClient(options=options) as client:
            try:
                await client.query(prompt=prompt)
            except Exception as exc:
                error_msg = str(exc)
                if "maximum context length" in error_msg.lower() or "context length" in error_msg.lower() or "131072" in error_msg:
                    logger.error(f"[Claude Code] Token 限制错误: {error_msg}")
                    logger.error(f"[Claude Code] Prompt 长度: {len(prompt)} 字符")
                    raise ValueError(f"请求内容过长，超出模型 token 限制。请减少 prompt 长度。原始错误: {error_msg}")
                raise
            async for message in client.receive_messages():
                if hasattr(message, "content"):
                    for block in message.content:
                        if hasattr(block, "text"):
                            text = block.text
                            # 调试：打印 text 的实际值和类型
                            logger.debug(f"[Claude Code] block.text 类型: {type(text)}, 值: {repr(text)}, 长度: {len(text) if text else 0}")
                            
                            # 检查 text 是否为 None、空字符串或 "(no content)"
                            if text is None:
                                logger.warning(f"[Claude Code] block.text 为 None，跳过")
                                continue
                            if text == "(no content)":
                                logger.warning(f"[Claude Code] 收到 '(no content)' 字符串，跳过")
                                continue
                            if not text.strip():
                                logger.debug(f"[Claude Code] block.text 为空字符串，跳过")
                                continue
                                
                            full_response += text
                            print(text, end="", flush=True)
                            
                            # 实时检测 AUP 拒绝错误
                            if any(keyword.lower() in full_response.lower() for keyword in aup_keywords):
                                logger.warning(f"[Claude Code] 在接收消息时检测到 AUP 拒绝响应，立即退出循环")
                                found_aup_error = True
                                break
                            
                            # 原有的 JSON 结束标记检测
                            if '}' in text and '"important_files"' in full_response:
                                if full_response.count('{') > 0 and full_response.count('}') >= full_response.count('{'):
                                    found_end_marker = True
                                    await asyncio.sleep(0.5)
                                    break
                    if found_end_marker or found_aup_error:
                        break
            print()  # 换行
            
        # 检测 AUP 拒绝情况（保留作为双重检查）
        if found_aup_error or any(keyword.lower() in full_response.lower() for keyword in aup_keywords):
            logger.warning(f"[Claude Code] 检测到 AUP 拒绝响应，返回空文件列表")
            return []

        # 解析 JSON
        json_str = None
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', full_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'```\s*(\{.*?"important_files".*?\})\s*```', full_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                start_pos = full_response.find('"important_files"')
                if start_pos != -1:
                    brace_start = full_response.rfind('{', 0, start_pos)
                    if brace_start != -1:
                        brace_count = 0
                        brace_end = -1
                        for i in range(brace_start, len(full_response)):
                            if full_response[i] == '{':
                                brace_count += 1
                            elif full_response[i] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    brace_end = i
                                    break
                        if brace_end != -1:
                            json_str = full_response[brace_start:brace_end + 1]

        if not json_str:
            raise ValueError("未找到 JSON 格式的文件列表")

        data = json.loads(json_str)
        if "important_files" in data and isinstance(data["important_files"], list):
            for file_path in data["important_files"]:
                if isinstance(file_path, str):
                    if os.path.isabs(file_path) and os.path.exists(file_path):
                        important_files.append(os.path.abspath(file_path))
                    elif file_path:
                        potential_path = os.path.join(target_dir, file_path.lstrip('/'))
                        if os.path.exists(potential_path):
                            important_files.append(os.path.abspath(potential_path))
                        else:
                            potential_path = os.path.join(PROJECT_ROOT, file_path.lstrip('/'))
                            if os.path.exists(potential_path):
                                important_files.append(os.path.abspath(potential_path))
                if len(important_files) >= MAX_FILES:
                    break

        return important_files[:MAX_FILES]
    
    # 使用号池调用
    return await _call_with_key_pool(_call_with_key)


async def analyze_file_technique_with_claude(
    prompt: str,
    file_path: str,
    project: RedTool
) -> Dict[str, Any]:
    """
    使用 Claude Code 分析文件技术
    
    Args:
        prompt: 完整的 prompt（通过 get_technique_prompt 生成）
        file_path: 文件的绝对路径
        project: 项目对象
        
    Returns:
        技术分析结果，格式与原有LLM接口一致
    """
    logger.info(f"[Claude Code] 开始分析文件技术")
    target_dir = _resolve_target_dir(project.project_path)
    file_dir = os.path.dirname(file_path) if os.path.isabs(file_path) else target_dir
    
    # 检查 prompt 长度（由于analyzer.py已经将代码块限制在25000字符内，这里主要记录警告）
    original_prompt_length = len(prompt)
    if len(prompt) > MAX_FILE_PROMPT_LENGTH:
        logger.warning(f"[Claude Code] Prompt 长度: {original_prompt_length} 字符，超过限制 {MAX_FILE_PROMPT_LENGTH} 字符")
        logger.warning(f"[Claude Code] 代码块已限制在25000字符内，prompt过长可能是由于模板或MITRE技术列表过长")
        # 不再截断，让模型处理（如果模型支持）或让API返回错误
        # 如果确实需要截断，可以取消下面的注释
        # header = prompt[:5000]  # 保留前5000字符（包含代码块）
        # footer = prompt[-2000:] if len(prompt) > 2000 else prompt  # 保留后2000字符
        # prompt = header + "\n... (提示内容已截断) ...\n" + footer
    
    # 定义内部函数，使用号池调用
    async def _call_with_key(key: str) -> Dict[str, Any]:
        options = ClaudeAgentOptions(
            cwd=PROJECT_ROOT,
            add_dirs=[PROJECT_ROOT, target_dir, file_dir],
            allowed_tools=["Read", "ListDir", "Glob"],
            system_prompt="You are a helpful coding assistant specialized in analyzing code for MITRE ATT&CK techniques.",
            env={
                "ANTHROPIC_AUTH_TOKEN": key,
                "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
                "ANTHROPIC_MODEL": "glm-4.7",
                "API_TIMEOUT_MS": "3000000",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
        )
        
        full_response = ""
        found_end_marker = False
        found_aup_error = False
        message_count = 0
        
        # AUP 检测关键词
        aup_keywords = [
            "Usage Policy",
            "unable to respond to this request",
            "violate our Usage Policy",
            "API Error",
            "aup"
        ]
        
        logger.info(f"[Claude Code] 开始分析文件技术: {file_path}")
        logger.info(f"[Claude Code] Prompt 长度: {len(prompt)} 字符")
        
        async with ClaudeSDKClient(options=options) as client:
            try:
                await client.query(prompt=prompt)
            except Exception as exc:
                error_msg = str(exc)
                if "maximum context length" in error_msg.lower() or "context length" in error_msg.lower() or "131072" in error_msg:
                    logger.error(f"[Claude Code] Token 限制错误: {error_msg}")
                    logger.error(f"[Claude Code] Prompt 长度: {len(prompt)} 字符")
                    return {
                        "result": False,
                        "ttps": [],
                        "status": "failed",
                        "error": "Token limit exceeded"
                    }
                raise
            
            logger.info(f"[Claude Code] 开始接收 Claude 响应消息...")
            async for message in client.receive_messages():
                message_count += 1
                logger.debug(f"[Claude Code] 收到第 {message_count} 条消息")
                if hasattr(message, "content"):
                    for block in message.content:
                        if hasattr(block, "text"):
                            text = block.text
                            if text is None or text == "(no content)" or not text.strip():
                                continue
                            
                            full_response += text
                            print(text, end="", flush=True)
                            logger.debug(f"[Claude Code] 累积响应长度: {len(full_response)} 字符")
                            
                            # 实时检测 AUP 拒绝错误
                            if any(keyword.lower() in full_response.lower() for keyword in aup_keywords):
                                logger.warning(f"[Claude Code] 在接收消息时检测到 AUP 拒绝响应，立即退出循环")
                                found_aup_error = True
                                break
                            
                            # 检测 JSON 结束标记（查找 "ttps" 字段）
                            if '}' in text and '"ttps"' in full_response:
                                if full_response.count('{') > 0 and full_response.count('}') >= full_response.count('{'):
                                    found_end_marker = True
                                    logger.info(f"[Claude Code] 检测到 JSON 结束标记，总响应长度: {len(full_response)} 字符")
                                    await asyncio.sleep(0.3)
                                    break
                    if found_end_marker or found_aup_error:
                        break
            print()  # 换行
            logger.info(f"[Claude Code] 完成接收消息，共接收 {message_count} 条消息，总响应长度: {len(full_response)} 字符")
        
        # 检测 AUP 拒绝情况
        if found_aup_error or any(keyword.lower() in full_response.lower() for keyword in aup_keywords):
            logger.warning(f"[Claude Code] 检测到 AUP 拒绝响应")
            return {
                "result": False,
                "ttps": [],
                "status": "failed",
                "error": "AUP rejection"
            }
    
        # 解析 JSON
        logger.info(f"[Claude Code] 开始解析 JSON 响应...")
        json_str = None
        
        # 策略1: 提取 ```json``` 代码块
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', full_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            logger.info(f"[Claude Code] 使用第一种模式匹配到 JSON（```json 格式），长度: {len(json_str)} 字符")
        else:
            # 策略2: 提取 ``` 代码块
            json_match = re.search(r'```\s*(\{.*?"ttps".*?\})\s*```', full_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                logger.info(f"[Claude Code] 使用第二种模式匹配到 JSON（``` 格式），长度: {len(json_str)} 字符")
            else:
                # 策略3: 直接查找 JSON 对象
                start_pos = full_response.find('"ttps"')
                if start_pos != -1:
                    logger.info(f"[Claude Code] 使用第三种模式查找 JSON，找到 'ttps' 位置: {start_pos}")
                    brace_start = full_response.rfind('{', 0, start_pos)
                    if brace_start != -1:
                        brace_count = 0
                        brace_end = -1
                        for i in range(brace_start, len(full_response)):
                            if full_response[i] == '{':
                                brace_count += 1
                            elif full_response[i] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    brace_end = i
                                    break
                        if brace_end != -1:
                            json_str = full_response[brace_start:brace_end + 1]
                            logger.info(f"[Claude Code] 使用第三种模式提取到 JSON，位置: {brace_start}-{brace_end}，长度: {len(json_str)} 字符")
        
        if not json_str:
            logger.warning(f"[Claude Code] 未找到 JSON 格式的响应，响应内容前500字符: {full_response[:500]}")
            return {
                "result": False,
                "ttps": [],
                "status": "failed",
                "error": "No JSON found"
            }
        
        logger.info(f"[Claude Code] 开始解析 JSON 字符串...")
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"[Claude Code] JSON 解析失败: {e}，json_str 前 500 字符: {json_str[:500]}")
            return {
                "result": False,
                "ttps": [],
                "status": "failed",
                "error": f"JSON decode error: {e}"
            }
        
        if not isinstance(data, dict):
            logger.error(f"[Claude Code] JSON 根节点不是对象类型，实际类型: {type(data)}")
            return {
                "result": False,
                "ttps": [],
                "status": "failed",
                "error": "Invalid JSON structure"
            }
        
        result = data.get("result", False)
        ttps = data.get("ttps", [])
        
        logger.info(f"[Claude Code] JSON 解析成功，result: {result}，ttps 数量: {len(ttps)}")
        
        return {
            "result": result,
            "ttps": ttps,
            # result为true就表示分析成功，即使ttps为空（表示没有发现技术，这也是合理的结果）
            "status": "success" if result else "failed"
        }
    
    # 使用号池调用
    return await _call_with_key_pool(_call_with_key)
