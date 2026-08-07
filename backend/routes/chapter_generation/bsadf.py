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

API 端点（前缀 /api/chapters/{chapter_id}）:
- POST /generate-bsadf   BS-ADF 引擎生成（SSE 事件序列）

SSE 事件序列（BS-ADF 专属 + 复用 ADF）:
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

⚠ 前端交互模式（2026-07-31 现状）：
当前 UI 只使用「步进模式（enable_stepping=true）」。Track A/B 是历史/兼容路径，
保留在路由层，但前端不再调用 track='B' 的暂停编辑流程。/confirm-beats 仅作为
历史端点保留，活跃路径为：
  generate-bsadf(enable_stepping=true) → STEPPING_INITIALIZED → /advance-beat 循环 → COMPLETE
Track A/B 注释仅说明兼容行为，未来若重新启用再维护。

使用方式：
    POST /api/chapters/{chapter_id}/generate-bsadf
    body: {"tier": "auto", "track": "A", "target_word_count": null, "max_segments": 6, "enable_stepping": true}
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
    StitchFragmentRequest,
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
# 实时流说明
# ============================================================
# SSE 空闲保活：长耗时阶段（如 Phase 4c 逐段渲染、后处理守卫）期间若无业务事件，
# 各 SSE 生成器按固定间隔发 HEARTBEAT data 帧（必须是 data 帧而非 SSE 注释帧
# ": heartbeat\n\n"——很多浏览器/代理只把 data 帧视为"连接活跃"），防止空闲掐断。


# ============================================================
# 内存存储：生成运行后台 task + 步进循环 task（供取消/清理）
# ============================================================
# _RUN_TASKS: {run_id: asyncio.Task} — generate-bsadf / confirm-beats 的后台 task
# _STEPPING_RUN_TASKS: {run_id: asyncio.Task} — 步进循环 stepping_loop task
# 注意：当前前端只使用步进模式；生成 task 在步进初始化后很快退出，
# 真正长时间运行的是 stepping_loop task。
_RUN_TASKS: Dict[str, asyncio.Task] = {}
_STEPPING_RUN_TASKS: Dict[str, asyncio.Task] = {}


def _cleanup_run_tasks(run_id: str) -> None:
    """取消并清理某 run_id 关联的后台 task + 步进循环 task + 暂存上下文。"""
    task = _RUN_TASKS.pop(run_id, None)
    if task and not task.done():
        task.cancel()
    stepping_task = _STEPPING_RUN_TASKS.pop(run_id, None)
    if stepping_task and not stepping_task.done():
        stepping_task.cancel()
    _PENDING_BEAT_SLOTS.pop(run_id, None)
    run_data = _GENERATION_RUNS.get(run_id)
    if run_data is not None:
        run_data["status"] = "error"
        run_data["error"] = "已取消"


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
# 运行事件中转：后台 task → SSE 生成器
# ============================================================
# 设计：workflow 跑在后台 asyncio.Task 里，progress_callback 把事件 append 到
# _GENERATION_RUNS[run_id]["events"] 列表；SSE 生成器（generate-bsadf /
# confirm-beats / advance-beat 各自一条流）增量读取并 yield 给前端，
# SSE 断连不影响后台执行。
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
                stepping_result = await workflow.execute_stepping(
                    progress_callback=_on_progress,
                    # NLE-ADF 2.0 作者模式 = 轻卡快速通道：4a 种子卡即挂起，
                    # Loop1/enrich/DDE 由下方后台 task 续跑（开门等待 ~1-3min → ~15-30s）
                    lazy_enhancements=getattr(self.request, "enable_authoring", False),
                )
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
                    authoring_mode=getattr(self.request, "enable_authoring", False),
                )
                workflow._paused_spine = stepping_result.spine_track
                workflow._paused_anchor = stepping_result.distal_anchor
                workflow._emotion_curve_samples = stepping_result.debug_info.get("emotion_curve_samples", [])

                _STEPPING_RUNS.set(stepping_run)
                enable_mem = getattr(self.request, "enable_memory_ingestion", False)
                stepping_task = asyncio.ensure_future(stepping_loop(stepping_run, enable_memory_ingestion=enable_mem))
                _STEPPING_RUN_TASKS[run_id] = stepping_task

                def _stepping_done(t: asyncio.Task) -> None:
                    _STEPPING_RUN_TASKS.pop(run_id, None)
                    cancelled = False
                    try:
                        t.result()
                    except asyncio.CancelledError:
                        cancelled = True
                    except Exception as e:
                        logger.exception(f"[BS-ADF] stepping_loop task 异常结束 run={run_id}: {e}")
                    if not cancelled:
                        # 步进模式落库（此前缺失：recorder 从不 flush，generation_runs
                        # 零记录，洞察视图成本/质量报告对步进生成章节恒空）。
                        # 正文仍由前端 COMPLETE 后 PUT 落库，这里只落 token/用量统计；
                        # 失败不阻塞（与 Track A/B 落库失败降级一致）。
                        try:
                            async def _flush_recorder() -> None:
                                from backend.database import AsyncSessionLocal
                                async with AsyncSessionLocal() as flush_db:
                                    await recorder.flush_to_db(flush_db)
                                    await flush_db.commit()
                            asyncio.ensure_future(_flush_recorder())
                        except Exception as e:
                            logger.warning(f"[BS-ADF] stepping recorder 落库失败（不阻塞）: {e}")
                        # 暂存 rerender 上下文（此前步进从不 _store_pending_beats →
                        # 完成后「重写本段」必走空上下文兜底：无 canon/专名表/知识约束，
                        # 渲染质量显著低于整章渲染）。卡取 stepping_run.cards 终态
                        # （含渲染后 status 与 branch_directive）。
                        if stepping_run.status == "done":
                            try:
                                rerender_ctx = {
                                    "spine": stepping_result.spine_track,
                                    "anchor": stepping_result.distal_anchor,
                                    "entities": ctx.get("entities", []),
                                    "locations": ctx.get("locations", []),
                                    "assets": ctx.get("assets", []),
                                    "relationships": ctx.get("relationships", []),
                                    "canon_context": ctx.get("canon_context", ""),
                                    "worldview_text": ctx.get("worldview_text", ""),
                                }
                                _store_pending_beats(run_id, stepping_run.cards, rerender_ctx)
                            except Exception as e:
                                logger.warning(f"[BS-ADF] stepping 暂存 rerender 上下文失败（不阻塞）: {e}")

                stepping_task.add_done_callback(_stepping_done)

                # NLE-ADF 2.0 懒增强后台续跑：Loop1 → enrich → DDE 完成时就地
                # 更新 run.cards / decision_set，并置 cards_enhanced 标记。
                # 增强失败绝不砸会话（种子卡已可创作，增强只是质量加成）。
                if getattr(self.request, "enable_authoring", False):
                    async def _lazy_enhance() -> None:
                        try:
                            out = await workflow.run_lazy_enhancements(
                                cards=stepping_run.cards,
                                progress_callback=_on_progress,
                            )
                            stepping_run.decision_set = out.get("decision_set") or {}
                            stepping_run.loop1_result = out.get("loop1_result")
                            stepping_run.cards_enhanced = True
                            # 事件队列通知（下一条 advance-beat SSE 会交付；
                            # 队列入口的选择性清场对本事件放行）
                            await stepping_run.event_queue.put(("BEAT_CARDS_ENRICHED", {
                                "beat_slots": [beat_slot_to_dict(c) for c in stepping_run.cards],
                                "decision_set": stepping_run.decision_set,
                                "loop1_result": stepping_run.loop1_result,
                            }))
                        except Exception as e:
                            logger.warning(f"[BS-ADF] 懒增强后台 task 异常（保持种子卡）: {e}")
                    asyncio.ensure_future(_lazy_enhance())

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
                            stepping_run.event_queue.get(), timeout=300.0
                        )
                        _emit(ev_name, ev_data)
                        if ev_name in ("BEAT_BRANCH_CHOICE", "BEAT_AUTHORING_OPEN"):
                            # 岔路门/作者模式：步进循环挂起等作者（时长由作者决定，
                            # 不受超时约束）。作者提交时 advance-beat 会新开 SSE
                            # 流交付后续事件，本桥接直接退出——继续空等只会触发
                            # 超时误报（岔路门已发生过的真实事故，作者模式同理）。
                            break
                    except asyncio.TimeoutError:
                        _emit("ERROR", {"error": "首段渲染超时（300s）"})
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

    ⚠ 前端当前只使用步进模式（enable_stepping=true）。Track A/B 为历史兼容路径，
    活跃流程：generate-bsadf → 跑到 Phase 4b 暂停 → 起 stepping_loop →
    STEPPING_INITIALIZED → 前端用 /advance-beat 逐段推进 → COMPLETE。

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
        try:
            async with AsyncSessionLocal() as bg_db:
                handler = _BSAdfStreamHandler(chapter_id=chapter_id, request=req, db=bg_db)
                await handler._run_generate(run_id)
        finally:
            _RUN_TASKS.pop(run_id, None)

    task = asyncio.ensure_future(_background())
    _RUN_TASKS[run_id] = task

    def _gen_done(t: asyncio.Task) -> None:
        _RUN_TASKS.pop(run_id, None)
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"[BS-ADF] generate-bsadf task 异常结束 run={run_id}: {e}")

    task.add_done_callback(_gen_done)

    return StreamingResponse(_sse_stream_from_run(run_id), media_type="text/event-stream")


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
    """Track B 恢复（SSE 流式）。后台 task 跑 resume_from_slots，SSE 从 dict 读事件。

    ⚠ 前端当前只使用步进模式，不再进入 Track B 暂停编辑流程。本端点保留为
    历史兼容；活跃推进路径是 /advance-beat。
    """
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
                _RUN_TASKS.pop(run_id, None)

    task = asyncio.ensure_future(_background())
    _RUN_TASKS[run_id] = task

    def _confirm_done(t: asyncio.Task) -> None:
        _RUN_TASKS.pop(run_id, None)
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"[BS-ADF] confirm-beats task 异常结束 run={run_id}: {e}")

    task.add_done_callback(_confirm_done)
    return StreamingResponse(_sse_stream_from_run(run_id), media_type="text/event-stream")


# ============================================================
# POST /cancel-run/{run_id} —— 取消生成/步进运行（释放资源）
# ============================================================

@router.post("/{chapter_id}/cancel-run/{run_id}")
async def cancel_run(chapter_id: str, run_id: str):
    """取消指定 run_id 的后台生成/步进运行，并清理内存/暂存上下文。

    前端在以下场景调用：
    - 用户点击生成面板的"取消"按钮
    - 关闭生成覆盖层 / 切换章节 / 组件卸载
    - 刷新页面前（可选，防止后端僵尸 task）
    """
    from backend.services.workflows.bsadf.stepping_runtime import _STEPPING_RUNS

    _cleanup_run_tasks(run_id)
    stepping_run = _STEPPING_RUNS.pop(run_id, None)
    if stepping_run is not None:
        try:
            stepping_run.event_queue.put_nowait(("ERROR", {"error": "已取消"}))
        except Exception:
            pass

    logger.info(f"[BS-ADF] 取消运行 run={run_id} chapter={chapter_id}")
    return {"ok": True, "run_id": run_id}


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
    # 终态守卫：循环已退出（post_processing/done/error）时动作入队无人消费，
    # 此前靠 current_beat_index 越界判断（循环结束后索引停在 len-1，恒不触发）
    # → 请求空挂到 SSE 超时误报。按 status 直接拒绝。
    if run.status != "stepping":
        raise HTTPException(status_code=409, detail="RUN_FINISHED")
    # 风险8修复：索引越界守卫（异常态：cards 空/current 越界）
    if not run.cards or run.current_beat_index >= len(run.cards):
        raise HTTPException(status_code=409, detail="RUN_FINISHED")
    if run.cards[run.current_beat_index].beat_id != request.beat_id:
        raise HTTPException(status_code=409, detail="BEAT_NOT_CURRENT")
    # edit 必须带 edited_slot（此前无校验，静默落到循环尾重渲染当前段，
    # 作者的卡编辑被无声丢弃）
    if request.action == "edit" and request.edited_slot is None:
        raise HTTPException(status_code=422, detail="EDIT_REQUIRES_SLOT")

    # 等待当前段渲染完成（BEAT_RENDER_READY）再接受裁决。
    # 防止段还在渲染中就 pass 导致事件错乱（pass 的 BEAT_LOCKED 会被
    # 当前段的 BEAT_RENDER_READY 抢先，SSE 流提前终止）。
    # 岔路门挂起（awaiting_branch_choice）时渲染尚未开始，本次裁决正是
    # 来解除挂起的（branch/pass/skip），跳过 ready 等待直接放行。
    # 岔路门挂起（awaiting_branch_choice）或作者模式挂起（awaiting_authoring）时
    # 渲染尚未开始，本次裁决正是来解除挂起的，跳过 ready 等待直接放行。
    if not run.awaiting_branch_choice and not getattr(run, "awaiting_authoring", False):
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
    elif request.action == "lock_with_text" and request.author_text is not None:
        # P2：作者直接定稿段正文（跳过 LLM，仍抽状态卡）。透传 author_text 给 stepping loop。
        action_payload["author_text"] = request.author_text

    # 清空 event_queue 里的遗留事件（当前段的 BEAT_RENDER_START/CHUNK/READY）。
    # advance-beat 的 SSE 流只消费 pass 之后的新事件（BEAT_LOCKED + 下一段序列）。
    # 例外：BEAT_CARDS_ENRICHED（懒增强完成通知）选择性保留——它是跨段有效的
    # 卡增强载荷，随本条流交付给前端刷新零件/决策集。
    _kept_events: list = []
    while not run.event_queue.empty():
        try:
            _ev = run.event_queue.get_nowait()
            if _ev[0] == "BEAT_CARDS_ENRICHED":
                _kept_events.append(_ev)
        except asyncio.QueueEmpty:
            break
    for _ev in _kept_events:
        run.event_queue.put_nowait(_ev)

    await run.action_queue.put(action_payload)
    _STEPPING_RUNS.touch(request.run_id)

    async def _stream():
        from backend.services.utils.sse import build_sse_event, build_sse_error
        try:
            while True:
                try:
                    ev_name, ev_data = await asyncio.wait_for(run.event_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # 心跳保活替代 120s 硬超时：单段渲染（2 次尝试+退避）或后处理
                    # 单阶段（守卫 reasoning+手术+复验）均可超过 120s，硬超时会把
                    # 健康会话误杀（前端双通道同时判死，只能从头重生成——真实事故）。
                    # HEARTBEAT 帧前端 sse.ts 直接忽略，不触发任何业务回调。
                    yield build_sse_event("HEARTBEAT", "")
                    # run 已终态且队列排空 → 不会再有事件，防流空挂
                    if run.status in ("done", "error") and run.event_queue.empty():
                        return
                    continue
                yield build_sse_event(ev_name, "", **ev_data)
                # BEAT_BRANCH_CHOICE 同属终态：下一段的岔路门挂起等作者选走向，
                # 作者提交时会新开一条 advance-beat SSE。本流须优雅结束（不报错），
                # 否则挂起期间无事件会让前端等空，且继续挂着会与下一条流争抢
                # event_queue 消费。ERROR 同为终态（循环异常兜底），不再空挂。
                # BEAT_AUTHORING_OPEN 亦属终态：作者模式下一段拍挂起等创作，
                # 作者的下一个动作（render/lock_with_text/skip/back）会新开流。
                if ev_name in ("BEAT_RENDER_READY", "COMPLETE", "BEAT_BRANCH_CHOICE", "BEAT_AUTHORING_OPEN", "ERROR"):
                    return
        except Exception as e:
            yield build_sse_error(f"步进流异常: {e}")

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ============================================================
# NLE-ADF 2.0：微缝合（stitch）
# ============================================================

_STITCH_MAX_CHARS = 160   # 超出即触发句界截断（契约 80~120 字 ×1.3 容忍带）
_STITCH_CUT_CHARS = 130   # 句界截断目标长度


def _truncate_stitch_at_sentence(text: str) -> str:
    """超长缝合文本的句界截断：在 _STITCH_CUT_CHARS 附近找最后一个句末标点切掉。

    与整段渲染的字数硬闸门同思路（宁缺勿残），但尺度是碎片级。
    找不到句界标点时硬切 _STITCH_CUT_CHARS（兜底，防无限长）。
    """
    text = text.strip()
    if len(text) <= _STITCH_MAX_CHARS:
        return text
    window = text[:_STITCH_MAX_CHARS]
    cut = -1
    for mark in ("。", "！", "？", "…", "”"):
        pos = window.rfind(mark, 0, _STITCH_CUT_CHARS + 1)
        if pos > cut:
            cut = pos
    if cut >= 30:  # 至少保住一个像样的句子，否则不如硬切
        return window[: cut + 1]
    return text[:_STITCH_CUT_CHARS]


@router.post("/{chapter_id}/stitch")
async def stitch_fragment(
    chapter_id: str,
    request: StitchFragmentRequest,
):
    """NLE-ADF 2.0 微缝合（SSE 流式，打字机推流）。

    作者按 Space 触发：把【作者原句碎片】+【点选的镜头零件】用白描契约缝合成
    80~120 字片段。轻量路径：不调 render_one/降级状态机、不抽状态卡、不写库——
    深护栏（去味剪枝/残句门禁/一致性守卫）在拍锁死与后处理时统一跑。

    SSE 事件序列：STITCH_START → STITCH_CHUNK × N（~6 字/帧，90ms 间隔，打字机感）
    → STITCH_DONE {text, word_count, fragment_preserved}；失败 STITCH_ERROR。
    """
    from fastapi import HTTPException
    from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
    from backend.services.prompts.bsadf_prompts import build_stitch_prompt
    from backend.services.workflows.bsadf.stepping_runtime import _STEPPING_RUNS

    # 双路：有 run = 拍卡引导缝合（方向+专名表）；无 run = 自由缝合
    # （零门槛开局期，管线未就绪——缝合不等卡，白描契约不变）。
    card = None
    proper_nouns: List[str] = []
    if request.run_id:
        run = _STEPPING_RUNS.get(request.run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
        if run.status != "stepping":
            raise HTTPException(status_code=409, detail="RUN_FINISHED")
        if not run.cards or run.current_beat_index >= len(run.cards):
            raise HTTPException(status_code=409, detail="RUN_FINISHED")
        card = run.cards[run.current_beat_index]
        if request.beat_id and card.beat_id != request.beat_id:
            raise HTTPException(status_code=409, detail="BEAT_NOT_CURRENT")
        # 专名表（角色+资产名，上限 20）：微缝合是小预算调用，无专名约束极易
        # 称呼漂移造名（"老烟"变"老烟枪"）；从 workflow 持有上下文取，0 LLM。
        workflow = getattr(run, "workflow", None)
        for coll_name in ("entities", "assets"):
            for item in getattr(workflow, coll_name, None) or []:
                name = getattr(item, "name", "") or (item.get("name") if isinstance(item, dict) else "")
                if name and name not in proper_nouns:
                    proper_nouns.append(name)
        proper_nouns = proper_nouns[:20]

    fragment = request.fragment.strip()
    rolling_prefix = (request.rolling_prefix or "")[-200:].strip()
    system_prompt, user_prompt = build_stitch_prompt(
        fragment=fragment,
        picked_parts=request.picked_parts,
        rolling_prefix=rolling_prefix,
        core_plot_event=(getattr(card, "core_plot_event", "") or "") if card else "",
        text_carrier=(getattr(card, "text_carrier", "") or "") if card else "",
        proper_nouns=proper_nouns,
    )

    async def _stream():
        try:
            # 非流式拿全量再打字机式分块：LLM 首 token 延迟（1~3s）无法压缩，
            # 但吐出节奏可控——100 字按 ~6 字/90ms 匀速浮现，体感"现场缝合"。
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                max_tokens=400,
                reasoning_config=REASONING_DISABLED,
            )
            text = (result.content or "").strip().strip('"').strip('"').strip()
            if not text:
                yield build_sse_event("STITCH_ERROR", "", error="缝合产出为空，请重试")
                return
            text = _truncate_stitch_at_sentence(text)
            # 硬契约自检：作者原句必须一字不改保留。违例时前置原句兜底
            # （宁拙勿缺——原句是作者主权文本，丢失比生硬衔接更严重）。
            fragment_preserved = fragment in text
            if not fragment_preserved:
                logger.warning(
                    f"[stitch] 作者原句未被保留 run={request.run_id} beat={request.beat_id}，前置兜底"
                )
                text = f"{fragment}{text}"
            yield build_sse_event("STITCH_START", "", beat_id=request.beat_id)
            # 打字机式分块推流（~6 字/帧 × 90ms ≈ 100 字 1.5s 吐完）
            chunk_size = 6
            for pos in range(0, len(text), chunk_size):
                yield build_sse_event(
                    "STITCH_CHUNK", "",
                    beat_id=request.beat_id,
                    delta=text[pos: pos + chunk_size],
                )
                await asyncio.sleep(0.09)
            yield build_sse_event(
                "STITCH_DONE", "",
                beat_id=request.beat_id,
                text=text,
                word_count=len(text),
                fragment_preserved=fragment_preserved,
            )
        except Exception as e:
            logger.warning(f"[stitch] 缝合失败 run={request.run_id} beat={request.beat_id}: {e}")
            yield build_sse_event("STITCH_ERROR", "", error=f"缝合失败: {e}")

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _degraded_hint_for_run(run: Any) -> Optional[Dict[str, Any]]:
    """从步进 run 当前卡快照还原降级提示（reason 无法从卡还原，给通用值）。

    stepping_loop 的 BEAT_RENDER_READY.degraded 是一次性事件，SSE 断流后
    前端轮询无法拿到——卡的 status='degraded' 是持久态，据此重建提示。
    """
    cards = getattr(run, "cards", None) or []
    idx = getattr(run, "current_beat_index", 0)
    if not cards or idx < 0 or idx >= len(cards):
        return None
    card = cards[idx]
    if getattr(card, "status", "") != "degraded":
        return None
    return {
        "beat_id": getattr(card, "beat_id", ""),
        "segment_index": getattr(card, "segment_index", idx),
        "reason": "render_degraded",
        "attempts": getattr(card, "render_attempts", 2),
    }


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
        # 等裁决态（ready=True）时当前段正文在 _pending_segment_text（尚未入 locked）；
        # 渲染中/非 ready 时 _pending 是上一段的残留，应回退到最后一条 locked 正文
        "current_segment_text": (
            (getattr(run, "_pending_segment_text", "") or "")
            if run.current_segment_ready
            else (run.locked_segments[-1].text if run.locked_segments else "")
        ),
        "locked_count": len(run.locked_segments),
        "total_beats": len(run.cards),
        "status": run.status,
        "cards": [
            c.beat_id if hasattr(c, "beat_id") else (c.get("beat_id", "") if isinstance(c, dict) else "")
            for c in run.cards
        ],
        # 步进循环终态产物（status=done 时非空）：SSE 断流丢失 COMPLETE 帧后，
        # 前端轮询本端点凭 final_result 补齐 done 落地（终稿/统计/rescue_needed），
        # 否则界面永久卡后处理态、正文永不落库
        "final_result": run.final_result,
        # 当前卡降级态（SSE 断流自愈恢复降级提示用；reason 无法从卡快照还原，
        # 给通用值 render_degraded）
        "current_segment_degraded": _degraded_hint_for_run(run),
        # 岔路门挂起状态（前端轮询自愈用）：
        # SSE 断流导致 BEAT_BRANCH_CHOICE 事件丢失时，前端靠轮询发现
        # awaiting_branch_choice=true 重建 branchChoicePending，切 beat_branch_choosing。
        "awaiting_branch_choice": run.awaiting_branch_choice,
        "pending_branch": run.pending_branch,
        # 作者模式挂起状态（NLE-ADF 2.0，前端轮询自愈用）：
        # SSE 断流导致 BEAT_AUTHORING_OPEN 丢失时，前端靠轮询发现
        # awaiting_authoring=true，凭 pending_authoring 的拍卡快照重建画布创作态。
        "awaiting_authoring": getattr(run, "awaiting_authoring", False),
        "pending_authoring": getattr(run, "pending_authoring", None),
        # NLE-ADF 2.0 懒增强就绪标记：轻卡通道下增强（enrich/DDE/Loop1）后台
        # 完成后置 True；前端创作期慢查本字段，True 时取增强卡与决策集刷新零件。
        "cards_enhanced": getattr(run, "cards_enhanced", False),
        "enhanced_beat_slots": (
            [beat_slot_to_dict(c) for c in run.cards]
            if getattr(run, "cards_enhanced", False) else None
        ),
        "enhanced_decision_set": (
            run.decision_set if getattr(run, "cards_enhanced", False) else None
        ),
        "loop1_result": getattr(run, "loop1_result", None),
    }


@router.delete("/stepping-run/{run_id}")
async def delete_stepping_run(run_id: str):
    """销毁步进运行（前端取消/退出步进面板时调用，释放内存）。

    同时取消关联的后台 task 与步进循环 task，清理 pending 上下文。
    """
    from backend.services.workflows.bsadf.stepping_runtime import _STEPPING_RUNS
    _cleanup_run_tasks(run_id)
    run = _STEPPING_RUNS.pop(run_id)
    if run is None:
        return {"ok": False, "reason": "RUN_NOT_FOUND"}
    return {"ok": True}


