"""
章节生成路由模块 - 提供章节生成的 API 路由。

职责：
- 定义 ADF 生成引擎与 Refinery 精修的 API 端点
- 提供大纲澄清、成本报告、质量报告等附属端点
- 处理 SSE 流式响应

模块结构：
- adf.py: V3.2 ADF 引擎路由（当前默认生成引擎）
- refinery.py: V4.1 Refinery 精修流水线路由
- 本文件: extra_router（clarify-outline / cost-report / quality-report）

引擎剥离（2026-07）：V3.0 Detonation / V3.1 Unified / V4.0 DualTrack 三套引擎路由
及其专属的 stream_handler / progress_tracker / checkpoint_manager 已整体迁至
backend/_deprecated/，本模块不再注册或导出它们。

使用方式：
    from backend.routes.chapter_generation import router

    app.include_router(router)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from backend.core.dependencies import get_chapter_repository, get_book_repository, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from backend.repositories import (
    ChapterRepository, BookRepository, MemoryRepository,
    PlotLedgerRepository, MapLocationRepository, RelationshipRepository,
    AssetRepository, ChapterAssetRepository,
    ChapterCardRepository, StyleCardRepository, QualityReportRepository,
)
from backend.schemas import (
    ClarifyOutlineRequest,
    QualityReportResponse,
)
# CP4.5：preview_agentic_beats / GenerateChapterAgenticRequest / PreviewResponse 已废弃
# （合并闸门 /plan + /plan/confirm 取代；旧 preview-beats 端点已删除）
from backend.services.utils.logging import get_runtime_logger
from backend.services.workflows.clarification_agent import execute_clarification_stage
from backend.services.context.loader import load_full_chapter_context
from backend.world_state_schemas import WorldTerminalState
from backend.models import GenerationRun

# V3.2 ADF（Anchor-Driven Flow）引擎路由（当前默认引擎）
from backend.routes.chapter_generation.adf import router as adf_router

# V4.1 Refinery 精修流水线路由
from backend.routes.chapter_generation.refinery import router as refinery_router

# BS-ADF（Beat-Slot Anchor-Driven Flow）引擎路由（ADF 并行引擎，Phase 4 槽位化流水线）

# NLE-ADF 3.0 自适应辅助路由（作者主导写作流程：perceive/stitch-ghost/settle/detect-branch/plan-suggest）
from backend.routes.chapter_generation.adaptive import router as adaptive_router

# 创建额外的路由（用于节拍预览等）
extra_router = APIRouter(prefix="/api", tags=["chapter_generation"])

logger = get_runtime_logger(__name__)



# CP4.5：/generate_chapter_agentic_preview_beats 已下线（合并闸门 /plan 取代）。
# 旧端点 body 见 git history。新链路：/plan（联合预览）→ /plan/confirm（确认）→ /generate-chapter（流式生成）。


@extra_router.post("/clarify-outline")
async def clarify_chapter_outline(
    request: ClarifyOutlineRequest,
    db: AsyncSession = Depends(get_db),
):
    """大纲澄清端点 - 用于在生成节拍前澄清和完善章节大纲"""
    logger.info(f"[ClarifyOutline] 收到大纲澄清请求: chapter_id={request.chapter_id}")
    
    repos = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        "memory": MemoryRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "map_location": MapLocationRepository(db),
        "relationship": RelationshipRepository(db),
        "asset": AssetRepository(db),
        "chapter_asset": ChapterAssetRepository(db),
    }
    
    context = await load_full_chapter_context(request.chapter_id, repos)
    
    if not context or not context.chapter:
        raise HTTPException(status_code=404, detail="章节或上下文加载失败")
        
    chapter = context.chapter
    book = context.book
    
    # previous_world_terminal_state 需要从 previous_world_snapshot 获取
    previous_world_state = None
            
    result = await execute_clarification_stage(
        ambiguous_text=request.ambiguous_text,
        book=book,
        chapter=chapter,
        entities=context.entities,
        relationships=context.relationships,
        open_hooks=context.open_hooks,
        previous_chapter_summary=context.previous_summary,
        locations=context.locations,
        author_intent=request.author_intent,
        global_taboos=book.core_motifs_taboos if book else None,
        user_instruction=request.user_instruction,
        previous_issues=request.previous_issues,
        previous_chapter_snapshot=context.previous_world_snapshot,
        previous_world_terminal_state=previous_world_state,
    )
    
    return result


# Phase 0 T1.6：章级成本报告端点（必须在 router 合并前注册到 extra_router）
@extra_router.get("/chapters/{chapter_id}/cost-report")
async def get_chapter_cost_report(
    chapter_id: str,
    run_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """章级成本报告 - 聚合 generation_runs 表的分阶段 token 计量。

    Phase 0 观测层 T1.6：供前端展示每章 LLM 调用成本与降级情况。

    Args:
        chapter_id: 章节 ID
        run_id: 可选的运行 ID 过滤；不传则返回该章节最近一次 run

    Returns:
        {
            "chapter_id": "...",
            "run_id": "...",
            "stages": [{"stage", "calls", "prompt_tokens", "completion_tokens",
                        "thinking_tokens", "latency_ms_avg", "degraded_count", "model_slots"}],
            "totals": {"calls", "prompt_tokens", "completion_tokens",
                       "thinking_tokens", "total_tokens", "degraded_count"}
        }
    """
    # 若未指定 run_id，取该章节最近一次 run
    if not run_id:
        latest_stmt = (
            select(GenerationRun.run_id)
            .where(GenerationRun.chapter_id == chapter_id)
            .where(GenerationRun.run_id.isnot(None))
            .order_by(GenerationRun.created_at.desc())
            .limit(1)
        )
        latest_result = await db.execute(latest_stmt)
        latest_row = latest_result.first()
        if not latest_row:
            return {
                "chapter_id": chapter_id,
                "run_id": None,
                "stages": [],
                "totals": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                           "thinking_tokens": 0, "total_tokens": 0, "degraded_count": 0},
            }
        run_id = latest_row[0]

    # 拉取本次 run 的全部记录
    stmt = (
        select(GenerationRun)
        .where(GenerationRun.chapter_id == chapter_id)
        .where(GenerationRun.run_id == run_id)
        .order_by(GenerationRun.created_at)
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()

    if not runs:
        return {
            "chapter_id": chapter_id,
            "run_id": run_id,
            "stages": [],
            "totals": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                       "thinking_tokens": 0, "total_tokens": 0, "degraded_count": 0},
        }

    # 按 stage 聚合
    stage_agg: dict[str, dict] = {}
    totals = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": 0,
        "degraded_count": 0,
    }
    for run in runs:
        agg = stage_agg.setdefault(run.stage, {
            "stage": run.stage,
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "thinking_tokens": 0,
            "latency_ms_sum": 0,
            "latency_ms_count": 0,
            "degraded_count": 0,
            "model_slots": set(),
        })
        agg["calls"] += 1
        agg["prompt_tokens"] += run.prompt_tokens or 0
        agg["completion_tokens"] += run.completion_tokens or 0
        agg["thinking_tokens"] += run.thinking_tokens or 0
        if run.latency_ms is not None:
            agg["latency_ms_sum"] += run.latency_ms
            agg["latency_ms_count"] += 1
        if run.degraded:
            agg["degraded_count"] += 1
        if run.model_slot:
            agg["model_slots"].add(run.model_slot)

        totals["calls"] += 1
        totals["prompt_tokens"] += run.prompt_tokens or 0
        totals["completion_tokens"] += run.completion_tokens or 0
        totals["thinking_tokens"] += run.thinking_tokens or 0
        if run.degraded:
            totals["degraded_count"] += 1

    totals["total_tokens"] = (
        totals["prompt_tokens"] + totals["completion_tokens"] + totals["thinking_tokens"]
    )

    stages_out = []
    for agg in stage_agg.values():
        latency_avg = (
            agg["latency_ms_sum"] / agg["latency_ms_count"]
            if agg["latency_ms_count"] > 0 else 0
        )
        stages_out.append({
            "stage": agg["stage"],
            "calls": agg["calls"],
            "prompt_tokens": agg["prompt_tokens"],
            "completion_tokens": agg["completion_tokens"],
            "thinking_tokens": agg["thinking_tokens"],
            "latency_ms_avg": round(latency_avg),
            "degraded_count": agg["degraded_count"],
            "model_slots": sorted(list(agg["model_slots"])),
        })

    return {
        "chapter_id": chapter_id,
        "run_id": run_id,
        "stages": stages_out,
        "totals": totals,
    }


# ============================================================
# CP3.1c：质量报告端点（双层审计：代码级 + LLM 级）
# ============================================================
# 蓝图 §4.8.3 + decisions §3.5：
# - GET  /chapters/{id}/quality-report        获取本章最新质量报告
# - POST /chapters/{id}/quality-report/rerun  重新触发审计（可选）
#
# 审计流程：
# 1. 加载章节正文 + 上下文（章节卡 / 角色 / beats / 上章摘要）
# 2. CP3.1b 代码级审计（7 个 Auditor，零 token）
# 3. CP3.1c LLM 级审计（reasoning 槽，证据链 JSON）
# 4. merge_audit_results 合并 → 写入 QualityReport 表


async def _build_audit_context(
    db: AsyncSession,
    chapter_id: str,
) -> dict:
    """组装双层审计所需的 context（供 code/llm auditor 共用）。

    返回 dict 含：text / book / style_card / chapter_card / characters /
                prev_chapter_summary / beats / code_audit_findings 占位
    """
    chapter_repo = ChapterRepository(db)
    book_repo = BookRepository(db)
    chapter_card_repo = ChapterCardRepository(db)
    style_card_repo = StyleCardRepository(db)

    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    book = await book_repo.get_by_id(chapter.book_id) if chapter.book_id else None

    # 正文：优先 content_text，其次 draft_text
    text = (chapter.content_text or chapter.draft_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="章节正文为空，无法审计")

    # 章节卡（CP2.3）
    chapter_card_obj = await chapter_card_repo.get_by_chapter(chapter_id)
    chapter_card_dict = None
    if chapter_card_obj:
        chapter_card_dict = {
            "purpose": chapter_card_obj.purpose,
            "must_hit_events": chapter_card_obj.must_hit_events or [],
            "foreshadow_ops": chapter_card_obj.foreshadow_ops or [],
            "continuity": chapter_card_obj.continuity or {},
            "word_target": chapter_card_obj.word_target,
        }

    # 书级 StyleCard（CP2.2）：查 chapter_id=null 的书级卡
    from backend.models import StyleCard
    style_specs = await style_card_repo.find_all(
        conditions=[
            StyleCard.book_id == chapter.book_id,
            StyleCard.chapter_id.is_(None),
        ],
        limit=1,
    )
    style_card_dict = None
    if style_specs:
        sc = style_specs[0]
        style_card_dict = {
            "negative_list": sc.negative_list or [],
            "dialogue_ratio_target": sc.dialogue_ratio_target,
        }

    # 涉及角色（通过 chapter_entities 关联）
    from backend.models import Character, ChapterEntity
    char_result = await db.execute(
        select(Character)
        .join(ChapterEntity, ChapterEntity.entity_id == Character.id)
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    characters = char_result.scalars().all()
    characters_dict = [
        {
            "name": c.name,
            "aliases": c.aliases or [],
            "static_prompt": c.static_prompt or "",
            "dynamic_state": c.dynamic_state or "",
        }
        for c in characters
    ]

    # 节拍（beats）
    from backend.models import StoryBeat
    beats_result = await db.execute(
        select(StoryBeat)
        .where(StoryBeat.chapter_id == chapter_id)
        .order_by(StoryBeat.position.asc())
    )
    beats_orm = beats_result.scalars().all()
    beats_dict = [
        {
            "position": b.position,
            "participants": b.participants or [],
            "red_lines": b.red_lines or [],
            "word_count_target": b.word_count_target or 0,
            "summary": b.summary or "",
            "action_summary": b.action_summary or "",
        }
        for b in beats_orm
    ]

    # 上一章摘要（衔接校验）
    prev_summary = None
    if chapter.chapter_number and chapter.chapter_number > 1:
        prev_result = await db.execute(
            select(Chapter)
            .where(Chapter.book_id == chapter.book_id)
            .where(Chapter.chapter_number == chapter.chapter_number - 1)
            .limit(1)
        )
        prev_chapter = prev_result.scalars().first()
        if prev_chapter and prev_chapter.summary:
            prev_summary = prev_chapter.summary

    return {
        "chapter": chapter,
        "book": book,
        "text": text,
        "chapter_card": chapter_card_dict,
        "style_card": style_card_dict,
        "characters": characters_dict,
        "beats": beats_dict,
        "prev_chapter_summary": prev_summary,
    }


async def _execute_dual_layer_audit(
    db: AsyncSession,
    chapter_id: str,
    run_id: Optional[str],
) -> dict:
    """执行双层审计并写入 QualityReport，返回报告 dict（响应体）。

    流程：代码级 → LLM 级 → merge → 持久化。
    """
    from backend.services.validation import (
        CodeAuditPipeline,
        LLMAuditor,
        merge_audit_results,
    )

    ctx = await _build_audit_context(db, chapter_id)
    chapter = ctx["chapter"]
    text = ctx["text"]

    # 构造代码级审计 context（与 code_auditors 契约对齐）
    code_ctx = {
        # db：ClichéAuditor → StyleClicheValidator 系统层禁词直查 SystemCliche 表
        # （用户在 /system/cliches 增改的禁词由此进审计；无此键时降级种子）
        "db": db,
        "book": {
            "style_blacklist": getattr(ctx["book"], "style_blacklist", []) if ctx["book"] else [],
            "core_motifs_taboos": getattr(ctx["book"], "core_motifs_taboos", "") if ctx["book"] else "",
        },
        "style_card": ctx["style_card"] or {},
        "beats": ctx["beats"],
        "characters": ctx["characters"],
        "chapter_card": ctx["chapter_card"] or {},
        "prev_chapter_summary": ctx["prev_chapter_summary"],
    }

    # CP3.1b 代码级审计（零 token）
    code_pipeline = CodeAuditPipeline()
    code_result = await code_pipeline.run(text, code_ctx)

    # CP3.1c LLM 级审计（reasoning 槽）
    llm_auditor = LLMAuditor()
    llm_result = await llm_auditor.audit(
        text,
        chapter_card=ctx["chapter_card"],
        characters=ctx["characters"],
        prev_chapter_summary=ctx["prev_chapter_summary"],
        code_audit_findings=code_result.findings,
        beats=ctx["beats"],
    )

    # 合并
    metrics, findings, verdict, degraded = merge_audit_results(code_result, llm_result)

    # 持久化到 QualityReport 表
    repo = QualityReportRepository(db)
    saved = await repo.create({
        "chapter_id": chapter.id,
        "run_id": run_id or chapter.generation_run_id,
        "metrics": metrics,
        "findings": findings,
        "degraded": degraded,
        "verdict": verdict,
    })

    logger.info(
        f"[QualityReport] chapter={chapter_id} run={run_id} 持久化完成 "
        f"verdict={verdict} findings={len(findings)} degraded={bool(degraded)}"
    )

    return {
        "id": str(saved.id),
        "chapter_id": str(saved.chapter_id),
        "run_id": saved.run_id,
        "metrics": saved.metrics,
        "findings": saved.findings,
        "degraded": saved.degraded,
        "verdict": saved.verdict,
        "created_at": saved.created_at.isoformat() if saved.created_at else None,
    }


@extra_router.get("/chapters/{chapter_id}/quality-report", response_model=QualityReportResponse)
async def get_chapter_quality_report(
    chapter_id: str,
    run_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """获取本章质量报告（CP3.1c）。

    Args:
        chapter_id: 章节 ID
        run_id: 可选 run ID 过滤；不传则返回最新一份

    Returns:
        QualityReportResponse：含 metrics / findings / verdict / degraded
    """
    repo = QualityReportRepository(db)
    if run_id:
        report = await repo.get_by_chapter_run(chapter_id, run_id)
    else:
        report = await repo.get_latest(chapter_id)
    if not report:
        raise HTTPException(
            status_code=404,
            detail="该章节尚无质量报告，请先触发生成或 rerun",
        )
    return report


@extra_router.post("/chapters/{chapter_id}/quality-report/rerun")
async def rerun_chapter_quality_report(
    chapter_id: str,
    run_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """重新触发本章双层审计（CP3.1c）。

    业务场景：
    - 用户修改章节正文后重新审计
    - 旧报告已损坏需重算
    - 开发调试

    Args:
        chapter_id: 章节 ID
        run_id: 可选指定 run ID；默认沿用 chapter.generation_run_id

    Returns:
        新创建的 QualityReport dict
    """
    logger.info(f"[QualityReport] rerun 触发: chapter={chapter_id} run={run_id}")
    return await _execute_dual_layer_audit(db, chapter_id, run_id)


# 合并路由（必须在所有端点注册到 extra_router 之后）
router = APIRouter()
router.include_router(extra_router)
router.include_router(adf_router)
router.include_router(refinery_router)
router.include_router(adaptive_router)

__all__ = [
    "router",
]
