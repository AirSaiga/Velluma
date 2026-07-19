"""
进度追踪器 (Progress Tracker) - 双轨生成路由的进度管理。

职责：
- 管理生成过程中的进度状态
- 提供进度事件队列
- 支持进度回调机制

主要功能：
- 创建和管理进度事件队列
- 发送 SSE 进度事件
- 处理心跳机制

依赖项：
- backend.services.utils.logging: SSE 事件构建函数

使用方式：
    from backend.routes.chapter_generation.progress_tracker import ProgressTracker

    tracker = ProgressTracker()
    await tracker.emit(event, message, **kwargs)
    # 或者使用回调模式
    tracker.set_callback(my_callback)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from backend.services.utils.logging import build_sse_event

logger = logging.getLogger(__name__)

# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 30


class ProgressTracker:
    """
    进度追踪器。

    职责：
    - 管理进度事件队列
    - 提供进度回调接口
    - 处理心跳机制

    设计决策：
    - 使用 asyncio.Queue 进行异步进度传递
    - 支持设置回调函数
    - 提供进度事件序列化
    """

    def __init__(self):
        """初始化进度追踪器"""
        self.queue: asyncio.Queue = asyncio.Queue()
        self.callbacks: List[Callable] = []
        self.last_event_time: float = datetime.now(timezone.utc).timestamp()
        self._closed: bool = False

    def set_callback(self, callback: Callable) -> None:
        """
        设置进度回调函数。

        Args:
            callback: 回调函数，签名为 async def callback(event, message, **kwargs)
        """
        self.callbacks.append(callback)

    async def emit(
        self,
        event: str,
        message: str,
        **kwargs: Any,
    ) -> None:
        """
        发送进度事件。

        Args:
            event: 事件类型
            message: 事件消息
            **kwargs: 附加参数
        """
        if self._closed:
            return

        event_data = {
            "event": event,
            "message": message,
            **kwargs,
        }

        # 放入队列
        await self.queue.put(event_data)

        # 调用回调
        for callback in self.callbacks:
            try:
                await callback(event=event, message=message, **kwargs)
            except Exception as e:
                logger.warning(f"[ProgressTracker] 回调执行失败: {e}")

        self.last_event_time = datetime.now(timezone.utc).timestamp()

    async def get_event(self, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
        """
        获取进度事件。

        Args:
            timeout: 超时时间（秒）

        Returns:
            事件数据，如果没有则返回 None
        """
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def get_all_pending(self) -> List[Dict[str, Any]]:
        """
        获取所有待处理的事件（非阻塞）。

        Returns:
            待处理事件列表
        """
        events = []
        while not self.queue.empty():
            try:
                event = self.queue.get_nowait()
                events.append(event)
            except asyncio.QueueEmpty:
                break
        return events

    def mark_done(self) -> None:
        """标记追踪完成"""
        self._closed = True
        # 放入结束信号
        asyncio.get_event_loop().call_soon(
            lambda: asyncio.create_task(self.queue.put(None))
        )

    def is_done(self) -> bool:
        """检查是否已标记完成"""
        return self._closed

    async def should_send_heartbeat(self) -> bool:
        """
        检查是否需要发送心跳。

        Returns:
            True 如果距离上次事件超过 HEARTBEAT_INTERVAL 秒
        """
        current_time = datetime.now(timezone.utc).timestamp()
        return (current_time - self.last_event_time) >= HEARTBEAT_INTERVAL

    def get_idle_time(self) -> float:
        """
        获取空闲时间。

        Returns:
            距离上次事件的秒数
        """
        current_time = datetime.now(timezone.utc).timestamp()
        return current_time - self.last_event_time

    def reset_idle_timer(self) -> None:
        """重置空闲计时器"""
        self.last_event_time = datetime.now(timezone.utc).timestamp()


class StreamEventBuilder:
    """
    流事件构建器。

    职责：
    - 构建 SSE 格式的事件字符串
    - 提供常用事件的快捷构建方法

    设计决策：
    - 静态方法，无需实例化
    - 封装 SSE 格式细节
    """

    @staticmethod
    def build_assembling_context(message: str = "加载章节上下文...") -> str:
        """构建 ASSEMBLING_CONTEXT 事件"""
        return f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': message}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_generation_run(run_id: str, message: str = "生成任务已初始化") -> str:
        """构建 GENERATION_RUN 事件"""
        return f"data: {json.dumps({'event': 'GENERATION_RUN', 'message': message, 'generation_run_id': run_id}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_context_loaded(entity_count: int, relationship_count: int) -> str:
        """构建 CONTEXT_LOADED 事件"""
        return f"data: {json.dumps({'event': 'CONTEXT_LOADED', 'message': f'加载 {entity_count} 个角色, {relationship_count} 组关系'}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_beats_confirmed(beat_count: int) -> str:
        """构建 BEATS_CONFIRMED 事件"""
        return f"data: {json.dumps({'event': 'BEATS_CONFIRMED', 'message': f'已接收 {beat_count} 个节拍，开始生成正文...'}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_drafting(iteration: int = 1) -> str:
        """构建 DRAFTING 事件"""
        return f"data: {json.dumps({'event': 'DRAFTING', 'message': '主笔 Agent 正在并行扩写节拍...', 'iteration': iteration}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_track_a_done(beat_count: int) -> str:
        """构建 TRACK_A_DONE 事件"""
        return f"data: {json.dumps({'event': 'TRACK_A_DONE', 'message': f'节拍扩写完成，{beat_count} 个片段'}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_track_b_done(word_count: int) -> str:
        """构建 TRACK_B_DONE 事件"""
        return f"data: {json.dumps({'event': 'TRACK_B_DONE', 'message': f'速写生成完成，{word_count} 字'}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_stitching() -> str:
        """构建 STITCHING 事件"""
        return f"data: {json.dumps({'event': 'STITCHING', 'message': '正在统稿拼接各节拍内容...'}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_reviewing(score: float, needs_fix: bool) -> str:
        """构建 REVIEWING 事件"""
        return f"data: {json.dumps({'event': 'REVIEWING', 'message': f'审阅完成，对齐度得分: {score:.1f}', 'score': score, 'needs_fix': needs_fix}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_final_text_stream(passed: bool) -> str:
        """构建 FINAL_TEXT_STREAM 事件"""
        return f"data: {json.dumps({'event': 'FINAL_TEXT_STREAM', 'message': '正在输出最终文本...', 'passed': passed}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_text_chunk(content: str) -> str:
        """构建 TEXT_CHUNK 事件"""
        return f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': content}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_heartbeat(run_id: str) -> str:
        """构建 HEARTBEAT 事件"""
        return f"data: {json.dumps({'event': 'HEARTBEAT', 'message': '', 'run_id': run_id, 'timestamp': datetime.now(timezone.utc).timestamp()}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_error(message: str, error_type: str, run_id: Optional[str] = None) -> str:
        """构建 ERROR 事件"""
        return f"data: {json.dumps({'event': 'ERROR', 'message': message, 'error_type': error_type, 'run_id': run_id}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_done(
        final_text: str,
        stats: Dict[str, Any],
        passed: bool,
        iterations: int,
        revision_count: int,
        generation_run_id: str,
        resumed: bool = False,
        alignment_score: Optional[float] = None,
    ) -> str:
        """构建 DONE 事件"""
        return f"data: {json.dumps({
            'event': 'DONE',
            'text': final_text,
            'stats': stats,
            'passed': passed,
            'iterations': iterations,
            'revision_count': revision_count,
            'generation_run_id': generation_run_id,
            'resumed': resumed,
            'alignment_score': alignment_score,
        }, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_metric(
        name: str,
        iteration: int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建指标帧"""
        data = {
            'event': name,
            'iteration': iteration,
        }
        if extra:
            data.update(extra)
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # ============================================================
    # CP3.4 双层审计事件（蓝图 §4.8 + 病灶 9 SSE 实时化）
    # ============================================================

    @staticmethod
    def build_audit_start() -> str:
        """构建 AUDIT_START 事件（LLM 审计开始时推送）"""
        return f"data: {json.dumps({'event': 'AUDIT_START', 'message': '正在执行双层审计（代码级 + LLM 级）...'}, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_audit_done(
        verdict: str,
        findings_count: int,
        degraded: Optional[bool] = None,
    ) -> str:
        """构建 AUDIT_DONE 事件（审计完成时推送）

        Args:
            verdict: pass / pass_with_fixes / fail / unaudited
            findings_count: findings 总数
            degraded: 是否降级（None 时不包含该字段）
        """
        data: Dict[str, Any] = {
            'event': 'AUDIT_DONE',
            'message': f'审计完成，结论：{verdict}（{findings_count} 条发现）',
            'verdict': verdict,
            'findings_count': findings_count,
        }
        if degraded is not None:
            data['degraded'] = degraded
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def build_degraded(
        stage: str,
        reason: str,
        action: str,
        detail: Optional[str] = None,
    ) -> str:
        """构建 DEGRADED 事件（任何降级时推送，蓝图 P5 失败不静默）

        Args:
            stage: 降级发生的阶段（如 stitching / reviewing / audit）
            reason: 降级原因
            action: 兜底动作
            detail: 可选补充
        """
        data: Dict[str, Any] = {
            'event': 'DEGRADED',
            'message': f'阶段 {stage} 降级：{reason}（兜底：{action}）',
            'stage': stage,
            'reason': reason,
            'action': action,
        }
        if detail:
            data['detail'] = detail[:200]
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
