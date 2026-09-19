# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：ask-book —— 问书（行间手势速查，04 下一阶段设计稿 M1-M3）。

图书管理员不是合著者：只读作者自己的数据、答完即止、逐条出处、零创作。
问题原文随响应落 data/ask_book_metrics.jsonl（05 瘦身口径独立台账）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.services.utils.logging import get_runtime_logger

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


class AskBookRequest(BaseModel):
    question: str = Field(..., max_length=200, description="一句话问题（行间 ?? 手势捕获）")


@router.post("/{chapter_id}/adaptive/ask-book")
async def ask_book(chapter_id: str, payload: AskBookRequest, db: AsyncSession = Depends(get_db)):
    """问书 → {kind, text, sources[]}；kind=not_found/no_match 也是合法答案（诚实是功能）。"""
    from backend.services.world.ask_book import answer_question, log_ask_metric

    try:
        chapter = await db.get(Chapter, chapter_id)
    except Exception:
        chapter = None
    if chapter is None:
        return {"kind": "not_found", "text": "没查到——找不到这个章节。", "sources": []}

    try:
        answer = await answer_question(db, str(chapter.book_id), chapter, payload.question)
    except Exception as e:
        logger.warning(f"[ask_book] 回答失败（按没查到，不阻塞写作）: {e}")
        answer = {"kind": "not_found", "text": "没查到——问书这会儿没答上来。", "sources": []}
    log_ask_metric(str(chapter.book_id), str(chapter_id), payload.question, str(answer.get("kind") or ""))
    return answer
