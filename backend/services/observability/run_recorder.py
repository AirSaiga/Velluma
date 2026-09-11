# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
RunRecorder - LLM 调用计量与降级事件的内存收集器。

职责：
- 在工作流层（dual_track / drafting / sketch_generator 等）随调用收集 LLMResult
- 收集降级事件（degraded）供 T5 降级显式化使用
- 提供批量落库接口，由持有 db session 的入口层（stream_handler / publish）调用

设计动机（调研报告 §2.2-13）：
- 工作流层不持有 db session（核查确认 dual_track.py / drafting.py 均无 AsyncSession）
- 因此采用"内存收集 + 入口层批量落库"的两层设计，避免 db 透传污染工作流签名

业务场景：
    recorder = RunRecorder(chapter_id, run_id)
    async with recorder.record_call(stage="drafting.beat_3", model_slot="creative") as r:
        result = await call_llm_with_usage(...)
        r.set_result(result)
    # 若发生异常，r 自动标记 degraded

    # 入口层最后一次性落库：
    await recorder.flush_to_db(db)

主要功能：
- record_call：上下文管理器，包装单次 LLM 调用，自动采集 result/异常
- record_degraded：独立记录降级事件（用于不调 LLM 的纯代码降级，如 Sketch markers 解析失败）
- flush_to_db：批量落库到 generation_runs 表
- snapshot：返回内存中的记录列表，供 SSE 实时上浮使用

依赖项：
- backend.models.GenerationRun：ORM 模型
- backend.services.llm.client.LLMResult：调用结果 dataclass
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.services.llm.client import LLMResult

logger = logging.getLogger(__name__)


@dataclass
class CallRecord:
    """单次 LLM 调用的内存记录（落库前的中间态）。

    与 GenerationRun 表字段对齐，但 chapter_id/run_id 由 RunRecorder 统一注入。
    """
    stage: str
    model_slot: Optional[str] = None
    model_name: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    thinking_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None  # 缓存命中输入 token（成本核算；None=厂商未回报）
    latency_ms: Optional[int] = None
    degraded: Optional[Dict[str, Any]] = None  # {reason, action, detail?}


class RunRecorder:
    """LLM 调用计量与降级事件的内存收集器。

    一个 recorder 绑定一次章节生成（一个 chapter_id + run_id），
    工作流层各阶段共享同一实例，入口层在适当时机 flush_to_db。

    线程安全：本类预期在单事件循环内使用（asyncio 工作流），不做跨线程同步。
    """

    def __init__(self, chapter_id: Optional[str] = None, run_id: Optional[str] = None):
        """
        Args:
            chapter_id: 章节 ID（字符串形式 UUID），落库时写入
            run_id: 运行 ID，与 Chapter.generation_run_id 对齐
        """
        self.chapter_id = chapter_id
        self.run_id = run_id
        self._records: List[CallRecord] = []
        self._degraded_events: List[Dict[str, Any]] = []  # 供 SSE 上浮

    @asynccontextmanager
    async def record_call(
        self,
        stage: str,
        model_slot: Optional[str] = None,
    ) -> AsyncIterator["_CallContext"]:
        """上下文管理器：包装单次 LLM 调用。

        用法：
            async with recorder.record_call(stage="drafting.beat_3", model_slot="creative") as ctx:
                result = await call_llm_with_usage(...)
                ctx.set_result(result)
            # 异常时 ctx 自动写入 degraded={reason: exception}

        Args:
            stage: 阶段标识，如 "planning.beats" / "drafting.beat_3" / "stitching"
            model_slot: 模型槽位 reasoning/creative/light
        """
        ctx = _CallContext(stage=stage, model_slot=model_slot)
        try:
            yield ctx
            record = ctx.to_record()
            self._records.append(record)
        except Exception as e:
            # 异常路径：标记 degraded，不再追加正常记录
            record = CallRecord(
                stage=stage,
                model_slot=model_slot,
                degraded={
                    "reason": "exception_during_call",
                    "action": "propagated",
                    "detail": f"{type(e).__name__}: {str(e)[:200]}",
                },
            )
            self._records.append(record)
            self._degraded_events.append({
                "stage": stage,
                "reason": "exception_during_call",
                "action": "propagated",
            })
            raise

    def record_result(
        self,
        stage: str,
        result: LLMResult,
        model_slot: Optional[str] = None,
        degraded: Optional[Dict[str, Any]] = None,
    ) -> None:
        """非上下文管理器形式：直接记录已知结果。

        适用于降级点（如 Sketch markers 解析失败）已经拿到了 LLMResult，
        需要追加 degraded 标记的场景。

        Args:
            stage: 阶段标识
            result: call_llm_with_usage 返回的 LLMResult
            model_slot: 模型槽位
            degraded: 附加降级标记（可选）
        """
        record = CallRecord(
            stage=stage,
            model_slot=model_slot,
            model_name=result.model_name,
            prompt_tokens=result.usage.get("prompt_tokens") if result.usage else None,
            completion_tokens=result.usage.get("completion_tokens") if result.usage else None,
            thinking_tokens=result.usage.get("reasoning_tokens") if result.usage else None,
            cached_tokens=result.usage.get("cached_tokens") if result.usage else None,
            latency_ms=result.latency_ms,
            degraded=degraded,
        )
        self._records.append(record)
        if degraded:
            self._degraded_events.append({
                "stage": stage,
                "reason": degraded.get("reason", "unknown"),
                "action": degraded.get("action", "unknown"),
            })

    def record_degraded(
        self,
        stage: str,
        reason: str,
        action: str,
        model_slot: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """记录纯代码降级事件（不涉及 LLM 调用）。

        用于 Sketch markers 解析失败、POV JSON 解析失败等不调用 LLM 的降级点。

        Args:
            stage: 阶段标识，如 "sketch.markers_parse"
            reason: 降级原因短码，如 "json_decode_failed"
            action: 采取的兜底动作，如 "uniform_distribution_fallback"
            model_slot: 关联的模型槽位（可选）
            detail: 详细说明（可选）
        """
        degraded_payload = {"reason": reason, "action": action}
        if detail:
            degraded_payload["detail"] = detail[:300]
        record = CallRecord(
            stage=stage,
            model_slot=model_slot,
            degraded=degraded_payload,
        )
        self._records.append(record)
        self._degraded_events.append({
            "stage": stage,
            "reason": reason,
            "action": action,
        })

    def snapshot(self) -> List[CallRecord]:
        """返回当前记录的浅拷贝（供 SSE 实时上浮查看）。"""
        return list(self._records)

    def drain(self) -> List[CallRecord]:
        """取出并清空当前记录（供入口层原子化 flush，防重复落库）。

        与 flush_to_db 的组合模式：先 drain 拿走记录，构造临时 recorder 落库；
        落库失败时用 restore 塞回，账不丢。adaptive 观测层（chapter 级常驻
        recorder + 多端点分散 flush）依赖此语义。
        """
        records = self._records
        self._records = []
        return records

    def restore(self, records: List[CallRecord]) -> None:
        """把 drain 走的记录塞回队首（flush 失败防丢账）。"""
        self._records[0:0] = records

    def degraded_events(self) -> List[Dict[str, Any]]:
        """返回累积的降级事件列表（供 SSE DEGRADED 事件批量上浮）。"""
        return list(self._degraded_events)

    @property
    def total_tokens(self) -> Dict[str, int]:
        """聚合 token 总量（供章级报告快速预览）。"""
        prompt = sum(r.prompt_tokens or 0 for r in self._records)
        completion = sum(r.completion_tokens or 0 for r in self._records)
        thinking = sum(r.thinking_tokens or 0 for r in self._records)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "thinking_tokens": thinking,
            "total": prompt + completion + thinking,
        }

    async def flush_to_db(self, db) -> int:
        """批量落库到 generation_runs 表。

        Args:
            db: AsyncSession 实例（由入口层 stream_handler/publish 提供）

        Returns:
            落库的记录数

        警示：
        - 本方法不 commit；调用方负责在合适时机 commit
        - 重复调用会重复插入（不做去重），调用方应确保只 flush 一次
        """
        if not self._records:
            return 0

        # 延迟导入避免循环依赖
        from backend.models import GenerationRun
        from backend.models import generate_uuid

        chapter_id_value = None
        if self.chapter_id:
            try:
                chapter_id_value = self.chapter_id if isinstance(self.chapter_id, str) else None
            except Exception:
                chapter_id_value = None

        count = 0
        for record in self._records:
            try:
                run = GenerationRun(
                    id=generate_uuid(),
                    chapter_id=chapter_id_value,
                    run_id=self.run_id,
                    stage=record.stage,
                    model_slot=record.model_slot,
                    model_name=record.model_name,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    thinking_tokens=record.thinking_tokens,
                    cached_tokens=record.cached_tokens,
                    latency_ms=record.latency_ms,
                    degraded=record.degraded,
                )
                db.add(run)
                count += 1
            except Exception as e:
                logger.warning(f"[RunRecorder] 落库失败 stage={record.stage}: {e}")

        return count


@dataclass
class _CallContext:
    """record_call 上下文对象，承载单次调用的结果或异常。

    设为私有（下划线前缀），外部仅通过 record_call 的 yield 访问。
    """
    stage: str
    model_slot: Optional[str] = None
    _result: Optional[LLMResult] = None
    _degraded: Optional[Dict[str, Any]] = None

    def set_result(self, result: LLMResult, degraded: Optional[Dict[str, Any]] = None) -> None:
        """设置 LLM 调用结果。

        Args:
            result: call_llm_with_usage 返回的 LLMResult
            degraded: 可选的降级标记（如解析成功但内容异常）
        """
        self._result = result
        self._degraded = degraded

    def to_record(self) -> CallRecord:
        """转换为 CallRecord（由 RunRecorder 在退出上下文时调用）。"""
        if self._result is None:
            # 调用方未设置结果（如直接 return），记为 degraded
            return CallRecord(
                stage=self.stage,
                model_slot=self.model_slot,
                degraded={
                    "reason": "no_result_set",
                    "action": "skipped",
                },
            )
        return CallRecord(
            stage=self.stage,
            model_slot=self.model_slot,
            model_name=self._result.model_name,
            prompt_tokens=self._result.usage.get("prompt_tokens") if self._result.usage else None,
            completion_tokens=self._result.usage.get("completion_tokens") if self._result.usage else None,
            thinking_tokens=self._result.usage.get("reasoning_tokens") if self._result.usage else None,
            cached_tokens=self._result.usage.get("cached_tokens") if self._result.usage else None,
            latency_ms=self._result.latency_ms,
            degraded=self._degraded,
        )
