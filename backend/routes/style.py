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
文风体系 API 路由（Phase 1 CP2.2b 新建）。

职责：提供 StyleCard / AuthorSample / SystemCliche 的 CRUD + StyleCard 提炼端点。

端点清单：
- StyleCard:
  - GET    /api/books/{id}/style-card           获取书级文风卡
  - PUT    /api/books/{id}/style-card           创建/更新书级文风卡
  - POST   /api/books/{id}/style-card/extract   从样本提炼文风画像（Match My Style）
- AuthorSample:
  - GET    /api/books/{id}/samples              列出作者样本
  - POST   /api/books/{id}/samples              创建作者样本（含向量化）
  - DELETE /api/books/{id}/samples/{sample_id}  删除作者样本
  - POST   /api/books/{id}/samples/search       向量检索相似样本
- SystemCliche:
  - GET    /api/system/cliches                  列出系统禁词
  - POST   /api/system/cliches                  新增系统禁词
  - PUT    /api/system/cliches/{id}             更新系统禁词
  - DELETE /api/system/cliches/{id}             删除系统禁词
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.repositories import (
    BookRepository,
    StyleCardRepository,
    AuthorSampleRepository,
    SystemClicheRepository,
)
from backend.schemas import (
    StyleCardCreate,
    StyleCardUpdate,
    StyleCardResponse,
    AuthorSampleCreate,
    AuthorSampleResponse,
    AuthorSampleSearchRequest,
    AuthorSampleSearchHit,
    SystemClicheCreate,
    SystemClicheUpdate,
    SystemClicheResponse,
    StyleExtractRequest,
    StyleExtractResponse,
)
from backend.services.style.extractor import extract_style_card
from backend.services.style.cliche_provider import invalidate_cache as invalidate_cliche_cache
from backend.services.llm.embedding import get_embedding
from backend.services.utils.logging import get_runtime_logger

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api", tags=["style"])


# ============================================================
# 辅助：依赖注入工厂（最小侵入，避免改 core/dependencies.py）
# ============================================================

def get_style_card_repo(db: AsyncSession = Depends(get_db)) -> StyleCardRepository:
    return StyleCardRepository(db)


def get_author_sample_repo(db: AsyncSession = Depends(get_db)) -> AuthorSampleRepository:
    return AuthorSampleRepository(db)


def get_system_cliche_repo(db: AsyncSession = Depends(get_db)) -> SystemClicheRepository:
    return SystemClicheRepository(db)


def get_book_repo(db: AsyncSession = Depends(get_db)) -> BookRepository:
    return BookRepository(db)


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

    fields = payload.model_dump(exclude={"chapter_id"}, exclude_none=True)
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
            card = await repo.update(existing)
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


# ============================================================
# AuthorSample 端点
# ============================================================

@router.get("/books/{book_id}/samples", response_model=List[AuthorSampleResponse])
async def list_author_samples(
    book_id: UUID,
    scene_type: Optional[str] = Query(None, description="场景类型过滤"),
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """列出书籍的作者样本。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    return await repo.list_by_book(book_id, scene_type=scene_type)


@router.post("/books/{book_id}/samples", response_model=AuthorSampleResponse, status_code=201)
async def create_author_sample(
    book_id: UUID,
    payload: AuthorSampleCreate,
    db: AsyncSession = Depends(get_db),
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """创建作者样本（保存时自动向量化）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 向量化（失败不阻断，embedding 留空）
    embedding = None
    try:
        embedding = await get_embedding(payload.content)
    except Exception as e:
        logger.warning(f"[AuthorSample] 向量化失败（不阻断创建）: {e}")

    sample = await repo.create_with_embedding(
        book_id=book_id,
        content=payload.content,
        scene_type=payload.scene_type,
        chapter_id=payload.chapter_id,
        source=payload.source,
        embedding=embedding,
    )
    await db.commit()
    await db.refresh(sample)
    return sample


@router.delete("/books/{book_id}/samples/{sample_id}", status_code=204)
async def delete_author_sample(
    book_id: UUID,
    sample_id: UUID,
    db: AsyncSession = Depends(get_db),
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
):
    """删除作者样本。"""
    sample = await repo.get_by_id(sample_id)
    if not sample or sample.book_id != book_id:
        raise HTTPException(status_code=404, detail="样本不存在")
    await repo.delete(sample)
    await db.commit()


@router.post("/books/{book_id}/samples/search", response_model=List[AuthorSampleSearchHit])
async def search_author_samples(
    book_id: UUID,
    payload: AuthorSampleSearchRequest,
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """向量检索相似作者样本。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 查询文本向量化
    try:
        query_embedding = await get_embedding(payload.query_text)
    except Exception as e:
        logger.error(f"[AuthorSample] 查询向量化失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询向量化失败: {e}")

    if not query_embedding:
        raise HTTPException(status_code=500, detail="查询向量化返回空")

    hits = await repo.search_by_style(
        embedding=query_embedding,
        book_id=book_id,
        scene_type=payload.scene_type,
        limit=payload.limit,
    )
    return [
        AuthorSampleSearchHit(
            sample=AuthorSampleResponse.model_validate(sample),
            distance=distance,
        )
        for sample, distance in hits
    ]


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
    await repo.update(cliche)
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


__all__ = ["router"]
