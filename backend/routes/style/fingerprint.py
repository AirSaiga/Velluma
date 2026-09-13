# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：/books/{id}/style-fingerprint —— 文风指纹测量（纯 code 0 LLM）。

「同一把尺子」红线：正文测量前必剥 HTML（services/utils/html_text 规范实现）。
"""
from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.repositories import AuthorSampleRepository, BookRepository, StyleCardRepository
from backend.schemas import StyleFingerprintResponse
from backend.services.style.fingerprint import (
    aggregate_corpus,
    compute_text_fingerprint,
    count_negative_hits,
)
from backend.services.utils.html_text import html_to_plain
from backend.services.utils.logging import get_runtime_logger
from backend.services.validation.thresholds import CV_THRESHOLD_HI, CV_THRESHOLD_LO

from ._deps import get_author_sample_repo, get_book_repo, get_style_card_repo

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api", tags=["style"])


# ============================================================
# 文风指纹（S1 测量层，docs/style-module-redesign.md §7.2）
# ============================================================

# 语料聚合上限：防极端大样本库拖慢请求（拼接后整体测量，见 aggregate_corpus）
_CORPUS_MAX_CHARS = 200_000




@router.get("/books/{book_id}/style-fingerprint", response_model=StyleFingerprintResponse)
async def get_book_style_fingerprint(
    book_id: UUID,
    with_chapters: bool = Query(False, description="附带章指纹（对账区数据，纯 code 实时计算）"),
    chapter_limit: int = Query(50, ge=1, le=200, description="章指纹取最近 N 章"),
    db: AsyncSession = Depends(get_db),
    repo: AuthorSampleRepository = Depends(get_author_sample_repo),
    style_repo: StyleCardRepository = Depends(get_style_card_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """文风指纹：语料聚合指纹 + 逐样本指纹 + 可选章指纹（对账）。

    纯 code 测量（0 LLM），作者样本与审计侧用同一把尺子
    （services/style/fingerprint.py，对拍单测锁定同值）。
    章指纹实时计算而非回填 QualityReport——永远与当前正文同步，
    且不会用 metrics-only 报告行遮蔽真实审计报告。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    samples = await repo.list_by_book(book_id)
    # 语料聚合只用近期样本（era != early）——文风会进化，早期的字只存档不掺语料
    recent_samples = [s for s in samples if (getattr(s, "era", "recent") or "recent") != "early"]
    corpus = aggregate_corpus(
        [s.content for s in recent_samples], max_chars=_CORPUS_MAX_CHARS,
    )
    sample_fps = [
        {"sample_id": str(s.id), "fingerprint": compute_text_fingerprint(s.content, light=True)}
        for s in samples
    ]

    # 对账参考：审计侧 CV 健康区间 + 对话占比「语料实测锚」（2026-09-14 去参数化：
    # 不再读文风卡上作者拨的 dialogue_ratio_target 浮点数——冻结只读后该值陈旧，
    # 对账带直接用作者自己语料的实测对话占比做目标带，零样本 → None 该带缺席）
    card = await style_repo.get_effective_card(book_id, chapter_id=None)
    dialogue_target = corpus.get("dialogue_ratio") or None if recent_samples else None

    chapters_payload: Optional[List[dict]] = None
    negative_hit_counts: Dict[str, int] = {}
    if with_chapters:
        query = (
            select(Chapter)
            .where(Chapter.book_id == book_id)
            .order_by(Chapter.chapter_number.desc())
            .limit(chapter_limit)
        )
        result = await db.execute(query)
        rows = list(result.scalars().all())
        rows.reverse()  # 章 1 → N 的时间序，前端直接画趋势
        # 「同一把尺子」：content_text 是 HTML，先剥再测（标签字符会污染句长/字数）；
        # 判空同样按纯文本——空文档落库为 "<p></p>"，HTML 判空会误判为有正文
        chapters_payload = []
        chapter_plain_texts: Dict[str, str] = {}
        for c in rows:
            plain = html_to_plain(c.content_text)
            if not plain:
                continue
            chapters_payload.append({
                "chapter_id": str(c.id),
                "chapter_number": c.chapter_number,
                "title": c.title or c.chapter_name,
                "fingerprint": compute_text_fingerprint(plain, light=True),
            })
            chapter_plain_texts[str(c.id)] = plain
        # 台账化：负面清单各词在近 10 章正文的命中次数（含 0——反向提醒可能不需要该词）
        negative_words = []
        if card and card.negative_list:
            for item in card.negative_list:
                if isinstance(item, dict):
                    w = item.get("word") or item.get("phrase") or ""
                    if w:
                        negative_words.append(w)
        if negative_words:
            # 「同一把尺子」：命中计数同样吃纯文本（HTML 标签残留会干扰词边界与口径）
            recent_chapter_texts = [
                chapter_plain_texts.get(str(c.id), "") for c in rows[-10:]
            ]
            negative_hit_counts = count_negative_hits(
                [t for t in recent_chapter_texts if t], negative_words,
            )

    # 指纹写穿缓存：供未来消费方（漂移提醒等）直接取用；读路径仍实时算保新鲜
    if card is not None:
        try:
            card.fingerprint = {"corpus": corpus, "sample_count": len(samples)}
            await db.commit()
        except Exception as e:
            logger.warning(f"[StyleFingerprint] 指纹写穿缓存失败（不阻塞）: {e}")
            await db.rollback()

    return StyleFingerprintResponse(
        corpus=corpus,
        samples=sample_fps,
        sample_count=len(samples),
        low_confidence=len(recent_samples) < 3,
        chapters=chapters_payload,
        reference={
            "cv_healthy": [CV_THRESHOLD_LO, CV_THRESHOLD_HI],
            "dialogue_target": dialogue_target,
        },
        negative_hit_counts=negative_hit_counts,
    )
