# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 约束事件台账（constraint_events.jsonl，零上报个人数据）
"""
约束执法事件的本地台账——信用分/服从率度量的唯一数据源。

schema 第一天带齐（导师审查硬性验收：数据不可补采，缺了未来信用分就是
无米之筹）：{ts, book_id, chapter_id, constraint_id, status_at_event,
outcome, reason, detail}。

- outcome: hit（检测命中）| drop（菜单件丢弃）| exempt（豁免命中，信号流
  与真命中分列）| mute（静音）| rewrite（确定性改写）；
  二期返修环扩词（2026-09-02）：repair（带稿改写返修成功）| excise
  （句级切除兜底成功）| reject（返修切除均失败，拒稿不上屏）|
  breaker_open（章级滑窗拒稿熔断开启，降级为警示上屏）。
- status_at_event 写入时从 registry 取——约束 promote/降级后历史事件仍可
  按当时状态分桶。

写侧照抄 collab_events 模式（routes/adaptive._append_collab_event）：
路径锚定项目根不随 CWD 漂移、VELLUMA_DATA_DIR 运行时覆盖、5MB 轮转 .1、
无锁同步 append、全程静默失败（埋点绝不阻塞业务）。

副作用：写 data/constraint_events.jsonl（可静默失败）。
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from backend.services.constraints.registry import status_of

logger = logging.getLogger(__name__)

_MAX_BYTES = 5 * 1024 * 1024  # 单文件 5MB 上限：超出轮转一份（与 collab_events 同纪律）


def _events_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    return data_dir / "constraint_events.jsonl"


def _rotated_path() -> Path:
    base = _events_path()
    return base.with_name(base.name + ".1")


def log_constraint_event(
    book_id: str,
    chapter_id: str,
    constraint_id: str,
    outcome: str,
    reason: str = "",
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """追加约束事件（失败静默——埋点绝不阻塞业务）。"""
    from datetime import datetime, timezone

    try:
        path = _events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                rotated = _rotated_path()
                rotated.unlink(missing_ok=True)  # Windows rename 目标存在会报错，先清位
                path.rename(rotated)
        except Exception as e:
            logger.debug(f"[ConstraintEvent] 轮转失败（继续追加原文件）: {e}")
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "book_id": str(book_id or ""),
                "chapter_id": str(chapter_id or ""),
                "constraint_id": constraint_id,
                "status_at_event": status_of(constraint_id),
                "outcome": outcome,
                "reason": reason,
                "detail": detail or {},
            }, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.debug(f"[ConstraintEvent] 写入失败（静默）: {e}")


def read_constraint_events(chapter_id: str = "", book_id: str = "") -> Dict[str, Any]:
    """读侧聚合（与写侧轮转对称读两份）。过滤条件为空即全量。

    返回 {total, by_constraint: {id: count}, by_outcome: {...},
    recent: [最新 20 条]}。summary 端点与未来信用分/换模型 checklist 消费
    同一入口。
    """
    from collections import Counter

    by_constraint: Counter = Counter()
    by_outcome: Counter = Counter()
    recent: deque = deque(maxlen=20)  # 取尾部（最新的 20 条），不是最先扫到的 20 条
    total = 0
    for path in (_events_path(), _rotated_path()):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if chapter_id and ev.get("chapter_id") != chapter_id:
                        continue
                    if book_id and ev.get("book_id") != book_id:
                        continue
                    total += 1
                    by_constraint[ev.get("constraint_id") or "?"] += 1
                    by_outcome[ev.get("outcome") or "?"] += 1
                    recent.append(ev)
        except Exception as e:
            logger.debug(f"[ConstraintEvent] 读取失败（跳过该文件）: {e}")
    return {
        "total": total,
        "by_constraint": dict(by_constraint),
        "by_outcome": dict(by_outcome),
        "recent": list(recent),
    }
