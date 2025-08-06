"""
LLM工具函数模块
"""
import re
import json
from typing import Optional, Dict, Any


def extract_json_content(content: str) -> Optional[Dict[str, Any]]:
    """
    从LLM响应中提取JSON内容
    
    Args:
        content: LLM响应的原始内容
        
    Returns:
        提取的JSON数据，失败返回None
    """
    if not content:
        return None
    
    # 尝试多种JSON提取策略
    
    # 策略1: 提取```json```代码块
    json_patterns = [
        r'```json\s*\n(.*?)\n```',  # ```json ... ```
        r'```\s*\n(\{.*?\})\s*\n```',  # ``` {...} ```
        r'```\s*(\{.*?\})\s*```',  # ```{...}```
        r'(\{.*\})',  # 直接的JSON对象
    ]
    
    for pattern in json_patterns:
        matches = re.findall(pattern, content, re.DOTALL | re.MULTILINE)
        for match in matches:
            try:
                # 清理匹配的内容
                json_str = match.strip()
                # 移除可能的注释
                json_str = re.sub(r'//.*?\n', '\n', json_str)
                json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
                
                # 尝试解析JSON
                result = json.loads(json_str)
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                continue
    
    # 策略2: 寻找以{开头、}结尾的完整JSON对象
    try:
        # 查找第一个{和最后一个}之间的内容
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            json_str = content[start_idx:end_idx + 1]
            # 清理内容
            json_str = re.sub(r'//.*?\n', '\n', json_str)
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
            
            result = json.loads(json_str)
            if isinstance(result, dict):
                return result
    except (json.JSONDecodeError, ValueError):
        pass
    
    # 策略3: 尝试修复常见的JSON错误
    try:
        # 移除多余的逗号
        cleaned_content = re.sub(r',\s*}', '}', content)
        cleaned_content = re.sub(r',\s*]', ']', cleaned_content)
        
        # 查找JSON对象
        start_idx = cleaned_content.find('{')
        end_idx = cleaned_content.rfind('}')
        
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            json_str = cleaned_content[start_idx:end_idx + 1]
            result = json.loads(json_str)
            if isinstance(result, dict):
                return result
    except (json.JSONDecodeError, ValueError):
        pass
    
    return None


def validate_summary_response(data: Dict[str, Any]) -> bool:
    """验证摘要响应格式"""
    required_fields = ["summary", "files"]
    return all(field in data for field in required_fields)


def validate_tactics_response(data: Dict[str, Any]) -> bool:
    """验证战术响应格式"""
    if "tactics" not in data:
        return False
    
    tactics = data["tactics"]
    if not isinstance(tactics, list):
        return False
    
    for tactic in tactics:
        if not isinstance(tactic, dict):
            return False
        required_fields = ["tactic", "tactic_id", "evidence"]
        if not all(field in tactic for field in required_fields):
            return False
    
    return True


def validate_technique_response(data: Dict[str, Any]) -> bool:
    """验证技术响应格式"""
    if "result" not in data or "ttps" not in data:
        return False
    
    ttps = data["ttps"]
    if not isinstance(ttps, list):
        return False
    
    for ttp in ttps:
        if not isinstance(ttp, dict):
            return False
        required_fields = ["technique_id", "name", "code_relevance", "chunk_number", "relevance", "have_code"]
        if not all(field in ttp for field in required_fields):
            return False
    
    return True


def format_code_chunks_for_llm(chunks: list) -> list:
    """
    格式化代码块以供LLM分析
    
    Args:
        chunks: 代码块列表
        
    Returns:
        格式化后的代码块列表
    """
    formatted_chunks = []
    
    for chunk in chunks:
        if hasattr(chunk, 'to_dict'):
            chunk_dict = chunk.to_dict()
        else:
            chunk_dict = chunk
        
        # 只保留LLM需要的字段
        formatted_chunk = {
            "chunk_number": chunk_dict.get("chunk_number", 0),
            "code": chunk_dict.get("code", "")
        }
        
        # 限制代码长度
        if len(formatted_chunk["code"]) > 5000:
            formatted_chunk["code"] = formatted_chunk["code"][:5000] + "\n... (truncated)"
        
        formatted_chunks.append(formatted_chunk)
    
    return formatted_chunks 