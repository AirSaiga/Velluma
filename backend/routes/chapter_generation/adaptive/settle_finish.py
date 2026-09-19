# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：settle / finish / model / fix-sentence / reader-feedback。

沉淀（Ctrl+Enter 倒灌）、完稿审计（现实校验/记忆索引/语义扫描/质感候选）、
残句定点修复与读者反馈同属「完稿闭环」，共享章级 recorder 与配额状态。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.database import AsyncSessionLocal
from backend.models import Chapter
from backend.services.adaptive.observing import (
    bind_adaptive_trace,
    flush_adaptive_records,
    get_adaptive_recorder,
)
from backend.services.adaptive.orchestrator import get_orchestrator
from backend.services.adaptive.world_model import WorldModelRepository
from backend.services.context.knowledge_plane import build_knowledge_view
from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.observability.run_trace import trace_event
from backend.services.utils.logging import get_runtime_logger

# 心跳侧共享态：收件箱计数缓存（settle/finish 落新候选时主动失效）
from .heartbeat import _WORLD_INBOX_CACHE, _pending_candidates_count
from .schemas import FixSentenceRequest, SettleRequest

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# 端点 2：settle — 段落锁死 + 沉淀倒灌
# ============================================================

@router.post("/{chapter_id}/adaptive/settle")
async def settle(
    chapter_id: str,
    request: SettleRequest,
    db: AsyncSession = Depends(get_db),
):
    """段落锁死 → 层1追加 + 异步触发沉淀组件（抽涌现实体 + 冲突检测）。"""
    bind_adaptive_trace(chapter_id)
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    result = await orch.on_settle(request.text, request.entities, commit=request.commit)
    # settle 落新候选 → 失效心跳积压缓存（下轮心跳拿到新计数）
    try:
        chapter = await db.get(Chapter, str(chapter_id))
        if chapter is not None:
            _WORLD_INBOX_CACHE.pop(str(chapter.book_id), None)
    except Exception:
        pass
    trace_event(
        "adaptive_settle",
        words=len(request.text),
        commit=request.commit,
        emergent_facts=len((result.get("emergent_facts") or {})),
        candidates_created=result.get("candidates_created", 0),
    )
    await flush_adaptive_records(chapter_id)
    return result

# ============================================================
# 端点 3：finish — 作者完稿 → 后处理
# ============================================================

@router.post("/{chapter_id}/adaptive/finish")
async def finish(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """作者完稿 → 异步触发后处理（审计/一致性/残句/章节卡覆盖）+ 章级记忆索引。"""
    bind_adaptive_trace(chapter_id)
    _SENTENCE_FIX_COUNT.pop(chapter_id, None)  # 新一轮审计 → 残句修复上限重置
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    result = await orch.on_finish()

    # B5 现实校验（不变量 10：失败即失效不沉默）：知识视图的生死论断回查
    # fresh fold——mismatches 非空 = 缓存过期/派生物说谎的直接证据，进报告
    # Phase D 盘活（2026-09-12）：补传场景钉 scene_location_id——激活
    # present_wrong_loc 分支（在场者位置 vs 场景钉对照，此前恒不触发）
    _kg = None
    try:
        from backend.services.world.reality_check import run_reality_check

        _bundle = await load_chapter_settings_bundle(chapter_id, db)
        _kg = build_knowledge_view(_bundle)
        _ch_rc = await db.get(Chapter, chapter_id)
        result["reality_check"] = await run_reality_check(
            db, _bundle.book_id, _bundle.world_time, _kg,
            scene_location_id=str(getattr(_ch_rc, "scene_location_id", None) or "") if _ch_rc else "",
        )
    except Exception as e:
        logger.debug(f"[adaptive/finish] 现实校验失败（不阻塞完稿）: {e}")

    # B9 认知浮现三时机（完稿时机）：总开关开且数据存在才浮现——可见性
    # 悖论纪律（认知模型默认不可见，docs/world-kernel-foundation.md §8）
    try:
        from backend.services.world.negative_space import dramatic_capital, irony_opportunities

        _ch = await db.get(Chapter, chapter_id)
        _bid = str(_ch.book_id) if _ch else ""
        _t = (getattr(_ch, "narrative_time", None) or 0) if _ch else 0
        from backend.models import Book as _Book2

        _book = await db.get(_Book2, _bid) if _bid else None
        if _book is None or bool(getattr(_book, "cognition_surfacing", True)):
            # Phase D 盘活（2026-09-12）：反讽机会补传在场实体集（此前恒空集——
            # belief 域对空视角一律 UNKNOWN，所有读者已知命题全被计成反讽机会，
            # docstring 的「在场者不知道」语义名存实亡）
            _perspectives = list(getattr(_kg, "present_entity_ids", None) or []) if _kg is not None else []
            result["cognition_surface"] = {
                "irony": await irony_opportunities(db, _bid, _t, _perspectives),
                "capital_count": len(await dramatic_capital(db, _bid, t=_t)),
            }
    except Exception as e:
        logger.debug(f"[adaptive/finish] 认知面聚合失败（不阻塞完稿）: {e}")

    # ---- 记忆倒灌（写入侧）：完稿 = 章级定稿时刻，整章重索引（章级替换，幂等）----
    # 画布即事实源：索引正文取 chapters.content_text；失败绝不让完稿失败
    memory_indexed = 0
    try:
        from backend.services.rag.memory_indexing import index_chapter_memories
        bundle = await load_chapter_settings_bundle(chapter_id, db)
        if bundle.book_id and bundle.content_text:
            memory_indexed = await index_chapter_memories(
                db,
                book_id=bundle.book_id,
                chapter_id=chapter_id,
                chapter_number=bundle.chapter_number,
                text=bundle.content_text,
            )
    except Exception as e:
        logger.warning(f"[adaptive/finish] 记忆索引失败（不影响完稿结果）: {e}")

    if isinstance(result, dict):
        result["memory_indexed"] = memory_indexed

    # ---- D 包语义扫描：embedding 相似度抓「换字逃逸」变体（疑似 AI 味）----
    # 精确匹配（prohibitions.finditer）抓不到改写变体，这里用语义相似度补位。
    # 红线：只进报告由作者裁决；未配置 embedding（SQLite 默认恒未配置）/
    # 零命中不设键（响应增量最小）；不进收件箱、不进 scan-negative、
    # 不进任何 SSE 流式路径；任何失败仅 log，绝不阻塞完稿。
    semantic_hits: List[Dict] = []
    try:
        from backend.models import Book
        from backend.repositories import StyleCardRepository
        from backend.services.utils.html_text import html_to_plain
        from backend.services.style.prohibitions import ProhibitionSet, load_prohibition_set
        from backend.services.style.semantic_match import semantic_scan_text
        from backend.services.style.texture_contracts import texture_enforcement_entries

        chapter = await db.get(Chapter, str(chapter_id))
        if chapter is not None:
            book = await db.get(Book, str(chapter.book_id))
            # Phase 4：语义扫描禁忌面取生效卡（章级特例整卡覆盖，回退书级）
            ps = await load_prohibition_set(
                db, book=book,
                style_card=await StyleCardRepository(db).get_effective_card(
                    chapter.book_id, chapter.id,
                ),
            )
            # 质感契约执法词表旁路合并（2026-09 收编批，与 stitch 洗层同口径）：
            # 完稿审计的语义扫描同样覆盖病灶词——系统护栏本书无配置也生效。
            _tex = texture_enforcement_entries()
            if _tex:
                _base = ps.entries if ps is not None else ()
                ps = ProhibitionSet(tuple(_base) + _tex)
            content = html_to_plain(chapter.content_text or "")
            semantic_hits = await semantic_scan_text(content, ps)
    except Exception as e:
        logger.warning(f"[adaptive/finish] 语义扫描失败（不影响完稿结果）: {e}")
    if semantic_hits and isinstance(result, dict):
        result["semantic_hits"] = semantic_hits

    # ---- 质感样本候选（2026-09-03 质感批次第四层）：完稿=章节定稿时刻，
    # 挑「本章最会停下来细写的一段」进文风收件箱（sample_candidate，作者
    # ✓ 裁决才入样本库——候选不直接生效，红线同 💛 黄金片段/事件候选池）。
    # 去重纪律：同书收件箱已有同文候选（任何状态——作者忽略过的不重投）
    # 即跳过。挂在 finish 而非 settle：settle 高频会刷屏，完稿与记忆重索引
    # 同机位。任何失败仅 log，绝不阻塞完稿。
    texture_candidate: Optional[Dict] = None
    try:
        from backend.models import StyleInboxItem
        from backend.services.utils.html_text import html_to_plain
        from backend.services.style.fingerprint import most_textured_window
        from backend.services.style.scene_hint import detect_scene_type

        _ch2 = await db.get(Chapter, str(chapter_id))
        _plain = html_to_plain(_ch2.content_text or "") if _ch2 is not None else ""
        win = most_textured_window(_plain) if _plain else None
        if win and _ch2 is not None:
            _existing = (await db.execute(
                select(StyleInboxItem).where(
                    StyleInboxItem.book_id == _ch2.book_id,
                    StyleInboxItem.kind == "sample_candidate",
                )
            )).scalars().all()
            _head = win["text"][:60]
            if not any(
                str((i.payload or {}).get("content") or "")[:60] == _head
                for i in _existing
            ):
                db.add(StyleInboxItem(
                    book_id=_ch2.book_id,
                    kind="sample_candidate",
                    payload={
                        "content": win["text"],
                        "scene_type": detect_scene_type(win["text"]) or "general",
                        "density_per_1k": win["density_per_1k"],
                        "chapter_id": str(chapter_id),
                        "note": (
                            f"第{_ch2.chapter_number}章里质感最密的一段"
                            f"（{win['density_per_1k']}/千词）——若这正是「你的字」"
                            f"最好的样子，确认后收进样本库"
                        ),
                    },
                    source="texture_pick",
                ))
                await db.commit()
                texture_candidate = {
                    "density_per_1k": win["density_per_1k"],
                    "chars": len(win["text"]),
                }
    except Exception as e:
        logger.warning(f"[adaptive/finish] 质感样本候选失败（不影响完稿结果）: {e}")
    if texture_candidate and isinstance(result, dict):
        result["texture_sample_candidate"] = texture_candidate

    # ---- A5c①：完稿报告附收件箱积压计数（book 级 pending；失败 0 不阻塞完稿）----
    # 与 candidates_created/memory_indexed 同层（响应顶层）——报告区「收件箱」块消费；
    # 完稿整章抽取刚落过候选，顺路失效心跳积压缓存让下轮心跳拿到新计数
    candidates_pending = 0
    try:
        chapter = await db.get(Chapter, str(chapter_id))
        if chapter is not None:
            candidates_pending = await _pending_candidates_count(db, str(chapter.book_id))
            _WORLD_INBOX_CACHE.pop(str(chapter.book_id), None)
    except Exception as e:
        logger.debug(f"[adaptive/finish] 收件箱计数失败（不影响完稿结果）: {e}")
    if isinstance(result, dict):
        result["candidates_pending"] = candidates_pending

    # ---- 读者清单（01 开章卡与读者清单 M2）：真相层折出的「读者此刻」三段清单 ----
    # 纯章号算术零 LLM；沿用报告区既有模式——try/except 不阻塞完稿、零命中不设键
    # （响应增量最小，docs/next-phase/01-opening-card-and-reader-ledger.md §3）
    try:
        from backend.services.world.reader_ledger import load_reader_ledger

        _ch_rl = await db.get(Chapter, str(chapter_id))
        if _ch_rl is not None and _ch_rl.chapter_number:
            _ledger = await load_reader_ledger(db, str(_ch_rl.book_id), int(_ch_rl.chapter_number))
            if _ledger:
                result["reader_ledger"] = _ledger
    except Exception as e:
        logger.debug(f"[adaptive/finish] 读者清单聚合失败（不影响完稿结果）: {e}")

    trace_event(
        "adaptive_finish",
        finished=result.get("finished", False) if isinstance(result, dict) else False,
        memory_indexed=memory_indexed,
        candidates_created=result.get("candidates_created", 0) if isinstance(result, dict) else 0,
        candidates_pending=candidates_pending,
        semantic_hits=len(semantic_hits),
        texture_candidate=int(texture_candidate is not None),
        texture_density=(texture_candidate or {}).get("density_per_1k"),
    )
    await flush_adaptive_records(chapter_id)
    return result


# ============================================================
# 端点 4：model — 拉取世界模型快照
# ============================================================

@router.get("/{chapter_id}/adaptive/model")
async def get_model(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """拉取世界模型快照（前端恢复/调试用）。"""
    repo = WorldModelRepository(db)
    snapshot = await repo.snapshot(chapter_id)
    # P3-1（C5）：快照附带最近失败组件（副驾「AI 视角」调试区消费；空 dict 零变化，
    # 与心跳响应同源——per-orchestrator 内存态，进程重启自然归零）
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    snapshot["last_component_errors"] = orch.last_component_errors()
    return snapshot

# ============================================================
# 端点 5.5：fix-sentence — 残句定点修复（审校闭环 P1.2，作者裁决式）
# ============================================================
# 红线：只产修复句，**不改正文**——采纳与否由前端作者裁决（作者裁决即闸门，
# 不引入自动改稿）。1×creative + REASONING_DISABLED + max_tokens=1600 +
# 安全网（still_defective/length_out_of_bounds/name_dropped），与 BS-ADF
# Phase 7.5 同参数同代码路径（services/workflows/sentence_integrity.py）。
# 上限：每轮审计后每章最多修 5 处（沿 Phase 7.5 成本上限）；finish 重置计数。
# ============================================================

_SENTENCE_FIX_CAP = 5
_SENTENCE_FIX_COUNT: Dict[str, int] = {}  # chapter_id → 本轮已修复数（finish 时重置）

@router.post("/{chapter_id}/adaptive/fix-sentence")
async def fix_sentence(
    chapter_id: str,
    request: FixSentenceRequest,
    db: AsyncSession = Depends(get_db),
):
    """残句定点修复：返回修复句供作者过目，正文不动。"""
    bind_adaptive_trace(chapter_id)
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if _SENTENCE_FIX_COUNT.get(chapter_id, 0) >= _SENTENCE_FIX_CAP:
        raise HTTPException(status_code=429, detail="本章修复已达上限（5 处），重新完稿审计后可继续")

    sentence = request.sentence.strip()
    # 画布即事实源：完稿审计对象 = 画布剥 HTML 全文（post_process._get_full_text），
    # 匹配与修复上下文同口径走 written_text——含内联标签/跨段的句子在原始 HTML
    # 里未必子串命中；层 1 事实不再兜底（作者删改后过期，曾致两源不一致假阳性）
    from backend.services.adaptive.paragraph_source import written_text
    content = written_text(chapter.content_text or "")
    if not sentence or sentence not in content:
        raise HTTPException(status_code=409, detail="未在当前正文找到该句（正文可能已改动，请重新审计）")

    from backend.services.workflows.sentence_integrity import repair_single_defect
    defect = {
        "sentence": sentence,
        "type": request.defect_type or "unknown",
        "description": request.description or "",
    }
    fixed, reason = await repair_single_defect(
        defect, content, recorder=get_adaptive_recorder(chapter_id),
    )
    trace_event("adaptive_fix_sentence", ok=fixed is not None, reason=reason, defect_type=defect["type"])
    await flush_adaptive_records(chapter_id)
    if fixed is None:
        return {"fixed": None, "reason": reason}
    _SENTENCE_FIX_COUNT[chapter_id] = _SENTENCE_FIX_COUNT.get(chapter_id, 0) + 1
    return {"fixed": fixed, "reason": "ok"}


@router.post("/{chapter_id}/adaptive/reader-feedback")
async def reader_feedback(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """读者反馈：AI 扮演读者写叙述性读感（1 次 reasoning LLM）。

    完稿体检报告内的**按需独立触发**卡片（Phase 0 拍板：不串行塞入 finish
    主链——推理槽实测均值 ~17.6s，串行会把体检拖到 60s+）。正文口径与
    finish/fix-sentence 同源（画布剥 HTML）；反馈文本不落库，只有 LLM 用量
    进章级 recorder（stage=adaptive.reader_feedback）。
    """
    bind_adaptive_trace(chapter_id)
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    from backend.services.adaptive.components.reader_feedback import (
        generate_reader_feedback,
    )
    from backend.services.adaptive.paragraph_source import written_text

    full_text = written_text(chapter.content_text or "")
    if len(full_text) < 200:
        raise HTTPException(status_code=422, detail="正文不足 200 字，先写一段再来听读者怎么说")

    result = await generate_reader_feedback(
        full_text=full_text,
        chapter_number=int(getattr(chapter, "chapter_number", 0) or 0) or 1,
        purpose=str(getattr(chapter, "outline_text", "") or "")[:300],
        recorder=get_adaptive_recorder(chapter_id),
    )
    trace_event(
        "adaptive_reader_feedback",
        chars=result.get("word_count", 0),
        error=bool(result.get("error")),
    )
    await flush_adaptive_records(chapter_id)
    return {
        "chapter_id": chapter_id,
        "feedback": result.get("feedback", ""),
        "word_count": result.get("word_count", 0),
        "error": result.get("error"),
    }
