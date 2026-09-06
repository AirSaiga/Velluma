# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Reader Mirror REST API（V4.2 路径 B）。

端点（前缀 /api/books/{book_id}/reader-mirror）：
- GET  /                       获取全书 mirror 快照
- GET  /plan/{chapter_number}  获取本章规划建议（仪表盘，介入点 1 用）
- POST /expectations           添加期待（作者声明）
- PUT  /expectations/{id}      更新期待（张力/状态/作者覆盖）
- DELETE /expectations/{id}    删除期待
- POST /tension/{chapter}      记录章节张力采样
- POST /infer/{chapter_id}     章节发布后自动推断期待变化
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.repositories import ChapterRepository
from backend.schemas import ExpectationUpdate
from backend.services.reader_mirror import ReaderMirrorService
from backend.services.utils.logging import get_runtime_logger

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/books", tags=["reader-mirror-v4.2"])


# ============================================================
# 请求模型
# ============================================================

class ExpectationCreate(BaseModel):
    """创建期待请求。"""
    id: str
    type: str
    description: str
    current_tension: int = 5
    expected_payoff_chapter: Optional[int] = None
    related_hook_ids: list = []
    related_character_ids: list = []
    author_override: Optional[str] = None


class TensionRecord(BaseModel):
    """章节张力记录请求。"""
    overall_tension: int
    is_payoff: bool = False
    note: str = ""


# ============================================================
# 端点
# ============================================================

@router.get("/{book_id}/reader-mirror")
async def get_mirror(book_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取全书 mirror 快照。"""
    service = ReaderMirrorService(db)
    return await service.get_snapshot(book_id)


@router.get("/{book_id}/reader-mirror/plan/{chapter_number}")
async def get_chapter_plan(
    book_id: UUID,
    chapter_number: int,
    db: AsyncSession = Depends(get_db),
):
    """获取本章规划建议（仪表盘，介入点 1 用）。"""
    service = ReaderMirrorService(db)
    plan = await service.get_chapter_plan(book_id, chapter_number)
    return plan.model_dump()


@router.post("/{book_id}/reader-mirror/expectations")
async def create_expectation(
    book_id: UUID,
    payload: ExpectationCreate,
    db: AsyncSession = Depends(get_db),
):
    """添加期待（作者声明）。"""
    service = ReaderMirrorService(db)
    expectation = {
        "id": payload.id,
        "book_id": str(book_id),
        "type": payload.type,
        "description": payload.description,
        "source": "author_declared",
        "status": "setup",
        "current_tension": payload.current_tension,
        "expected_payoff_chapter": payload.expected_payoff_chapter,
        "tension_history": [],
        "related_hook_ids": payload.related_hook_ids,
        "related_character_ids": payload.related_character_ids,
        "author_override": payload.author_override,
    }
    return await service.add_expectation(book_id, expectation)


@router.put("/{book_id}/reader-mirror/expectations/{expectation_id}")
async def update_expectation(
    book_id: UUID,
    expectation_id: str,
    payload: ExpectationUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新期待（张力/状态）。"""
    service = ReaderMirrorService(db)
    updated = await service.update_expectation(book_id, expectation_id, payload)
    if not updated:
        raise HTTPException(404, "期待不存在")
    return updated


@router.delete("/{book_id}/reader-mirror/expectations/{expectation_id}")
async def delete_expectation(
    book_id: UUID,
    expectation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除期待。"""
    service = ReaderMirrorService(db)
    ok = await service.delete_expectation(book_id, expectation_id)
    if not ok:
        raise HTTPException(404, "期待不存在")
    return {"deleted": True, "id": expectation_id}


@router.post("/{book_id}/reader-mirror/tension/{chapter_number}")
async def record_tension(
    book_id: UUID,
    chapter_number: int,
    payload: TensionRecord,
    db: AsyncSession = Depends(get_db),
):
    """记录章节张力采样。"""
    service = ReaderMirrorService(db)
    await service.record_chapter_tension(
        book_id, chapter_number,
        overall_tension=payload.overall_tension,
        is_payoff=payload.is_payoff,
        note=payload.note,
    )
    return {"recorded": True, "chapter": chapter_number}


@router.post("/{book_id}/reader-mirror/infer/{chapter_id}")
async def infer_after_publish(
    book_id: UUID,
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """章节发布后自动推断期待变化。"""
    chapter_repo = ChapterRepository(db)
    chapter = await chapter_repo.get_by_id(str(chapter_id))
    if not chapter:
        raise HTTPException(404, "章节不存在")
    text = chapter.content_text or chapter.draft_text or ""
    chapter_number = getattr(chapter, "chapter_number", 1) or 1

    service = ReaderMirrorService(db)
    updated = await service.update_after_chapter_published(book_id, chapter_number, text)
    return {
        "updated": True,
        "expectations_count": len(updated.get("expectations", [])),
    }
