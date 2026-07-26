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
- BEAT_SLOTS_BUILT         槽位卡构建完成（count 张）
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
- track='A'（默认）：全自动跑完全程
- track='B'：跑到 Phase 4a 暂停（P3 实现；当前版本 Track B 也跑完全程，BEAT_SLOTS_BUILT 事件后理论上应暂停）

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
    ConfirmBeatsRequest,
    GenerateBSAdfRequest,
    RerenderBeatRequest,
)
from backend.services.observability.run_recorder import RunRecorder
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
# SSE 心跳间隔（秒）。长耗时阶段（如 Phase 4c 逐段渲染）期间若无业务事件，
# 每 HEARTBEAT_INTERVAL 秒发一个 SSE 注释帧（": heartbeat\n\n"），防止代理/中间件
# 因空闲掐断连接。前端 streamSse 因 line.startsWith('data: ') 检查会自动忽略注释帧。
HEARTBEAT_INTERVAL = 15


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


def _pop_pending_beats(run_id: str) -> Optional[Dict[str, Any]]:
    _cleanup_expired_beats()
    return _PENDING_BEAT_SLOTS.pop(run_id, None)


# ============================================================
# SSE 事件格式化
# ============================================================

def _format_bsadf_event(event: str, data: dict) -> str:
    """把单个 BS-ADF 进度事件（来自 progress_callback）格式化为 SSE 帧。

    与 _format_adf_event 同构；新增 BS-ADF 专属事件（BSADF_STAGE /
    BEAT_SLOTS_BUILT / BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED），
    ADF 共享事件（PRUNE/AUDIT/CONSISTENCY 等）按 ADF 名字透传。
    """
    # ---- BS-ADF 专属事件 ----
    if event == "BSADF_STAGE":
        return build_sse_event("BSADF_STAGE", f"进入阶段：{data.get('stage')}", **data)
    elif event == "BEAT_SLOTS_BUILT":
        count = data.get("count", 0)
        return build_sse_event("BEAT_SLOTS_BUILT", f"槽位卡构建完成：{count} 张", **data)
    elif event == "BEAT_RENDER_PROGRESS":
        status = data.get("status", "")
        idx = data.get("segment_index", 0)
        wc = data.get("word_count", 0)
        if status == "rendered":
            return build_sse_event(
                "BEAT_RENDER_PROGRESS",
                f"第 {idx + 1} 段渲染完成（{wc} 字）",
                **data,
            )
        return build_sse_event(
            "BEAT_RENDER_PROGRESS",
            f"第 {idx + 1} 段 {status}",
            **data,
        )
    elif event == "BEAT_DOWNGRADED":
        return build_sse_event(
            "BEAT_DOWNGRADED",
            f"第 {data.get('segment_index', 0) + 1} 段降级（{data.get('reason')}）",
            **data,
        )

    # ---- ADF 共享事件（按 ADF 名字透传，复用 _format_adf_event 的文案逻辑）----
    elif event == "ADF_STAGE":
        return build_sse_event("ADF_STAGE", f"进入阶段：{data.get('stage')}", **data)
    elif event == "ADF_SPINE_BUILT":
        return build_sse_event("ADF_SPINE_BUILT", "脉络轨构建完成", **data)
    elif event == "ADF_ANCHOR_DESIGNED":
        # 去掉大字段（setup_points 列表），保留摘要
        emit_data = {k: v for k, v in data.items() if k != "setup_points"}
        return build_sse_event("ADF_ANCHOR_DESIGNED", "高潮设计完成", **emit_data)
    elif event == "TIER_DECIDED":
        return build_sse_event("TIER_DECIDED", f"定档：{data.get('tier')}", **data)
    elif event == "ADF_PRECONDITION_LANDED":
        return build_sse_event(
            "ADF_PRECONDITION_LANDED",
            f"铺垫到位：{data.get('precondition_id')}",
            **data,
        )
    elif event == "ADF_PRUNE_PROGRESS":
        return build_sse_event(
            "ADF_PRUNE_PROGRESS",
            f"剪枝 {data.get('segment_index')}/{data.get('total_segments')}",
            **data,
        )
    elif event == "ADF_AUDIT":
        msg = f"检查结论：{data.get('verdict')}"
        missing_beats = data.get("missing_beats") or []
        if missing_beats:
            msg += f"；缺 {len(missing_beats)} 个大纲节拍"
        return build_sse_event("ADF_AUDIT", msg, **data)
    elif event == "ADF_CONSISTENCY":
        msg = (
            f"一致性守卫：发现 {data.get('issues_found', 0)} 处，"
            f"修复 {data.get('issues_fixed', 0)} 处"
        )
        rolled_back = data.get("rolled_back", 0)
        if rolled_back:
            msg += f"；回滚 {rolled_back} 个手术"
        return build_sse_event("ADF_CONSISTENCY", msg, **data)

    # 未知事件：安全忽略（不阻塞流）
    return ""


# ============================================================
# SSE 流处理器
# ============================================================

class _BSAdfStreamHandler:
    """BS-ADF 引擎 SSE 流处理器。

    职责：
    - 加载上下文（复用 ADF 的 _load_adf_context）
    - 初始化 RunRecorder
    - 执行 BSAdfWorkflow
    - 把阶段进度 + 事件通过 SSE 推给前端
    - 持久化生成结果到 Chapter.draft_text + RunRecorder 落库

    Track A（默认）：跑完全程。
    Track B（track='B'）：当前版本也跑完全程（P3 改为跑到 Phase 4a 暂停）。
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

    async def stream(self):
        """SSE 流生成器（BS-ADF 事件序列）。"""
        run_id = f"bsadf_{uuid4().hex[:12]}"

        try:
            # ---- Phase 0: 上下文组装（复用 ADF 的 _load_adf_context）----
            yield build_sse_event(
                "BSADF_STAGE",
                "进入阶段：CONTEXT_ASSEMBLING",
                stage="CONTEXT_ASSEMBLING",
            )
            ctx = await _load_adf_context(self.db, self.chapter_id)
            chapter = ctx["chapter"]

            # ---- 初始化 RunRecorder ----
            recorder = RunRecorder(chapter_id=self.chapter_id, run_id=run_id)
            yield build_sse_event(
                "GENERATION_RUN",
                "BS-ADF 引擎已初始化",
                generation_run_id=run_id,
            )

            # ---- 初始化 BSAdfWorkflow（签名与 ADFWorkflow 完全一致）----
            workflow = BSAdfWorkflow(
                chapter=chapter,
                book=ctx["book"],
                chapter_card=ctx["chapter_card"],
                entities=ctx["entities"],
                style_card=ctx["style_card"],
                author_samples=None,  # v1 简化（与 ADF 对齐）
                recorder=recorder,
                request=self.request,
                previous_summary=ctx["previous_summary"],
                rolling_summary=ctx["rolling_summary"],
                open_hooks=ctx["open_hooks"],
                canon_context=ctx.get("canon_context", ""),  # V4.0 新增
                author_intent=getattr(self.request, "author_intent", None),  # V4.2 介入点 1
                expectation_actions=getattr(self.request, "expectation_actions", None),
                # V3.5 设定感知层数据（用户章级显式指定的角色/地点/资产/关系）
                locations=ctx.get("locations", []),
                assets=ctx.get("assets", []),
                relationships=ctx.get("relationships", []),
                worldview_text=ctx.get("worldview_text", ""),  # V3.5 世界观设定
            )

            # ---- progress_callback 转 SSE（asyncio.Queue 桥接，照搬 ADF）----
            # 设计：workflow.execute 是普通 async 调用，本 stream() 是 async generator。
            # 用 asyncio.Queue 做通道：callback 把事件 put 进 queue，本生成器边取边 yield。
            progress_queue: "asyncio.Queue[Tuple[str, dict]]" = asyncio.Queue()

            async def _on_progress(event: str, data: dict) -> None:
                await progress_queue.put((event, data))

            # Track A：跑完全程；Track B：跑到 Phase 4a 暂停
            track = getattr(self.request, "track", "A")
            pause_after_slot_build = (track == "B")

            # 把 workflow 包成 task，与"取队列"任务并发，用 FIRST_COMPLETED 决定下一步：
            # - execute 先完成：drain 队列剩余事件后跳出循环
            # - 队列先有事件：yield 该事件，重建队列任务继续
            # - 都没就绪超过 HEARTBEAT_INTERVAL：发心跳保活
            execute_task = asyncio.ensure_future(
                workflow.execute(
                    progress_callback=_on_progress,
                    pause_after_slot_build=pause_after_slot_build,
                )
            )
            result = None

            try:
                while True:
                    get_task = asyncio.ensure_future(progress_queue.get())
                    done, _pending = await asyncio.wait(
                        {execute_task, get_task},
                        timeout=HEARTBEAT_INTERVAL,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if not done:
                        # 超时：两任务都未完成 → 发 SSE 注释帧保活（前端忽略，仅防空闲断流）
                        get_task.cancel()
                        yield ": heartbeat\n\n"
                        continue

                    if get_task in done:
                        # 取到一个事件 → 实时 yield，循环继续（execute 可能还在跑）
                        event, data = get_task.result()
                        yield _format_bsadf_event(event, data)
                        # 若 execute 也恰好完成，进入下方 drain；否则继续循环
                        if execute_task.done():
                            break
                        continue

                    # execute 先完成（且本次 get 未就绪）：取消挂起的 get，drain 剩余事件
                    get_task.cancel()
                    break

                # execute 已结束，取最终结果（同时传播异常）
                result = execute_task.result()

                # drain：execute 可能已 put 但尚未被消费的事件（保证不丢事件）
                while not progress_queue.empty():
                    event, data = progress_queue.get_nowait()
                    yield _format_bsadf_event(event, data)

            except Exception as e:
                logger.exception(f"[BS-ADF] workflow.execute 异常: {e}")
                if not execute_task.done():
                    execute_task.cancel()
                yield build_sse_error(
                    f"生成失败: {type(e).__name__}: {str(e)[:200]}"
                )
                return

            if result is None:
                # 兜底：理论上不应到达
                logger.error("[BS-ADF] workflow.execute 未返回结果，终止流")
                yield build_sse_error("生成失败：工作流未返回结果")
                return

            # ============================================================
            # Track B 暂停分支：存 pending + 持久化 slots + emit AUTHOR_DIALOGUE，关流
            # ============================================================
            if result.debug_info.get("paused"):
                cards_dicts = result.debug_info.get("beat_slots", [])
                cards: List[BeatSlotCard] = [beat_slot_from_dict(d) for d in cards_dicts]

                # 1. 暂存内存上下文（resume_from_slots 所需 + 重建 workflow 所需）
                paused_spine: StoryContext = result.debug_info.get("paused_spine") or result.spine_track
                paused_anchor: ChapterClimax = result.debug_info.get("paused_anchor") or result.distal_anchor
                workflow_ctx = {
                    "spine": paused_spine,
                    "anchor": paused_anchor,
                    "tier": result.debug_info.get("paused_tier") or result.tier_decision.get("tier"),
                    "target_word_count": result.debug_info.get(
                        "paused_target_word_count"
                    ) or result.tier_decision.get("target_word_count"),
                    "max_segments": result.debug_info.get(
                        "paused_max_segments"
                    ) or result.tier_decision.get("max_segments"),
                    # 重建 BSAdfWorkflow 所需的上下文（来自 _load_adf_context）
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
                    "request": self.request,  # enable_* 开关（resume 也读它）
                }
                _store_pending_beats(run_id, cards, workflow_ctx)

                # 2. 持久化 slots 到 DB（供刷新后 / rerender-beat 兜底恢复）
                try:
                    chapter.bsadf_beat_slots = json.dumps(cards_dicts, ensure_ascii=False)
                    chapter.generation_run_id = run_id
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[BS-ADF] Track B 持久化 beat_slots 失败（不阻塞）: {e}")

                # 3. RunRecorder 落库（暂停阶段也有诊断数据）
                try:
                    count = await recorder.flush_to_db(self.db)
                    await self.db.commit()
                    logger.info(f"[BS-ADF] Track B RunRecorder 落库 {count} 条")
                except Exception as e:
                    logger.warning(f"[BS-ADF] RunRecorder 落库失败（不阻塞）: {e}")

                # 4. 推送降级事件（即便暂停也可能有 Phase 1-3 降级）
                for deg in result.degraded:
                    yield build_sse_event(
                        "DEGRADED",
                        f"阶段 {deg.get('phase', '?')} 降级",
                        phase=deg.get("phase", ""),
                        reason=deg.get("reason", ""),
                        detail=str(deg.get("detail", ""))[:200],
                    )

                # 5. emit 槽位卡（带 run_id，前端据此调 /confirm-beats）
                yield build_sse_event(
                    "BEAT_SLOTS_BUILT",
                    f"槽位卡构建完成：{len(cards)} 张（待作者编辑）",
                    run_id=run_id,
                    count=len(cards),
                    beat_ids=[c.beat_id for c in cards],
                    beat_slots=cards_dicts,
                    climax_design=climax_to_dict(paused_anchor),
                    story_context=story_context_to_dict(paused_spine),
                    tier=result.tier_decision,
                )

                # 6. 切阶段：作者对话（流关闭，前端拉作者决策后调 confirm-beats）
                yield build_sse_event(
                    "BSADF_STAGE",
                    "等待作者编辑（AUTHOR_DIALOGUE）",
                    stage="AUTHOR_DIALOGUE",
                    run_id=run_id,
                )

                logger.info(f"[BS-ADF] Track B 暂停完成 run_id={run_id}，{len(cards)} 张卡待编辑")
                return  # 流关闭，不进 4c

            # ---- 持久化 RunRecorder（flush 不 commit，调用方负责 commit）----
            try:
                count = await recorder.flush_to_db(self.db)
                await self.db.commit()
                logger.info(f"[BS-ADF] RunRecorder 落库 {count} 条")
            except Exception as e:
                logger.warning(f"[BS-ADF] RunRecorder 落库失败（不阻塞）: {e}")

            # ---- 持久化正文到 Chapter.draft_text ----
            if result.final_text:
                try:
                    chapter.draft_text = result.final_text
                    chapter.generation_run_id = run_id
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[BS-ADF] 持久化 draft_text 失败: {e}")

            # ---- 推送降级事件（失败不静默）----
            # 来源 1：BSAdfWorkflow 各 Phase 异常记录的 result.degraded
            #         （含 BS-ADF 专属的 render 降级 beat）
            for deg in result.degraded:
                yield build_sse_event(
                    "DEGRADED",
                    f"阶段 {deg.get('phase', '?')} 降级",
                    phase=deg.get("phase", ""),
                    reason=deg.get("reason", ""),
                    detail=str(deg.get("detail", ""))[:200],
                    beat_id=deg.get("beat_id", ""),
                    attempts=deg.get("attempts", 0),
                )
            # 来源 2：RunRecorder 收集的逐调用降级（如单段 LLM 超时）
            for deg in recorder.degraded_events():
                stage = deg.get("stage", "?")
                yield build_sse_event(
                    "DEGRADED",
                    f"{stage} 降级",
                    phase=stage,
                    reason=deg.get("reason", ""),
                    detail=f"动作：{deg.get('action', '')}",
                )

            # ---- 推送元数据（高潮设计 + 前文脉络 + 结构检查，复用 ADF 序列化）----
            yield build_sse_event(
                "BSADF_METADATA",
                "本章元数据",
                climax_design=climax_to_dict(result.distal_anchor),
                story_context=story_context_to_dict(result.spine_track),
                audit=audit_to_dict(result.audit),
                beat_slots=result.debug_info.get("beat_slots", []),
                degraded_beats=result.debug_info.get("degraded_beats", []),
            )

            # ---- 推送审计指标 ----
            yield build_sse_event(
                "UNIFIED_METRIC",
                "BS-ADF 引擎审计指标",
                metrics={
                    "audit": audit_to_dict(result.audit),
                    "stats": result.stats,
                },
            )

            # ---- 流式推送正文（按 200 字切块，照搬 ADF）----
            if result.final_text:
                yield build_sse_event("FINAL_TEXT_STREAM", "正在输出最终文本")
                text = result.final_text
                chunk_size = 200
                for i in range(0, len(text), chunk_size):
                    chunk = text[i:i + chunk_size]
                    yield build_sse_text_chunk(chunk)

            # ---- COMPLETE ----
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
                # BS-ADF 专属：槽位卡与降级 beat（供前端 Track B 入口与 /rerender-beat）
                "beat_slots": result.debug_info.get("beat_slots", []),
                "degraded_beats": result.debug_info.get("degraded_beats", []),
            }
            yield f"data: {json.dumps(complete_payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception(f"[BS-ADF] SSE 流异常: {e}")
            yield build_sse_error(
                f"生成失败: {type(e).__name__}: {str(e)[:200]}"
            )


# ============================================================
# POST /generate-bsadf —— BS-ADF 引擎入口
# ============================================================

@router.post("/{chapter_id}/generate-bsadf")
async def generate_bsadf_stream(
    chapter_id: str,
    request: Optional[GenerateBSAdfRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """BS-ADF 引擎生成入口。

    Track A（默认）：槽位化流水线跑完全程
        SPINE → ANCHOR → TIER → SLOT_BUILD → RENDER → PRUNE → AUDIT → REFINE → CONSISTENCY
    Track B（track='B'）：跑到 Phase 4a 暂停，emit BEAT_SLOTS_BUILT 后关流，
        待作者编辑槽位卡后调 /confirm-beats 恢复（P3 实现）

    Args:
        chapter_id: 章节 ID
        request: tier=auto(默认)|climax|turn|progress|transition +
                 track=A(默认)|B +
                 target_word_count + max_segments + 开关参数

    Returns:
        流式 SSE 响应（BS-ADF 事件序列）

    前置：无（BS-ADF 管线自主完成全部流程，不依赖闸门）
    """
    handler = _BSAdfStreamHandler(
        chapter_id=chapter_id,
        request=request or GenerateBSAdfRequest(),
        db=db,
    )
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


# ============================================================
# POST /confirm-beats —— Track B 恢复（照搬 refinery confirm 的 asyncio.Queue 模式）
# ============================================================

class _ConfirmBeatsHandler:
    """Track B 恢复 SSE 流处理器。

    流程：
    1. 从 _PENDING_BEAT_SLOTS 取出（cards + ctx，含 spine/anchor/tier 等）
    2. 用 request.edited_slots 覆盖 cards（标记 edited=True，edit_count+=1）
    3. 重建 BSAdfWorkflow（用 ctx 里的 chapter/book 等构造参数）
    4. 调 workflow.resume_from_slots(edited_cards, spine, anchor, ...) 跑 Phase 4c-7
    5. asyncio.Queue 桥接把渲染/审计/守卫事件实时推 SSE（同 generate-bsadf）
    6. 持久化正文 + slots + 流式输出 + COMPLETE
    7. _pop_pending_beats(run_id) 清理
    """

    def __init__(
        self,
        chapter_id: str,
        request: ConfirmBeatsRequest,
        db: AsyncSession,
    ):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def stream(self):
        run_id = self.request.run_id
        if not run_id:
            yield build_sse_error("缺少 run_id")
            return

        pending = _load_pending_beats(run_id)
        if not pending:
            yield build_sse_error(f"无效或已过期的 run_id: {run_id}")
            return

        cards: List[BeatSlotCard] = pending["cards"]
        ctx = pending["ctx"]
        chapter = ctx["chapter"]
        spine: StoryContext = ctx["spine"]
        anchor: ChapterClimax = ctx["anchor"]
        tier: str = ctx["tier"]
        target_word_count: int = ctx["target_word_count"]
        max_segments: int = ctx["max_segments"]

        # 用作者编辑后的 slots 覆盖服务端暂存卡
        # 策略：以 edited_slots 的 (beat_id → slot) 为权威覆盖；未编辑的保留原卡
        if self.request.edited_slots:
            edited_map = {s.beat_id: s for s in self.request.edited_slots}
            new_cards: List[BeatSlotCard] = []
            for card in cards:
                if card.beat_id in edited_map:
                    schema = edited_map[card.beat_id]
                    # 从 schema 重建 BeatSlotCard，保留原 segment_index/status 基线
                    edited_card = beat_slot_from_dict(schema.model_dump())
                    edited_card.segment_index = card.segment_index
                    edited_card.status = "author_pending"
                    edited_card.edited = True
                    edited_card.edit_count = card.edit_count + 1
                    new_cards.append(edited_card)
                else:
                    new_cards.append(card)
            cards = new_cards

        # 重建 BSAdfWorkflow（构造参数与 generate-bsadf 一致）
        workflow = BSAdfWorkflow(
            chapter=chapter,
            book=ctx["book"],
            chapter_card=ctx["chapter_card"],
            entities=ctx["entities"],
            style_card=ctx["style_card"],
            author_samples=None,
            recorder=RunRecorder(chapter_id=self.chapter_id, run_id=run_id),
            request=ctx.get("request") or self.request,
            previous_summary=ctx.get("previous_summary"),
            rolling_summary=ctx.get("rolling_summary"),
            open_hooks=ctx.get("open_hooks"),
            canon_context=ctx.get("canon_context", ""),
            author_intent=ctx.get("author_intent"),
            expectation_actions=ctx.get("expectation_actions"),
            locations=ctx.get("locations", []),
            assets=ctx.get("assets", []),
            relationships=ctx.get("relationships", []),
            worldview_text=ctx.get("worldview_text", ""),
        )
        recorder = workflow.recorder

        yield build_sse_event(
            "GENERATION_RUN",
            "BS-ADF Track B 恢复已初始化",
            generation_run_id=run_id,
        )

        # asyncio.Queue 桥接（同 generate-bsadf / refinery confirm）
        progress_queue: "asyncio.Queue[Tuple[str, dict]]" = asyncio.Queue()

        async def _on_progress(event: str, data: dict) -> None:
            await progress_queue.put((event, data))

        resume_task = asyncio.ensure_future(
            workflow.resume_from_slots(
                edited_cards=cards,
                spine=spine,
                anchor=anchor,
                tier=tier,
                target_word_count=target_word_count,
                max_segments=max_segments,
                progress_callback=_on_progress,
            )
        )
        result = None
        try:
            while True:
                get_task = asyncio.ensure_future(progress_queue.get())
                done, _pending = await asyncio.wait(
                    {resume_task, get_task},
                    timeout=HEARTBEAT_INTERVAL,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    get_task.cancel()
                    yield ": heartbeat\n\n"
                    continue
                if get_task in done:
                    event, data = get_task.result()
                    yield _format_bsadf_event(event, data)
                    if resume_task.done():
                        break
                    continue
                get_task.cancel()
                break

            result = resume_task.result()
            while not progress_queue.empty():
                event, data = progress_queue.get_nowait()
                yield _format_bsadf_event(event, data)

        except Exception as e:
            logger.exception(f"[BS-ADF] confirm-beats resume 异常: {e}")
            if not resume_task.done():
                resume_task.cancel()
            yield build_sse_error(f"恢复失败: {type(e).__name__}: {str(e)[:200]}")
            return

        if result is None:
            yield build_sse_error("恢复失败：工作流未返回结果")
            return

        # ---- 持久化 RunRecorder ----
        try:
            count = await recorder.flush_to_db(self.db)
            await self.db.commit()
            logger.info(f"[BS-ADF] confirm-beats RunRecorder 落库 {count} 条")
        except Exception as e:
            logger.warning(f"[BS-ADF] RunRecorder 落库失败（不阻塞）: {e}")

        # ---- 持久化正文 + 清空 slots（恢复完成）----
        if result.final_text:
            try:
                chapter.draft_text = result.final_text
                chapter.generation_run_id = run_id
                # slots 落库（含渲染后状态，供后续 rerender / 审计）
                chapter.bsadf_beat_slots = json.dumps(
                    result.debug_info.get("beat_slots", []), ensure_ascii=False,
                )
                await self.db.commit()
            except Exception as e:
                logger.warning(f"[BS-ADF] confirm-beats 持久化失败: {e}")

        # ---- 推送降级事件 ----
        for deg in result.degraded:
            yield build_sse_event(
                "DEGRADED",
                f"阶段 {deg.get('phase', '?')} 降级",
                phase=deg.get("phase", ""),
                reason=deg.get("reason", ""),
                detail=str(deg.get("detail", ""))[:200],
                beat_id=deg.get("beat_id", ""),
                attempts=deg.get("attempts", 0),
            )
        for deg in recorder.degraded_events():
            yield build_sse_event(
                "DEGRADED",
                f"{deg.get('stage', '?')} 降级",
                phase=deg.get("stage", ""),
                reason=deg.get("reason", ""),
                detail=f"动作：{deg.get('action', '')}",
            )

        # ---- 推送元数据 + 指标 ----
        yield build_sse_event(
            "BSADF_METADATA",
            "本章元数据",
            climax_design=climax_to_dict(result.distal_anchor),
            story_context=story_context_to_dict(result.spine_track),
            audit=audit_to_dict(result.audit),
            beat_slots=result.debug_info.get("beat_slots", []),
            degraded_beats=result.debug_info.get("degraded_beats", []),
        )
        yield build_sse_event(
            "UNIFIED_METRIC",
            "BS-ADF Track B 审计指标",
            metrics={"audit": audit_to_dict(result.audit), "stats": result.stats},
        )

        # ---- 流式推送正文 ----
        if result.final_text:
            yield build_sse_event("FINAL_TEXT_STREAM", "正在输出最终文本")
            text = result.final_text
            chunk_size = 200
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i + chunk_size]
                yield build_sse_text_chunk(chunk)

        # ---- COMPLETE ----
        complete_payload = {
            "event": "COMPLETE",
            "text": result.final_text,
            "engine": "bsadf",
            "track": "B",
            "generation_run_id": run_id,
            "tier": result.tier_decision.get("tier"),
            "segment_count": len(result.segments),
            "climax_score": result.audit.climax_score,
            "audit_verdict": result.audit.verdict,
            "stats": result.stats,
            "degraded_count": len(result.degraded),
            "beat_slots": result.debug_info.get("beat_slots", []),
            "degraded_beats": result.debug_info.get("degraded_beats", []),
        }
        yield f"data: {json.dumps(complete_payload, ensure_ascii=False)}\n\n"

        # ---- 清理 pending ----
        _pop_pending_beats(run_id)


@router.post("/{chapter_id}/confirm-beats")
async def confirm_beats_stream(
    chapter_id: str,
    request: ConfirmBeatsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Track B 恢复：作者编辑槽位卡后从 Phase 4c 继续渲染到完成。

    需要 run_id（从 generate-bsadf track='B' 阶段获得的 GENERATION_RUN 事件取得）。
    从内存 _PENDING_BEAT_SLOTS 取出槽位卡 + 上下文，用 edited_slots 覆盖后调
    BSAdfWorkflow.resume_from_slots 跑 Phase 4c-7（渲染 + 后处理）。

    Returns:
        流式 SSE 响应（与 generate-bsadf Track A 的 4c-7 阶段事件序列等价）
    """
    handler = _ConfirmBeatsHandler(chapter_id=chapter_id, request=request, db=db)
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


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

    Returns:
        JSON: {segment: {...}, card: {...}, degraded: {...|null}, generation_run_id}
    """
    from fastapi import HTTPException
    from backend.repositories import ChapterRepository

    chapter_repo = ChapterRepository(db)
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    edited_card = beat_slot_from_dict(request.edited_slot.model_dump())
    edited_card.edited = True
    edited_card.edit_count += 1
    edited_card.status = "pending"

    # 优先从 pending 取（同一 run_id 的渲染上下文最完整）
    pending = _load_pending_beats(request.beat_id)  # rerender 用 beat_id 作 key 尝试
    ctx_dict = pending.get("ctx") if pending else None

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
    from backend.services.workflows.adf.segment_writer import _build_style_contract
    from backend.services.workflows.adf.name_registry import build_name_registry, registry_to_prompt_block
    from backend.services.workflows.adf.setting_resolver import build_scene_setting_text
    from backend.services.workflows.bsadf.downgrade import render_with_downgrade

    run_id = f"rerender_{uuid4().hex[:12]}"
    recorder = RunRecorder(chapter_id=chapter_id, run_id=run_id)

    style_contract = _build_style_contract(getattr(chapter, "style_card", None))
    emotion_curve_text = format_emotion_curve([
        {"progress": s.progress, "register": s.register, "energy": s.energy}
        for s in anchor.emotion_curve.samples
    ])
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
        )
    except Exception as e:
        logger.exception(f"[BS-ADF] rerender-beat 渲染失败: {e}")
        raise HTTPException(status_code=500, detail=f"单卡渲染失败: {e}")

    # recorder 落库
    try:
        await recorder.flush_to_db(db)
        await db.commit()
    except Exception as e:
        logger.warning(f"[BS-ADF] rerender-beat recorder 落库失败（不阻塞）: {e}")

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
