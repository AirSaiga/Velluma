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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.core.dependencies import get_db
from backend.database import AsyncSessionLocal
from backend.models import Chapter
from backend.repositories.world_repository import WorldRepository
from backend.services.adaptive.orchestrator import get_orchestrator
from backend.services.adaptive.change_detector import AuthorState
from backend.services.adaptive.observing import (
    bind_adaptive_trace,
    flush_adaptive_records,
    get_adaptive_recorder,
)
from backend.services.adaptive.world_model import WorldModelRepository
from backend.services.context.settings_bundle import (
    load_chapter_settings_bundle,
    render_style_positive,
)
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.prompts.adaptive_prompts import (
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
)
from backend.services.rag.recall import recall_memories
from backend.services.style.retrieval import retrieve_author_samples
from backend.services.observability.run_trace import trace_event
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
    # 世界数据版本（写作页切片条保鲜比对；路由层附带，查询失败为 None）
    world_version: Optional[Dict] = Field(None)


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
    bind_adaptive_trace(chapter_id)
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

    # 世界数据版本（写作页切片保鲜比对搭心跳便车；失败静默 None 不阻塞心跳本体）
    world_version = None
    chapter = None
    try:
        chapter = await db.get(Chapter, str(chapter_id))
        if chapter is not None:
            world_version = await WorldRepository(db).world_version(str(chapter.book_id))
    except Exception:
        world_version = None

    # 文风漂移轻提示（完整落地批，设计稿 §5 心跳感知通道）：以 kind=style_drift
    # 并入 canon_hints——前端感知带零新增管线直接渲染。纯 code + 按内容长度缓存
    drift_hint = await _style_drift_hint_for_heartbeat(chapter, db)
    if drift_hint:
        canon_hints = list(canon_hints) + [drift_hint]

    # 观测（P0-2）：心跳事件进 chapter 级 trace；顺路冲走累积的组件调用账
    # （含上一次心跳派生的后台组件——它们自开 session，只能靠后续请求落库）
    trace_event(
        "adaptive_heartbeat",
        word_count=request.word_count,
        paused_ms=request.paused_ms,
        activated=result.get("activated", []),
        dock_parts=len(dock_parts),
        direction_cards=len(direction_cards),
        canon_hints=len(canon_hints),
    )
    await flush_adaptive_records(chapter_id)

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
        world_version=world_version,
    )


def _extract_dock_parts(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 dock_generator 缓存的挂件。"""
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__dock__"):
            return proj.get("parts", [])
    return []


# 文风漂移提示缓存（chapter_id → (content_len, hint|None)）——内容没变不重算
_STYLE_HINT_CACHE: Dict[str, tuple] = {}


async def _style_drift_hint_for_heartbeat(chapter: Any, db: AsyncSession) -> Optional[Dict]:
    """文风漂移心跳轻提示（设计稿 §5）：章尾 3000 字同尺测量 vs 目标/健康带。

    纯 code 零 LLM；显著偏离才返回提示卡（kind=style_drift，走 canon_hints 管线）。
    任何失败/文本过短 → None（绝不阻塞心跳）。
    """
    if chapter is None:
        return None
    content = getattr(chapter, "content_text", "") or ""
    cache_key = str(chapter.id)
    cached = _STYLE_HINT_CACHE.get(cache_key)
    if cached is not None and cached[0] == len(content):
        return cached[1]

    hint: Optional[Dict] = None
    if len(content) >= 400:
        try:
            from backend.models import StyleCard as StyleCardModel
            from backend.services.style.fingerprint import compute_style_drift_hint
            from backend.services.validation.thresholds import CV_THRESHOLD_LO, CV_THRESHOLD_HI

            sc_result = await db.execute(
                select(StyleCardModel).where(
                    StyleCardModel.book_id == chapter.book_id,
                    StyleCardModel.chapter_id.is_(None),
                ).limit(1)
            )
            card = sc_result.scalar_one_or_none()
            target = None
            if card is not None and card.dialogue_ratio_target is not None:
                target = float(card.dialogue_ratio_target)
            message = compute_style_drift_hint(
                content[-3000:], target, CV_THRESHOLD_LO, CV_THRESHOLD_HI,
            )
            if message:
                hint = {
                    "kind": "style_drift",
                    "node_label": "文风",
                    "node_type": "style",
                    "detail": message,
                }
        except Exception:
            hint = None
    _STYLE_HINT_CACHE[cache_key] = (len(content), hint)
    return hint


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
    bind_adaptive_trace(chapter_id)
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    result = await orch.on_settle(request.text, request.entities, commit=request.commit)
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
    trace_event(
        "adaptive_finish",
        finished=result.get("finished", False) if isinstance(result, dict) else False,
        memory_indexed=memory_indexed,
        candidates_created=result.get("candidates_created", 0) if isinstance(result, dict) else 0,
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
    bind_adaptive_trace(chapter_id)
    trace_event("adaptive_stitch_start", mode=request.mode, target_chars=request.target_chars)
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

    # 文风执行层（S2 E1/E2）：正面画像 + few-shot 笔迹示范注入全部四模式。
    # 检索锚 = 记忆召回同一 query（当前写作上下文）；无样本/无文风卡 → 空，
    # prompt 零变化（不阻塞生成）
    style_positive = render_style_positive(bundle.style_card)
    author_samples: List[str] = []
    if bundle.book_id:
        author_samples = await retrieve_author_samples(
            db, bundle.book_id, recall_query, k=2,
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
            style_positive=style_positive,
            author_samples=author_samples,
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
            style_positive=style_positive,
            author_samples=author_samples,
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
            style_positive=style_positive,
            author_samples=author_samples,
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
            style_positive=style_positive,
            author_samples=author_samples,
        )

    async def _stream():
        recorder = get_adaptive_recorder(chapter_id)
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
            recorder.record_result(f"adaptive.stitch_ghost.{request.mode}", result, model_slot="creative")
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
                    recorder.record_result("adaptive.stitch_ghost.compress", compressed, model_slot="creative")
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
            trace_event(
                "adaptive_stitch_complete",
                mode=request.mode,
                target_chars=request.target_chars,
                actual_chars=len(text),
            )
        except Exception as e:
            logger.warning(f"[adaptive/stitch-ghost] 失败: {e}")
            yield build_sse_error(f"续写失败: {e}")
        finally:
            # SSE 流结束（正常/异常/客户端断连）统一冲账——stitch 是请求内直接调 LLM，
            # 不冲就没人冲（下一个心跳也能兜底，但那要等作者继续打字）
            await flush_adaptive_records(chapter_id)

    return StreamingResponse(_stream(), media_type="text/event-stream")


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


class FixSentenceRequest(BaseModel):
    sentence: str = Field(..., description="缺陷句原文（scan_sentence_defects 的 sentence 字段）")
    defect_type: str = ""
    description: str = ""


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
    content = chapter.content_text or ""
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


class SpineAnchor(BaseModel):
    id: str = ""
    text: str
    source: str = "author"    # author | ai
    status: str = "pending"   # pending | hit | dropped


class SpineUpdateRequest(BaseModel):
    intent: Optional[Dict] = None            # {text, source}
    anchors: Optional[List[SpineAnchor]] = None


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
                raise HTTPException(422, detail=f"锚点「{text or '（空）'}」太短——锚点是 2-12 字的短语，细节请留给大纲")
            if len(text) > SPINE_ANCHOR_TEXT_MAX:
                raise HTTPException(422, detail=f"锚点「{text[:12]}…」超过 12 字——锚点只记方向，展开请写进大纲")
            anchors.append({
                "id": a.id or f"a{i + 1}",
                "text": text,
                "source": a.source if a.source in ("author", "ai") else "author",
                "status": a.status if a.status in ("pending", "hit", "dropped") else "pending",
            })
        if len(anchors) > SPINE_MAX_ANCHORS:
            raise HTTPException(422, detail=f"锚点超过 {SPINE_MAX_ANCHORS} 个——说明在写大纲了。细节留给大纲，谋篇只记方向")
        spine["anchors"] = anchors
    return spine


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
        # 谋篇建议要质量：走 creative 槽、保留默认 thinking（设计稿 §4.1）
        model_type="creative", temperature=0.4, max_tokens=800,
    )
    get_adaptive_recorder(chapter_id).record_result("adaptive.spine_suggest", result, model_slot="creative")

    from backend.services.utils.json_safe import parse_json_safe
    parsed = parse_json_safe(result.content or "") or {}
    intent = str(parsed.get("intent", "") or "").strip()[:SPINE_INTENT_TEXT_MAX]
    anchors = []
    for a in (parsed.get("anchors") or [])[:SPINE_MAX_ANCHORS]:
        text = str(a or "").strip()[:SPINE_ANCHOR_TEXT_MAX]
        if len(text) >= SPINE_ANCHOR_TEXT_MIN:
            anchors.append(text)
    trace_event("adaptive_spine_suggest", intent=bool(intent), anchors=len(anchors))
    await flush_adaptive_records(chapter_id)
    return {"intent": intent, "anchors": anchors}


# ============================================================
# 端点 6：event — 协作交互埋点（P0-3，本地 JSONL 零上报）
# ============================================================
# 用途定位（roadmap §0.1/§1）：个人镜子——自我可见性（协作质量与 token 成本），
# 非增长分析。事件词表（前端 dispatchCollabEvent / logCollabEvent）：
#   cards_delivered {count}      走向卡亮出（前端按卡集签名去重，防心跳重复计）
#   card_burst {event}           走向卡连写（Ctrl+Space 选卡）
#   ghost_request {mode}         Space 续写/缝合触发
#   ghost_adopt / ghost_discard  Enter 落地 / Esc 蒸发
#   capsule_create / capsule_expand {note_id}  细纲胶囊创建 / 落笔扩写
#   slice_mode {mode}            切片条读者视角档切换
#   context_card                 情境浮卡打开
#   quick_note {action}          世界速记 commit / undo
#   ignition / settle {commit} / finish / sentence_fix {action: propose|adopt|reject}
#   spine_intent_set / spine_anchor_add|drop|remove / spine_suggest /
#   spine_suggest_adopt {part} / spine_suggest_discard（P1.4 章级谋篇）
# ============================================================

_COLLAB_EVENTS_FILE = "data/collab_events.jsonl"


class CollabEventRequest(BaseModel):
    kind: str
    detail: Dict = Field(default_factory=dict)


def _append_collab_event(book_id: str, chapter_id: str, kind: str, detail: Dict) -> None:
    """追加事件到本地 JSONL（失败静默——埋点绝不阻塞业务）。"""
    import json as _json
    from datetime import datetime, timezone as _tz
    from pathlib import Path as _Path

    try:
        path = _Path(_COLLAB_EVENTS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps({
                "ts": datetime.now(_tz.utc).isoformat(),
                "book_id": book_id,
                "chapter_id": chapter_id,
                "kind": kind,
                "detail": detail or {},
            }, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.debug(f"[CollabEvent] 写入失败（静默）: {e}")


@router.post("/{chapter_id}/adaptive/event", status_code=204)
async def log_collab_event(
    chapter_id: str,
    payload: CollabEventRequest,
    db: AsyncSession = Depends(get_db),
):
    """记录协作交互事件（book_id 服务端从章节解析，前端不传防伪）。"""
    book_id = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            book_id = str(chapter.book_id)
    except Exception:
        pass
    _append_collab_event(book_id, chapter_id, payload.kind, payload.detail)


@router.get("/{chapter_id}/adaptive/events/summary")
async def collab_events_summary(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """协作交互汇总（个人镜子：走向卡/幽灵稿/胶囊的采纳率——P0 出口标准）。"""
    import json as _json
    from collections import Counter as _Counter
    from pathlib import Path as _Path

    book_id = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            book_id = str(chapter.book_id)
    except Exception:
        pass

    counts: Dict = _Counter()
    try:
        path = _Path(_COLLAB_EVENTS_FILE)
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = _json.loads(line)
                        if ev.get("chapter_id") == chapter_id:
                            counts[ev.get("kind", "?")] += 1
                    except Exception:
                        continue
    except Exception:
        pass

    def _rate(num: str, den: str):
        n, d = counts.get(num, 0), counts.get(den, 0)
        return round(n / d, 3) if d > 0 else None

    return {
        "chapter_id": chapter_id,
        "book_id": book_id,
        "total": sum(counts.values()),
        "by_kind": dict(counts),
        "card_burst_rate": _rate("card_burst", "cards_delivered"),
        "ghost_adopt_rate": _rate("ghost_adopt", "ghost_request"),
        "capsule_expand_count": counts.get("capsule_expand", 0),
        "quick_note_commit": counts.get("quick_note", 0),
    }
