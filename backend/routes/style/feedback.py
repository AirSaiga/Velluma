# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：作者反馈环 —— 收件箱裁决 / 试听 / 禁词扫描 / 可逆学习 / 采纳池。

红线：候选不直接生效——作者确认才入库；扫描只提示绝不改正文。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.core.dependencies import get_db
from backend.models import Chapter, StyleInboxItem
from backend.repositories import AuthorSampleRepository, BookRepository, StyleCardRepository
from backend.schemas import (
    StyleAuditionRequest,
    StyleInboxAddRequest,
    StyleInboxConfirmRequest,
    StyleInboxItemResponse,
    StyleScanNegativeRequest,
)
from backend.services.context.settings_bundle import render_style_positive
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.llm.embedding import get_embedding
from backend.services.prompts.adaptive_prompts import build_audition_prompt
from backend.services.style.cliche_provider import invalidate_cache as invalidate_cliche_cache
from backend.services.style.events import append_style_event as _append_style_event
from backend.services.style.retrieval import retrieve_author_samples
from backend.services.utils.html_text import html_to_plain
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import build_sse_error, build_sse_event

from ._deps import get_author_sample_repo, get_book_repo, get_style_card_repo

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api", tags=["style"])


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


def _resolve_negative_confirm(
    item_payload: Dict[str, Any],
    override: Optional[StyleInboxConfirmRequest] = None,
) -> Tuple[str, Optional[str], str]:
    """解析 negative_candidate 确认入清单的 (word, alternative, severity)。

    - severity 白名单透传：仅 payload 显式 "blocker" 原样收，其余一律 "warning"
    - override（Phase 3 确认前就地编辑）：word 覆盖 strip 后非空才生效；
      alternative 覆盖空串=清除替代（None=不覆盖）。旧调用方不带覆盖字段
      时行为逐字节不变。
    """
    word = str(item_payload.get("word") or "").strip()
    alternative = str(item_payload.get("alternative") or "").strip() or None
    severity = "blocker" if item_payload.get("severity") == "blocker" else "warning"
    if override is not None:
        if override.word is not None and override.word.strip():
            word = override.word.strip()
        if override.alternative is not None:
            alternative = override.alternative.strip() or None
    return word, alternative, severity


@router.post("/books/{book_id}/style/inbox/{item_id}/confirm", response_model=StyleInboxItemResponse)
async def confirm_style_inbox_item(
    book_id: UUID,
    item_id: UUID,
    override: Optional[StyleInboxConfirmRequest] = None,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
    style_repo: StyleCardRepository = Depends(get_style_card_repo),
    sample_repo: AuthorSampleRepository = Depends(get_author_sample_repo),
):
    """确认候选（✓）。negative_candidate → 写入书级文风卡负面清单；
    sample_candidate → 存入作者样本库（自动向量化）。

    可选请求体 {word?, alternative?}：确认前就地编辑词块的覆盖值
    （Phase 3，前端收件箱契约）；空 body（旧调用方）行为不变。
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
        word, alternative, severity = _resolve_negative_confirm(item.payload, override)
        card = await style_repo.get_effective_card(book_id, chapter_id=None)
        if card is None:
            from backend.models import StyleCard as StyleCardModel
            card = StyleCardModel(book_id=book_id, negative_list=[])
            db.add(card)
        negative = list(card.negative_list or [])
        if not any((e.get("word") if isinstance(e, dict) else "") == word for e in negative):
            negative.append({"word": word, "alternative": alternative, "severity": severity})
            card.negative_list = negative
        # 双写收敛（任务包 B）：不再同步 book.style_blacklist（历史书级黑名单已
        # 启动迁移并入 negative_list，该列冻结只读）；负面清单是唯一权威。
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
    bare=True = 裸奔基线（验枪靶场栏①）：画像与样本全跳过，只留系统基座，
    演示通用模型的塑料味——与 styled 轨的差值即「字帖+规矩」的纯收益。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    if request.bare:
        style_positive = ""
    elif request.style_override is not None:
        style_positive = render_style_positive(request.style_override)
    else:
        # Phase 4：章级编辑态的 baseline 取该章生效卡（章级特例整卡覆盖）
        card = await style_repo.get_effective_card(book_id, chapter_id=request.chapter_id)
        style_positive = render_style_positive(card)

    author_samples: List[str] = []
    if request.use_samples and not request.bare:
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
        # 剥 HTML（2026-09-04 审计修复）：content_text 是编辑器 HTML，此前直接
        # 进扫描——word_count 是 HTML 长度、标签打断词边界漏报、occurrences
        # 偏移锚在 HTML 串上。与同文件指纹/负面命中/收编同一把尺子。
        text = html_to_plain(chapter.content_text or chapter.draft_text or "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="待扫描文本为空")

    # Phase 4：扫描章级正文时禁忌面取该章生效卡（章级特例整卡覆盖）
    card = await style_repo.get_effective_card(book_id, chapter_id=request.chapter_id)

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
# 三平面分权·呈现平面配套（2026-08-29，docs/style-paradigm.md）
# ============================================================

class WashPreferOriginalRequest(BaseModel):
    pattern: str


@router.post("/books/{book_id}/style/wash-prefer-original", status_code=204)
async def wash_prefer_original(
    book_id: UUID,
    payload: WashPreferOriginalRequest,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """可逆学习（P1 配套铁律 3）：作者查看原稿后仍用原稿 = 一次肯定胜过三次
    否定——该禁忌从硬禁降为提醒（洗层此后对该词只提示不动手）。

    处置分两路：负面清单里的条目直接 severity 降级（作者自己标的，作者自己
    撤）；不在负面清单（系统陈词层来的 blocker）→ 加本书豁免
    （books.style_cliche_exemptions，与系统陈词豁免同一机制）。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    pattern = (payload.pattern or "").strip()
    if not pattern:
        return

    demoted_in_list = False
    try:
        from backend.repositories import StyleCardRepository
        card = await StyleCardRepository(db).get_book_card(book_id)
        if card is not None:
            negative = list(card.negative_list or [])
            changed = False
            for item in negative:
                if isinstance(item, dict) and item.get("word") == pattern and item.get("severity") == "blocker":
                    item["severity"] = "warning"
                    changed = True
            if changed:
                card.negative_list = negative
                await db.commit()
                demoted_in_list = True
    except Exception as e:
        logger.warning(f"[StyleWash] 负面清单降级失败: {e}")

    if not demoted_in_list:
        # 系统层 blocker → 本书豁免（作者明示保留该词）
        try:
            exemptions = list(book.style_cliche_exemptions or [])
            if pattern not in exemptions:
                exemptions.append(pattern)
                book.style_cliche_exemptions = exemptions
                await db.commit()
                invalidate_cliche_cache()
        except Exception as e:
            logger.warning(f"[StyleWash] 豁免写入失败: {e}")

    _append_style_event(str(book_id), "wash_prefer_original", pattern)


@router.get("/books/{book_id}/style/adopted-ghosts")
async def list_adopted_ghosts(
    book_id: UUID,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """P5 采纳幽灵收编池：作者采纳过的幽灵草稿（带正文者），文风页「收为
    样本」用。红线：候选不直接生效——作者确认才入库（收编走既有 samples
    创建端点，source=adopted_ghost，装配时 AI 来源样本每批 ≤1 防自蒸馏）。

    数据源：本地 collab_events.jsonl 的 ghost_adopt 事件（detail.text 由
    前端在采纳时携带）。近 30 条、正文去重、每条 ≤400 字。
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    import json as _json
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[3]
    path = root / "data" / "collab_events.jsonl"
    out = []
    seen_text = set()
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                for line in reversed(path.read_text(encoding="utf-8").splitlines() or []):
                    try:
                        ev = _json.loads(line)
                    except Exception:
                        continue
                    if ev.get("kind") != "ghost_adopt" or ev.get("book_id") != str(book_id):
                        continue
                    detail = ev.get("detail") or {}
                    text = str(detail.get("text") or "").strip()
                    if not text or text in seen_text:
                        continue
                    seen_text.add(text)
                    out.append({
                        "ts": ev.get("ts", ""),
                        "source": detail.get("source") or "",
                        "wash_hits": int(detail.get("wash_hits") or 0),
                        "text": text[:400],
                    })
                    if len(out) >= 30:
                        break
    except Exception as e:
        logger.debug(f"[StyleWash] 采纳池读取失败: {e}")
    return out

