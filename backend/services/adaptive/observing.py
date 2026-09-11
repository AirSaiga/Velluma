# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - adaptive 流观测层（P0-2）
"""
adaptive 端点的成本核算与 trace（roadmap P0-2，2026-08-18）。

与其他引擎（adf/bsadf/refinery：一次请求一个 run）不同，adaptive 是
**章节级长会话**：心跳高频进、组件异步跑、产出跨请求落世界模型。因此
观测采用 chapter 作用域：

- **RunRecorder 按 chapter 常驻**（run_id = adaptive_{chapter_id}），
  组件在任意请求/后台 task 里 record_result 累积，任意端点离开时
  flush（drain + 落库 + commit，失败塞回防丢账，per-chapter 锁防并发
  重复落库）。后台异步组件的账由下一次心跳/settle/finish 顺路冲走。
- **trace 按 chapter 一个文件**（logs/trace_adaptive_{chapter_id}.jsonl）：
  路由入口 bind_adaptive_trace 绑定 contextvar，llm/client 的自动埋点
  （llm_call 事件含 prompt/usage/latency）对请求内与由其派生的后台
  task 均生效；事件按 ts 追加，跨多次写作会话共存于同文件。

stage 命名：adaptive.<component>[.<detail>]（intent_inference /
future_projection / dock_generator / canon_watch / post_process.critique /
event_scout.{settle|finish|auto_read} / read_entities /
stitch_ghost[.compress|.repair] / spine_suggest[.retry]）。
用量面板的 stage→标签/链路分组唯一权威在 routes/chapter_generation/usage.py。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict

from backend.services.observability.run_recorder import RunRecorder
from backend.services.observability.run_trace import create_trace

logger = logging.getLogger(__name__)

# chapter_id → 常驻 recorder（与 orchestrator 同生命周期；章节实例极少，不做淘汰）
_RECORDERS: Dict[str, RunRecorder] = {}
_FLUSH_LOCKS: Dict[str, asyncio.Lock] = {}


def get_adaptive_recorder(chapter_id: str) -> RunRecorder:
    """取（或建）章节的常驻 recorder——组件 record_result 的唯一入口。"""
    rec = _RECORDERS.get(chapter_id)
    if rec is None:
        rec = RunRecorder(chapter_id=chapter_id, run_id=f"adaptive_{chapter_id}")
        _RECORDERS[chapter_id] = rec
    return rec


def bind_adaptive_trace(chapter_id: str) -> None:
    """路由入口绑定 chapter 级 trace（同文件追加；llm/client 自动埋点生效）。"""
    create_trace(run_id=f"adaptive_{chapter_id}", engine="adaptive", chapter_id=chapter_id)


async def flush_adaptive_records(chapter_id: str) -> int:
    """drain 本章累积的调用记录并落库（自开 session + commit，失败塞回）。

    副作用：写 generation_runs 表。并发安全：per-chapter 锁，drain 原子。
    """
    rec = _RECORDERS.get(chapter_id)
    if not rec or not rec.snapshot():
        return 0
    lock = _FLUSH_LOCKS.setdefault(chapter_id, asyncio.Lock())
    async with lock:
        records = rec.drain()
        if not records:
            return 0
        try:
            from backend.database import AsyncSessionLocal

            # 构造临时 recorder 复用 flush_to_db 的行映射，避免字段清单双份维护
            carrier = RunRecorder(chapter_id=chapter_id, run_id=rec.run_id)
            carrier.restore(records)
            async with AsyncSessionLocal() as db:
                count = await carrier.flush_to_db(db)
                await db.commit()
            return count
        except Exception as e:
            logger.warning(f"[adaptive/observing] 落库失败（记录塞回待下次冲走）: {e}")
            rec.restore(records)
            return 0
