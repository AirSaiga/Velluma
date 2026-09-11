# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：/books/{id}/samples —— 作者样本库（手动/章节收编/黄金片段导入）。

样本是文风 few-shot 与指纹语料的唯一来源；向量经 get_embedding 自动生成，
失败不阻断（新近兜底检索仍可用）。
"""
from __future__ import annotations

import re
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.repositories import AuthorSampleRepository, BookRepository
from backend.schemas import (
    AuthorSampleCreate,
    AuthorSamplePatchRequest,
    AuthorSampleResponse,
    AuthorSampleSearchHit,
    AuthorSampleSearchRequest,
    SamplesFromChaptersRequest,
)
from backend.services.llm.embedding import get_embedding
from backend.services.utils.html_text import html_to_plain
from backend.services.utils.logging import get_runtime_logger

from ._deps import get_author_sample_repo, get_book_repo

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api", tags=["style"])


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
        era=payload.era,
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
        # 未配置 embedding 时 get_embedding 静默返回空——给人话而非裸 500
        raise HTTPException(
            status_code=409,
            detail="向量检索不可用（未配置 embedding 或当前 SQLite 后端不支持——专业级向量记忆需 PostgreSQL）",
        )

    try:
        hits = await repo.search_by_style(
            embedding=query_embedding,
            book_id=book_id,
            scene_type=payload.scene_type,
            limit=payload.limit,
        )
    except Exception as e:
        # SQLite 方言下 cosine_distance 编译失败等——记内部日志，对外只回人话
        logger.error(f"[AuthorSample] 向量检索执行失败: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=409,
            detail="向量检索不可用（未配置 embedding 或当前 SQLite 后端不支持——专业级向量记忆需 PostgreSQL）",
        )
    return [
        AuthorSampleSearchHit(
            sample=AuthorSampleResponse.model_validate(sample),
            distance=distance,
        )
        for sample, distance in hits
    ]



@router.post("/books/{book_id}/samples/from-chapters", response_model=List[AuthorSampleResponse], status_code=201)
async def create_samples_from_chapters(
    book_id: UUID,
    payload: SamplesFromChaptersRequest,
    db: AsyncSession = Depends(get_db),
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """从已发布章节一键收编作者样本（文风页零状态坡道兜底，设计稿 §6.3）。

    已发布章节优先；一本从未发布的书回落到有正文的章节
    （作者主导写作模式下正文即作者的字）。摘取章节开头至句界。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    def _has_content(c: Chapter) -> bool:
        # 必须按纯文本判空——空文档落库为 "<p></p>"，HTML 判空会误判为有正文
        # （_plain_text 已提升为模块级函数：指纹/命中/收编三处测量共用同一剥法）
        return bool(html_to_plain(c.content_text))

    base = (
        select(Chapter)
        .where(Chapter.book_id == book_id)
        .order_by(Chapter.chapter_number.desc())
        .limit(50)
    )
    result = await db.execute(base)
    recent = list(result.scalars().all())

    published = [c for c in recent if c.status == "published" and _has_content(c)][: payload.max_chapters]
    picked = published or [c for c in recent if _has_content(c)][: payload.max_chapters]
    if not picked:
        raise HTTPException(status_code=404, detail="本书尚无可收编的章节正文")

    # 幂等：已收编过的章节跳过（防重复点击产生重复样本，与 from-golden 去重同原则）
    existing = await repo.list_by_book(book_id)
    collected_chapter_ids = {s.chapter_id for s in existing if s.source == "published_chapter" and s.chapter_id}
    picked = [c for c in picked if c.id not in collected_chapter_ids]

    picked.reverse()  # 按章号升序收编，样本列表时序自然

    created = []
    for chapter in picked:
        excerpt = _excerpt_to_sentence_boundary(html_to_plain(chapter.content_text), payload.excerpt_chars)
        if not excerpt:
            continue
        embedding = None
        try:
            embedding = await get_embedding(excerpt)
        except Exception as e:
            logger.warning(f"[AuthorSample] 章节收编向量化失败（不阻断）: {e}")
        sample = await repo.create_with_embedding(
            book_id=book_id,
            content=excerpt,
            scene_type="general",
            chapter_id=chapter.id,
            source="published_chapter",
            embedding=embedding,
        )
        created.append(sample)

    await db.commit()
    for sample in created:
        await db.refresh(sample)
    return created


def _excerpt_to_sentence_boundary(text: str, max_chars: int) -> str:
    """摘取章节开头至句界（最后一个中文句末标点），防半截句入库。"""
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    matches = list(re.finditer(r"[。！？!?…]", window))
    if not matches:
        return window
    cut = matches[-1].end()
    # 句界截断后过短（章节开头长段无句读）则原样返回
    return window[:cut] if cut >= 100 else window

# ============================================================
# 补全批次（完整落地）：样本时期/收藏 PATCH / 黄金片段导入 / 系统陈词豁免 / 埋点
# ============================================================

@router.patch("/books/{book_id}/samples/{sample_id}", response_model=AuthorSampleResponse)
async def patch_author_sample(
    book_id: UUID,
    sample_id: UUID,
    payload: AuthorSamplePatchRequest,
    db: AsyncSession = Depends(get_db),
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
):
    """样本局部更新：时期标记 / 收藏 / 场景类型 / 正文。

    正文变更时重算 word_count 并重新向量化。旧向量与新文本不再同义，
    重向量化失败（含未配置 embedding，get_embedding 返回 []）时清空为
    None——宁缺勿旧：无向量的样本仍走检索层的新近兜底，带旧向量的样本
    会按改前的文本错配。
    """
    sample = await repo.get_by_id(sample_id)
    if not sample or sample.book_id != book_id:
        raise HTTPException(status_code=404, detail="样本不存在")
    if payload.era is not None:
        sample.era = payload.era
    if payload.favorite is not None:
        sample.favorite = payload.favorite
    if payload.scene_type is not None:
        sample.scene_type = payload.scene_type
    if payload.content is not None:
        content = payload.content.strip()
        if not content:
            raise HTTPException(status_code=422, detail="样本正文不能为空")
        sample.content = content
        sample.word_count = len(content)
        try:
            sample.embedding = await get_embedding(content) or None
        except Exception as e:
            logger.warning(f"[AuthorSample] 重向量化失败（清空旧向量）: {e}")
            sample.embedding = None
    await db.commit()
    await db.refresh(sample)
    return sample


@router.post("/books/{book_id}/samples/from-golden", response_model=List[AuthorSampleResponse], status_code=201)
async def create_samples_from_golden(
    book_id: UUID,
    db: AsyncSession = Depends(get_db),
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """把书级 golden_snippets（旧黄金片段表）一键导入文风样本库。

    设计稿 §7.2 端点补全：按内容精确去重（已导入过的跳过）；
    导入后 source=golden_snippet、era=recent。存量书的黄金片段
    由此一次性进入 few-shot 与指纹语料（评估结论：旧表维持双写，见 §11）。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    snippets = [s for s in (book.golden_snippets or []) if isinstance(s, str) and s.strip()]
    if not snippets:
        raise HTTPException(status_code=404, detail="本书没有黄金片段可导入")

    existing = await repo.list_by_book(book_id)
    seen_contents = {(s.content or "").strip() for s in existing}

    created = []
    for snippet in snippets:
        if snippet.strip() in seen_contents:
            continue
        embedding = None
        try:
            embedding = await get_embedding(snippet)
        except Exception as e:
            logger.warning(f"[AuthorSample] 黄金片段导入向量化失败（不阻断）: {e}")
        sample = await repo.create_with_embedding(
            book_id=book_id,
            content=snippet,
            scene_type="general",
            source="golden_snippet",
            embedding=embedding,
        )
        created.append(sample)
    await db.commit()
    for sample in created:
        await db.refresh(sample)
    return created
