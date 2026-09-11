# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：spine —— 章级谋篇软脉络（GET/PATCH + spine-suggest，chapters.spine JSONB）。

度优先：意图一句话可空、锚点硬上限 5、AI 建议不落库（D-4 预填红线）、
无脉络的书一切 UI 静默缺席（D-3）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.services.adaptive.observing import (
    bind_adaptive_trace,
    flush_adaptive_records,
    get_adaptive_recorder,
)
from backend.services.context.budget import SPINE_SUGGEST_MAX_TOKENS
from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.observability.run_trace import trace_event
from backend.services.utils.logging import get_runtime_logger

from .schemas import SpineAnchor, SpineUpdateRequest

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# 端点 5.6：spine — 章级谋篇软脉络（P1.4 M1，docs/chapter-planning-spine.md）
# ============================================================
# 度优先（设计稿第一原则）：意图一句话可空、锚点硬上限 5、AI 建议不落库（D-4
# 预填红线）、无脉络的书一切 UI 静默缺席（D-3）。轻量存取——不进正文版本
# 历史、不触发 world-refresh。
# ============================================================

SPINE_MAX_ANCHORS = 5
SPINE_ANCHOR_TEXT_MIN = 2
SPINE_ANCHOR_TEXT_MAX = 12   # 锚点是短语不是句子（D-5 防膨胀成第二大纲）
SPINE_INTENT_TEXT_MAX = 60


def _normalize_branch(branch: Optional[Dict]) -> Optional[Dict]:
    """岔路标记校验（M3）：2-3 个走向短语（2-12 字），非法整个丢弃（宁缺勿脏）。"""
    if not isinstance(branch, dict):
        return None
    options = []
    for o in (branch.get("options") or [])[:3]:
        t = str(o or "").strip()[:SPINE_ANCHOR_TEXT_MAX]
        if len(t) >= SPINE_ANCHOR_TEXT_MIN:
            options.append(t)
    if len(options) < 2:
        return None
    return {"options": options}


def _normalize_spine(current: Optional[Dict], req: SpineUpdateRequest) -> Dict:
    """合并校验：None 字段保持原值；锚点数/长度硬校验（422 带人话劝阻文案）。"""
    spine = dict(current or {})
    if req.intent is not None:
        text = str(req.intent.get("text", "") or "").strip()[:SPINE_INTENT_TEXT_MAX]
        spine["intent"] = {"text": text, "source": req.intent.get("source") or "author"}
    if req.anchors is not None:
        anchors = []
        for i, a in enumerate(req.anchors):
            text = a.text.strip()
            if len(text) < SPINE_ANCHOR_TEXT_MIN:
                raise HTTPException(422, detail=f"「{text or '（空）'}」太短——每条情节用 2-12 个字记个意思就行，细节请留给大纲")
            if len(text) > SPINE_ANCHOR_TEXT_MAX:
                raise HTTPException(422, detail=f"「{text[:12]}…」超过 12 字——这里只记个意思，展开请写进大纲")
            anchors.append({
                "id": a.id or f"a{i + 1}",
                "text": text,
                "source": a.source if a.source in ("author", "ai") else "author",
                "status": a.status if a.status in ("pending", "hit", "dropped") else "pending",
                **({"branch": _normalize_branch(a.branch)} if a.branch else {}),
            })
        if len(anchors) > SPINE_MAX_ANCHORS:
            raise HTTPException(422, detail=f"情节超过 {SPINE_MAX_ANCHORS} 条——说明在写大纲了。细节留给大纲，这里只记最要紧的")
        spine["anchors"] = anchors
    return spine


async def _spine_anchor_rows_for_prompt(chapter_id: str, db: AsyncSession) -> List[dict]:
    """outline 档 stitch-ghost 的 spine 锚点行数据源（C3 · docs/foundation-hardening.md §5.3）。

    从 chapter.spine（JSONB，字段口径同 _normalize_spine：{intent, anchors}）
    抽 [{text, status}] 供 build_outline_expand_prompt 渲染全锚点行——胶囊
    扩写不只看到自己挂的单锚（serves_anchor），还有全章谋篇盘面（含兑现
    状态）。builder 侧再滤 dropped、截 STITCH_OUTLINE_SPINE_ANCHORS_MAX；
    无脉络/章节不存在/读取失败 → 空列表（锚点行缺席，prompt 逐字节零变化）。
    纯读无写，不触发 world-refresh。
    """
    try:
        chapter = await db.get(Chapter, str(chapter_id))
        spine = chapter.spine if chapter is not None else None
        if not isinstance(spine, dict):
            return []
        rows: List[dict] = []
        for a in (spine.get("anchors") or []):
            if isinstance(a, dict) and str(a.get("text") or "").strip():
                rows.append({
                    "text": str(a["text"]).strip(),
                    "status": str(a.get("status") or "").strip() or "pending",
                })
        return rows
    except Exception as e:
        logger.debug(f"[adaptive/stitch-ghost] spine 锚点读取失败（行缺席）: {e}")
        return []


@router.get("/{chapter_id}/adaptive/spine")
async def get_spine(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """读软脉络（NULL → {"spine": null}，前端据此静默缺席）。"""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"spine": chapter.spine}


@router.patch("/{chapter_id}/adaptive/spine")
async def patch_spine(
    chapter_id: str,
    request: SpineUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """存软脉络（部分合并：只改传了的字段）。"""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    spine = _normalize_spine(chapter.spine, request)
    if not spine.get("intent", {}).get("text") and not spine.get("anchors"):
        spine = None  # 全空 = 无脉络（静默缺席契约）
    chapter.spine = spine
    await db.commit()
    trace_event(
        "adaptive_spine_saved",
        has_intent=bool(spine and spine.get("intent", {}).get("text")),
        anchors=len((spine or {}).get("anchors", [])),
    )
    return {"spine": spine}


@router.post("/{chapter_id}/adaptive/spine-suggest")
async def spine_suggest(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """AI 谋篇建议（1×creative）——**不落库**（D-4：建议只在作者收下/编辑后才入库）。"""
    bind_adaptive_trace(chapter_id)
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    soft = bundle.soft_constraints()

    # 上一章未兑现锚点（作者上章想写没写到的，建议可顺延）
    prev_pending: List[str] = []
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            prev_result = await db.execute(
                select(Chapter)
                .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number < chapter.chapter_number)
                .order_by(Chapter.chapter_number.desc())
                .limit(1)
            )
            prev = prev_result.scalar_one_or_none()
            if prev is not None and isinstance(prev.spine, dict):
                prev_pending = [
                    a.get("text", "") for a in prev.spine.get("anchors", [])
                    if isinstance(a, dict) and a.get("status") == "pending" and a.get("text")
                ]
    except Exception:
        prev_pending = []

    from backend.services.prompts.adaptive_prompts import build_spine_suggest_prompt
    sys_p, usr_p = build_spine_suggest_prompt(
        outline_text=bundle.outline_text or "",
        open_hooks=str(soft.get("open_hooks") or ""),
        canon_context=bundle.canon_context or "",
        worldview_text=bundle.worldview_text or "",
        prev_pending_anchors=prev_pending,
        previous_summary=bundle.previous_summary or "",
    )
    result = await call_llm_with_usage(
        system_prompt=sys_p, user_prompt=usr_p,
        # 谋篇建议要质量：走 creative 槽、保留默认 thinking（设计稿 §4.1）。
        # 预算提额（2026-08-25 实证：800 曾被 MiMo 隐藏思考烧光返回空，
        # finish=length——谋篇建议空输出是静默失败，作者只会看到「没建议」）
        model_type="creative", temperature=0.4, max_tokens=SPINE_SUGGEST_MAX_TOKENS,
    )
    get_adaptive_recorder(chapter_id).record_result("adaptive.spine_suggest", result, model_slot="creative")

    from backend.services.utils.json_safe import parse_json_safe
    parsed = parse_json_safe(result.content or "") or {}
    if not (parsed.get("intent") or parsed.get("anchors")):
        # 空输出兜底重试一次：关思考小预算再试（烧光预算型空输出的针对性解法）；
        # 还空就算了——建议本就柔性，空结果契约不变
        retry = await call_llm_with_usage(
            system_prompt=sys_p, user_prompt=usr_p,
            model_type="creative", temperature=0.4, max_tokens=800,
            reasoning_config=REASONING_DISABLED,
        )
        get_adaptive_recorder(chapter_id).record_result(
            "adaptive.spine_suggest.retry", retry, model_slot="creative")
        retry_parsed = parse_json_safe(retry.content or "") or {}
        if retry_parsed.get("intent") or retry_parsed.get("anchors"):
            parsed = retry_parsed
    intent = str(parsed.get("intent", "") or "").strip()[:SPINE_INTENT_TEXT_MAX]
    anchors = []
    for a in (parsed.get("anchors") or [])[:SPINE_MAX_ANCHORS]:
        text = str(a or "").strip()[:SPINE_ANCHOR_TEXT_MAX]
        if len(text) >= SPINE_ANCHOR_TEXT_MIN:
            anchors.append(text)
    trace_event("adaptive_spine_suggest", intent=bool(intent), anchors=len(anchors))
    await flush_adaptive_records(chapter_id)
    return {"intent": intent, "anchors": anchors}
