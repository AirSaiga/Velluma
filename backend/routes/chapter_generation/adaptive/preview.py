# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：context-preview —— AI 此刻所见注入预览（与 stitch-ghost 同源装配，不调 LLM）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.services.adaptive.paragraph_source import sentence_clean_tail
from backend.services.context.budget import (
    STITCH_ROLLING_LONG_MAX_CHARS,
    STITCH_ROLLING_SHORT_MAX_CHARS,
)
from backend.services.context.stitch_context import (
    assemble_stitch_context,
    build_context_preview,
)
from backend.services.utils.logging import get_runtime_logger

from .schemas import ContextPreviewResponse

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# AI 此刻所见预览（P5 B2，docs/foundation-hardening.md §2.1）：跑 stitch-ghost
# 全套上下文装配（与真实注入同源——共用 assemble_stitch_context +
# adaptive_prompts.render_system_blocks，禁止平行实现），**不调 LLM 文本生成**。
# ============================================================

_PREVIEW_MODES = ("stitch", "continue", "burst", "outline", "open")


@router.get(
    "/{chapter_id}/adaptive/context-preview",
    response_model=ContextPreviewResponse,
    response_model_exclude_none=True,  # A3b：trimmed 无裁剪时省略（其余字段均非 None）
)
async def context_preview(
    chapter_id: str,
    mode: str = "continue",
    db: AsyncSession = Depends(get_db),
):
    """AI 此刻所见预览：stitch-ghost 将注入的全部上下文块，按注入序返回。

    query 构造与 stitch 路由同口径——预览无作者碎片（fragment=""），
    rolling_prefix 取章节正文纯文本尾部（stitch 由前端送纯文本；这里从落库
    HTML 剥成纯文本，与 memory_indexing 同口径），assemble 内部仍按各模式
    统一截 [-150:] 拼 query。open 模式 query 走大纲（同 stitch）。
    """
    if mode not in _PREVIEW_MODES:
        raise HTTPException(422, detail=f"mode 仅支持 {'/'.join(_PREVIEW_MODES)}")

    # rolling_prefix = 章节正文尾部（剥 HTML；失败/无章退化为空串，open 模式不消费）
    # 句界净截与 stitch 路由同源（预览与注入同源红线，2026-08-25 调窗后同步；
    # 2026-09-04 修复：截窗 cap 补齐 mode-aware——此前预览对所有模式统一 LONG
    # 1200，stitch/continue 真实注入只有 SHORT 800，称呼表过滤/scene_hint 取材
    # 两端口径不一致，预览可能显示真实注入里被过滤掉的名字）
    rolling_prefix = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            from backend.services.rag.memory_indexing import _html_to_plain

            _preview_cap = (
                0 if mode == "open"
                else STITCH_ROLLING_LONG_MAX_CHARS if mode in ("outline", "burst")
                else STITCH_ROLLING_SHORT_MAX_CHARS
            )
            if _preview_cap:
                rolling_prefix = sentence_clean_tail(
                    _html_to_plain(chapter.content_text or ""), _preview_cap,
                )
    except Exception:
        rolling_prefix = ""

    ctx = await assemble_stitch_context(
        chapter_id=chapter_id,
        mode=mode,
        fragment="",
        rolling_prefix=rolling_prefix,
        db=db,
    )
    # 显式构造 response model：response_model 只在路由层做文档/序列化，直调
    # （单测/内部复用）也拿到结构化对象而非裸 dict
    return ContextPreviewResponse(**build_context_preview(ctx, mode))
