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
文风体系 API 路由（Phase 1 CP2.2b 新建；S1-S3 文风模块重构扩展，docs/style-module-redesign.md）。

职责：提供 StyleCard / AuthorSample / SystemCliche 的 CRUD + 文风指纹/收件箱/试听/扫描。

端点清单：
- StyleCard:
  - GET    /api/books/{id}/style-card           获取书级文风卡
  - PUT    /api/books/{id}/style-card           创建/更新书级文风卡（章级覆盖优先）
  - DELETE /api/books/{id}/style-card           删除章级覆盖（S3 恢复继承，须带 chapter_id）
  - POST   /api/books/{id}/style-card/extract   从样本提炼文风画像（Match My Style）
- 文风指纹（S1）:
  - GET    /api/books/{id}/style-fingerprint    语料聚合+逐样本+章指纹（纯 code 实时算）
- AuthorSample:
  - GET    /api/books/{id}/samples              列出作者样本
  - POST   /api/books/{id}/samples              创建作者样本（含向量化）
  - DELETE /api/books/{id}/samples/{sample_id}  删除作者样本
  - POST   /api/books/{id}/samples/search       向量检索相似样本
  - POST   /api/books/{id}/samples/from-chapters 已发布章节一键收编（零状态坡道兜底）
- 文风收件箱（S3）:
  - GET    /api/books/{id}/style/inbox          待过目候选列表
  - POST   /api/books/{id}/style/inbox          投递候选（不直接生效）
  - POST   /api/books/{id}/style/inbox/{item_id}/confirm   确认（负面候选入清单/样本入库）
  - POST   /api/books/{id}/style/inbox/{item_id}/dismiss   忽略
- 试听/扫描（S3）:
  - POST   /api/books/{id}/style/audition       试听改写（SSE，真实注入管线，支持 A/B 基线）
  - POST   /api/books/{id}/style/scan-negative  三层禁词扫描（纯 code，审稿模式数据源）
- SystemCliche:
  - GET    /api/system/cliches                  列出系统禁词
  - POST   /api/system/cliches                  新增系统禁词
  - PUT    /api/system/cliches/{id}             更新系统禁词
  - DELETE /api/system/cliches/{id}             删除系统禁词
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.core.dependencies import get_db
from backend.models import Chapter, StyleInboxItem
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
    StyleFingerprintResponse,
    SamplesFromChaptersRequest,
    StyleInboxAddRequest,
    StyleInboxItemResponse,
    StyleAuditionRequest,
    StyleScanNegativeRequest,
    AuthorSamplePatchRequest,
    ClicheExemptionsUpdate,
    StyleEventRequest,
)
from backend.services.style.extractor import extract_style_card
from backend.services.style.fingerprint import (
    aggregate_corpus,
    compute_text_fingerprint,
    count_negative_hits,
)
from backend.services.style.retrieval import retrieve_author_samples
from backend.services.style.cliche_provider import invalidate_cache as invalidate_cliche_cache
from backend.services.validation.thresholds import CV_THRESHOLD_LO, CV_THRESHOLD_HI
from backend.services.context.settings_bundle import render_style_positive
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.llm.embedding import get_embedding
from backend.services.prompts.adaptive_prompts import build_audition_prompt
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import build_sse_event, build_sse_error

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


# ============================================================
# 文风指纹（S1 测量层，docs/style-module-redesign.md §7.2）
# ============================================================

# 语料聚合上限：防极端大样本库拖慢请求（拼接后整体测量，见 aggregate_corpus）
_CORPUS_MAX_CHARS = 200_000


def _plain_text(html: Optional[str]) -> str:
    """剥 HTML 为纯文本（与 memory_indexing 同口径）。

    画布正文以编辑器 getHTML 落库（content_text 是 HTML），一切「测量」消费
    （章指纹 / 负面命中 / 章节收编）必须先剥——标签字符混入会污染句长/字数
    统计，违反「同一把尺子」红线（services/style/fingerprint.py，对拍单测锁定同值）。
    """
    plain = re.sub(r"<[^>]+>", "\n", html or "")
    return re.sub(r"\n{3,}", "\n\n", plain).strip()


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

    # 对账目标：书级文风卡的对话占比目标 + 审计侧 CV 健康区间（同一参考系）
    card = await style_repo.get_effective_card(book_id, chapter_id=None)
    dialogue_target = float(card.dialogue_ratio_target) if card and card.dialogue_ratio_target is not None else None

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
            plain = _plain_text(c.content_text)
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
        return bool(_plain_text(c.content_text))

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
        excerpt = _excerpt_to_sentence_boundary(_plain_text(chapter.content_text), payload.excerpt_chars)
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
# 章级覆盖删除（S3「恢复继承」）+ 文风收件箱 + 试听 + 禁词扫描
# ============================================================

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


@router.get("/books/{book_id}/style/inbox", response_model=List[StyleInboxItemResponse])
async def list_style_inbox(
    book_id: UUID,
    include_resolved: bool = Query(False, description="含已确认/已忽略条目"),
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """文风收件箱：待作者过目的候选（pending 优先，新→旧）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    query = select(StyleInboxItem).where(StyleInboxItem.book_id == book_id)
    if not include_resolved:
        query = query.where(StyleInboxItem.status == "pending")
    query = query.order_by(StyleInboxItem.created_at.desc()).limit(100)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/books/{book_id}/style/inbox", response_model=StyleInboxItemResponse, status_code=201)
async def add_style_inbox_item(
    book_id: UUID,
    payload: StyleInboxAddRequest,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """投递文风候选（写作台「这不像我」等入口）。候选不直接生效——进收件箱待过目。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if payload.kind == "negative_candidate":
        word = str(payload.payload.get("word") or "").strip()
        if not word:
            raise HTTPException(status_code=422, detail="negative_candidate 需要 payload.word")
    item = StyleInboxItem(
        book_id=book_id,
        kind=payload.kind,
        payload=payload.payload,
        source=payload.source,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/books/{book_id}/style/inbox/{item_id}/confirm", response_model=StyleInboxItemResponse)
async def confirm_style_inbox_item(
    book_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
    style_repo: StyleCardRepository = Depends(get_style_card_repo),
    sample_repo: AuthorSampleRepository = Depends(get_author_sample_repo),
):
    """确认候选（✓）。negative_candidate → 写入书级文风卡负面清单并同步书级黑名单；
    sample_candidate → 存入作者样本库（自动向量化）。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    item = (
        await db.execute(
            select(StyleInboxItem).where(
                StyleInboxItem.id == item_id, StyleInboxItem.book_id == book_id,
            )
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="收件箱条目不存在")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"条目已处理（{item.status}）")

    if item.kind == "negative_candidate":
        word = str(item.payload.get("word") or "").strip()
        alternative = str(item.payload.get("alternative") or "").strip() or None
        card = await style_repo.get_effective_card(book_id, chapter_id=None)
        if card is None:
            from backend.models import StyleCard as StyleCardModel
            card = StyleCardModel(book_id=book_id, negative_list=[])
            db.add(card)
        negative = list(card.negative_list or [])
        if not any((e.get("word") if isinstance(e, dict) else "") == word for e in negative):
            negative.append({"word": word, "alternative": alternative})
            card.negative_list = negative
        # 与书级黑名单保持一致（旧消费方仍读 book.style_blacklist）
        blacklist = list(book.style_blacklist or [])
        if word not in blacklist:
            blacklist.append(word)
            book.style_blacklist = blacklist
        invalidate_cliche_cache()
    elif item.kind == "sample_candidate":
        content = str(item.payload.get("content") or "").strip()
        if not content:
            raise HTTPException(status_code=422, detail="sample_candidate 缺少 content")
        embedding = None
        try:
            embedding = await get_embedding(content)
        except Exception as e:
            logger.warning(f"[StyleInbox] 样本候选向量化失败（不阻断）: {e}")
        await sample_repo.create_with_embedding(
            book_id=book_id,
            content=content,
            scene_type=str(item.payload.get("scene_type") or "general"),
            source="golden_snippet",
            embedding=embedding,
        )
    else:
        raise HTTPException(status_code=422, detail=f"未知候选类型: {item.kind}")

    item.status = "confirmed"
    item.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/books/{book_id}/style/inbox/{item_id}/dismiss", response_model=StyleInboxItemResponse)
async def dismiss_style_inbox_item(
    book_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """忽略候选（✗）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    item = (
        await db.execute(
            select(StyleInboxItem).where(
                StyleInboxItem.id == item_id, StyleInboxItem.book_id == book_id,
            )
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="收件箱条目不存在")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"条目已处理（{item.status}）")
    item.status = "dismissed"
    item.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/books/{book_id}/style/audition")
async def style_audition(
    book_id: UUID,
    request: StyleAuditionRequest,
    book_repo: BookRepository = Depends(get_book_repo),
    style_repo: StyleCardRepository = Depends(get_style_card_repo),
    db: AsyncSession = Depends(get_db),
):
    """试听（试衣间）：给定段落 + 文风配置 → 真实注入管线改写，SSE 打字机推流。

    与 stitch-ghost 同一套基座/画像块/示范块（build_audition_prompt）——
    作者在文风页看到的改写效果，就是写作台续写会走的效果。
    style_override 非空 = 试听未保存的草稿配置；use_samples=False = A/B 基线版。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    if request.style_override is not None:
        style_positive = render_style_positive(request.style_override)
    else:
        card = await style_repo.get_effective_card(book_id, chapter_id=None)
        style_positive = render_style_positive(card)

    author_samples: List[str] = []
    if request.use_samples:
        author_samples = await retrieve_author_samples(
            db, str(book_id), request.text[:200], k=2,
        )

    target_chars = request.target_chars or max(80, len(request.text))
    system_prompt, user_prompt = build_audition_prompt(
        text=request.text,
        style_positive=style_positive,
        author_samples=author_samples,
        target_chars=target_chars,
    )

    async def _stream():
        try:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                max_tokens=max(1200, target_chars * 2 + 1000),
                reasoning_config=REASONING_DISABLED,
            )
            text = (result.content or "").strip().strip("“").strip("”").strip()
            if not text:
                yield build_sse_error("试听产出为空，请重试")
                return
            yield build_sse_event("AUDITION_START", "")
            for pos in range(0, len(text), 12):
                yield build_sse_event("AUDITION_CHUNK", "", delta=text[pos: pos + 12])
                await asyncio.sleep(0.03)
            yield build_sse_event("AUDITION_DONE", "", text=text, word_count=len(text))
        except Exception as e:
            logger.warning(f"[style/audition] 失败: {e}")
            yield build_sse_error(f"试听失败: {e}")

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/books/{book_id}/style/scan-negative")
async def scan_negative(
    book_id: UUID,
    request: StyleScanNegativeRequest,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
    style_repo: StyleCardRepository = Depends(get_style_card_repo),
):
    """禁词扫描（E3 审稿模式数据源，纯 code 0 LLM）。

    四层禁忌面（系统陈词库 + 书级黑名单 + 文风卡负面清单 + 静态反 AI 词）
    经 prohibitions.py 归一合并后扫描文本，返回按词聚合的命中清单
    （替代建议 + 每处上下文）。替换由作者逐条 ✓ 后前端应用——本端点
    绝不改正文。
    ⚠ 禁忌面归一起行为变化：命中现在**含静态反 AI 词**（深邃/宛如等 15 词，
    severity 恒 warning）——审稿扫描是呈现面，全量可见符合「让作者看见」
    的设计；fail-fast 校验侧（StyleClicheValidator.validate）才排除静态源。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    text = request.text or ""
    if request.chapter_id:
        chapter = (
            await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
        ).scalar_one_or_none()
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(status_code=404, detail="章节不存在")
        text = chapter.content_text or chapter.draft_text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="待扫描文本为空")

    card = await style_repo.get_effective_card(book_id, chapter_id=None)

    # 禁忌面归一（任务包 A）：四源合并唯一权威（db 直查 SystemCliche、
    # book.style_blacklist / style_cliche_exemptions、card.negative_list、静态词）
    from backend.services.style.prohibitions import load_prohibition_set

    ps = await load_prohibition_set(db, book=book, style_card=card)

    grouped: Dict[str, Dict[str, Any]] = {}
    for m, entry in ps.finditer(text):
        word = m.group(0)
        g = grouped.setdefault(word, {
            "word": word,
            "alternative": entry.alternative or "",
            "severity": entry.severity or "warning",
            "count": 0,
            "occurrences": [],
        })
        offset = m.start()
        snippet = text[max(0, offset - 15): offset + len(word) + 15]
        g["count"] += 1
        if len(g["occurrences"]) < 5:
            g["occurrences"].append({"offset": offset, "context": snippet})

    hits = sorted(grouped.values(), key=lambda e: -e["count"])[:50]
    return {"word_count": len(text), "hit_words": len(hits), "total_hits": sum(e["count"] for e in hits), "hits": hits}


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


# ---- 埋点（本地 JSONL，零外部上报；桌面应用隐私边界内） ----
_STYLE_EVENTS_FILE = "data/style_events.jsonl"


def _append_style_event(book_id: str, kind: str, detail: Optional[str]) -> None:
    """追加事件到本地 JSONL（失败静默——埋点绝不阻塞业务）。"""
    import json as _json
    from datetime import datetime, timezone as _tz
    from pathlib import Path as _Path

    try:
        path = _Path(_STYLE_EVENTS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps({
                "ts": datetime.now(_tz.utc).isoformat(),
                "book_id": book_id,
                "kind": kind,
                "detail": detail or "",
            }, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[StyleEvent] 写入失败（静默）: {e}")


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
        path = _Path(_STYLE_EVENTS_FILE)
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


__all__ = ["router"]
