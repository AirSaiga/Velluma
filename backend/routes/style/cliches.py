# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：/system/cliches + /books/{id}/cliche-exemptions —— 系统陈词库与本书豁免。"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.repositories import BookRepository, SystemClicheRepository
from backend.schemas import (
    ClicheExemptionsUpdate,
    SystemClicheCreate,
    SystemClicheResponse,
    SystemClicheUpdate,
)
from backend.services.style.cliche_provider import invalidate_cache as invalidate_cliche_cache

from ._deps import get_book_repo, get_system_cliche_repo

router = APIRouter(prefix="/api", tags=["style"])


@router.get("/books/{book_id}/cliche-exemptions", response_model=ClicheExemptionsUpdate)
async def get_cliche_exemptions(
    book_id: UUID,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """系统陈词库本书豁免列表。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return ClicheExemptionsUpdate(patterns=list(getattr(book, "style_cliche_exemptions", None) or []))


@router.put("/books/{book_id}/cliche-exemptions", response_model=ClicheExemptionsUpdate)
async def put_cliche_exemptions(
    book_id: UUID,
    payload: ClicheExemptionsUpdate,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """设置系统陈词库本书豁免（整体覆盖；不删全局层，仅本书审计/扫描/合并不生效）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    book.style_cliche_exemptions = [p for p in payload.patterns if p]
    db.add(book)
    await db.commit()
    invalidate_cliche_cache()
    return ClicheExemptionsUpdate(patterns=book.style_cliche_exemptions)


# ============================================================
# SystemCliche 端点
# ============================================================

@router.get("/system/cliches", response_model=List[SystemClicheResponse])
async def list_system_cliches(
    language: Optional[str] = Query(None, description="语言过滤"),
    severity: Optional[str] = Query(None, description="严重性过滤"),
    category: Optional[str] = Query(None, description="类别过滤"),
    enabled_only: bool = Query(True, description="仅返回启用的"),
    repo: SystemClicheRepository = Depends(get_system_cliche_repo),
):
    """列出系统禁词。"""
    from sqlalchemy import select
    from backend.models import SystemCliche
    query = select(SystemCliche)
    if enabled_only:
        query = query.where(SystemCliche.enabled.is_(True))
    if language:
        query = query.where(SystemCliche.language == language)
    if severity:
        query = query.where(SystemCliche.severity == severity)
    if category:
        query = query.where(SystemCliche.category == category)
    query = query.order_by(SystemCliche.created_at.asc())
    result = await repo._db.execute(query)
    return list(result.scalars().all())


@router.post("/system/cliches", response_model=SystemClicheResponse, status_code=201)
async def create_system_cliche(
    payload: SystemClicheCreate,
    db: AsyncSession = Depends(get_db),
    repo: SystemClicheRepository = Depends(get_system_cliche_repo),
):
    """新增系统禁词（创建后自动清缓存）。"""
    from backend.models import SystemCliche
    cliche = SystemCliche(**payload.model_dump())
    repo._db.add(cliche)
    await db.commit()
    await db.refresh(cliche)
    invalidate_cliche_cache()
    return cliche


@router.put("/system/cliches/{cliche_id}", response_model=SystemClicheResponse)
async def update_system_cliche(
    cliche_id: UUID,
    payload: SystemClicheUpdate,
    db: AsyncSession = Depends(get_db),
    repo: SystemClicheRepository = Depends(get_system_cliche_repo),
):
    """更新系统禁词（更新后自动清缓存）。"""
    cliche = await repo.get_by_id(cliche_id)
    if not cliche:
        raise HTTPException(status_code=404, detail="禁词不存在")

    update_data = payload.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(cliche, k, v)
    await db.commit()
    await db.refresh(cliche)
    invalidate_cliche_cache()
    return cliche


@router.delete("/system/cliches/{cliche_id}", status_code=204)
async def delete_system_cliche(
    cliche_id: UUID,
    db: AsyncSession = Depends(get_db),
    repo: SystemClicheRepository = Depends(get_system_cliche_repo),
):
    """删除系统禁词（删除后自动清缓存）。"""
    cliche = await repo.get_by_id(cliche_id)
    if not cliche:
        raise HTTPException(status_code=404, detail="禁词不存在")
    await repo.delete(cliche)
    await db.commit()
    invalidate_cliche_cache()

