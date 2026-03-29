"""
SSE 消息构建工具

职责：
- 集中管理 Server-Sent Events 数据帧的序列化格式
- 提供各类 SSE 事件帧的标准化构建函数
"""

import json
from typing import Any, Dict, Optional


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
