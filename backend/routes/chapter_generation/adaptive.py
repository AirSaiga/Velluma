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
from backend.services.prompts.adaptive_prompts import (
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
)
from backend.services.rag.recall import recall_memories
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import build_sse_event, build_sse_error

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# 细纲扩写字数硬闸门（对齐 bsadf/downgrade 的实测经验：软约束段均超写
# 近 2 倍。细纲的产品承诺是「生成字数不多、改起来轻」，必须硬保证。
# SSE 先生成后播放 → 压缩重试/截断对前端完全透明）
# ============================================================

OUTLINE_WC_HARD_RATIO = 1.6      # 超过 target×1.6 → 带压缩反馈重试一次
OUTLINE_WC_TRUNCATE_RATIO = 1.5  # 仍超 → 句界硬截断（截断上限必须 ≤ HARD）


def _truncate_at_sentence(text: str, limit: int) -> str:
    """句界硬截断：在 limit 内找最后一个句末标点切断。

    复制自 bsadf/downgrade._truncate_at_sentence（无依赖纯函数，刻意不
    import bsadf——adaptive 链路不依赖步进流任何设施）。找不到句末标点
    （极端长句）退化为按字截断：字数硬闸门优先级高于单句完整性。
    """
    if len(text) <= limit:
        return text
    cut = max(text.rfind(p, 0, limit) for p in ("。", "！", "？", "…"))
    if cut > 0:
        return text[: cut + 1]
    return text[:limit]


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
    direction_cards: List[Dict] = Field(default_factory=list)  # 走向卡（层3推测首 beat：event+anchors）
    intent_source: str = "none"
    intent_arc: str = ""
    intent_confidence: float = 0.0
    fact_count: int = 0
    total_words: int = 0
    activated: List[str] = Field(default_factory=list)
    signals: List[str] = Field(default_factory=list)
    canon_hints: List[Dict] = Field(default_factory=list)  # Canon 感知（角色出场/伏笔回收/private 泄露），canon_watch 写入


class SettleRequest(BaseModel):
    text: str = Field(..., description="锁死的段落正文")
    entities: List[Dict] = Field(default_factory=list, description="本段涌现的实体（前端可预填）")
    commit: bool = Field(False, description="是否落库涌现实体")


class StitchGhostRequest(BaseModel):
    fragment: str = Field(..., description="作者原句碎片（outline 模式=细纲速记原文）")
    rolling_prefix: str = Field("")
    mode: str = Field("stitch", description="stitch|continue|burst（段落级连写）|outline（细纲扩写）|open（点火）")
    picked_parts: List[str] = Field(default_factory=list)
    target_chars: int = Field(120)
    chapter_intent: str = Field("")
    beat_guidance: str = Field("", description="burst 模式：选定走向卡的走向文本（空=自由发挥）")
    after_text: str = Field("", description="outline 模式：细纲之后的已写正文开头（双端缝合用，可空）")
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
    # 走向卡（层 3 推测首 beat）——Ctrl+Space 走向卡舱的数据源
    direction_cards = _extract_direction_cards(snapshot)
    # Canon 感知（canon_watch 写入的 __canon_watch__ 项）
    canon_hints = _extract_canon_hints(snapshot)

    intent = snapshot.get("intent", {})
    return HeartbeatResponse(
        dock_parts=dock_parts,
        direction_cards=direction_cards,
        intent_source=intent.get("source", "none"),
        intent_arc=intent.get("arc", ""),
        intent_confidence=intent.get("confidence", 0.0),
        fact_count=snapshot.get("fact_count", 0),
        total_words=snapshot.get("total_words", 0),
        activated=result.get("activated", []),
        signals=result.get("signals", []),
        canon_hints=canon_hints,
    )


def _extract_dock_parts(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 dock_generator 缓存的挂件。"""
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__dock__"):
            return proj.get("parts", [])
    return []


def _extract_canon_hints(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 canon_watch 缓存的 Canon 感知 hints。"""
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__canon_watch__"):
            return proj.get("hints", [])
    return []


def _extract_direction_cards(snapshot: Dict) -> List[Dict]:
    """从层 3 推测提取走向卡（跳过 __dock__ 缓存项；每个推测取首个 beat）。

    走向卡 = {event, anchors}，一句话剧情走向，供 Ctrl+Space 走向卡舱选择。
    """
    cards: List[Dict] = []
    for proj in (snapshot.get("projections") or []):
        if not isinstance(proj, dict) or proj.get("__dock__"):
            continue
        for beat in (proj.get("possible_beats") or [])[:1]:
            event = (beat.get("event") or "").strip() if isinstance(beat, dict) else ""
            if event:
                cards.append({
                    "event": event[:60],
                    "anchors": [str(a)[:20] for a in (beat.get("anchors") or [])][:3],
                })
    return cards[:3]


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
    """作者完稿 → 异步触发后处理（审计/一致性/残句/章节卡覆盖）+ 章级记忆索引。"""
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    result = await orch.on_finish()

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

    # 前情召回（记忆倒灌·检索侧）：query = 当前写作上下文；open 模式无正文用大纲。
    # 降级为空列表时 prompt 零变化（不阻塞生成）
    if request.mode == "open":
        recall_query = bundle.outline_text[:200]
    else:
        recall_query = ((request.rolling_prefix or "")[-150:] + " " + request.fragment.strip()).strip()
    memory_echoes = await recall_memories(
        db,
        book_id=bundle.book_id or "",
        chapter_id=chapter_id,
        chapter_number=bundle.chapter_number,
        query_text=recall_query,
        k=3,
    )

    if request.mode == "open":
        # 点火（冷启动）：空章 + 大纲 → 开篇引子。大纲是唯一燃料，无已写正文
        system_prompt, user_prompt = build_opening_prompt(
            outline_text=bundle.outline_text[:800],
            previous_summary=bundle.previous_summary or "",
            worldview_text=bundle.worldview_text[:200] if bundle.worldview_text else "",
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            memory_echoes=memory_echoes,
        )
    elif request.mode == "outline":
        # 细纲扩写：作者亲笔速记 + 双端正文锚定 → 小段正文（前文承接 + 后文引向）
        system_prompt, user_prompt = build_outline_expand_prompt(
            outline_note=request.fragment.strip(),
            rolling_prefix=(request.rolling_prefix or "")[-500:].strip(),
            after_text=(request.after_text or "")[:300].strip(),
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
        )
    elif request.mode == "burst":
        # 段落级连写：走向卡驱动 + 更大衔接窗口 + 更快打字机节奏
        system_prompt, user_prompt = build_burst_prompt(
            fragment=request.fragment.strip(),
            rolling_prefix=(request.rolling_prefix or "")[-500:].strip(),
            beat_guidance=request.beat_guidance.strip(),
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
        )
    else:
        system_prompt, user_prompt = build_continue_prompt(
            fragment=request.fragment.strip(),
            rolling_prefix=(request.rolling_prefix or "")[-200:].strip(),
            mode=request.mode,
            picked_parts=request.picked_parts,
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
        )

    async def _stream():
        try:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                # 推理模型（deepseek-v4-pro）即使 REASONING_DISABLED 仍消耗 reasoning tokens（~800-1000），
                # max_tokens 必须给 reasoning 留够空间，否则产出为空
                max_tokens=max(1200, request.target_chars * 2 + 1000),
                reasoning_config=REASONING_DISABLED,
            )
            text = (result.content or "").strip().strip('"').strip('"').strip()
            if not text:
                yield build_sse_error("续写产出为空，请重试")
                return
            # 字数硬闸门（outline 模式）：超 target×1.6 先带压缩反馈重试一次，
            # 仍超则句界硬截断到 ×1.5。先生成后播放，对前端完全透明
            if request.mode == "outline" and request.target_chars > 0:
                hard_limit = int(request.target_chars * OUTLINE_WC_HARD_RATIO)
                if len(text) > hard_limit:
                    compressed = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=(
                            f"{user_prompt}\n\n# 上次输出被拒\n"
                            f"上次输出 {len(text)} 字，超过 {hard_limit} 字硬上限。"
                            f"请压缩到 {request.target_chars} 字以内：删减重复修饰与冗余动作，"
                            f"细纲核心事件必须全部保留。只输出压缩后的正文。"
                        ),
                        model_type="creative",
                        temperature=0.7,
                        max_tokens=max(1200, request.target_chars * 2 + 1000),
                        reasoning_config=REASONING_DISABLED,
                    )
                    cand = (compressed.content or "").strip()
                    if cand:
                        text = cand
                if len(text) > hard_limit:
                    text = _truncate_at_sentence(text, int(request.target_chars * OUTLINE_WC_TRUNCATE_RATIO))
                    logger.info(
                        f"[adaptive/stitch-ghost] 细纲扩写字数末次仍超上限，"
                        f"句界截断到 {len(text)} 字（目标 {request.target_chars}）"
                    )
            fragment = request.fragment.strip()
            if request.mode == "stitch" and fragment and fragment not in text:
                text = f"{fragment}{text}"
            yield build_sse_event("GHOST_START", "", mode=request.mode)
            # burst/open/outline 文本长 → 更大步长更快节奏（700 字约 2.3s 播完），短档保持原速
            chunk_size = 12 if request.mode in ("burst", "open", "outline") else 6
            frame_delay = 0.04 if request.mode in ("burst", "open", "outline") else 0.09
            for pos in range(0, len(text), chunk_size):
                yield build_sse_event("GHOST_CHUNK", "", delta=text[pos: pos + chunk_size])
                await asyncio.sleep(frame_delay)
            yield build_sse_event("GHOST_DONE", "", text=text, word_count=len(text))
        except Exception as e:
            logger.warning(f"[adaptive/stitch-ghost] 失败: {e}")
            yield build_sse_error(f"续写失败: {e}")

    return StreamingResponse(_stream(), media_type="text/event-stream")
