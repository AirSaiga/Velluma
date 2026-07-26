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
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.routes.chapter_generation.adf import _load_adf_context
from backend.schemas.bsadf import GenerateBSAdfRequest
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
from backend.services.workflows.bsadf.bsadf_workflow import BSAdfWorkflow

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

            # 把 workflow 包成 task，与"取队列"任务并发，用 FIRST_COMPLETED 决定下一步：
            # - execute 先完成：drain 队列剩余事件后跳出循环
            # - 队列先有事件：yield 该事件，重建队列任务继续
            # - 都没就绪超过 HEARTBEAT_INTERVAL：发心跳保活
            execute_task = asyncio.ensure_future(
                workflow.execute(progress_callback=_on_progress)
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
    Track B（track='B'）：跑到 Phase 4a 暂停（P3 实现；当前版本也跑完全程）

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
