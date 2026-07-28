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
