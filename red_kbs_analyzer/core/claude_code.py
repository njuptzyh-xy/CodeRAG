import os
import json
import re
import asyncio
from typing import Dict, List

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from ..run_logs.logger import logger
from ..models.project import RedTool


PROJECT_ROOT = os.path.abspath("/root/ch/red_rag_new/red-team-graph-rag")
UPLOAD_CODE_DIR = os.path.join(PROJECT_ROOT, "upload_code")
MAX_FILES = 5


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
    project_name = project.project_name
    file_tree = project.file_tree
    prompt = f"""这是该项目的文件目录结构
  {file_tree}

你需要从红队（RED Team）和 MITRE ATT&CK 攻击框架的角度分析该项目，并推断软件可能涉及的主要战术，以及数据的流向。
分析结果不应超过 200 个字。

你还需要提供一个典型文件列表（最多 5 个文件），这些文件可以代表软件的主要战术活动。

输出格式如下：
```json
{{
    "summary": "项目摘要",
    "important_files": [
        "/absolute/path/file1",
        "/absolute/path/file2"
    ]
}}
```
软件名称: {project_name}
注意：只返回 JSON，不要输出其他内容。"""

    options = ClaudeAgentOptions(
        cwd=PROJECT_ROOT,
        add_dirs=[PROJECT_ROOT, target_dir],
        allowed_tools=["Read", "ListDir", "Glob"],
        system_prompt="You are a helpful coding assistant specialized in summarizing projects and identifying key files.",
        env={
            **os.environ,
            "IS_SANDBOX": "0",
            "PATH": os.environ.get("PATH", "") + ":/usr/local/bin",
            "ANTHROPIC_BASE_URL": "http://localhost:8050",
            "ANTHROPIC_MODEL": "claude-3-5-sonnet-20241022",
            "ANTHROPIC_AUTH_TOKEN": "anything",
        },
    )

    full_response = ""
    found_end_marker = False

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for message in client.receive_messages():
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        text = block.text
                        full_response += text
                        if '}' in text and '"summary"' in full_response:
                            if full_response.count('{') > 0 and full_response.count('}') >= full_response.count('{'):
                                found_end_marker = True
                                await asyncio.sleep(0.3)
                                break
                if found_end_marker:
                    break

    # 解析 JSON
    json_str = None
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', full_response, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r'```\s*(\{.*?"summary".*?\})\s*```', full_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            start_pos = full_response.find('"summary"')
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
        raise ValueError("未找到 JSON 格式的摘要返回")

    data = json.loads(json_str)
    summary = data.get("summary", "")
    files = data.get("important_files", []) if isinstance(data, dict) else []

    validated_files = []
    for file_path in files or []:
        if isinstance(file_path, str):
            if os.path.isabs(file_path) and os.path.exists(file_path):
                validated_files.append(os.path.abspath(file_path))
            else:
                potential_path = os.path.join(target_dir, file_path.lstrip('/'))
                if os.path.exists(potential_path):
                    validated_files.append(os.path.abspath(potential_path))
                else:
                    potential_path = os.path.join(PROJECT_ROOT, file_path.lstrip('/'))
                    if os.path.exists(potential_path):
                        validated_files.append(os.path.abspath(potential_path))
        if len(validated_files) >= MAX_FILES:
            break

    return {
        "summary": summary or "",
        "files": validated_files
    }


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
- 分析目录: {target_dir}
- 必须返回有效的 JSON 格式，文件路径必须是完整的绝对路径，最多返回5个文件。

请开始分析。"""

    options = ClaudeAgentOptions(
        cwd=PROJECT_ROOT,
        add_dirs=[PROJECT_ROOT, target_dir],
        allowed_tools=["Read", "ListDir", "Glob"],
        system_prompt="You are a helpful coding assistant specialized in analyzing codebases and identifying important files.",
        env={
            **os.environ,
            "IS_SANDBOX": "0",
            "PATH": os.environ.get("PATH", "") + ":/usr/local/bin",
            "ANTHROPIC_BASE_URL": "http://localhost:8050",
            "ANTHROPIC_MODEL": "claude-3-5-sonnet-20241022",
            "ANTHROPIC_AUTH_TOKEN": "anything",
        },
    )

    important_files: List[str] = []
    full_response = ""
    found_end_marker = False

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for message in client.receive_messages():
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        text = block.text
                        full_response += text
                        if '}' in text and '"important_files"' in full_response:
                            if full_response.count('{') > 0 and full_response.count('}') >= full_response.count('{'):
                                found_end_marker = True
                                await asyncio.sleep(0.5)
                                break
                if found_end_marker:
                    break

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

