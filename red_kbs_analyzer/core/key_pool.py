"""
Claude API Key 号池管理器
支持多个 API key 的轮询使用和失败重试
"""
import random
import threading
from typing import List, Optional, Dict
from ..run_logs.logger import logger


class ClaudeKeyPool:
    """Claude API Key 号池管理器"""
    
    def __init__(self, keys: List[str]):
        """
        初始化号池
        
        Args:
            keys: API key 列表
        """
        if not keys:
            raise ValueError("至少需要一个 API key")
        
        # 过滤空字符串
        self.keys = [k.strip() for k in keys if k and k.strip()]
        
        if not self.keys:
            raise ValueError("至少需要一个有效的 API key")
        
        self.current_index = 0
        self.lock = threading.Lock()  # 线程安全锁
        self.key_stats = {key: {"success": 0, "failed": 0, "errors": []} for key in self.keys}
        self.failed_keys = set()  # 临时失效的 key（可以定期重置）
        
        logger.info(f"[KeyPool] 初始化号池，共 {len(self.keys)} 个 key")
    
    def get_key(self) -> str:
        """
        获取一个可用的 key（轮询方式）
        
        Returns:
            API key
        """
        with self.lock:
            available_keys = [k for k in self.keys if k not in self.failed_keys]
            
            if not available_keys:
                # 所有 key 都失效了，重置并返回第一个
                logger.warning("[KeyPool] 所有 key 都失效，重置失败列表")
                self.failed_keys.clear()
                available_keys = self.keys
            
            # 轮询选择
            key = available_keys[self.current_index % len(available_keys)]
            self.current_index += 1
            
            return key
    
    def mark_success(self, key: str):
        """标记 key 使用成功"""
        with self.lock:
            if key in self.key_stats:
                self.key_stats[key]["success"] += 1
                # 如果之前失败过，从失败列表中移除
                self.failed_keys.discard(key)
    
    def mark_failed(self, key: str, error: str = ""):
        """
        标记 key 使用失败
        
        Args:
            key: 失败的 key
            error: 错误信息
        """
        with self.lock:
            if key in self.key_stats:
                self.key_stats[key]["failed"] += 1
                if error:
                    self.key_stats[key]["errors"].append(error)
                    # 只保留最近10个错误
                    if len(self.key_stats[key]["errors"]) > 10:
                        self.key_stats[key]["errors"] = self.key_stats[key]["errors"][-10:]
                
                # 如果失败次数过多，临时标记为失效
                if self.key_stats[key]["failed"] > 5:
                    self.failed_keys.add(key)
                    logger.warning(f"[KeyPool] Key 失败次数过多，临时标记为失效: {key[:20]}...")
    
    def get_stats(self) -> Dict:
        """获取号池统计信息"""
        with self.lock:
            return {
                "total_keys": len(self.keys),
                "available_keys": len(self.keys) - len(self.failed_keys),
                "failed_keys": len(self.failed_keys),
                "key_stats": self.key_stats.copy()
            }
    
    def reset_failed_keys(self):
        """重置失败列表（可以定期调用）"""
        with self.lock:
            self.failed_keys.clear()
            logger.info("[KeyPool] 已重置失败 key 列表")

