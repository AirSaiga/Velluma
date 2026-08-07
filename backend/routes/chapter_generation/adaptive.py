# Velluma - NLE-ADF 3.0 自适应辅助路由
# AGPL-3.0
"""
作者主导写作流程的自适应辅助端点（NLE-ADF 3.0）。

核心协议：心跳模式。前端防抖发 heartbeat（作者状态），后端调度器决定激活
哪些组件（意图反推/未来推测/挂件生发/沉淀/后处理），异步跑、写回世界模型。
前端下次心跳拿到组件产出（挂件/建议）。

端点：
- POST /adaptive/heartbeat：作者状态心跳 → 触发调度器 → 返回快照 + 挂件
- POST /adaptive/settle：段落锁死 → 层1追加 + 沉淀倒灌
- POST /adaptive/finish：作者完稿 → 后处理审计
- GET  /adaptive/model/{id}：拉取世界模型快照（恢复/调试用）
- POST /adaptive/stitch-ghost：微缝合（SSE，按需触发，不变）

设定数据来源：services.context.settings_bundle（分级访问 hard/soft/nutrients）。
副作用：settle 写设定库（可选）；heartbeat 触发异步组件（写世界模型）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.core.dependencies import get_db
from backend.database import AsyncSessionLocal
from backend.services.adaptive.orchestrator import get_orchestrator
from backend.services.adaptive.change_detector import AuthorState
from backend.services.adaptive.world_model import WorldModelRepository
from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.prompts.adaptive_prompts import build_continue_prompt
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import build_sse_event, build_sse_error

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# Schemas
# ============================================================

class HeartbeatRequest(BaseModel):
    word_count: int = 0
    segment_count: int = 0
    paused_ms: int = 0
    cursor_at_paragraph_end: bool = False
    has_outline: bool = False
    outline_text: str = ""
    recent_text: str = Field("", description="当前段落尾部（≤500字）")


class HeartbeatResponse(BaseModel):
    dock_parts: List[Dict] = Field(default_factory=list)
    intent_source: str = "none"
    intent_arc: str = ""
    intent_confidence: float = 0.0
    fact_count: int = 0
    total_words: int = 0
    activated: List[str] = Field(default_factory=list)
    signals: List[str] = Field(default_factory=list)


class SettleRequest(BaseModel):
    text: str = Field(..., description="锁死的段落正文")
    entities: List[Dict] = Field(default_factory=list, description="本段涌现的实体（前端可预填）")
    commit: bool = Field(False, description="是否落库涌现实体")


class StitchGhostRequest(BaseModel):
    fragment: str = Field(..., description="作者原句碎片")
    rolling_prefix: str = Field("")
    mode: str = Field("stitch", description="stitch|continue")
    picked_parts: List[str] = Field(default_factory=list)
    target_chars: int = Field(120)
    chapter_intent: str = Field("")
    adopted_direction: Optional[str] = Field(None, description="作者缝合采纳的叙事方向（主线/伏笔/刻画/环境/关系），用于负反馈降权")


# ============================================================
# 端点 1：heartbeat — 作者状态心跳
# ============================================================

@router.post("/{chapter_id}/adaptive/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    chapter_id: str,
    request: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    """作者状态心跳 → 触发调度器（异步激活组件）→ 返回当前快照 + 挂件。

    前端防抖 2-4s 发一次。后端不阻塞——组件异步跑，下次心跳拿到产出。
    """
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    state = AuthorState(
        chapter_id=chapter_id,
        word_count=request.word_count,
        segment_count=request.segment_count,
        paused_ms=request.paused_ms,
        cursor_at_paragraph_end=request.cursor_at_paragraph_end,
        has_outline=request.has_outline,
        outline_text=request.outline_text,
        recent_text=request.recent_text,
    )
    result = await orch.on_heartbeat(state)
    snapshot = result.get("snapshot", {})

    # 从世界模型拉挂件缓存（dock_generator 写入的 __dock__ 项）
    dock_parts = _extract_dock_parts(snapshot)

    intent = snapshot.get("intent", {})
    return HeartbeatResponse(
        dock_parts=dock_parts,
        intent_source=intent.get("source", "none"),
        intent_arc=intent.get("arc", ""),
        intent_confidence=intent.get("confidence", 0.0),
        fact_count=snapshot.get("fact_count", 0),
        total_words=snapshot.get("total_words", 0),
        activated=result.get("activated", []),
        signals=result.get("signals", []),
    )


def _extract_dock_parts(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 dock_generator 缓存的挂件。"""
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__dock__"):
            return proj.get("parts", [])
    return []


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
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    result = await orch.on_settle(request.text, request.entities, commit=request.commit)
    return result


# ============================================================
# 端点 3：finish — 作者完稿 → 后处理
# ============================================================

@router.post("/{chapter_id}/adaptive/finish")
async def finish(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """作者完稿 → 异步触发后处理（审计/一致性/残句/章节卡覆盖）。"""
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    return await orch.on_finish()


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
    return await repo.snapshot(chapter_id)


# ============================================================
# 端点 5：stitch-ghost — 微缝合（SSE，保留不变）
# ============================================================

@router.post("/{chapter_id}/adaptive/stitch-ghost")
async def stitch_ghost(
    chapter_id: str,
    request: StitchGhostRequest,
    db: AsyncSession = Depends(get_db),
):
    """续写/缝合幽灵草稿，SSE 打字机推流。不依赖 run_id（自由路径）。"""
    # 方向采纳回报：作者缝合了某方向的碎片 → 通知调度器降权（负反馈）
    if request.adopted_direction:
        orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
        orch.on_direction_adopted(request.adopted_direction)

    bundle = await load_chapter_settings_bundle(chapter_id, db)
    proper_nouns = bundle.proper_nouns()
    chapter_intent = request.chapter_intent or bundle.outline_text[:200]

    system_prompt, user_prompt = build_continue_prompt(
        fragment=request.fragment.strip(),
        rolling_prefix=(request.rolling_prefix or "")[-200:].strip(),
        mode=request.mode,
        picked_parts=request.picked_parts,
        proper_nouns=proper_nouns,
        canon_context=bundle.canon_context,
        target_chars=request.target_chars,
        chapter_intent=chapter_intent,
    )

    async def _stream():
        try:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                max_tokens=min(800, request.target_chars * 2),
                reasoning_config=REASONING_DISABLED,
            )
            text = (result.content or "").strip().strip('"').strip('"').strip()
            if not text:
                yield build_sse_error("续写产出为空，请重试")
                return
            fragment = request.fragment.strip()
            if request.mode == "stitch" and fragment and fragment not in text:
                text = f"{fragment}{text}"
            yield build_sse_event("GHOST_START", "", mode=request.mode)
            chunk_size = 6
            for pos in range(0, len(text), chunk_size):
                yield build_sse_event("GHOST_CHUNK", "", delta=text[pos: pos + chunk_size])
                await asyncio.sleep(0.09)
            yield build_sse_event("GHOST_DONE", "", text=text, word_count=len(text))
        except Exception as e:
            logger.warning(f"[adaptive/stitch-ghost] 失败: {e}")
            yield build_sse_error(f"续写失败: {e}")

    return StreamingResponse(_stream(), media_type="text/event-stream")
