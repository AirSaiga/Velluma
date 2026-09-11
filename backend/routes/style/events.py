# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：/books/{id}/style/events —— 文风使用事件记录与汇总（本地 JSONL 零上报）。

写侧唯一权威在 services/style/events.py（2026-09-11 收敛：路由侧原有一份
逐字副本已删，本模块只做 HTTP 编排）。
"""
from __future__ import annotations

from typing import Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.repositories import BookRepository
from backend.schemas import StyleEventRequest
from backend.services.style.events import (
    STYLE_EVENTS_FILE,
    append_style_event as _append_style_event,
)

from ._deps import get_book_repo

router = APIRouter(prefix="/api", tags=["style"])


# ---- 埋点（本地 JSONL，零外部上报；桌面应用隐私边界内） ----

@router.post("/books/{book_id}/style/events", status_code=204)
async def log_style_event(
    book_id: UUID,
    payload: StyleEventRequest,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """记录文风使用事件（试听/喂养/收件箱裁决/预设——设计稿 §8 验证点的数据基础）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    _append_style_event(str(book_id), payload.kind, payload.detail)


@router.get("/books/{book_id}/style/events/summary")
async def style_events_summary(
    book_id: UUID,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """事件计数汇总（验证点：试听点击量 / 喂养率 / 收件箱采纳率）。"""
    import json as _json
    from collections import Counter as _Counter
    from pathlib import Path as _Path

    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    counts: Dict[str, int] = _Counter()
    try:
        path = _Path(STYLE_EVENTS_FILE)
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = _json.loads(line)
                        if ev.get("book_id") == str(book_id):
                            counts[ev.get("kind", "?")] += 1
                    except Exception:
                        continue
    except Exception:
        pass
    total = sum(counts.values())
    confirms = counts.get("inbox_confirm", 0)
    return {
        "total": total,
        "by_kind": dict(counts),
        "inbox_accept_rate": round(confirms / (confirms + counts.get("inbox_dismiss", 0)), 3)
        if (confirms + counts.get("inbox_dismiss", 0)) > 0 else None,
    }
