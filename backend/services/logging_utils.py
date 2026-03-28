"""
日志工具模块 - 统一日志格式和辅助函数

职责：
- 提供标准化的日志前缀格式
- 提供 SSE 消息构建工具
- 提供性能计时装饰器

设计原则：
- 所有日志前缀统一格式：[ModuleName] message
- SSE 消息构建集中管理，避免重复代码
"""

import json
import logging
import time
from functools import wraps
from typing import Any, Dict, Optional, Callable, Union

# 日志值类型限制
LogValue = Union[str, int, float, bool, None]


# =============================================================================
# 日志前缀常量定义
# =============================================================================

LOG_PREFIX_DUAL_TRACK = "[DualTrack]"
LOG_PREFIX_RAG = "[RAG]"
LOG_PREFIX_PROMPT_LOGGER = "[PromptLogger]"
LOG_PREFIX_EMBEDDING = "[Embedding]"
LOG_PREFIX_SUMMARY = "[Summary]"
LOG_PREFIX_WORKFLOW = "[Workflow]"
LOG_PREFIX_SYSTEM = "[System]"


# =============================================================================
# 标准化日志函数
# =============================================================================

def log_info(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 info 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.info(f"{prefix} {message} {extra_info}")
    else:
        logger.info(f"{prefix} {message}")


def log_warning(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 warning 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.warning(f"{prefix} {message} {extra_info}")
    else:
        logger.warning(f"{prefix} {message}")


def log_error(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 error 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.error(f"{prefix} {message} {extra_info}")
    else:
        logger.error(f"{prefix} {message}")


def log_debug(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 debug 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.debug(f"{prefix} {message} {extra_info}")
    else:
        logger.debug(f"{prefix} {message}")


# =============================================================================
# SSE 消息构建工具
# =============================================================================

def build_sse_event(event: str, message: str, **kwargs) -> str:
    """
    构建 SSE 事件消息
    
    Args:
        event: 事件类型
        message: 消息内容
        **kwargs: 额外字段
        
    Returns:
        SSE 格式的数据帧
    """
    payload: Dict[str, Any] = {"event": event, "message": message}
    payload.update(kwargs)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_sse_metric_frame(event: str, iteration: int = 1, extra: Optional[Dict[str, Any]] = None) -> str:
    """
    构建统计帧 SSE 消息
    
    Args:
        event: 事件类型
        iteration: 迭代轮次
        extra: 额外统计信息
        
    Returns:
        SSE 格式的数据帧
    """
    payload = {
        "event": event,
        "iteration": iteration,
        "metrics": extra or {},
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_sse_text_chunk(content: str) -> str:
    """构建文本块 SSE 消息"""
    return f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': content}, ensure_ascii=False)}\n\n"


def build_sse_done(text: str, stats: Optional[Dict] = None, **kwargs) -> str:
    """构建完成事件 SSE 消息"""
    payload: Dict[str, Any] = {"event": "DONE", "text": text}
    if stats:
        payload["stats"] = stats
    payload.update(kwargs)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_sse_error(error_msg: str, done: bool = True) -> str:
    """构建错误事件 SSE 消息"""
    messages = [f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"]
    if done:
        messages.append(f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n")
    return "".join(messages)


# =============================================================================
# 性能计时工具
# =============================================================================

def timed(logger: Optional[logging.Logger] = None, prefix: str = "", log_level: int = logging.INFO):
    """
    性能计时装饰器
    
    用法：
        @timed(logger, "[Module]")
        async def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} completed in {elapsed:.2f}s"
                    logger.log(log_level, log_msg)
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} failed after {elapsed:.2f}s: {e}"
                    logger.error(log_msg)
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} completed in {elapsed:.2f}s"
                    logger.log(log_level, log_msg)
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} failed after {elapsed:.2f}s: {e}"
                    logger.error(log_msg)
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


# 需要导入 asyncio 用于检测
import asyncio


# =============================================================================
# 超时控制装饰器
# =============================================================================

def with_timeout(timeout_seconds: float, timeout_message: str = "Operation timed out"):
    """
    为异步函数添加超时控制的装饰器
    
    用法：
        @with_timeout(120, "LLM call timed out")
        async def call_llm_with_timeout(...):
            return await call_llm(...)
    
    Args:
        timeout_seconds: 超时时间（秒）
        timeout_message: 超时时的错误消息
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(timeout_message)
        return wrapper
    return decorator


class TimeoutManager:
    """
    超时管理器 - 统一管理常用操作的超时设置
    
    用法：
        timeout_mgr = TimeoutManager()
        result = await timeout_mgr.call_with_timeout(llm_call(), "llm")
    """
    
    # 默认超时配置（秒）
    DEFAULT_TIMEOUTS = {
        "llm": 120,           # LLM 调用
        "embedding": 60,      # Embedding 生成
        "summary": 180,       # 摘要生成
        "world_state": 150,   # 世界状态提取
        "character_update": 180,  # 角色状态更新
        "db_query": 30,       # 数据库查询
    }
    
    def __init__(self, custom_timeouts: Optional[Dict[str, float]] = None):
        """
        初始化超时管理器
        
        Args:
            custom_timeouts: 自定义超时配置，覆盖默认值
        """
        self._timeouts = {**self.DEFAULT_TIMEOUTS, **(custom_timeouts or {})}
    
    async def call_with_timeout(
        self,
        coro,
        operation_type: str,
        custom_timeout: Optional[float] = None
    ):
        """
        使用配置的超时时间执行协程
        
        Args:
            coro: 要执行的协程
            operation_type: 操作类型（用于查找默认超时）
            custom_timeout: 自定义超时（覆盖配置）
            
        Returns:
            协程执行结果
            
        Raises:
            asyncio.TimeoutError: 超时
        """
        timeout = custom_timeout or self._timeouts.get(operation_type, 120)
        return await asyncio.wait_for(coro, timeout=timeout)
    
    def get_timeout(self, operation_type: str) -> float:
        """获取指定操作类型的超时时间"""
        return self._timeouts.get(operation_type, 120)
    
    def set_timeout(self, operation_type: str, timeout: float) -> None:
        """设置指定操作类型的超时时间"""
        self._timeouts[operation_type] = timeout


# =============================================================================
# 便捷日志类（用于服务中快速记录）
# =============================================================================

class ServiceLogger:
    """
    服务日志助手 - 为特定服务提供预配置前缀的日志方法
    
    用法：
        logger = ServiceLogger(logging.getLogger(__name__), "[DualTrack]")
        logger.info("Starting workflow")
        # 输出: [DualTrack] Starting workflow
    """
    
    def __init__(self, logger: logging.Logger, prefix: str):
        self._logger = logger
        self._prefix = prefix
    
    def info(self, message: str, **kwargs: LogValue) -> None:
        log_info(self._logger, self._prefix, message, **kwargs)
    
    def warning(self, message: str, **kwargs: LogValue) -> None:
        log_warning(self._logger, self._prefix, message, **kwargs)
    
    def error(self, message: str, **kwargs: LogValue) -> None:
        log_error(self._logger, self._prefix, message, **kwargs)
    
    def debug(self, message: str, **kwargs: LogValue) -> None:
        log_debug(self._logger, self._prefix, message, **kwargs)
