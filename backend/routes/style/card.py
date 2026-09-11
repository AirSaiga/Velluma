# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：/books/{id}/style-card —— 文风卡读取/保存/提炼 + 章级覆盖删除。"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.repositories import BookRepository, StyleCardRepository
from backend.schemas import (
    StyleCardCreate,
    StyleCardResponse,
    StyleExtractRequest,
    StyleExtractResponse,
)
from backend.services.style.extractor import extract_style_card

from ._deps import get_book_repo, get_style_card_repo

router = APIRouter(prefix="/api", tags=["style"])


# ============================================================
# StyleCard 端点
# ============================================================

@router.get("/books/{book_id}/style-card", response_model=Optional[StyleCardResponse])
async def get_book_style_card(
    book_id: UUID,
    chapter_id: Optional[UUID] = Query(None, description="章级覆盖（非空时优先返回章级）"),
    repo: StyleCardRepository = Depends(get_style_card_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """获取生效的文风卡（章级覆盖优先，回退书级）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    card = await repo.get_effective_card(book_id, chapter_id=chapter_id)
    return card  # 可能为 None


@router.put("/books/{book_id}/style-card", response_model=StyleCardResponse)
async def upsert_book_style_card(
    book_id: UUID,
    payload: StyleCardCreate,
    db: AsyncSession = Depends(get_db),
    repo: StyleCardRepository = Depends(get_style_card_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """创建或更新文风卡（书级或章级覆盖）。"""
    from backend.models import StyleCard as StyleCardModel

    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # exclude_unset 而非 exclude_none：前端 StyleView 总是全量发送，显式 null
    # 是「清除」语义（如 dialogue_ratio_target=null 拨回「自动」档）——
    # exclude_none 会把 null 键丢掉，DB 旧值复活（「自动」档清不掉事故）
    fields = payload.model_dump(exclude={"chapter_id"}, exclude_unset=True)
    chapter_id = payload.chapter_id

    if chapter_id is None:
        # 书级：upsert
        card = await repo.upsert_book_card(book_id, **fields)
    else:
        # 章级覆盖：先查再改/建
        existing = await repo.get_chapter_override(chapter_id)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            card = existing
        else:
            card = StyleCardModel(book_id=book_id, chapter_id=chapter_id, **fields)
            repo._db.add(card)
            await db.flush()

    await db.commit()
    await db.refresh(card)
    return card


@router.post("/books/{book_id}/style-card/extract", response_model=StyleExtractResponse)
async def extract_book_style_card(
    book_id: UUID,
    payload: StyleExtractRequest,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """从作者样本提炼文风画像（Match My Style 式，蓝图 §6.2）。

    不落库——仅返回提炼结果，前端确认后再 PUT /style-card。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 用 book.genre 作兜底题材
    genre = payload.genre or getattr(book, "genre", None)

    result = await extract_style_card(
        samples=payload.samples,
        genre=genre,
    )
    return StyleExtractResponse(**result)



@router.delete("/books/{book_id}/style-card", status_code=204)
async def delete_chapter_style_override(
    book_id: UUID,
    chapter_id: UUID = Query(..., description="要删除的章级覆盖（书级卡不可删，走 PUT 清空字段）"),
    db: AsyncSession = Depends(get_db),
    repo: StyleCardRepository = Depends(get_style_card_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """删除章级文风覆盖（本章恢复继承书级文风）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    card = await repo.get_chapter_override(chapter_id)
    if not card or card.book_id != book_id:
        raise HTTPException(status_code=404, detail="本章没有章级文风覆盖")
    await repo.delete(card)
    await db.commit()
