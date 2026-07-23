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
统一引擎路由（V3.1 §9.1 新建）。

职责（规格 §9.1 端点合并）：
提供统一生成入口 POST /api/chapters/{id}/generate，参数 tier: auto|climax|turn|progress|transition。
旧端点 /generate-chapter（双轨）+ /generate-v3（高潮倒推）保留并标记 deprecated，行为不变。

API 端点（前缀 /api/chapters/{chapter_id}）：
- POST /generate                   统一生成（SSE v3 事件序列）

SSE v3 事件序列（规格 §9.1 + 前端文档 §11.2）：
- UNIFIED_STAGE        阶段切换（TIER_CLASSIFY/SETUP_GROW/CLIMAX_WRITE/ZONE_WRITE/
                                SKETCH_BASELINE/ASSEMBLING/GRAPH_AUDIT/ANCHORED_AUDIT/
                                CLIMAX_REWRITE/REFINING）
- TIER_DECIDED         定档通知（含 tier/reason/climax_score）
- ZONE_ASSIGNED        三分区分配完成
- ZONE_PROGRESS        分区写作进度（含 zone 标识）
- SKETCH_BASELINE      自由速写对照结论
- INFLIGHT_REGULATION  飞行中调节事件
- MERGE_SUGGESTION     并章建议
- DEGRADED             降级事件（失败不静默）
- TEXT_CHUNK           文本块（流式正文）
- COMPLETE             完成（含 tier/zones/climax_check_score）
- ERROR                错误

与旧端点的关系：
- /generate-chapter（双轨）：保留不动，deprecated header
- /generate-v3（高潮倒推）：保留不动，deprecated header
- 本端点是新统一入口，自主完成定档+九个 Phase

使用方式：
    POST /api/chapters/{chapter_id}/generate
    body: {"tier": "auto"}  # 或 climax/turn/progress/transition
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.repositories import (
    ChapterRepository, BookRepository, PlotLedgerRepository,
    ChapterCardRepository, StyleCardRepository,
    ChapterAssetRepository, AssetRepository, MapLocationRepository,
    MemoryRepository, RelationshipRepository,
    DetonationChainRepository,
)
from backend.schemas import GenerateUnifiedRequest
from backend.services.context.loader import load_full_chapter_context
from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.detonation_prompts import (
    build_payload_candidate_prompt,
    parse_payload_candidate_response,
)
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import (
    build_sse_event, build_sse_text_chunk, build_sse_error,
)
from backend.services.workflows.detonation import (
    grow_detonation_chain,
    extract_established_facts,
    plant_ledgers_from_chain,
)
from backend.services.workflows.detonation.unified_workflow import UnifiedWorkflow

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-unified-v3.1"])


# ============================================================
# 辅助：上下文加载（与 detonation.py 同构，独立避免循环依赖）
# ============================================================

async def _load_unified_context(
    db: AsyncSession,
    chapter_id: str,
) -> Dict[str, Any]:
    """加载统一生成所需的完整上下文。"""
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
    from backend.models import StyleCard
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
    except Exception as e:
        logger.warning(f"[Unified] load_full_chapter_context 失败，降级空上下文: {e}")
        entities = []
        open_hooks = []
        previous_summary = None

    rolling_summary = getattr(book, "rolling_summary", None) if book else None

    return {
        "chapter": chapter,
        "book": book,
        "chapter_card": chapter_card,
        "style_card": style_card,
        "entities": entities,
        "open_hooks": open_hooks,
        "previous_summary": previous_summary,
        "rolling_summary": rolling_summary,
    }


async def _generate_payload_candidates(
    ctx: Dict[str, Any],
    count: int,
    recorder: Optional[RunRecorder],
) -> List[Dict[str, Any]]:
    """生成高潮点候选（含 climax_score 强度自评，规格 §2.2 依据 1）。"""
    chapter = ctx["chapter"]
    system_prompt, user_prompt = build_payload_candidate_prompt(
        chapter=chapter,
        chapter_card=ctx["chapter_card"] or chapter,
        previous_summary=ctx["previous_summary"],
        rolling_summary=ctx["rolling_summary"],
        open_hooks=ctx["open_hooks"],
        entities=ctx["entities"],
        count=count,
    )
    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="unified.payload_candidate",
                model_slot="reasoning",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.5,
                    max_tokens=4096,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.5,
                max_tokens=4096,
            )
        candidates, degraded = parse_payload_candidate_response(result.content, expected_count=count)
        return candidates
    except Exception as e:
        logger.warning(f"[Unified] 候选生成失败: {e}")
        return []


# ============================================================
# POST /generate —— 统一生成入口（SSE v3 事件序列）
# ============================================================

@router.post("/{chapter_id}/generate")
async def generate_unified_stream(
    chapter_id: str,
    request: Optional[GenerateUnifiedRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """统一引擎生成入口（V3.1，规格 §9.1）。

    自主完成：定档 → 铺垫结构生长 → 三区写作 → 审校 → 飞行中调节 → 回写。

    Args:
        chapter_id: 章节 ID
        request: tier=auto(默认)|climax|turn|progress|transition

    Returns:
        流式 SSE 响应（v3 事件序列）

    前置：无（统一管线自主完成全部流程，不依赖闸门）
    """
    handler = _UnifiedStreamHandler(
        chapter_id=chapter_id,
        request=request or GenerateUnifiedRequest(),
        db=db,
    )
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


# ============================================================
# SSE 流处理器（内部类）
# ============================================================

class _UnifiedStreamHandler:
    """统一引擎 SSE 流处理器。

    职责：
    - 加载上下文（Phase 0）
    - 生成高潮候选（Phase 1 输入）
    - 初始化 RunRecorder
    - 执行 UnifiedWorkflow
    - 把阶段进度 + 事件通过 SSE v3 推给前端
    - 持久化生成结果到 Chapter.draft_text + DetonationChain（SetupGraph）
    """

    def __init__(
        self,
        chapter_id: str,
        request: GenerateUnifiedRequest,
        db: AsyncSession,
    ):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def stream(self):
        """SSE 流生成器（v3 事件序列）。"""
        run_id = f"unified_{uuid4().hex[:12]}"

        try:
            # ---- Phase 0: 上下文组装 ----
            yield build_sse_event("UNIFIED_STAGE", "进入阶段：CONTEXT_ASSEMBLING", stage="CONTEXT_ASSEMBLING")
            ctx = await _load_unified_context(self.db, self.chapter_id)
            chapter = ctx["chapter"]
            book = ctx["book"]

            # ---- 初始化 RunRecorder ----
            recorder = RunRecorder(chapter_id=self.chapter_id, run_id=run_id)
            yield build_sse_event("GENERATION_RUN", "统一引擎已初始化", generation_run_id=run_id)

            # ---- Phase 1 输入：生成高潮候选（含强度自评）----
            yield build_sse_event("UNIFIED_STAGE", "进入阶段：PAYLOAD_CANDIDATES", stage="PAYLOAD_CANDIDATES")
            candidates = await _generate_payload_candidates(
                ctx=ctx,
                count=self.request.payload_count,
                recorder=recorder,
            )
            yield build_sse_event("PAYLOAD_CANDIDATES", f"已生成 {len(candidates)} 个高潮候选",
                                  count=len(candidates),
                                  candidates=[{"description": c.get("description", ""),
                                               "climax_score": c.get("climax_score")} for c in candidates])

            # ---- 构造 established_facts（供 Phase 2 铺垫结构生长用）----
            established_facts = extract_established_facts(
                entities=ctx["entities"],
                open_hooks=ctx["open_hooks"],
                previous_summary=ctx["previous_summary"],
                rolling_summary=ctx["rolling_summary"],
            )

            # ---- 初始化 UnifiedWorkflow ----
            workflow = UnifiedWorkflow(
                chapter=chapter,
                book=book,
                chapter_card=ctx["chapter_card"],
                entities=ctx["entities"],
                style_card=ctx["style_card"],
                author_samples=None,  # Slice A 简化
                recorder=recorder,
                tier=self.request.tier,
                candidates=candidates,
                user_tier_hint=self.request.user_tier_hint,
                established_facts=established_facts,
                open_hooks=ctx["open_hooks"],
                previous_summary=ctx["previous_summary"],
                rolling_summary=ctx["rolling_summary"],
                enable_sketch_baseline=self.request.enable_sketch_baseline,
                enable_anchored_audit=self.request.enable_anchored_audit,
                enable_refinement=self.request.enable_refinement,
                enable_inflight_regulation=self.request.enable_inflight_regulation,
            )

            # ---- progress_callback 转 SSE v3 事件 ----
            sse_queue: list = []

            async def _on_progress(event: str, data: dict) -> None:
                # 简化策略：直接 yield 不行（callback 不能 yield），用 list 暂存
                # 这里改为：workflow 内部串行，事件直接在下面循环推送
                sse_queue.append((event, data))

            # 由于 callback 不能直接 yield，且 workflow 是串行的，
            # 这里 await 整个 execute，期间事件不实时上浮（简化）。
            # 真正实时流式留待优化：把 progress_callback 改为 asyncio.Queue。
            result = await workflow.execute(progress_callback=_on_progress)

            # 把 callback 期间累积的事件推出去
            for event, data in sse_queue:
                if event == "TIER_DECIDED":
                    yield build_sse_event("TIER_DECIDED", f"定档：{data.get('tier')}", **data)
                elif event == "ZONE_ASSIGNED":
                    yield build_sse_event("ZONE_ASSIGNED", "三分区分配完成", **data)
                elif event == "ZONE_PROGRESS":
                    yield build_sse_event("ZONE_PROGRESS",
                                          f"写作 {data.get('segment_index')}/{data.get('total_segments')} ({data.get('zone')})",
                                          **data)
                elif event == "SKETCH_BASELINE":
                    yield build_sse_event("SKETCH_BASELINE", "自由速写对照完成", **data)
                elif event == "INFLIGHT_REGULATION":
                    yield build_sse_event("INFLIGHT_REGULATION",
                                          f"飞行中调节：{data.get('type')}", **data)
                elif event == "MERGE_SUGGESTION":
                    yield build_sse_event("MERGE_SUGGESTION",
                                          f"并章建议：{data.get('suggestion_type')}", **data)
                elif event == "UNIFIED_STAGE":
                    yield build_sse_event("UNIFIED_STAGE",
                                          f"进入阶段：{data.get('stage')}", **data)

            # ---- 持久化 RunRecorder ----
            try:
                count = await recorder.flush_to_db(self.db)
                await self.db.commit()
                logger.info(f"[Unified] RunRecorder 落库 {count} 条")
            except Exception as e:
                logger.warning(f"[Unified] RunRecorder 落库失败（不阻塞）: {e}")

            # ---- 持久化正文到 Chapter.draft_text ----
            if result.final_text:
                try:
                    chapter.draft_text = result.final_text
                    chapter.generation_run_id = run_id
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[Unified] 持久化 draft_text 失败: {e}")

            # ---- 持久化 SetupGraph 到 DetonationChain（V3.1 演进）----
            chain = None
            try:
                chain_repo = DetonationChainRepository(self.db)
                # 若已有活跃链，标记 done
                existing = await chain_repo.get_active_by_chapter(chapter.id)
                if existing:
                    await chain_repo.update_status(existing, status="done")
                # 新建 chain（tier=zones 写入，演进为 SetupGraph 语义）
                chain = await chain_repo.create_for_chapter(
                    book_id=chapter.book_id,
                    chapter_id=chapter.id,
                    payload=result.payload,
                    nodes=result.nodes,
                    reading_order=result.reading_order,
                    status="done",
                    confirmed_by="auto",
                    tier=result.tier_decision.get("tier"),
                    tier_reason=result.tier_decision.get("reason"),
                    zones=result.zones,
                )
            except Exception as e:
                logger.warning(f"[Unified] SetupGraph 持久化失败（不阻塞）: {e}")

            # ---- Phase 9: 伏笔自动登记（规格 §9 + D5）----
            ledger_result = None
            try:
                ledger_result = await plant_ledgers_from_chain(
                    db=self.db,
                    chain_id=chain.id if chain else uuid4(),
                    book_id=chapter.book_id,
                    chapter_id=chapter.id,
                    nodes=result.nodes,
                    full_text=result.final_text,
                    chapter_number=getattr(chapter, "chapter_number", None),
                )
                if ledger_result.get("planted"):
                    await self.db.commit()
                    logger.info(f"[Unified] 伏笔自动登记 {len(ledger_result['planted'])} 条")
            except Exception as e:
                logger.warning(f"[Unified] 伏笔登记失败（不阻塞）: {e}")
                ledger_result = {"planted": [], "skipped": 0,
                                 "degraded": {"reason": "exception", "action": "skip"}}

            # ---- 推送降级事件（失败不静默）----
            for deg in result.degraded:
                yield build_sse_event(
                    "DEGRADED",
                    f"阶段 {deg.get('reason', '?')} 降级",
                    stage=deg.get("reason", ""),
                    reason=deg.get("reason", ""),
                    action=deg.get("action", ""),
                    detail=str(deg.get("detail", ""))[:200],
                )

            # ---- 推送审计指标 ----
            yield build_sse_event(
                "UNIFIED_METRIC",
                "统一引擎审计指标",
                metrics={
                    "graph_audit": result.graph_audit,
                    "anchored_audit": result.anchored_audit,
                    "stats": result.stats,
                    "ledger_plant": ledger_result,
                    "sketch_baselines": result.sketch_baselines,
                    "inflight_events": result.inflight_events,
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

            # ---- COMPLETE（v3 事件，含 tier/zones/climax_check_score）----
            complete_payload = {
                "event": "COMPLETE",
                "text": result.final_text,
                "stats": result.stats,
                "generation_run_id": run_id,
                "chain_id": str(chain.id) if chain else None,
                # V3.1 新字段
                "tier": result.tier_decision.get("tier"),
                "tier_reason": result.tier_decision.get("reason"),
                "zones": result.zones,
                "climax_check_score": result.stats.get("climax_check_score"),
                "graph_audit_verdict": result.graph_audit.get("verdict") if result.graph_audit else None,
                "inflight_event_count": len(result.inflight_events),
            }
            yield f"data: {json.dumps(complete_payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception(f"[Unified] SSE 流异常: {e}")
            yield build_sse_error(f"生成失败: {type(e).__name__}: {str(e)[:200]}")
