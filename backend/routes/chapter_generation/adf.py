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
ADF 引擎路由（V3.2 §6 + §7 新建）。

职责（设计文档 §6.1）：
提供 ADF 引擎入口 POST /api/chapters/{id}/generate-adf。
旧端点 /generate（V3.1）保留不动；本端点是 V3.2 独立入口。

API 端点（前缀 /api/chapters/{chapter_id}）：
- POST /generate-adf           ADF 引擎生成（SSE v3.2 事件序列）

SSE v3.2 事件序列（设计文档 §7）：
- ADF_STAGE                阶段切换（SPINE_BUILDING/ANCHOR_DESIGN/TIER_DECIDE/
                                    FORWARD_FLOW/PRUNE/ANCHOR_AUDIT/REFINE）
- ADF_SPINE_BUILT          脉络轨构建完成
- ADF_ANCHOR_DESIGNED      远端锚设计完成
- TIER_DECIDED             定档通知（复用 V3.1 事件名）
- ADF_PROGRESS             正向流写作进度
- ADF_PRUNE_PROGRESS       去 AI 味剪枝进度（Phase 4.5，每段重构）
- ADF_PRECONDITION_LANDED  条件落地事件
- ADF_AUDIT                锚点审计结论
- ADF_CONSISTENCY          一致性守卫结论（Phase 7：发现/修复数）
- DEGRADED                 降级事件（失败不静默）
- TEXT_CHUNK               文本块（流式正文，复用）
- COMPLETE / ERROR         完成/错误（复用）

与旧端点的关系：
- /generate（V3.1）：保留不动
- /generate-chapter（V4.0 双轨）：保留不动
- /generate-v3（V3.0 闸门）：保留不动
- 本端点是 ADF 新入口，与旧端点并存，前端通过引擎切换选择

使用方式：
    POST /api/chapters/{chapter_id}/generate-adf
    body: {"tier": "auto", "target_word_count": null, "max_segments": 6}
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter, StyleCard
from backend.repositories import (
    ChapterRepository, BookRepository, PlotLedgerRepository,
    ChapterCardRepository, StyleCardRepository,
    ChapterAssetRepository, AssetRepository, MapLocationRepository,
    MemoryRepository, RelationshipRepository,
)
from backend.schemas import GenerateADFRequest
from backend.services.context.loader import load_full_chapter_context
from backend.services.canon import build_canon_context_for_prompt
from backend.services.reader_mirror import suggest_chapter_plan, load_mirror
from backend.services.observability.run_recorder import RunRecorder
from backend.services.observability.run_trace import clear_trace, create_trace, trace_event
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import (
    build_sse_event, build_sse_text_chunk, build_sse_error,
)
from backend.services.workflows.adf import (
    ADFWorkflow,
    climax_to_dict,
    story_context_to_dict,
    audit_to_dict,
)
from backend.services.workflows.adf.setting_resolver import build_worldview_text

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-adf-v3.2"])

# ============================================================
# 实时流常量
# ============================================================
# SSE 心跳间隔（秒）。长耗时阶段（如 FORWARD_FLOW 逐段写作）期间若无业务事件，
# 每 HEARTBEAT_INTERVAL 秒发一个 SSE 注释帧（": heartbeat\n\n"），防止代理/中间件
# 因空闲掐断连接。前端 streamSse 因 line.startsWith('data: ') 检查会自动忽略注释帧。
HEARTBEAT_INTERVAL = 15


# ============================================================
# 辅助：上下文加载（复用 V3.1 的 _load_unified_context 模式）
# ============================================================

async def _load_adf_context(
    db: AsyncSession,
    chapter_id: str,
) -> Dict[str, Any]:
    """加载 ADF 生成所需的完整上下文（与 V3.1 _load_unified_context 同构）。"""
    chapter_repo = ChapterRepository(db)
    book_repo = BookRepository(db)
    cc_repo = ChapterCardRepository(db)
    style_card_repo = StyleCardRepository(db)
    plot_ledger_repo = PlotLedgerRepository(db)

    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    book = await book_repo.get_by_id(chapter.book_id) if chapter.book_id else None

    chapter_card = await cc_repo.get_by_chapter(chapter.id)

    # 书级 StyleCard
    style_specs = await style_card_repo.find_all(
        conditions=[
            StyleCard.book_id == chapter.book_id,
            StyleCard.chapter_id.is_(None),
        ],
        limit=1,
    )
    style_card = style_specs[0] if style_specs else None

    repos = {
        "chapter": chapter_repo,
        "book": book_repo,
        "plot_ledger": plot_ledger_repo,
        "chapter_asset": ChapterAssetRepository(db),
        "asset": AssetRepository(db),
        "map_location": MapLocationRepository(db),
        "memory": MemoryRepository(db),
        "relationship": RelationshipRepository(db),
    }
    try:
        context = await load_full_chapter_context(chapter.id, repos)
        entities = context.entities if context else []
        open_hooks = context.open_hooks if context else []
        previous_summary = context.previous_summary if context else None
        # V3.5：取回之前被丢弃的地点/资产/关系网（用户章级显式指定的设定）
        locations = context.locations if context else []
        assets = context.assets if context else []
        relationships = context.relationships if context else []
    except Exception as e:
        logger.warning(f"[ADF] load_full_chapter_context 失败，降级空上下文: {e}")
        entities = []
        open_hooks = []
        previous_summary = None
        locations = []
        assets = []
        relationships = []

    rolling_summary = getattr(book, "rolling_summary", None) if book else None

    # V4.0 Canon：加载作者脑中世界图谱，构建 prompt 上下文段
    canon_context = ""
    try:
        chapter_number = getattr(chapter, "chapter_number", None)
        canon_context = await build_canon_context_for_prompt(
            db, chapter.book_id, chapter_number=chapter_number,
        )
    except Exception as e:
        logger.warning(f"[ADF] Canon 上下文加载失败（降级空 Canon）: {e}")
        canon_context = "（Canon 为空，无强约束）"

    # V3.5：世界观设定（global_sys_prompt + worldview_settings → 可读文本）
    worldview_text = build_worldview_text(book)

    return {
        "chapter": chapter,
        "book": book,
        "chapter_card": chapter_card,
        "style_card": style_card,
        "entities": entities,
        "open_hooks": open_hooks,
        "previous_summary": previous_summary,
        "rolling_summary": rolling_summary,
        "canon_context": canon_context,  # V4.0 新增
        "worldview_text": worldview_text,  # V3.5 新增：世界观设定
        # V3.5 新增：设定感知层的数据来源（用户章级显式指定）
        "locations": locations,
        "assets": assets,
        "relationships": relationships,
    }


# ============================================================
# POST /generate-adf —— ADF 引擎入口（SSE v3.2 事件序列）
# ============================================================

@router.post("/{chapter_id}/generate-adf")
async def generate_adf_stream(
    chapter_id: str,
    request: Optional[GenerateADFRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """ADF 引擎生成入口（V3.2）。

    自主完成：脉络轨构建 → 远端锚设计 → 定档 → 正向流写作 → 锚点审计 → 条件补埋 → 回写。

    Args:
        chapter_id: 章节 ID
        request: tier=auto(默认)|climax|turn|progress|transition +
                 target_word_count + max_segments + 开关参数

    Returns:
        流式 SSE 响应（v3.2 事件序列）

    前置：无（ADF 管线自主完成全部流程，不依赖闸门）
    """
    handler = _ADFStreamHandler(
        chapter_id=chapter_id,
        request=request or GenerateADFRequest(),
        db=db,
    )
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


# ============================================================
# SSE 流处理器
# ============================================================

def _format_adf_event(event: str, data: dict) -> str:
    """把单个 ADF 进度事件（来自 progress_callback）格式化为 SSE v3.2 帧。

    与原缓冲逻辑里的事件分支一一对应，提取为函数以便实时流与 drain 复用。
    """
    if event == "ADF_STAGE":
        return build_sse_event("ADF_STAGE", f"进入阶段：{data.get('stage')}", **data)
    elif event == "ADF_SPINE_BUILT":
        return build_sse_event("ADF_SPINE_BUILT", "脉络轨构建完成", **data)
    elif event == "ADF_ANCHOR_DESIGNED":
        # 去掉大字段（setup_points 列表），保留摘要
        emit_data = {k: v for k, v in data.items() if k != "setup_points"}
        return build_sse_event("ADF_ANCHOR_DESIGNED", "高潮设计完成", **emit_data)
    elif event == "TIER_DECIDED":
        return build_sse_event("TIER_DECIDED", f"定档：{data.get('tier')}", **data)
    elif event == "ADF_PROGRESS":
        return build_sse_event(
            "ADF_PROGRESS",
            f"写作 {data.get('segment_index')}/{data.get('total_segments')} "
            f"({data.get('register')})",
            **data,
        )
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


class _ADFStreamHandler:
    """ADF 引擎 SSE 流处理器。

    职责：
    - 加载上下文（Phase 0）
    - 初始化 RunRecorder
    - 执行 ADFWorkflow
    - 把阶段进度 + 事件通过 SSE v3.2 推给前端
    - 持久化生成结果到 Chapter.draft_text
    """

    def __init__(
        self,
        chapter_id: str,
        request: GenerateADFRequest,
        db: AsyncSession,
    ):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def stream(self):
        """SSE 流生成器（v3.2 事件序列）。"""
        run_id = f"adf_{uuid4().hex[:12]}"
        trace = create_trace(run_id, "adf", self.chapter_id)
        trace_event(
            "run_start",
            request=self.request.model_dump() if self.request else {},
        )

        try:
            # ---- Phase 0: 上下文组装 ----
            yield build_sse_event("ADF_STAGE", "进入阶段：CONTEXT_ASSEMBLING", stage="CONTEXT_ASSEMBLING")
            ctx = await _load_adf_context(self.db, self.chapter_id)
            chapter = ctx["chapter"]

            # ---- 初始化 RunRecorder ----
            recorder = RunRecorder(chapter_id=self.chapter_id, run_id=run_id)
            yield build_sse_event("GENERATION_RUN", "ADF 引擎已初始化", generation_run_id=run_id)

            # ---- 初始化 ADFWorkflow ----
            workflow = ADFWorkflow(
                chapter=chapter,
                book=ctx["book"],
                chapter_card=ctx["chapter_card"],
                entities=ctx["entities"],
                style_card=ctx["style_card"],
                author_samples=None,  # V3.2 v1 简化
                recorder=recorder,
                request=self.request,
                previous_summary=ctx["previous_summary"],
                rolling_summary=ctx["rolling_summary"],
                open_hooks=ctx["open_hooks"],
                canon_context=ctx.get("canon_context", ""),  # V4.0 新增
                author_intent=getattr(self.request, "author_intent", None),  # V4.2 介入点 1
                expectation_actions=getattr(self.request, "expectation_actions", None),
                # V3.5 新增：设定感知层数据（用户章级显式指定的角色/地点/资产/关系）
                locations=ctx.get("locations", []),
                assets=ctx.get("assets", []),
                relationships=ctx.get("relationships", []),
                worldview_text=ctx.get("worldview_text", ""),  # V3.5 世界观设定
            )

            # ---- progress_callback 转 SSE v3.2 事件（实时流出）----
            # 设计：workflow.execute 是普通 async 调用，而本 stream() 是 async generator。
            # 用 asyncio.Queue 做通道：callback 把事件 put 进 queue，本生成器边取边 yield。
            # 前端 composable/api/UI 已按事件实时更新 ref，事件实时到达即实时渲染。
            progress_queue: "asyncio.Queue[Tuple[str, dict]]" = asyncio.Queue()

            async def _on_progress(event: str, data: dict) -> None:
                # 桥接到运行级 trace：阶段切换更新 stage 字段，其余事件原样记录
                if event == "ADF_STAGE":
                    trace.set_stage(data.get("stage") or "")
                trace_event(event, **data)
                await progress_queue.put((event, data))

            # 把 workflow 包成 task，与"取队列"任务并发，用 FIRST_COMPLETED 决定下一步：
            # - execute 先完成：drain 队列剩余事件后跳出循环
            # - 队列先有事件：yield 该事件，重建队列任务继续
            # - 都没就绪超过 HEARTBEAT_INTERVAL：发心跳保活
            execute_task = asyncio.ensure_future(workflow.execute(progress_callback=_on_progress))
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
                        yield _format_adf_event(event, data)
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
                    yield _format_adf_event(event, data)

            except Exception as e:
                logger.exception(f"[ADF] workflow.execute 异常: {e}")
                trace_event("run_error", phase="workflow_execute", error=f"{type(e).__name__}: {e}")
                if not execute_task.done():
                    execute_task.cancel()
                yield build_sse_error(f"生成失败: {type(e).__name__}: {str(e)[:200]}")
                return

            if result is None:
                # 兜底：理论上不应到达
                logger.error("[ADF] workflow.execute 未返回结果，终止流")
                yield build_sse_error("生成失败：工作流未返回结果")
                return

            # ---- 持久化 RunRecorder ----
            try:
                count = await recorder.flush_to_db(self.db)
                await self.db.commit()
                logger.info(f"[ADF] RunRecorder 落库 {count} 条")
            except Exception as e:
                logger.warning(f"[ADF] RunRecorder 落库失败（不阻塞）: {e}")

            # ---- 持久化正文到 Chapter.draft_text ----
            if result.final_text:
                try:
                    chapter.draft_text = result.final_text
                    chapter.generation_run_id = run_id
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[ADF] 持久化 draft_text 失败: {e}")

            # ---- 推送降级事件（失败不静默）----
            # 来源 1：ADFWorkflow 各 Phase 异常记录的 result.degraded（phase/reason/detail）
            for deg in result.degraded:
                yield build_sse_event(
                    "DEGRADED",
                    f"阶段 {deg.get('phase', '?')} 降级",
                    phase=deg.get("phase", ""),
                    reason=deg.get("reason", ""),
                    detail=str(deg.get("detail", ""))[:200],
                )
            # 来源 2：RunRecorder 收集的逐调用降级（如单段 LLM 超时 segment_timeout）。
            # 这些记录在 recorder 内部，不经过 result.degraded，需单独上浮否则前端看不到。
            for deg in recorder.degraded_events():
                stage = deg.get("stage", "?")
                yield build_sse_event(
                    "DEGRADED",
                    f"{stage} 降级",
                    phase=stage,
                    reason=deg.get("reason", ""),
                    detail=f"动作：{deg.get('action', '')}",
                )

            # ---- 推送 ADF 元数据（高潮设计 + 前文脉络 + 结构检查）----
            yield build_sse_event(
                "ADF_METADATA",
                "本章元数据",
                climax_design=climax_to_dict(result.distal_anchor),
                story_context=story_context_to_dict(result.spine_track),
                audit=audit_to_dict(result.audit),
            )

            # ---- 推送审计指标 ----
            yield build_sse_event(
                "UNIFIED_METRIC",
                "ADF 引擎审计指标",
                metrics={
                    "audit": audit_to_dict(result.audit),
                    "stats": result.stats,
                },
            )

            # ---- 流式推送正文（按段切块）----
            if result.final_text:
                yield build_sse_event("FINAL_TEXT_STREAM", "正在输出最终文本")
                text = result.final_text
                chunk_size = 200
                for i in range(0, len(text), chunk_size):
                    chunk = text[i:i + chunk_size]
                    yield build_sse_text_chunk(chunk)

            # ---- COMPLETE ----
            trace_event("final_text", text=result.final_text or "")
            trace_event(
                "run_complete",
                stats=result.stats,
                degraded_count=len(result.degraded),
                tier=result.tier_decision.get("tier"),
                audit_verdict=result.audit.verdict if result.audit else None,
            )
            complete_payload = {
                "event": "COMPLETE",
                "text": result.final_text,
                "engine": "adf",
                "generation_run_id": run_id,
                "tier": result.tier_decision.get("tier"),
                "tier_reason": result.tier_decision.get("reason"),
                "target_word_count": result.tier_decision.get("target_word_count"),
                "segment_count": len(result.segments),
                "setup_points_total": result.stats.get("setup_point_total", 0),
                "setup_points_landed": result.stats.get("setup_point_landed", 0),
                "climax_score": result.audit.climax_score,
                "audit_verdict": result.audit.verdict,
                "stats": result.stats,
            }
            yield f"data: {json.dumps(complete_payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception(f"[ADF] SSE 流异常: {e}")
            trace_event("run_error", phase="sse_stream", error=f"{type(e).__name__}: {e}")
            yield build_sse_error(f"生成失败: {type(e).__name__}: {str(e)[:200]}")
        finally:
            clear_trace()


# ============================================================
# V4.2 对话式介入点 1：章节规划建议（生成前）
# ============================================================

@router.post("/{chapter_id}/plan-suggestion")
async def get_plan_suggestion(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """对话式介入点 1：生成前的章节规划建议。

    综合 Reader Mirror（期待账本）+ Canon（作者脑中世界）+ 章节信息，
    产出本章规划建议。作者在前端弹窗确认/调整后，再调 /generate-adf。

    设计要点（第 7 轮修正）：
    - 纯建议，不强制——作者可无视
    - 透明化给出理由
    - 作者可在确认时给出 author_override
    """
    try:
        # 加载章节
        chapter_repo = ChapterRepository(db)
        chapter = await chapter_repo.get_by_id(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")

        chapter_number = getattr(chapter, "chapter_number", 1) or 1
        book_id = chapter.book_id

        # 1. Reader Mirror 规划建议
        try:
            mirror = await load_mirror(db, book_id)
            rm_plan = suggest_chapter_plan(mirror, chapter_number)
        except Exception as e:
            logger.warning(f"[ADF] Reader Mirror 加载失败: {e}")
            rm_plan = None

        # 2. Canon 摘要
        try:
            canon_ctx = await build_canon_context_for_prompt(db, book_id, chapter_number)
        except Exception as e:
            logger.warning(f"[ADF] Canon 加载失败: {e}")
            canon_ctx = ""

        # 3. 章节基础信息
        outline = getattr(chapter, "outline_text", "") or ""

        # 4. 活跃期待（带描述，供作者判断）
        active_expectations = []
        if rm_plan:
            mirror_exp = mirror.get("expectations", []) if mirror else []
            for exp in mirror_exp:
                if exp.get("status") in ("setup", "accumulating"):
                    active_expectations.append({
                        "id": exp.get("id"),
                        "type": exp.get("type"),
                        "description": exp.get("description"),
                        "current_tension": exp.get("current_tension", 5),
                        "recommended_action": (
                            "payoff" if exp.get("id") in (rm_plan.expectations_to_payoff or []) else
                            "accumulate" if exp.get("id") in (rm_plan.expectations_to_accumulate or []) else
                            "setup" if exp.get("id") in (rm_plan.expectations_to_setup or []) else
                            "none"
                        ),
                    })

        # 5. 悬空伏笔（来自 Canon）
        try:
            from backend.repositories import CanonRepository
            canon_repo = CanonRepository(db)
            open_hooks = await canon_repo.nodes.find_hooks(book_id, only_open=True)
            hooks_data = [
                {
                    "id": str(h.id),
                    "label": h.label,
                    "strength": (h.metadata_ or {}).get("strength", 5),
                    "expected_reveal_chapter": h.expected_reveal_chapter,
                }
                for h in open_hooks[:8]
            ]
        except Exception as e:
            logger.warning(f"[ADF] Canon hooks 加载失败: {e}")
            hooks_data = []

        return {
            "chapter_id": chapter_id,
            "chapter_number": chapter_number,
            "outline": outline,
            "reader_mirror_plan": rm_plan.model_dump() if rm_plan else None,
            "active_expectations": active_expectations,
            "open_hooks": hooks_data,
            "canon_summary_excerpt": canon_ctx[:500] if canon_ctx else "",
            "suggested_questions": _build_author_questions(rm_plan, active_expectations, hooks_data),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[ADF] plan-suggestion 异常: {e}")
        raise HTTPException(status_code=500, detail=f"规划建议失败: {e}")


def _build_author_questions(
    rm_plan: Any,
    active_expectations: List[Dict[str, Any]],
    open_hooks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建向作者提问的问题清单（对话式介入点 1 的核心）。

    只问影响后续 3 章以上的决策，或不可逆的设定。
    """
    questions: List[Dict[str, Any]] = []

    if rm_plan and rm_plan.is_payoff_chapter_recommended:
        questions.append({
            "id": "Q_PAYOFF",
            "type": "confirm",
            "question": f"本章建议释放爽点（{rm_plan.rationale[:80]}）。确认吗？",
            "default": "confirm",
            "options": ["confirm", "delay", "subvert"],
            "option_labels": {
                "confirm": "确认释放（按建议）",
                "delay": "推迟，继续累积",
                "subvert": "反转（故意不打脸）",
            },
        })

    # 高张力期待：单独问
    high_exp = [e for e in active_expectations if e.get("current_tension", 0) >= 8]
    if high_exp and (not rm_plan or not rm_plan.is_payoff_chapter_recommended):
        for exp in high_exp[:2]:
            questions.append({
                "id": f"Q_EXP_{exp['id']}",
                "type": "expectation_action",
                "question": f"期待 [{exp['description'][:50]}] 张力已达 {exp['current_tension']}/10，本章如何处理？",
                "expectation_id": exp["id"],
                "options": ["accumulate", "payoff", "ignore"],
                "option_labels": {
                    "accumulate": "继续累积（卡爽点）",
                    "payoff": "释放",
                    "ignore": "本章不涉及",
                },
            })

    # 长期悬空伏笔：建议回收
    long_open_hooks = [
        h for h in open_hooks
        if h.get("expected_reveal_chapter") is None
    ]
    if long_open_hooks:
        questions.append({
            "id": "Q_HOOKS",
            "type": "hooks",
            "question": f"有 {len(long_open_hooks)} 个伏笔未标注预期回收章节。本章是否回收其一？",
            "hook_ids": [h["id"] for h in long_open_hooks[:3]],
            "options": ["recycle_one", "not_now"],
            "option_labels": {
                "recycle_one": "回收一个",
                "not_now": "暂不",
            },
        })

    # 通用：作者补充意图
    questions.append({
        "id": "Q_AUTHOR_INTENT",
        "type": "free_text",
        "question": "本章你有什么特别的意图或要求吗？（可选）",
        "default": "",
    })

    return questions
