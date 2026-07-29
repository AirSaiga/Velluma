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
BS-ADF（Beat-Slot Anchor-Driven Flow）引擎路由（P2.5 新建）。

职责：
- 提供 BS-ADF 引擎入口 POST /api/chapters/{id}/generate-bsadf
- 复用 ADF 的上下文加载（_load_adf_context）、asyncio.Queue 桥接、SSE 流式输出
- 与 ADF 端点并存，前端通过引擎切换选择

API 端点（前缀 /api/chapters/{chapter_id}）：
- POST /generate-bsadf   BS-ADF 引擎生成（SSE 事件序列）

SSE 事件序列（BS-ADF 专属 + 复用 ADF）：
- GENERATION_RUN           生成已初始化（携带 run_id）
- BSADF_STAGE              BS-ADF 阶段切换（SLOT_BUILD / RENDER）
- BEAT_SLOTS_BUILT         槽位卡构建完成（count 张；Track B 暂停时内嵌 decision_set）
- DDE_AUTO_APPLIED         Track A 静默 DDE 结果（有分支=已按默认走向突变；无分支=has_story_branch=false）
- BEAT_RENDER_PROGRESS     单段渲染进度（rendered）
- BEAT_DOWNGRADED          单段降级（reason）
- ADF_STAGE                复用 ADF 阶段切换（SPINE_BUILDING / ANCHOR_DESIGN / TIER_DECIDE / PRUNE / ANCHOR_AUDIT / REFINE / CONSISTENCY_GUARD）
- ADF_SPINE_BUILT          脉络轨构建完成（复用）
- ADF_ANCHOR_DESIGNED      远端锚设计完成（复用）
- TIER_DECIDED             定档通知（复用）
- ADF_PRUNE_PROGRESS       去AI味剪枝进度（复用，Phase 4.5）
- ADF_PRECONDITION_LANDED  条件落地事件（复用）
- ADF_AUDIT                锚点审计结论（复用）
- ADF_CONSISTENCY          一致性守卫结论（复用）
- DEGRADED                 降级事件（失败不静默）
- FINAL_TEXT_STREAM        正在输出最终文本
- TEXT_CHUNK               文本块（流式正文）
- COMPLETE / ERROR         完成/错误

与 ADF 端点的关系：
- /generate-adf：保留不动（ADF 引擎）
- /generate-bsadf：本端点（BS-ADF 引擎，Phase 4 用槽位化流水线，其余复用 ADF）
- 前端通过引擎切换选择；两者并存，互不影响

Track A/B：
- track='A'（默认）：全自动跑完全程（DDE 有分支时静默应用 default_option，
  emit DDE_AUTO_APPLIED，不暂停）
- track='B'：跑到 Phase 4b 单次暂停（BEAT_SLOTS_BUILT 内嵌 decision_set），
  作者编辑槽位卡 + 选定分支后 /confirm-beats 一并提交恢复

使用方式：
    POST /api/chapters/{chapter_id}/generate-bsadf
    body: {"tier": "auto", "track": "A", "target_word_count": null, "max_segments": 6}
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.routes.chapter_generation.adf import _load_adf_context
from backend.schemas.bsadf import (
    AdvanceBeatRequest,
    ConfirmBeatsRequest,
    GenerateBSAdfRequest,
    RerenderBeatRequest,
)
from backend.services.observability.run_recorder import RunRecorder
from backend.services.observability.run_trace import (
    clear_trace,
    create_trace,
    trace_event,
)
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import (
    build_sse_event,
    build_sse_text_chunk,
    build_sse_error,
)
from backend.services.workflows.adf import (
    climax_to_dict,
    story_context_to_dict,
    audit_to_dict,
)
from backend.services.workflows.adf.types import ChapterClimax, StoryContext
from backend.services.workflows.bsadf.bsadf_workflow import BSAdfWorkflow
from backend.services.workflows.bsadf.dde.slot_mutator import mutate_slot_cards
from backend.services.workflows.bsadf.dde.types import chapter_decision_set_from_dict
from backend.services.workflows.bsadf.types import (
    beat_slot_to_dict,
    beat_slot_from_dict,
    BeatSlotCard,
)

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-bsadf"])

# ============================================================
# 实时流常量
# ============================================================
# SSE 心跳间隔（秒）。长耗时阶段（如 Phase 4c 逐段渲染、DDE 决策卡生成）期间
# 若无业务事件，每 HEARTBEAT_INTERVAL 秒发一个 HEARTBEAT data 帧，防止代理/中间件/
# 浏览器因空闲掐断连接。注意：必须是 data 帧（不是 SSE 注释帧 ": heartbeat\n\n"），
# 因为很多浏览器/代理只把 data 帧视为"连接活跃"，注释帧会被忽略导致超时掐断。
# 设为 5 秒（而非 15 秒）：DDE 单卡 LLM 调用 20-40 秒，15 秒间隔只发 1-2 次心跳，
# 实测 Chromium 会在此期间掐断 fetch ReadableStream；5 秒间隔确保每卡期间至少 4-8 次心跳。
HEARTBEAT_INTERVAL = 5


# ============================================================
# 内存存储：Track B 暂停后的槽位卡 + 上下文（照搬 refinery _PENDING_REFINERIES）
# ============================================================
# 结构：{run_id: {
#     "cards": List[BeatSlotCard],          # 槽位卡（待作者编辑）
#     "ctx": {
#         "spine": StoryContext,             # 前一请求 Phase 1 产物
#         "anchor": ChapterClimax,           # 前一请求 Phase 2 产物
#         "tier": str,                        # 前一请求 Phase 3 定档
#         "target_word_count": int,
#         "max_segments": int,
#         "chapter": chapter,                 # route 层重建 workflow 必需
#         "book": book,
#         "chapter_card": chapter_card,
#         "entities": [...],
#         "style_card": style_card,
#         ...其余 BSAdfWorkflow 构造参数
#     },
#     "expires": datetime,                   # TTL 1 小时
# }}
# Track B 暂停（generate-bsadf track='B'）写入；/confirm-beats 取出并 pop。
_PENDING_BEAT_SLOTS: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL = timedelta(hours=1)


def _cleanup_expired_beats() -> None:
    """清理过期的 pending beat slots（与 refinery._cleanup_expired 同构）。"""
    now = datetime.now()
    expired = [k for k, v in _PENDING_BEAT_SLOTS.items() if v.get("expires", now) < now]
    for k in expired:
        _PENDING_BEAT_SLOTS.pop(k, None)


def _store_pending_beats(run_id: str, cards: List[BeatSlotCard], workflow_ctx: Dict[str, Any]) -> None:
    """暂存 Track B 暂停的槽位卡 + 恢复上下文。

    workflow_ctx 应含 spine/anchor/tier/target_word_count/max_segments +
    构造 BSAdfWorkflow 所需的全部参数（chapter/book/chapter_card/entities/style_card 等）。
    """
    _cleanup_expired_beats()
    _PENDING_BEAT_SLOTS[run_id] = {
        "cards": cards,
        "ctx": workflow_ctx,
        "expires": datetime.now() + _PENDING_TTL,
    }


def _load_pending_beats(run_id: str) -> Optional[Dict[str, Any]]:
    _cleanup_expired_beats()
    return _PENDING_BEAT_SLOTS.get(run_id)


def _find_pending_by_beat(beat_id: str) -> Optional[Dict[str, Any]]:
    """按 beat_id 扫描全部 pending 条目（rerender 缺 run_id 时的兜底）。

    _PENDING_BEAT_SLOTS 以 run_id 为 key，但 rerender 请求可能拿不到 run_id
    （如刷新页面后），此时遍历各条目的 cards 匹配 beat_id。
    """
    _cleanup_expired_beats()
    for entry in _PENDING_BEAT_SLOTS.values():
        for card in entry.get("cards", []):
            if getattr(card, "beat_id", None) == beat_id:
                return entry
    return None


def _pop_pending_beats(run_id: str) -> Optional[Dict[str, Any]]:
    _cleanup_expired_beats()
    return _PENDING_BEAT_SLOTS.pop(run_id, None)


# ============================================================
# 轮询基础设施：替代 SSE 长连接的进度查询机制
# ============================================================
# 设计：workflow 跑在后台 asyncio.Task 里，progress_callback 把事件 append 到
# _GENERATION_RUNS[run_id]["events"] 列表。前端用 GET /generation-status/{run_id}?since=N
# 增量轮询（每次只取 events[N:]），彻底消除 SSE 长连接的传输层问题
# （Vite proxy buffer / Starlette yield 阻塞 / asyncio.Queue 竞态）。
#
# 结构：{run_id: {
#     "events": List[dict],       # 事件列表（每项 {event, ...payload}，前端按 event 分流）
#     "status": str,              # "running" | "done" | "paused_track_b" | "error"
#     "error": str,               # status=error 时的错误信息
#     "result": dict | None,      # status=done/paused 时的最终产物（COMPLETE payload 等）
#     "expires": datetime,        # TTL（同 _PENDING_BEAT_SLOTS）
# }}
_GENERATION_RUNS: Dict[str, Dict[str, Any]] = {}


def _cleanup_expired_runs() -> None:
    now = datetime.now()
    expired = [k for k, v in _GENERATION_RUNS.items() if v.get("expires", now) < now]
    for k in expired:
        _GENERATION_RUNS.pop(k, None)


def _get_run(run_id: str) -> Optional[Dict[str, Any]]:
    _cleanup_expired_runs()
    return _GENERATION_RUNS.get(run_id)


def _init_run(run_id: str) -> Dict[str, Any]:
    """初始化一个 run 的进度存储。"""
    run_data = {
        "events": [],
        "status": "running",
        "error": "",
        "result": None,
        "expires": datetime.now() + _PENDING_TTL,
    }
    _GENERATION_RUNS[run_id] = run_data
    return run_data


def _push_run_event(run_id: str, event_payload: dict) -> None:
    """往 run 的事件列表追加一个事件（供前端轮询取走）。"""
    run = _GENERATION_RUNS.get(run_id)
    if run is not None:
        run["events"].append(event_payload)


def _set_run_status(run_id: str, status: str, error: str = "", result: Any = None) -> None:
    run = _GENERATION_RUNS.get(run_id)
    if run is not None:
        run["status"] = status
        if error:
            run["error"] = error
        if result is not None:
            run["result"] = result
        run["expires"] = datetime.now() + _PENDING_TTL  # 续期


async def _sse_stream_from_run(run_id: str):
    """通用 SSE generator：从 _GENERATION_RUNS[run_id] 读事件，yield SSE 帧。

    后台 task 往 dict push 事件，本 generator 从 dict 读事件 yield。
    两者通过 dict 解耦——后台 task 不依赖 SSE 连接，SSE 断了也不影响后台执行。
    当 status 变为终止态（done/paused/error）时，yield 最后的事件后结束。
    """
    since = 0
    while True:
        run = _get_run(run_id)
        if not run:
            yield build_sse_error("运行状态丢失")
            return
        # 增量取事件
        events = run["events"]
        new_events = events[since:] if since < len(events) else []
        for payload in new_events:
            ev = payload.get("event", "")
            msg = payload.get("message", "")
            yield build_sse_event(ev, msg, **{k: v for k, v in payload.items() if k not in ("event", "message")})
        since = len(events)

        status = run["status"]
        if status in ("done", "paused_track_b", "error", "stepping"):
            if status == "error":
                yield build_sse_error(run.get("error", "生成失败"))
            return

        # 短暂等待新事件
        await asyncio.sleep(0.3)


# ============================================================
# SSE 流处理器
# ============================================================

class _BSAdfStreamHandler:
    """BS-ADF 引擎后台执行器（轮询模式）。

    职责：
    - 加载上下文（复用 ADF 的 _load_adf_context）
    - 初始化 RunRecorder
    - 执行 BSAdfWorkflow（直接 await，不走 SSE 桥接）
    - 把阶段进度事件 push 到 _GENERATION_RUNS（前端轮询取走）
    - 持久化生成结果到 Chapter.draft_text + RunRecorder 落库

    Track A（默认）：跑完全程。
    Track B（track='B'）：跑到 Phase 4a/4a.5 暂停。
    """

    def __init__(
        self,
        chapter_id: str,
        request: GenerateBSAdfRequest,
        db: AsyncSession,
    ):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def _run_generate(self, run_id: str):
        """后台执行 BS-ADF workflow（轮询模式，不再 yield SSE 帧）。"""
        trace = create_trace(run_id, "bsadf", self.chapter_id)
        trace_event(
            "run_start",
            request=self.request.model_dump() if self.request else {},
        )

        def _emit(event: str, data: dict) -> None:
            """进度回调：把事件推到轮询队列（替代 SSE yield）。"""
            payload = {"event": event, **data}
            _push_run_event(run_id, payload)

        try:
            # ---- Phase 0: 上下文组装 ----
            _emit("BSADF_STAGE", {"stage": "CONTEXT_ASSEMBLING", "message": "进入阶段：CONTEXT_ASSEMBLING"})
            ctx = await _load_adf_context(self.db, self.chapter_id)
            chapter = ctx["chapter"]

            # ---- 初始化 RunRecorder ----
            recorder = RunRecorder(chapter_id=self.chapter_id, run_id=run_id)
            _emit("GENERATION_RUN", {"generation_run_id": run_id, "message": "BS-ADF 引擎已初始化"})

            # ---- 初始化 BSAdfWorkflow ----
            workflow = BSAdfWorkflow(
                chapter=chapter,
                book=ctx["book"],
                chapter_card=ctx["chapter_card"],
                entities=ctx["entities"],
                style_card=ctx["style_card"],
                author_samples=None,
                recorder=recorder,
                request=self.request,
                previous_summary=ctx["previous_summary"],
                rolling_summary=ctx["rolling_summary"],
                open_hooks=ctx["open_hooks"],
                canon_context=ctx.get("canon_context", ""),
                author_intent=getattr(self.request, "author_intent", None),
                expectation_actions=getattr(self.request, "expectation_actions", None),
                locations=ctx.get("locations", []),
                assets=ctx.get("assets", []),
                relationships=ctx.get("relationships", []),
                worldview_text=ctx.get("worldview_text", ""),
            )

            # ---- 直接执行 workflow（progress_callback 推事件到轮询队列）----
            async def _on_progress(event: str, data: dict) -> None:
                if event in ("BSADF_STAGE", "ADF_STAGE"):
                    trace.set_stage(str(data.get("stage", "")))
                trace_event(event, **data)
                _emit(event, data)

            track = getattr(self.request, "track", "A")
            pause_after_slot_build = (track == "B")

            # ============================================================
            # NLE-ADF 步进模式：跑到 Phase 4b 暂停，起 stepping_loop 协程，
            # run 状态置 "stepping"，本请求返回（前端改走 /advance-beat 推进）。
            # ============================================================
            if getattr(self.request, "enable_stepping", False):
                # 步进模式下 track 参数无意义（步进是"渲一段裁一段"，不经过 Track B 全章确认）
                if getattr(self.request, "track", "A") == "B":
                    logger.warning(
                        "[BSADF] enable_stepping=true 且 track='B' 同时传入——"
                        "步进模式将忽略 track 参数（Track B 全章确认语义被步进逐段裁决替代）"
                    )
                stepping_result = await workflow.execute_stepping(progress_callback=_on_progress)
                cards_dicts = stepping_result.debug_info.get("beat_slots", [])
                # 从 dict 重建 BeatSlotCard（debug_info 存的是 dict）
                cards = [beat_slot_from_dict(d) for d in cards_dicts] if cards_dicts else []

                from backend.services.workflows.bsadf.stepping_runtime import (
                    SteppingRun, _STEPPING_RUNS, stepping_loop,
                )
                stepping_run = SteppingRun(
                    run_id=run_id,
                    chapter_id=str(self.chapter_id),
                    cards=cards,
                    workflow=workflow,
                    decision_set=stepping_result.debug_info.get("decision_set") or {},
                )
                workflow._paused_spine = stepping_result.spine_track
                workflow._paused_anchor = stepping_result.distal_anchor
                workflow._paused_cards = cards
                workflow._emotion_curve_samples = stepping_result.debug_info.get("emotion_curve_samples", [])

                _STEPPING_RUNS.set(stepping_run)
                enable_mem = getattr(self.request, "enable_memory_ingestion", False)
                asyncio.ensure_future(stepping_loop(stepping_run, enable_memory_ingestion=enable_mem))

                # 补发步进就绪事件：携带 run_id（前端 advanceBeat 需要）+
                # 全部槽位卡快照（前端立即展示分镜监视器）。
                # workflow 内部发的 BEAT_SLOTS_BUILT 不带 run_id，这里补关联。
                _emit("STEPPING_INITIALIZED", {
                    "run_id": run_id,
                    "beat_slots": [beat_slot_to_dict(c) for c in cards],
                    "beat_ids": [c.beat_id for c in cards],
                    "decision_set": stepping_result.debug_info.get("decision_set") or {},
                })

                # 等待首段 BEAT_RENDER_READY，期间把 stepping_loop 的
                # BEAT_RENDER_START/BEAT_TEXT_CHUNK 事件转发到 _GENERATION_RUNS
                # （generate-bsadf 的 SSE 流在 status=stepping 终止后，前端无法
                #  收到首段渲染事件——死锁：前端等 BEAT_RENDER_READY 才显示 Space，
                #  但该事件只在 event_queue 里没人消费）。
                # 修复：这里桥接 event_queue → _emit，直到首段 ready 再终止 SSE 流。
                while not stepping_run.current_segment_ready:
                    if stepping_run.status in ("error", "done"):
                        break
                    try:
                        ev_name, ev_data = await asyncio.wait_for(
                            stepping_run.event_queue.get(), timeout=120.0
                        )
                        _emit(ev_name, ev_data)
                        if ev_name == "BEAT_BRANCH_CHOICE":
                            # 岔路门：步进循环挂起等作者选走向（时长由作者决定，
                            # 不受 120s 约束）。作者提交选择时 advance-beat 会
                            # 新开 SSE 流交付后续渲染事件，本桥接直接退出——
                            # 继续空等只会触发下方 120s 误报（真实事故）。
                            break
                    except asyncio.TimeoutError:
                        _emit("ERROR", {"error": "首段渲染超时（120s）"})
                        break

                _set_run_status(run_id, "stepping")
                return

            result = await workflow.execute(
                progress_callback=_on_progress,
                pause_after_slot_build=pause_after_slot_build,
            )

            if result is None:
                _emit("ERROR", {"error": "生成失败：工作流未返回结果"})
                _set_run_status(run_id, "error", error="工作流未返回结果")
                return

            # ============================================================
            # 暂停分支：Track B 单次暂停（decision_set 已随卡内嵌）
            # ============================================================
            if result.debug_info.get("paused"):
                cards_dicts = result.debug_info.get("beat_slots", [])
                cards: List[BeatSlotCard] = [beat_slot_from_dict(d) for d in cards_dicts]

                paused_spine: StoryContext = result.debug_info.get("paused_spine") or result.spine_track
                paused_anchor: ChapterClimax = result.debug_info.get("paused_anchor") or result.distal_anchor
                workflow_ctx = {
                    "spine": paused_spine,
                    "anchor": paused_anchor,
                    "tier": result.debug_info.get("paused_tier") or result.tier_decision.get("tier"),
                    "target_word_count": result.debug_info.get("paused_target_word_count") or result.tier_decision.get("target_word_count"),
                    "max_segments": result.debug_info.get("paused_max_segments") or result.tier_decision.get("max_segments"),
                    # 定档理由一并暂存：resume 回填 tier_decision，供 Track B
                    # COMPLETE 载荷的 tier_reason 与 Track A 对齐
                    "tier_reason": result.tier_decision.get("reason"),
                    "chapter": chapter,
                    "book": ctx["book"],
                    "chapter_card": ctx["chapter_card"],
                    "entities": ctx["entities"],
                    "style_card": ctx["style_card"],
                    "previous_summary": ctx.get("previous_summary"),
                    "rolling_summary": ctx.get("rolling_summary"),
                    "open_hooks": ctx.get("open_hooks"),
                    "canon_context": ctx.get("canon_context", ""),
                    "author_intent": getattr(self.request, "author_intent", None),
                    "expectation_actions": getattr(self.request, "expectation_actions", None),
                    "locations": ctx.get("locations", []),
                    "assets": ctx.get("assets", []),
                    "relationships": ctx.get("relationships", []),
                    "worldview_text": ctx.get("worldview_text", ""),
                    "request": self.request,
                }

                # 持久化 slots
                try:
                    chapter.bsadf_beat_slots = json.dumps(cards_dicts, ensure_ascii=False)
                    chapter.generation_run_id = run_id
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[BS-ADF] Track B 持久化 beat_slots 失败（不阻塞）: {e}")

                # RunRecorder 落库
                try:
                    await recorder.flush_to_db(self.db)
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[BS-ADF] RunRecorder 落库失败（不阻塞）: {e}")

                # 推送降级事件
                for deg in result.degraded:
                    _emit("DEGRADED", {
                        "message": f"阶段 {deg.get('phase', '?')} 降级",
                        "phase": deg.get("phase", ""),
                        "reason": deg.get("reason", ""),
                        "detail": str(deg.get("detail", ""))[:200],
                    })

                # ============================================================
                # Track B 单次暂停分支（DDE decision_set 随卡一起给作者，
                # 不再有独立的 DDE 弹窗轮次）
                # ============================================================
                workflow_ctx["decision_set"] = result.debug_info.get("decision_set") or {}
                _store_pending_beats(run_id, cards, workflow_ctx)

                _emit("BEAT_SLOTS_BUILT", {
                    "message": f"槽位卡构建完成：{len(cards)} 张（待作者编辑）",
                    "run_id": run_id,
                    "count": len(cards),
                    "beat_ids": [c.beat_id for c in cards],
                    "beat_slots": cards_dicts,
                    "decision_set": result.debug_info.get("decision_set") or {},
                    "climax_design": climax_to_dict(paused_anchor),
                    "story_context": story_context_to_dict(paused_spine),
                    "tier": result.tier_decision,
                })
                _emit("BSADF_STAGE", {"stage": "AUTHOR_DIALOGUE", "run_id": run_id, "message": "等待作者编辑"})

                logger.info(f"[BS-ADF] Track B 暂停完成 run_id={run_id}，{len(cards)} 张卡待编辑")
                trace_event("track_b_pause", count=len(cards), beat_slots=cards_dicts)
                _set_run_status(run_id, "paused_track_b")
                return

            # ============================================================
            # Track A 完成：持久化 + 推送结果
            # ============================================================
            try:
                await recorder.flush_to_db(self.db)
                await self.db.commit()
            except Exception as e:
                logger.warning(f"[BS-ADF] RunRecorder 落库失败（不阻塞）: {e}")

            if result.final_text:
                try:
                    chapter.draft_text = result.final_text
                    chapter.generation_run_id = run_id
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[BS-ADF] 持久化 draft_text 失败: {e}")

            # 暂存 rerender 上下文 + 持久化 slots
            try:
                beat_slot_dicts = result.debug_info.get("beat_slots", [])
                if beat_slot_dicts:
                    rerender_cards: List[BeatSlotCard] = [beat_slot_from_dict(d) for d in beat_slot_dicts]
                    rerender_ctx = {
                        "spine": result.spine_track,
                        "anchor": result.distal_anchor,
                        "entities": ctx.get("entities", []),
                        "locations": ctx.get("locations", []),
                        "assets": ctx.get("assets", []),
                        "relationships": ctx.get("relationships", []),
                        "canon_context": ctx.get("canon_context", ""),
                        "worldview_text": ctx.get("worldview_text", ""),
                    }
                    _store_pending_beats(run_id, rerender_cards, rerender_ctx)
                    chapter.bsadf_beat_slots = json.dumps(beat_slot_dicts, ensure_ascii=False)
                    chapter.generation_run_id = run_id
                    await self.db.commit()
            except Exception as e:
                logger.warning(f"[BS-ADF] 暂存 rerender 上下文失败（不阻塞）: {e}")

            # 推送降级事件
            for deg in result.degraded:
                _emit("DEGRADED", {
                    "message": f"阶段 {deg.get('phase', '?')} 降级",
                    "phase": deg.get("phase", ""),
                    "reason": deg.get("reason", ""),
                    "detail": str(deg.get("detail", ""))[:200],
                    "beat_id": deg.get("beat_id", ""),
                    "attempts": deg.get("attempts", 0),
                })
            for deg in recorder.degraded_events():
                _emit("DEGRADED", {
                    "message": f"{deg.get('stage', '?')} 降级",
                    "phase": deg.get("stage", ""),
                    "reason": deg.get("reason", ""),
                    "detail": f"动作：{deg.get('action', '')}",
                })

            # 推送元数据
            _emit("BSADF_METADATA", {
                "message": "本章元数据",
                "climax_design": climax_to_dict(result.distal_anchor),
                "story_context": story_context_to_dict(result.spine_track),
                "audit": audit_to_dict(result.audit),
                "beat_slots": result.debug_info.get("beat_slots", []),
                "degraded_beats": result.debug_info.get("degraded_beats", []),
                "rescue_needed": result.debug_info.get("rescue_needed", []),
            })
            _emit("UNIFIED_METRIC", {
                "message": "BS-ADF 引擎审计指标",
                "metrics": {"audit": audit_to_dict(result.audit), "stats": result.stats},
            })

            # 文本块
            if result.final_text:
                _emit("FINAL_TEXT_STREAM", {"message": "正在输出最终文本"})
                text = result.final_text
                chunk_size = 200
                for i in range(0, len(text), chunk_size):
                    _emit("TEXT_CHUNK", {"content": text[i:i + chunk_size]})

            # COMPLETE
            trace_event("final_text", text=result.final_text or "")
            trace_event("run_complete", stats=result.stats, degraded_count=len(result.degraded), audit_verdict=result.audit.verdict)
            complete_payload = {
                "event": "COMPLETE",
                "text": result.final_text,
                "engine": "bsadf",
                "generation_run_id": run_id,
                "tier": result.tier_decision.get("tier"),
                "tier_reason": result.tier_decision.get("reason"),
                "target_word_count": result.tier_decision.get("target_word_count"),
                "segment_count": len(result.segments),
                "climax_score": result.audit.climax_score,
                "audit_verdict": result.audit.verdict,
                "stats": result.stats,
                "degraded_count": len(result.degraded),
                "beat_slots": result.debug_info.get("beat_slots", []),
                "degraded_beats": result.debug_info.get("degraded_beats", []),
                "rescue_needed": result.debug_info.get("rescue_needed", []),
            }
            _push_run_event(run_id, complete_payload)
            _set_run_status(run_id, "done", result=complete_payload)

        except Exception as e:
            logger.exception(f"[BS-ADF] 后台执行异常: {e}")
            trace_event("run_error", phase="background_run", error=f"{type(e).__name__}: {str(e)[:300]}")
            _emit("ERROR", {"error": f"生成失败: {type(e).__name__}: {str(e)[:200]}"})
            _set_run_status(run_id, "error", error=str(e)[:300])
        finally:
            clear_trace()


# ============================================================
# POST /generate-bsadf —— BS-ADF 引擎入口（轮询模式）
# ============================================================

@router.post("/{chapter_id}/generate-bsadf")
async def generate_bsadf(
    chapter_id: str,
    request: Optional[GenerateBSAdfRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """BS-ADF 引擎生成入口（SSE 流式 + 轮询）。

    Phase 1-4b + 4c-7 用 SSE 流式输出（事件通过 _GENERATION_RUNS dict 中转，
    SSE generator 从 dict 读事件 yield）。

    Track A：SSE 跑完全程（enable_dde 时 DDE 章节分叉判断在 4b 后静默执行，
        有分支按 default_option 自动应用，emit DDE_AUTO_APPLIED，不暂停）。
    Track B（track='B'）：SSE 跑到 Phase 4b 单次暂停（BEAT_SLOTS_BUILT 内嵌
        decision_set），作者编辑槽位卡 + 选分支后 POST /confirm-beats 恢复。
    """
    from backend.database import AsyncSessionLocal

    run_id = f"bsadf_{uuid4().hex[:12]}"
    _init_run(run_id)
    req = request or GenerateBSAdfRequest()

    # 后台 task 跑 workflow（事件 push 到 _GENERATION_RUNS dict）
    async def _background():
        async with AsyncSessionLocal() as bg_db:
            handler = _BSAdfStreamHandler(chapter_id=chapter_id, request=req, db=bg_db)
            await handler._run_generate(run_id)

    asyncio.ensure_future(_background())

    return StreamingResponse(_sse_stream_from_run(run_id), media_type="text/event-stream")


@router.get("/{chapter_id}/generation-status/{run_id}")
async def generation_status(
    chapter_id: str,
    run_id: str,
    since: int = 0,
):
    """轮询查询生成进度（增量）。

    Args:
        run_id: 从 POST /generate-bsadf / /confirm-beats 获得
        since: 上次取到的事件索引（增量轮询，只返回 events[since:]）

    Returns:
        {status, events: [...], total_events, error?}
        - status: "running" | "done" | "paused_track_b" | "error"
        - events: 事件列表（前端按 event 字段分流）
    """
    run = _get_run(run_id)
    if not run:
        return {"status": "not_found", "events": [], "total_events": 0, "error": f"无效或已过期的 run_id: {run_id}"}

    events = run["events"]
    new_events = events[since:] if since < len(events) else []
    return {
        "status": run["status"],
        "events": new_events,
        "total_events": len(events),
        "error": run.get("error", ""),
    }


# ============================================================
# confirm-beats 后台执行器（轮询模式）
# ============================================================

async def _run_confirm_beats(run_id: str, request: "ConfirmBeatsRequest"):
    """后台执行 Track B 恢复（轮询模式）。"""
    trace = create_trace(run_id, "bsadf_confirm", request.chapter_id or "")
    trace.set_stage("CONFIRM_BEATS")
    trace_event("confirm_start", edited_count=len(request.edited_slots or []))

    def _emit(event: str, data: dict) -> None:
        _push_run_event(run_id, {"event": event, **data})

    try:
        pending = _load_pending_beats(request.run_id)
        if not pending:
            _emit("ERROR", {"error": f"无效或已过期的 run_id: {request.run_id}"})
            _set_run_status(run_id, "error", error="无效或已过期的 run_id")
            return

        cards: List[BeatSlotCard] = pending["cards"]
        ctx = pending["ctx"]
        chapter = ctx["chapter"]
        spine: StoryContext = ctx["spine"]
        anchor: ChapterClimax = ctx["anchor"]

        # 风险1修复：chapter 是 generate-bsadf 暂存的 detached ORM 对象（原 session 已关闭），
        # confirm-beats 的新 bg_db 不认识它。重新查询绑定到当前 session。
        db = _get_db_for_run(run_id)
        if db is not None:
            from backend.repositories import ChapterRepository
            chapter_repo = ChapterRepository(db)
            fresh_chapter = await chapter_repo.get_by_id(request.chapter_id or str(getattr(chapter, "id", "")))
            if fresh_chapter is not None:
                chapter = fresh_chapter
        tier: str = ctx["tier"]
        target_word_count: int = ctx["target_word_count"]
        max_segments: int = ctx["max_segments"]

        # SlotMutator：先按 branch_choices 突变剧情走向（写 branch_directive；
        # skipped 或未作答的节点走 default_option——默认选项是主路径），
        # 再应用 edited_slots 覆盖（作者面板里的整卡编辑优先）
        decision_set_dict = ctx.get("decision_set") or {}
        if decision_set_dict.get("decision_nodes"):
            decision_set = chapter_decision_set_from_dict(decision_set_dict)
            cards = mutate_slot_cards(
                cards=cards,
                decision_set=decision_set,
                branch_choices=request.branch_choices or {},
                skipped=request.skipped,
            )
            trace_event(
                "dde_mutated",
                skipped=request.skipped,
                choice_count=len(request.branch_choices or {}),
                mutated_count=sum(1 for c in cards if c.branch_directive),
            )

        # 用作者编辑后的 slots 覆盖
        if request.edited_slots:
            edited_map = {s.beat_id: s for s in request.edited_slots}
            new_cards: List[BeatSlotCard] = []
            for card in cards:
                if card.beat_id in edited_map:
                    schema = edited_map[card.beat_id]
                    edited_card = beat_slot_from_dict(schema.model_dump())
                    edited_card.segment_index = card.segment_index
                    edited_card.status = "author_pending"
                    edited_card.edited = True
                    edited_card.edit_count = card.edit_count + 1
                    new_cards.append(edited_card)
                else:
                    new_cards.append(card)
            cards = new_cards

        # 重建 workflow
        workflow = BSAdfWorkflow(
            chapter=chapter, book=ctx["book"], chapter_card=ctx["chapter_card"],
            entities=ctx["entities"], style_card=ctx["style_card"], author_samples=None,
            recorder=RunRecorder(chapter_id=request.chapter_id or "", run_id=run_id),
            request=ctx.get("request") or request,
            previous_summary=ctx.get("previous_summary"), rolling_summary=ctx.get("rolling_summary"),
            open_hooks=ctx.get("open_hooks"), canon_context=ctx.get("canon_context", ""),
            author_intent=ctx.get("author_intent"), expectation_actions=ctx.get("expectation_actions"),
            locations=ctx.get("locations", []), assets=ctx.get("assets", []),
            relationships=ctx.get("relationships", []), worldview_text=ctx.get("worldview_text", ""),
        )
        recorder = workflow.recorder

        _emit("GENERATION_RUN", {"generation_run_id": run_id, "message": "BS-ADF Track B 恢复已初始化"})
        _emit("BSADF_STAGE", {"stage": "RENDER_RESUMED", "count": len(cards), "message": "逐段渲染"})

        async def _on_progress(event: str, data: dict) -> None:
            if event in ("BSADF_STAGE", "ADF_STAGE"):
                trace.set_stage(str(data.get("stage", "")))
            trace_event(event, **data)
            _emit(event, data)

        result = await workflow.resume_from_slots(
            edited_cards=cards, spine=spine, anchor=anchor, tier=tier,
            target_word_count=target_word_count, max_segments=max_segments,
            progress_callback=_on_progress,
            tier_reason=ctx.get("tier_reason"),
        )

        if result is None:
            _emit("ERROR", {"error": "恢复失败：工作流未返回结果"})
            _set_run_status(run_id, "error", error="工作流未返回结果")
            return

        # 持久化
        try:
            await recorder.flush_to_db(_get_db_for_run(run_id))
            await _get_db_for_run(run_id).commit()
        except Exception as e:
            logger.warning(f"[BS-ADF] confirm-beats RunRecorder 落库失败（不阻塞）: {e}")

        if result.final_text:
            try:
                chapter.draft_text = result.final_text
                chapter.generation_run_id = run_id
                chapter.bsadf_beat_slots = json.dumps(result.debug_info.get("beat_slots", []), ensure_ascii=False)
                await _get_db_for_run(run_id).commit()
            except Exception as e:
                # 风险1修复：不再静默吞掉——落库失败是严重问题（正文会丢失）
                logger.error(f"[BS-ADF] confirm-beats 持久化失败（终稿可能未落库）: {e}", exc_info=True)
                _emit("ERROR", {"error": f"终稿落库失败: {e}"})

        # 推送降级 + 元数据
        for deg in result.degraded:
            _emit("DEGRADED", {"message": f"阶段 {deg.get('phase', '?')} 降级", "phase": deg.get("phase", ""), "reason": deg.get("reason", ""), "detail": str(deg.get("detail", ""))[:200], "beat_id": deg.get("beat_id", ""), "attempts": deg.get("attempts", 0)})

        _emit("BSADF_METADATA", {"message": "本章元数据", "climax_design": climax_to_dict(result.distal_anchor), "story_context": story_context_to_dict(result.spine_track), "audit": audit_to_dict(result.audit), "beat_slots": result.debug_info.get("beat_slots", []), "degraded_beats": result.debug_info.get("degraded_beats", []), "rescue_needed": result.debug_info.get("rescue_needed", [])})
        # 与 Track A 同构的 UNIFIED_METRIC（此前只 Track A 发，Track B 前端指标恒空）
        _emit("UNIFIED_METRIC", {
            "message": "BS-ADF 引擎审计指标",
            "metrics": {"audit": audit_to_dict(result.audit), "stats": result.stats},
        })

        if result.final_text:
            _emit("FINAL_TEXT_STREAM", {"message": "正在输出最终文本"})
            text = result.final_text
            for i in range(0, len(text), 200):
                _emit("TEXT_CHUNK", {"content": text[i:i+200]})

        trace_event("final_text", text=result.final_text or "")
        trace_event("run_complete", stats=result.stats, degraded_count=len(result.degraded), audit_verdict=result.audit.verdict)
        complete_payload = {
            "event": "COMPLETE", "text": result.final_text, "engine": "bsadf", "track": "B",
            "generation_run_id": run_id, "tier": result.tier_decision.get("tier"),
            # 与 Track A complete_payload 字段契约对齐（tier_reason/target_word_count）
            "tier_reason": result.tier_decision.get("reason"),
            "target_word_count": result.tier_decision.get("target_word_count"),
            "segment_count": len(result.segments), "climax_score": result.audit.climax_score,
            "audit_verdict": result.audit.verdict, "stats": result.stats,
            "degraded_count": len(result.degraded),
            "beat_slots": result.debug_info.get("beat_slots", []),
            "degraded_beats": result.debug_info.get("degraded_beats", []),
            "rescue_needed": result.debug_info.get("rescue_needed", []),
        }
        _push_run_event(run_id, complete_payload)
        # 与 Track A 对称：完成后保留 pending（刷新 TTL），供 /rerender-beat
        # 取完整渲染上下文（场景设定/专名表/canon）。此前 pop 导致 Track B
        # 完成后的重渲染只能走空上下文兜底，质量显著低于整章渲染。
        _store_pending_beats(request.run_id, cards, ctx)
        _set_run_status(run_id, "done", result=complete_payload)

    except Exception as e:
        logger.exception(f"[BS-ADF] confirm-beats 后台异常: {e}")
        trace_event("run_error", phase="confirm_resume", error=f"{type(e).__name__}: {str(e)[:300]}")
        _emit("ERROR", {"error": f"恢复失败: {type(e).__name__}: {str(e)[:200]}"})
        _set_run_status(run_id, "error", error=str(e)[:300])
    finally:
        clear_trace()


# DB session 存储：后台 task 需要独立 session（不依赖请求生命周期）
_RUN_DBS: Dict[str, AsyncSession] = {}

def _get_db_for_run(run_id: str) -> AsyncSession:
    """获取后台 task 专属的 DB session（在 _run_confirm_beats 里通过闭包传入更佳，此处保留兼容）。"""
    return _RUN_DBS.get(run_id)


# ============================================================
# POST /confirm-beats —— Track B 恢复（轮询模式）
# ============================================================

@router.post("/{chapter_id}/confirm-beats")
async def confirm_beats(
    chapter_id: str,
    request: ConfirmBeatsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Track B 恢复（SSE 流式）。后台 task 跑 resume_from_slots，SSE 从 dict 读事件。"""
    from backend.database import AsyncSessionLocal

    run_id = f"bsadf_confirm_{uuid4().hex[:12]}"
    _init_run(run_id)
    request.chapter_id = chapter_id

    async def _background():
        async with AsyncSessionLocal() as bg_db:
            _RUN_DBS[run_id] = bg_db
            try:
                await _run_confirm_beats(run_id, request)
            finally:
                _RUN_DBS.pop(run_id, None)

    asyncio.ensure_future(_background())
    return StreamingResponse(_sse_stream_from_run(run_id), media_type="text/event-stream")


# ============================================================
# POST /rerender-beat —— 降级单卡恢复（同步 JSON 响应）
# ============================================================

@router.post("/{chapter_id}/rerender-beat")
async def rerender_beat(
    chapter_id: str,
    request: RerenderBeatRequest,
    db: AsyncSession = Depends(get_db),
):
    """降级单卡重渲染（同步 JSON 响应，非 SSE）。

    Phase 4d 降级的槽位卡（status='degraded'）由作者重新编辑后，用本端点单卡重渲染，
    不重跑全章。优先从 _PENDING_BEAT_SLOTS 取上下文；若已过期则从 DB + chapter
    重建最小上下文（仅渲染必需）。

    edited_slot 可选：提供时用它替代服务端暂存的卡快照重渲染（前端"编辑后再
    重渲染"路径）；缺省时用 _PENDING_BEAT_SLOTS 里该 beat 的卡快照原样重渲。

    Returns:
        JSON: {segment: {...}, card: {...}, degraded: {...|null}, generation_run_id}
    """
    from fastapi import HTTPException
    from backend.repositories import ChapterRepository

    chapter_repo = ChapterRepository(db)
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 优先从 pending 取（同一 run_id 的渲染上下文最完整）：
    # 先按请求带的 run_id 精确查；缺失/miss 时按 beat_id 扫描兜底
    pending = _load_pending_beats(request.run_id) if request.run_id else None
    if pending is None:
        pending = _find_pending_by_beat(request.beat_id)
    ctx_dict = pending.get("ctx") if pending else None

    if request.edited_slot is not None:
        edited_card = beat_slot_from_dict(request.edited_slot.model_dump())
        edited_card.edited = True
        edited_card.edit_count += 1
        edited_card.status = "pending"
    else:
        snapshot = next(
            (
                c for c in (pending.get("cards", []) if pending else [])
                if getattr(c, "beat_id", None) == request.beat_id
            ),
            None,
        )
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail="未提供 edited_slot，且服务端无该槽位卡快照（pending 不存在或已过期）",
            )
        edited_card = snapshot
        edited_card.status = "pending"

    # 从 DB slots 取该卡的历史快照（兜底：找 anchor/spine 不可能，只能渲染单段）
    db_slots_raw = []
    try:
        raw = getattr(chapter, "bsadf_beat_slots", None)
        if isinstance(raw, str):
            db_slots_raw = json.loads(raw) if raw else []
        elif isinstance(raw, list):
            db_slots_raw = raw
    except Exception as e:
        logger.warning(f"[BS-ADF] rerender-beat 解析 bsadf_beat_slots 失败: {e}")

    # 找该 beat 的前段尾段作为 rolling_prefix（兜底空串）
    rolling_prefix = "（单卡重渲染）"
    for slot_dict in db_slots_raw:
        if slot_dict.get("beat_id") == request.beat_id:
            # 找前一段（segment_index - 1）的尾段
            prev_idx = slot_dict.get("segment_index", 0) - 1
            if prev_idx >= 0 and prev_idx < len(db_slots_raw):
                # 没有正文快照（slots 不含 text），用 carrier 兜底
                rolling_prefix = (
                    db_slots_raw[prev_idx].get("text_carrier")
                    or "（前段无快照）"
                )
            break

    # 构建最小 workflow 上下文（仅渲染必需；anchor/spine 用空对象兜底）
    # 注意：单卡重渲染不要求 anchor 完整，仅 emotion_curve_text 需要 samples
    from backend.services.workflows.adf.types import (
        ChapterClimax, ClimaxSpec, EmotionCurve, EmotionCurveSample,
    )
    anchor = ctx_dict.get("anchor") if ctx_dict else None
    if anchor is None:
        anchor = ChapterClimax(
            climax=ClimaxSpec(description="（rerender 兜底）", intensity=5),
            emotion_curve=EmotionCurve(samples=[
                EmotionCurveSample(progress=0.0, register="入口", energy=3),
                EmotionCurveSample(progress=1.0, register="收束", energy=5),
            ]),
        )

    from backend.services.prompts.adf_prompts import format_emotion_curve
    from backend.services.workflows.adf.segment_writer import (
        _build_style_contract,
        _build_compact_canon_hint,
        _build_knowledge_constraints,
    )
    from backend.services.workflows.adf.name_registry import build_name_registry, registry_to_prompt_block
    from backend.services.workflows.adf.setting_resolver import (
        build_scene_setting_text,
        resolve_characters,
        resolve_hidden_constraints,
    )
    from backend.services.workflows.bsadf.downgrade import render_with_downgrade

    run_id = f"rerender_{uuid4().hex[:12]}"
    recorder = RunRecorder(chapter_id=chapter_id, run_id=run_id)
    trace = create_trace(run_id, "bsadf_rerender", chapter_id)
    trace.set_stage("RERENDER")
    trace_event(
        "rerender_start",
        beat_id=request.beat_id,
        edited_slot=request.edited_slot.model_dump() if request.edited_slot else None,
        context_source="pending" if ctx_dict else "db_fallback",
    )

    style_contract = _build_style_contract(getattr(chapter, "style_card", None))
    emotion_curve_text = format_emotion_curve([
        {"progress": s.progress, "register": s.register, "energy": s.energy}
        for s in anchor.emotion_curve.samples
    ])
    # 有 pending 上下文时重建与整章渲染一致的场景设定/专名表/写作期防线；
    # 否则空兜底
    canon_hint = ""
    knowledge_constraints: List[str] = []
    if ctx_dict:
        scene_setting_text = build_scene_setting_text(
            ctx_dict.get("entities", []),
            ctx_dict.get("locations", []),
            ctx_dict.get("assets", []),
            ctx_dict.get("relationships", []),
        )
        name_registry_block = registry_to_prompt_block(build_name_registry(
            ctx_dict.get("entities", []),
            ctx_dict.get("locations", []),
            ctx_dict.get("assets", []),
            ctx_dict.get("canon_context", ""),
        ))
        canon_hint = _build_compact_canon_hint(ctx_dict.get("canon_context", ""))
        knowledge_constraints = _build_knowledge_constraints(
            ctx_dict.get("canon_context", ""),
            resolve_hidden_constraints(
                ctx_dict.get("relationships", []),
                resolve_characters(ctx_dict.get("entities", [])),
            ),
        )
    else:
        scene_setting_text = build_scene_setting_text([], [], [], [])
        name_registry_block = registry_to_prompt_block(build_name_registry([], [], [], ""))

    try:
        segment, card, degraded = await render_with_downgrade(
            card=edited_card,
            rolling_prefix=rolling_prefix,
            scene_setting_text=scene_setting_text,
            name_registry_block=name_registry_block,
            state_card_block="",
            emotion_curve_text=emotion_curve_text,
            style_contract=style_contract,
            genre=None,
            recorder=recorder,
            prev_card_state=None,
            knowledge_constraints=knowledge_constraints,
            canon_hint=canon_hint,
        )
    except Exception as e:
        logger.exception(f"[BS-ADF] rerender-beat 渲染失败: {e}")
        trace_event("run_error", phase="rerender", error=f"{type(e).__name__}: {str(e)[:300]}")
        clear_trace()
        raise HTTPException(status_code=500, detail=f"单卡渲染失败: {e}")

    # recorder 落库
    try:
        await recorder.flush_to_db(db)
        await db.commit()
    except Exception as e:
        logger.warning(f"[BS-ADF] rerender-beat recorder 落库失败（不阻塞）: {e}")

    trace_event(
        "rerender_result",
        beat_id=card.beat_id,
        status=card.status,
        degraded_reason=degraded.reason if degraded else None,
        segment_text=segment.text,
    )
    clear_trace()

    return {
        "chapter_id": chapter_id,
        "generation_run_id": run_id,
        "segment": {
            "index": segment.index,
            "text": segment.text,
            "scene_summary": segment.scene_summary,
            "emotion_register": segment.emotion_register,
            "landed_preconditions": segment.landed_preconditions,
        },
        "card": beat_slot_to_dict(card),
        "degraded": (
            {
                "beat_id": degraded.beat_id,
                "segment_index": degraded.segment_index,
                "reason": degraded.reason,
                "attempts": degraded.attempts,
            }
            if degraded is not None
            else None
        ),
    }


@router.post("/{chapter_id}/advance-beat")
async def advance_beat(
    chapter_id: str,
    request: AdvanceBeatRequest,
):
    """NLE-ADF 步进推进（SSE 流式）。

    把作者对当前段的裁决（pass/edit/branch/skip）塞进 stepping_run 的 action_queue，
    然后开 SSE 流把 stepping_loop 后续产出的事件（BEAT_RENDER_READY / BEAT_LOCKED /
    BEAT_SKIPPED / COMPLETE 等）逐条 yield 出去，直到碰到终态事件（BEAT_RENDER_READY
    表示新段已就绪待下次裁决；COMPLETE 表示全章完成）。
    """
    from fastapi import HTTPException
    from backend.services.workflows.bsadf.stepping_runtime import _STEPPING_RUNS

    run = _STEPPING_RUNS.get(request.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    # 风险8修复：索引越界守卫（异常态：run 已完成/cards 空/current 越界）
    if not run.cards or run.current_beat_index >= len(run.cards):
        raise HTTPException(status_code=409, detail="RUN_FINISHED")
    if run.cards[run.current_beat_index].beat_id != request.beat_id:
        raise HTTPException(status_code=409, detail="BEAT_NOT_CURRENT")

    # 等待当前段渲染完成（BEAT_RENDER_READY）再接受裁决。
    # 防止段还在渲染中就 pass 导致事件错乱（pass 的 BEAT_LOCKED 会被
    # 当前段的 BEAT_RENDER_READY 抢先，SSE 流提前终止）。
    # 岔路门挂起（awaiting_branch_choice）时渲染尚未开始，本次裁决正是
    # 来解除挂起的（branch/pass/skip），跳过 ready 等待直接放行。
    if not run.awaiting_branch_choice:
        for _ in range(240):  # 最长等 120 秒（240 × 0.5s）
            if run.current_segment_ready or run.status in ("done", "error", "post_processing"):
                break
            await asyncio.sleep(0.5)
        if not run.current_segment_ready and run.status == "stepping":
            raise HTTPException(status_code=409, detail="SEGMENT_NOT_READY")

    action_payload: Dict[str, Any] = {
        "action": request.action,
        "beat_id": request.beat_id,
    }
    if request.action == "edit" and request.edited_slot is not None:
        action_payload["edited_slot"] = request.edited_slot.model_dump()
    elif request.action == "branch" and request.branch_choice:
        action_payload["branch_choice"] = request.branch_choice

    # 清空 event_queue 里的遗留事件（当前段的 BEAT_RENDER_START/CHUNK/READY）。
    # advance-beat 的 SSE 流只消费 pass 之后的新事件（BEAT_LOCKED + 下一段序列）。
    while not run.event_queue.empty():
        try:
            run.event_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    await run.action_queue.put(action_payload)
    _STEPPING_RUNS.touch(request.run_id)

    async def _stream():
        from backend.services.utils.sse import build_sse_event, build_sse_error
        try:
            while True:
                try:
                    ev_name, ev_data = await asyncio.wait_for(run.event_queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    yield build_sse_error("步进推进超时（120s 无事件）")
                    return
                yield build_sse_event(ev_name, "", **ev_data)
                # BEAT_BRANCH_CHOICE 同属终态：下一段的岔路门挂起等作者选走向，
                # 作者提交时会新开一条 advance-beat SSE。本流须优雅结束（不报错），
                # 否则挂起期间 120s 无事件会误报"步进推进超时"，且继续挂着会与
                # 下一条流争抢 event_queue 消费。
                if ev_name in ("BEAT_RENDER_READY", "COMPLETE", "BEAT_RERENDERED", "BEAT_BRANCH_CHOICE"):
                    return
        except Exception as e:
            yield build_sse_error(f"步进流异常: {e}")

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/stepping-run/{run_id}/state")
async def get_stepping_run_state(run_id: str):
    """查询步进运行状态（前端轮询/恢复展示用）。"""
    from fastapi import HTTPException
    from backend.services.workflows.bsadf.stepping_runtime import _STEPPING_RUNS
    run = _STEPPING_RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return {
        "run_id": run.run_id,
        "chapter_id": run.chapter_id,
        "current_beat_index": run.current_beat_index,
        "current_beat_id": run.cards[run.current_beat_index].beat_id if run.cards else None,
        "current_segment_ready": run.current_segment_ready,
        "current_segment_text": (
            run.locked_segments[-1].text if run.locked_segments else
            (getattr(run, "_pending_segment_text", "") or "")
        ),
        "locked_count": len(run.locked_segments),
        "total_beats": len(run.cards),
        "status": run.status,
        "cards": [
            c.beat_id if hasattr(c, "beat_id") else (c.get("beat_id", "") if isinstance(c, dict) else "")
            for c in run.cards
        ],
    }


@router.delete("/stepping-run/{run_id}")
async def delete_stepping_run(run_id: str):
    """销毁步进运行（前端取消/退出步进面板时调用，释放内存）。"""
    from backend.services.workflows.bsadf.stepping_runtime import _STEPPING_RUNS
    run = _STEPPING_RUNS.pop(run_id)
    if run is None:
        return {"ok": False, "reason": "RUN_NOT_FOUND"}
    return {"ok": True}


