# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
双轨生成路由 (Dual Track Generation Routes) - V3.5

职责：提供基于双轨对抗架构的章节生成 API。

双轨架构流程：
1. 节拍生成（复用原有 planning）
2. 双轨并行生成（Track A: 节拍扩写 + Track B: 短文生成）
3. 节拍统稿
4. 对抗校对
5. 融合精修（可选）

API 端点：
- POST /api/chapters/{chapter_id}/generate-dual-track
- POST /api/chapters/{chapter_id}/generate-dual-track-preview

与原有路由的区别：
- 原有路由使用串行或纯并行生成
- 双轨路由使用并行 + 对抗校对，保证连贯性的同时不牺牲速度
"""

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.schemas import GenerateChapterAgenticRequest, ConfirmedStoryBeat
from backend.repositories import (
    ChapterRepository, BookRepository, MemoryRepository,
    PlotLedgerRepository, MapLocationRepository, RelationshipRepository,
)
from backend.services.orchestration import resolve_high_level_params, normalize_confirmed_beats
from backend.services.workflows.dual_track import (
    DualTrackWorkflow,
    DualTrackConfig,
    DualTrackResult,
)
from backend.services.workflows.sketch_generator import SketchGeneratorConfig
from backend.services.workflows.adversarial_aligner import AdversarialAlignerConfig
from backend.services.utils.prompt_logger import create_logger
from backend.services.utils.logging import (
    ServiceLogger, LOG_PREFIX_DUAL_TRACK,
    build_sse_event, build_sse_metric_frame, build_sse_done
)
from backend.services.context import (
    load_full_chapter_context,
    save_story_beats,
    build_physical_state_lock,
    ChapterContext,
)

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_DUAL_TRACK)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-dual-track"])


async def _persist_checkpoint(
    db: AsyncSession,
    chapter: Any,
    run_id: str,
    stage: str,
    status: str,
    payload: Optional[dict] = None,
) -> None:
    checkpoints = list(chapter.generation_checkpoints or [])
    checkpoint = {
        "stage": stage,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }
    checkpoints.append(checkpoint)
    chapter.generation_run_id = run_id
    chapter.generation_checkpoints = checkpoints[-20:]
    chapter.generation_status = {
        **(chapter.generation_status or {}),
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "updated_at": checkpoint["timestamp"],
    }
    await db.commit()


def _resolve_run_id(request: "DualTrackGenerationRequest", chapter: Any) -> str:
    if request.generation_run_id:
        return request.generation_run_id
    if request.resume_from_checkpoint and chapter.generation_run_id:
        return str(chapter.generation_run_id)
    return f"run_{uuid4().hex}"


class DualTrackGenerationRequest(GenerateChapterAgenticRequest):
    """双轨生成请求（扩展原有请求）"""
    
    # 用户在 beat 预览弹窗中确认的节拍（若提供则跳过内部 PLANNING，直接使用）
    beats: Optional[List[ConfirmedStoryBeat]] = None
    
    # 双轨特有配置
    enable_sketch_track: bool = True
    enable_adversarial_alignment: bool = True
    use_sketch_for_refinement: bool = True
    alignment_threshold: float = 70.0
    
    # Sketch 配置
    sketch_ratio: float = 0.45  # Sketch 字数占比
    
    # 模型选择
    sketch_model: Optional[str] = None  # 默认使用 creative_model


@router.post("/{chapter_id}/generate-dual-track")
async def generate_chapter_dual_track(
    chapter_id: str,
    request: DualTrackGenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    使用双轨架构生成章节正文。

    职责边界：本接口只负责【生成】，不做规划。
    调用方必须先通过 /generate_chapter_agentic_preview_beats 获取节拍，
    经用户确认后将 beats 附在请求体中发给本接口。

    Args:
        chapter_id: 章节 ID
        request: 双轨生成请求，request.beats 不得为空

    Returns:
        流式 SSE 响应，包含生成进度和最终结果
    """
    if str(request.chapter_id) != chapter_id:
        raise HTTPException(status_code=422, detail="path chapter_id 与请求体 chapter_id 不一致")

    if not request.beats and not request.resume_from_checkpoint:
        raise HTTPException(
            status_code=422,
            detail=(
                "beats 不能为空。"
                "请先通过 /generate_chapter_agentic_preview_beats 获取节拍，"
                "经用户确认后再调用本接口。"
            ),
        )

    async def generate_stream():
        import asyncio
        
        # 初始化 Prompt 日志记录器
        prompt_logger = create_logger(chapter_id=chapter_id, book_id=None)
        prompt_logger._finalized = False
        prompt_logger._final_text_length = 0
        prompt_logger._total_iterations = 1
        prompt_logger._review_passed = False
        
        # 创建事件队列，用于在 workflow 执行过程中接收进度事件
        progress_queue = asyncio.Queue()
        
        # 初始化关键变量，确保在异常处理时可用
        chapter = None
        run_id = None

        try:
            resolved_params = resolve_high_level_params(request)

            yield build_sse_event("ASSEMBLING_CONTEXT", "加载章节上下文...")

            repos = {
                "chapter": ChapterRepository(db),
                "book": BookRepository(db),
                "memory": MemoryRepository(db),
                "plot_ledger": PlotLedgerRepository(db),
                "map_location": MapLocationRepository(db),
                "relationship": RelationshipRepository(db),
            }

            context = await load_full_chapter_context(
                chapter_id, repos,
                rag_params=resolved_params if request.is_basic_mode() else None,
                api_key=request.api_key,
                base_url=request.base_url,
            )

            if not context:
                yield build_sse_event("ERROR", "章节不存在")
                return

            chapter = context.chapter
            book = context.book
            run_id = _resolve_run_id(request, chapter)
            effective_word_count = request.word_count or 2000
            effective_reasoning_model = request.reasoning_model or request.model
            effective_creative_model = request.creative_model or effective_reasoning_model
            effective_sketch_model = request.sketch_model or effective_creative_model
            effective_config = {
                "run_id": run_id,
                "chapter_id": chapter_id,
                "max_iterations": resolved_params["max_iterations"],
                "rag_top_k": resolved_params["rag_top_k"],
                "rag_alpha": resolved_params["rag_alpha"],
                "rag_beta": resolved_params["rag_beta"],
                "rag_gamma": resolved_params["rag_gamma"],
                "model": request.model,
                "reasoning_model": effective_reasoning_model,
                "creative_model": effective_creative_model,
                "sketch_model": effective_sketch_model,
                "word_count": effective_word_count,
            }
            chapter.generation_run_id = run_id
            chapter.generation_status = {
                **(chapter.generation_status or {}),
                "run_id": run_id,
                "status": "running",
                "stage": "ASSEMBLING_CONTEXT",
                "effective_config": effective_config,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.commit()
            yield build_sse_event("GENERATION_RUN", "生成任务已初始化", generation_run_id=run_id)

            prompt_logger.book_id = str(chapter.book_id) if chapter.book_id else None

            if request.tension_level is not None:
                chapter.tension_level = request.tension_level
            if request.pacing_style:
                chapter.pacing_style = request.pacing_style
            await db.commit()

            yield build_sse_event("ASSEMBLING_CONTEXT", "正在回顾前文与检索相关伏笔...")

            entities_list = list(context.entities)
            relationships_list = list(context.relationships)

            context_dict = {
                "entities_count": len(entities_list),
                "relationships_count": len(relationships_list),
            }

            yield build_sse_metric_frame("ASSEMBLING_CONTEXT_DONE", iteration=0, extra=context_dict)

            await _persist_checkpoint(
                db=db,
                chapter=chapter,
                run_id=run_id,
                stage="ASSEMBLING_CONTEXT_DONE",
                status="running",
                payload={
                    "entities": len(entities_list),
                    "relationships": len(relationships_list),
                    "memories": len(context.relevant_memories),
                    "locations": len(context.locations),
                },
            )

            prompt_logger.set_context(
                chapter_info={
                    "id": str(chapter.id),
                    "title": chapter.title,
                    "chapter_number": chapter.chapter_number,
                    "chapter_name": chapter.chapter_name,
                    "outline_preview": chapter.outline_text[:500] if chapter.outline_text else "",
                },
                book_info={
                    "id": str(book.id) if book else None,
                    "title": book.title if book else None,
                    "genre": book.genre if book else None,
                },
                entities=entities_list,
                relationships=relationships_list,
                request_params={
                    **effective_config,
                }
            )

            yield build_sse_event(
                "CONTEXT_LOADED",
                f"加载 {len(entities_list)} 个角色, {len(relationships_list)} 组关系"
            )
            
            # ========================================================================
            # BEATS 接收：直接使用调用方提供的已确认节拍，注入跨章状态约束
            # ========================================================================
            from backend.services.workflows.planning import assign_pov_to_beats
            from backend.services.prompts.world_state_prompts import format_snapshot_for_planner

            # 强制注入世界状态快照约束（P0 级 - 不可跳过）
            world_snapshot_constraints = ""
            if context.previous_world_snapshot:
                world_snapshot_constraints = format_snapshot_for_planner(context.previous_world_snapshot)
                svc_logger.info("World snapshot constraints injected", enabled=bool(world_snapshot_constraints))

            latest_status = chapter.generation_status or {}
            if request.resume_from_checkpoint and latest_status.get("run_id") == run_id and latest_status.get("status") == "completed":
                cached_text = latest_status.get("final_text") or chapter.draft_text or ""
                if cached_text:
                    yield build_sse_done(
                        text=cached_text,
                        stats=latest_status.get("stats") or {},
                        passed=bool(latest_status.get("passed", True)),
                        iterations=1,
                        revision_count=int(latest_status.get("revision_count", 0) or 0),
                        generation_run_id=run_id,
                        resumed=True,
                    )
                    return

            beats = []
            if request.beats:
                beats = normalize_confirmed_beats(request.beats, effective_word_count)
            elif request.resume_from_checkpoint and latest_status.get("run_id") == run_id:
                for checkpoint in reversed(chapter.generation_checkpoints or []):
                    if checkpoint.get("stage") == "BEATS_CONFIRMED":
                        beats = checkpoint.get("payload", {}).get("beats", [])
                        if beats:
                            break
            if not beats:
                raise HTTPException(status_code=422, detail="恢复失败：缺少可用 beats，请重新预览并确认节拍")

            for beat_dict in beats:
                if world_snapshot_constraints:
                    beat_dict["_world_snapshot_constraints"] = world_snapshot_constraints

            chapter_narrative_anchor = next(
                (b.get("pov_character") or "" for b in beats if b.get("pov_character")), ""
            )

            yield build_sse_event(
                "BEATS_CONFIRMED",
                f"已接收 {len(beats)} 个节拍，开始生成正文...",
                iteration=1
            )

            # 记录已确认的 beats（无 LLM 调用，仅记录最终执行的节拍列表）
            prompt_logger.start_stage("BEATS_CONFIRMED", iteration=1)
            prompt_logger.log_inputs(
                word_count=effective_word_count,
                has_previous_summary=bool(context.previous_summary),
                source="user_confirmed_beats",
            )
            prompt_logger.log_outputs(
                beat_count=len(beats),
                beats_preview=[{"id": b.get("beat_id"), "summary": b.get("summary", "")[:100]} for b in beats],
                chapter_narrative_anchor=chapter_narrative_anchor or None,
            )
            prompt_logger.end_stage(success=True)
            await _persist_checkpoint(
                db=db,
                chapter=chapter,
                run_id=run_id,
                stage="BEATS_CONFIRMED",
                status="running",
                payload={
                    "beats": beats,
                    "chapter_narrative_anchor": chapter_narrative_anchor or "",
                },
            )

            yield build_sse_metric_frame(
                "PLANNING_DONE",
                iteration=1,
                extra={"beat_count": len(beats), "chapter_narrative_anchor": chapter_narrative_anchor}
            )
            
            # ========================================================================
            # POV_ASSIGNMENT 阶段：视角分配
            # ========================================================================
            try:
                yield build_sse_event(
                    "POV_ASSIGNMENT",
                    "正在为剧情节拍分配 POV 角色...",
                    iteration=1
                )
                
                seen_char_ids: set = set()
                pov_candidates = []
                for e in context.entities:
                    if e.character and str(e.character.id) not in seen_char_ids:
                        seen_char_ids.add(str(e.character.id))
                        pov_candidates.append({
                            "name": e.character.name,
                            "role": "Main" if e.character.importance_level >= 8 else "Supporting",
                            "description": e.character.static_prompt or "",
                        })
                
                book_title = book.title if book else "Unknown Book"
                story_premise = f"Title: {book_title}\nChapter Outline: {chapter.outline_text or ''}"
                
                beats, pov_prompt_data = await assign_pov_to_beats(
                    beats=beats,
                    characters=pov_candidates,
                    story_premise=story_premise,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=effective_reasoning_model,
                    previous_chapter_summary=context.previous_summary,
                    prompt_logger=prompt_logger,
                    chapter_narrative_anchor=chapter_narrative_anchor,
                )
                
                # 发送 POV prompt 到前端
                yield f"data: {json.dumps({'prompt': pov_prompt_data}, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                svc_logger.error("POV Assignment failed", error=str(e))
                # Continue even if assignment fails
            
            anchor_pov = beats[0].get("pov_character") if beats else None
            
            # P1: 构建物理状态锁定
            physical_state_lock = build_physical_state_lock(beats)
            
            # P2: 保存 StoryBeat 到数据库
            story_beats = await save_story_beats(db, chapter, beats)
            svc_logger.debug("StoryBeats saved", count=len(story_beats))
            await _persist_checkpoint(
                db=db,
                chapter=chapter,
                run_id=run_id,
                stage="STATE_PERSISTENCE",
                status="running",
                payload={"saved_story_beats": len(story_beats)},
            )
            
            # 构建双轨配置
            config = DualTrackConfig(
                enable_sketch_track=request.enable_sketch_track,
                enable_adversarial_alignment=request.enable_adversarial_alignment,
                use_sketch_for_refinement=request.use_sketch_for_refinement,
                alignment_threshold=request.alignment_threshold,
                sketch_config=SketchGeneratorConfig(
                    sketch_ratio=request.sketch_ratio,
                ),
                aligner_config=AdversarialAlignerConfig(
                    min_acceptable_score=request.alignment_threshold,
                ),
            )
            
            # 创建双轨工作流，传入 prompt_logger
            workflow = DualTrackWorkflow(
                api_key=request.api_key,
                base_url=request.base_url,
                reasoning_model=effective_reasoning_model,
                creative_model=effective_creative_model,
                sketch_model=effective_sketch_model,
                config=config,
                prompt_logger=prompt_logger,
            )
            
            yield build_sse_event("DUAL_TRACK_START", "启动双轨并行生成...")
            
            # 发送 DRAFTING 事件，表示 Track A (节拍扩写) 开始
            yield build_sse_event("DRAFTING", "主笔 Agent 正在并行扩写节拍...", iteration=1)
            
            # 定义进度回调函数，用于在 workflow 执行过程中发送进度事件
            async def progress_callback(event: str, message: str, **kwargs):
                await progress_queue.put({'event': event, 'message': message, **kwargs})
            
            # 执行双轨生成的任务
            async def run_workflow():
                try:
                    result = await workflow.execute(
                        chapter=chapter,
                        book=book,
                        beats=beats,
                        entities=context.entities,
                        relationships=context.relationships,
                        word_count=effective_word_count,
                        previous_summary=context.previous_summary,  # P0: 跨章衔接
                        relevant_memories=context.relevant_memories,  # P1: RAG 记忆
                        locations=context.locations,  # P1: 地图位置
                        physical_state_lock=physical_state_lock,  # P1: 物理状态锁
                        chapter_assets_schema=chapter.chapter_assets_schema or "",  # P1: 章节资产模式
                        anchor_pov=anchor_pov,
                        progress_callback=progress_callback,
                    )
                    return result
                finally:
                    await progress_queue.put(None)  # 标记 workflow 完成
            
            # 并发执行 workflow 和进度事件处理
            workflow_task = asyncio.create_task(run_workflow())
            
            # 处理进度事件，直到 workflow 完成
            while True:
                try:
                    # 等待队列中的事件，设置超时以便检查 workflow 是否完成
                    event_data = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                    if event_data is None:  # workflow 完成信号
                        break
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 检查 workflow 是否已完成
                    if workflow_task.done():
                        # 处理队列中剩余的事件（使用非阻塞方式）
                        while not progress_queue.empty():
                            try:
                                event_data = progress_queue.get_nowait()
                                if event_data is not None:
                                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                            except asyncio.QueueEmpty:
                                break
                        break
            
            # 获取 workflow 结果
            result: DualTrackResult = await workflow_task
            
            # 更新最终状态
            prompt_logger._final_text_length = len(result.final_text) if result.final_text else 0
            prompt_logger._review_passed = not (result.adjustment_plan and result.adjustment_plan.needs_adjustment)
            
            # 发送 Track A 完成事件（内部事件，前端主要关注 DRAFTING 状态）
            yield build_sse_event(
                "TRACK_A_DONE",
                f"节拍扩写完成，{len(result.beat_drafts)} 个片段"
            )
            
            # 发送 Track B 完成事件（如果有，内部事件）
            if result.sketch_result:
                yield build_sse_event(
                    "TRACK_B_DONE",
                    f"速写生成完成，{result.sketch_result.word_count} 字"
                )
            
            # 发送统稿开始事件（STITCHING 表示进行中状态）
            yield build_sse_event("STITCHING", "正在统稿拼接各节拍内容...")
            
            # 计算是否需要调整（提前定义以便后续使用）
            needs_adjustment = result.adjustment_plan.needs_adjustment if result.adjustment_plan else False
            
            # 发送审阅事件（使用前端期望的 REVIEWING 而非 ALIGNMENT_DONE）
            if result.adjustment_plan:
                score = result.adjustment_plan.alignment_score
                needs_fix = result.adjustment_plan.needs_adjustment
                yield build_sse_event(
                    "REVIEWING",
                    f"审阅完成，对齐度得分: {score:.1f}",
                    score=score,
                    needs_fix=needs_fix
                )
            
            # 发送最终文本流事件（模拟流式输出以兼容前端）
            yield build_sse_event(
                "FINAL_TEXT_STREAM",
                "正在输出最终文本...",
                passed=not needs_adjustment
            )
            
            # 发送文本内容（分块以支持流式显示效果）
            final_text = result.final_text or ""
            chunk_size = 100  # 每块约100字符
            for i in range(0, len(final_text), chunk_size):
                chunk = final_text[i:i + chunk_size]
                yield f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': chunk}, ensure_ascii=False)}\n\n"
            
            # 发送最终结果（使用前端期望的 DONE 而非 COMPLETE）
            chapter.draft_text = result.final_text
            chapter.review_feedback = {
                **(chapter.review_feedback or {}),
                "generation_run_id": run_id,
                "alignment_score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
                "needs_adjustment": needs_adjustment,
                "stats": result.stats,
            }
            chapter.revision_count = 1 if needs_adjustment else 0
            chapter.generation_status = {
                **(chapter.generation_status or {}),
                "run_id": run_id,
                "status": "completed",
                "stage": "DONE",
                "passed": not needs_adjustment,
                "revision_count": chapter.revision_count,
                "stats": result.stats,
                "final_text": result.final_text,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await _persist_checkpoint(
                db=db,
                chapter=chapter,
                run_id=run_id,
                stage="DONE",
                status="completed",
                payload={
                    "alignment_score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
                    "final_length": len(result.final_text or ""),
                    "stats": result.stats,
                },
            )

            yield build_sse_done(
                text=result.final_text,
                stats=result.stats,
                alignment_score=result.adjustment_plan.alignment_score if result.adjustment_plan else None,
                passed=not needs_adjustment,
                iterations=1,
                revision_count=1 if needs_adjustment else 0,
                generation_run_id=run_id,
                resumed=request.resume_from_checkpoint,
            )
            
            # 完成日志记录
            prompt_logger.finalize(
                final_text_length=prompt_logger._final_text_length,
                total_iterations=1,
                review_passed=prompt_logger._review_passed
            )
            prompt_logger._finalized = True
        except BaseException as e:
            exc_type = type(e).__name__
            svc_logger.error(f"Generator exception: {exc_type}: {str(e)}")
            if chapter is not None and run_id is not None:
                try:
                    await _persist_checkpoint(
                        db=db,
                        chapter=chapter,
                        run_id=run_id,
                        stage="FAILED",
                        status="failed",
                        payload={"error": str(e), "exception_type": exc_type},
                    )
                except Exception:
                    pass

            if not isinstance(e, (GeneratorExit, asyncio.CancelledError)):
                try:
                    yield build_sse_event("ERROR", f"生成失败: {str(e)}")
                except Exception:
                    pass

            if isinstance(e, GeneratorExit):
                return

        finally:
            if not prompt_logger._finalized:
                prompt_logger.finalize(
                    final_text_length=prompt_logger._final_text_length,
                    total_iterations=prompt_logger._total_iterations,
                    review_passed=prompt_logger._review_passed
                )
                prompt_logger._finalized = True
    
    from fastapi.responses import StreamingResponse
    return StreamingResponse(generate_stream(), media_type="text/event-stream")


@router.post("/{chapter_id}/generate-dual-track-simple")
async def generate_chapter_dual_track_simple(
    chapter_id: str,
    request: DualTrackGenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    简化的双轨生成 API（非流式）
    
    返回完整的生成结果，不包含中间进度。
    """
    if str(request.chapter_id) != chapter_id:
        raise HTTPException(status_code=422, detail="path chapter_id 与请求体 chapter_id 不一致")

    resolved_params = resolve_high_level_params(request)
    effective_word_count = request.word_count or 2000
    effective_reasoning_model = request.reasoning_model or request.model
    effective_creative_model = request.creative_model or effective_reasoning_model
    effective_sketch_model = request.sketch_model or effective_creative_model

    # 构建 Repository 字典
    repos = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        "memory": MemoryRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "map_location": MapLocationRepository(db),
        "relationship": RelationshipRepository(db),
    }
    
    # 使用统一的上下文加载服务
    context = await load_full_chapter_context(chapter_id, repos)
    if not context:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    chapter = context.chapter
    book = context.book
    run_id = _resolve_run_id(request, chapter)
    chapter.generation_run_id = run_id
    chapter.generation_status = {
        **(chapter.generation_status or {}),
        "run_id": run_id,
        "status": "running",
        "stage": "ASSEMBLING_CONTEXT",
        "effective_config": {
            "run_id": run_id,
            "max_iterations": resolved_params["max_iterations"],
            "rag_top_k": resolved_params["rag_top_k"],
            "rag_alpha": resolved_params["rag_alpha"],
            "rag_beta": resolved_params["rag_beta"],
            "rag_gamma": resolved_params["rag_gamma"],
            "reasoning_model": effective_reasoning_model,
            "creative_model": effective_creative_model,
            "sketch_model": effective_sketch_model,
            "word_count": effective_word_count,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()
    
    # P2: 更新章节设置
    if request.tension_level is not None:
        chapter.tension_level = request.tension_level
    if request.pacing_style:
        chapter.pacing_style = request.pacing_style
    
    # 节拍生成（若请求携带 confirmed beats，直接使用；否则调用 LLM 重新规划）
    from backend.services.workflows.planning import generate_beats, assign_pov_to_beats
    
    if request.beats and len(request.beats) > 0:
        beats = normalize_confirmed_beats(request.beats, effective_word_count)
    else:
        beats, _ = await generate_beats(
            chapter=chapter,
            book=book,
            entities=context.entities,
            relationships=context.relationships,
            word_count=effective_word_count,
            open_hooks=context.open_hooks,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            previous_chapter_summary=context.previous_summary,
        )
    
    # POV 分配（confirmed beats 通常已带 pov_character，assign 仍可兜底补全）
    seen_char_ids_simple: set = set()
    pov_candidates = []
    for e in context.entities:
        if e.character and str(e.character.id) not in seen_char_ids_simple:
            seen_char_ids_simple.add(str(e.character.id))
            pov_candidates.append({
                "name": e.character.name,
                "role": "Main" if e.character.importance_level >= 8 else "Supporting",
                "description": e.character.static_prompt or "",
            })
    
    beats, _ = await assign_pov_to_beats(
        beats=beats,
        characters=pov_candidates,
        story_premise=book.title if book else "",
        api_key=request.api_key,
        base_url=request.base_url,
        model=effective_reasoning_model,
        previous_chapter_summary=context.previous_summary,
    )
    
    anchor_pov = beats[0].get("pov_character") if beats else None
    
    # P1: 构建物理状态锁定
    physical_state_lock = build_physical_state_lock(beats)
    
    # P2: 保存 StoryBeat 到数据库
    await save_story_beats(db, chapter, beats)
    
    # 执行双轨生成
    config = DualTrackConfig(
        enable_sketch_track=request.enable_sketch_track,
        enable_adversarial_alignment=request.enable_adversarial_alignment,
    )
    
    workflow = DualTrackWorkflow(
        api_key=request.api_key,
        base_url=request.base_url,
        reasoning_model=effective_reasoning_model,
        creative_model=effective_creative_model,
        sketch_model=effective_sketch_model,
        config=config,
    )
    
    result = await workflow.execute(
        chapter=chapter,
        book=book,
        beats=beats,
        entities=context.entities,
        relationships=context.relationships,
        word_count=effective_word_count,
        previous_summary=context.previous_summary,
        relevant_memories=context.relevant_memories,
        locations=context.locations,
        physical_state_lock=physical_state_lock,
        chapter_assets_schema=chapter.chapter_assets_schema or "",
        anchor_pov=anchor_pov,
    )

    needs_adjustment = result.adjustment_plan.needs_adjustment if result.adjustment_plan else False
    chapter.draft_text = result.final_text
    chapter.review_feedback = {
        **(chapter.review_feedback or {}),
        "generation_run_id": run_id,
        "alignment_score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
        "needs_adjustment": needs_adjustment,
        "stats": result.stats,
    }
    chapter.revision_count = 1 if needs_adjustment else 0
    chapter.generation_status = {
        **(chapter.generation_status or {}),
        "run_id": run_id,
        "status": "completed",
        "stage": "DONE",
        "passed": not needs_adjustment,
        "revision_count": chapter.revision_count,
        "stats": result.stats,
        "final_text": result.final_text,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _persist_checkpoint(
        db=db,
        chapter=chapter,
        run_id=run_id,
        stage="DONE",
        status="completed",
        payload={
            "alignment_score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
            "final_length": len(result.final_text or ""),
            "stats": result.stats,
        },
    )
    
    return {
        "success": True,
        "generation_run_id": run_id,
        "text": result.final_text,
        "word_count": len(result.final_text),
        "stats": result.stats,
        "alignment": {
            "score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
            "needs_adjustment": result.adjustment_plan.needs_adjustment if result.adjustment_plan else False,
            "gaps_count": len(result.adjustment_plan.gaps) if result.adjustment_plan else 0,
        } if result.adjustment_plan else None,
    }


# =============================================================================
# 辅助函数
# =============================================================================

# 注意：所有数据加载函数已下沉到 backend.services.context_loader 模块
# 本路由文件仅保留 API 层逻辑，业务逻辑下沉到服务层
