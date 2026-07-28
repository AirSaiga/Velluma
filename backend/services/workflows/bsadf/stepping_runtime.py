# Velluma - NLE-ADF Stepping Runtime
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""
NLE-ADF 步进状态机运行时。

职责：
- 持有单个步进生成运行的可恢复状态（SteppingRun）
- 管理 run 的内存存储 + TTL 清理（与 _PENDING_BEAT_SLOTS 同模式）
- 提供 advance_event / action_queue / event_queue 三个并发原语
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SteppingRun:
    """单个步进生成运行的可恢复状态。"""

    run_id: str
    chapter_id: int
    cards: List[Any]
    workflow: Any

    current_beat_index: int = 0
    locked_segments: List[Any] = field(default_factory=list)
    state_card_chain: List[Any] = field(default_factory=list)
    decision_set: Dict[str, Any] = field(default_factory=dict)

    advance_event: asyncio.Event = field(default_factory=asyncio.Event)
    action_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    status: str = "stepping"
    final_result: Optional[Dict[str, Any]] = None
    _sse_seq_counter: int = 0


class SteppingRunStore:
    """SteppingRun 的内存存储 + TTL 清理。"""

    def __init__(self, ttl_seconds: int = 3600):
        self._runs: Dict[str, SteppingRun] = {}
        self._ttl = ttl_seconds

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            rid for rid, run in self._runs.items()
            if now - run.last_activity > self._ttl
        ]
        for rid in expired:
            del self._runs[rid]

    def set(self, run: SteppingRun) -> None:
        self._cleanup_expired()
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> Optional[SteppingRun]:
        self._cleanup_expired()
        run = self._runs.get(run_id)
        if run is not None:
            run.last_activity = time.time()
        return run

    def pop(self, run_id: str) -> Optional[SteppingRun]:
        self._cleanup_expired()
        return self._runs.pop(run_id, None)

    def touch(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is not None:
            run.last_activity = time.time()


_STEPPING_RUNS = SteppingRunStore(ttl_seconds=3600)


async def _emit_event(run: "SteppingRun", event: str, data: dict) -> None:
    payload = {"event": event, **data}
    await run.event_queue.put((event, data))


def _card_to_dict_safe(card: Any) -> dict:
    if hasattr(card, "beat_id"):
        try:
            from backend.services.workflows.bsadf.types import beat_slot_to_dict
            return beat_slot_to_dict(card)
        except Exception:
            pass
    return {"beat_id": getattr(card, "beat_id", ""), "segment_index": getattr(card, "segment_index", 0)}


def _degraded_to_dict_safe(degraded: Any) -> Optional[dict]:
    if degraded is None:
        return None
    return {
        "beat_id": getattr(degraded, "beat_id", ""),
        "segment_index": getattr(degraded, "segment_index", 0),
        "reason": getattr(degraded, "reason", ""),
        "attempts": getattr(degraded, "attempts", 0),
    }


def _apply_edited_slot(card: Any, edited_slot: dict) -> None:
    for field_name in ("core_plot_event", "key_anchors", "text_carrier", "outline_beat", "negative_bounds"):
        if field_name in edited_slot:
            setattr(card, field_name, edited_slot[field_name])


async def stepping_loop(
    run: "SteppingRun",
    enable_memory_ingestion: bool = True,
) -> None:
    """Phase 4 步进主循环。

    逐段：渲染 → BEAT_RENDER_READY → 挂起等 action →
    pass/edit/branch/skip → 下一段。末段锁死后跑 Phase 4.5-7.5，发 COMPLETE。
    """
    run.status = "stepping"
    i = 0
    while i < len(run.cards):
        run.current_beat_index = i
        card = run.cards[i]

        await _emit_event(run, "BEAT_RENDER_START", {
            "beat_id": card.beat_id,
            "segment_index": i,
            "target_word_count": getattr(card, "target_word_count", 500),
            "card_snapshot": _card_to_dict_safe(card),
        })
        segment, degraded = await run.workflow.render_one(
            card=card,
            segment_index=i,
            locked_segments=run.locked_segments,
            state_card_chain=run.state_card_chain,
            run=run,
        )
        await _emit_event(run, "BEAT_RENDER_READY", {
            "beat_id": card.beat_id,
            "segment_index": i,
            "word_count": len(getattr(segment, "text", "") or ""),
            "degraded": _degraded_to_dict_safe(degraded),
            "card_snapshot": _card_to_dict_safe(card),
        })

        action = await run.action_queue.get()
        run.last_activity = time.time()

        act = action.get("action")
        if act == "pass":
            facts = None
            if enable_memory_ingestion:
                facts = await run.workflow.ingest_memory(
                    segment=segment, card=card, segment_index=i,
                )
            run.locked_segments.append(segment)
            await _emit_event(run, "BEAT_LOCKED", {
                "beat_id": card.beat_id,
                "segment_index": i,
                "extracted_facts": facts,
            })
            i += 1
        elif act == "skip":
            await _emit_event(run, "BEAT_SKIPPED", {
                "beat_id": card.beat_id,
                "segment_index": i,
            })
            i += 1
        elif act in ("edit", "branch"):
            edited_slot = action.get("edited_slot")
            if edited_slot is not None and act == "edit":
                _apply_edited_slot(card, edited_slot)
                card.edited = True
                card.edit_count = getattr(card, "edit_count", 0) + 1
            elif act == "branch":
                choice = action.get("branch_choice", {})
                directive = choice.get("plot_impact") or choice.get("label", "")
                if directive:
                    card.branch_directive = directive
            card.status = "pending"
            card.render_attempts = 0
            continue

    await _emit_event(run, "ALL_BEATS_LOCKED", {
        "segment_count": len(run.cards),
        "total_word_count": sum(
            len(getattr(s, "text", "") or "") for s in run.locked_segments
        ),
    })
    run.status = "post_processing"
    final_text = "\n\n".join(
        getattr(s, "text", "") for s in run.locked_segments if getattr(s, "text", "").strip()
    )
    result = await run.workflow.run_post_step_phases(
        final_text=final_text,
        locked_segments=run.locked_segments,
        run=run,
    )
    run.status = "done"
    run.final_result = result
    await _emit_event(run, "COMPLETE", result)

