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
import time
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from backend.core.dependencies import get_db
from backend.models import (
    Chapter, Book, ChapterEntity, CharacterRelationship,
    ChapterMapLocation, PlotLedger, StoryBeat
)
from backend.schemas import GenerateChapterAgenticRequest, ConfirmedStoryBeat
from backend.services.workflows.dual_track import (
    DualTrackWorkflow,
    DualTrackConfig,
    DualTrackResult,
)
from backend.services.workflows.sketch_generator import SketchGeneratorConfig
from backend.services.workflows.adversarial_aligner import AdversarialAlignerConfig
from backend.services.prompt_logger import create_logger, get_logger
from backend.services.llm_client import get_embedding
from backend.repositories import MemoryRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-dual-track"])


# =============================================================================
# 观测性辅助函数
# =============================================================================

def _to_secs(elapsed: float) -> float:
    """将秒转换为保留3位小数的浮点数"""
    return round(elapsed, 3)


def _metric_frame(
    event: str,
    iteration: int = 1,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """生成统计帧 SSE 消息"""
    payload = {
        "event": event,
        "iteration": iteration,
        "metrics": extra or {},
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
    使用双轨架构生成章节
    
    这是 V3.5 推荐的高级生成模式，特点：
    - 并行生成节拍扩写和连贯速写
    - 自动进行对抗校对
    - 修复节拍间的连贯性问题
    
    Args:
        chapter_id: 章节 ID
        request: 双轨生成请求
        
    Returns:
        流式 SSE 响应，包含生成进度和最终结果
    """
    
    async def generate_stream():
        # 初始化 Prompt 日志记录器
        prompt_logger = create_logger(chapter_id=chapter_id, book_id=None)
        prompt_logger._finalized = False
        prompt_logger._final_text_length = 0
        prompt_logger._total_iterations = 1
        prompt_logger._review_passed = False
        
        try:
            # 加载上下文
            yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '加载章节上下文...'}, ensure_ascii=False)}\n\n"
            
            chapter = await _load_chapter(db, chapter_id)
            if not chapter:
                yield f"data: {json.dumps({'error': '章节不存在'}, ensure_ascii=False)}\n\n"
                return
            
            # 更新日志记录器的 book_id
            prompt_logger.book_id = str(chapter.book_id) if chapter.book_id else None
            
            # P2: 更新章节设置（tension_level / pacing_style）
            if request.tension_level is not None:
                chapter.tension_level = request.tension_level
            if request.pacing_style:
                chapter.pacing_style = request.pacing_style
            
            book = await _load_book(db, chapter.book_id)
            entities = await _load_entities(db, chapter_id)
            relationships = await _load_relationships(db, entities)
            
            # P1: 加载地图位置
            locations = await _load_locations(db, chapter_id)
            
            yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '正在回顾前文与检索相关伏笔...'}, ensure_ascii=False)}\n\n"
            
            # P0: 加载上一章摘要（跨章衔接核心）
            previous_summary = await _load_previous_summary(db, chapter)
            logger.debug(f"[DualTrack] Previous Summary: {bool(previous_summary)}")

            # P0: 加载上一章世界状态快照
            previous_chapter_snapshot = await _load_previous_world_snapshot(db, chapter)
            logger.debug(f"[DualTrack] Previous World Snapshot: {bool(previous_chapter_snapshot)}")
            
            # P0: 加载开放伏笔
            open_hooks = await _load_open_hooks(db, chapter)
            logger.debug(f"[DualTrack] Open Hooks: {len(open_hooks)}")
            
            # P1: 加载 RAG 相关记忆
            relevant_memories = await _load_relevant_memories(db, chapter, request)
            logger.debug(f"[DualTrack] Relevant Memories: {len(relevant_memories)}")
            
            # 发送上下文加载完成统计帧
            yield _metric_frame("ASSEMBLING_CONTEXT_DONE", iteration=0, extra={
                "entities_count": len(entities),
                "relationships_count": len(relationships),
                "locations_count": len(locations),
                "open_hooks_count": len(open_hooks),
                "has_previous_summary": bool(previous_summary),
            })
            
            # 设置日志记录器的上下文信息
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
                entities=list(entities),
                relationships=list(relationships),
                request_params={
                    "model": request.model,
                    "reasoning_model": request.reasoning_model,
                    "creative_model": request.creative_model,
                    "word_count": request.word_count,
                }
            )
            
            yield f"data: {json.dumps({'event': 'CONTEXT_LOADED', 'message': f'加载 {len(entities)} 个角色, {len(relationships)} 组关系'}, ensure_ascii=False)}\n\n"
            
            # ========================================================================
            # PLANNING 阶段：节拍生成（若请求携带 confirmed beats，则走快速路径）
            # ========================================================================
            planning_started_at = time.perf_counter()
            
            from backend.services.workflows.planning import assign_pov_to_beats
            from backend.services.prompts import build_planner_agent_prompt, parse_planner_full_result
            from backend.services.llm_client import call_llm
            from backend.services.prompts.world_state_prompts import format_snapshot_for_planner
            
            confirmed_beats = request.beats  # 前端 beat 预览弹窗中用户确认的节拍
            
            if confirmed_beats and len(confirmed_beats) > 0:
                # ── 快速路径：直接使用用户确认的节拍，跳过 LLM PLANNING ──
                # ⚠️ 重要：即使走快速路径，世界状态快照约束也必须注入！
                # 注意：确认 beats 后直接进入生成，不再记录 PLANNING 阶段
                
                # ========================================================================
                # 强制注入：世界状态快照约束（P0级 - 不可跳过）
                # ========================================================================
                world_snapshot_constraints = ""
                if previous_chapter_snapshot:
                    world_snapshot_constraints = format_snapshot_for_planner(previous_chapter_snapshot)
                    logger.info(f"[快速路径] 注入世界状态快照约束: {bool(world_snapshot_constraints)}")
                
                beats = []
                for b in confirmed_beats:
                    beat_dict = b.model_dump()
                    # 保证 target_words 有值
                    if not beat_dict.get("target_words") or beat_dict["target_words"] <= 0:
                        beat_dict["target_words"] = beat_dict.get("word_count_target") or max(200, request.word_count // len(confirmed_beats))
                    # 🔒 强制附加世界状态约束到每个beat（供DRAFTING阶段使用）
                    if world_snapshot_constraints:
                        beat_dict["_world_snapshot_constraints"] = world_snapshot_constraints
                    beats.append(beat_dict)
                
                # 叙事核心角色：取第一个有 pov_character 的 beat，或空字符串
                chapter_narrative_anchor = next(
                    (b.get("pov_character") or "" for b in beats if b.get("pov_character")), ""
                )
                
                # 记录用户确认的 beats（无 LLM 调用，但记录最终执行的 beats）
                prompt_logger.start_stage("BEATS_CONFIRMED", iteration=1)
                prompt_logger.log_inputs(
                    word_count=request.word_count,
                    has_previous_summary=bool(previous_summary),
                    source="user_confirmed_beats",
                )
                prompt_logger.log_outputs(
                    beat_count=len(beats),
                    beats_preview=[{"id": b.get("beat_id"), "summary": b.get("summary", "")[:100]} for b in beats],
                    chapter_narrative_anchor=chapter_narrative_anchor or None,
                )
                prompt_logger.end_stage(success=True)
                
            else:
                # ── 标准路径：调用 LLM 重新规划节拍 ──
                yield f"data: {json.dumps({'event': 'PLANNING', 'message': 'Planner 正在拆分章节 beats...', 'iteration': 1}, ensure_ascii=False)}\n\n"
                
                # 构建 Planner Prompt
                planner_system_prompt, planner_user_prompt = build_planner_agent_prompt(
                    chapter=chapter,
                    book=book,
                    entities=entities,
                    relationships=relationships,
                    word_count=request.word_count,
                    open_hooks=open_hooks,
                    previous_chapter_summary=previous_summary,
                    locations=locations,
                    global_taboos=book.core_motifs_taboos if book else None,
                    author_intent=getattr(request, 'author_intent', None),
                    previous_chapter_snapshot=previous_chapter_snapshot,
                )
                
                # 记录 PLANNING 阶段的 Prompt
                prompt_logger.start_stage("PLANNING", iteration=1)
                prompt_logger.log_inputs(
                    word_count=request.word_count,
                    open_hooks_count=len(open_hooks),
                    has_previous_summary=bool(previous_summary)
                )
                _planning_model = request.reasoning_model or request.model
                prompt_logger.log_prompts(
                    system_prompt=planner_system_prompt,
                    user_prompt=planner_user_prompt,
                    model=_planning_model,
                    temperature=0.2,
                    max_tokens=1800,
                    prompt_label="PLANNER"
                )
                
                # 发送 prompt 到前端（用于 Debug 窗口）
                yield f"data: {json.dumps({'prompt': {'system_prompt': planner_system_prompt, 'user_prompt': planner_user_prompt}}, ensure_ascii=False)}\n\n"
                
                # 调用 LLM 生成节拍
                planner_result_raw = await call_llm(
                    system_prompt=planner_system_prompt,
                    user_prompt=planner_user_prompt,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=_planning_model,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    max_tokens=1800,
                )
                
                beats, chapter_narrative_anchor = parse_planner_full_result(planner_result_raw, chapter.outline_text or "", request.word_count)
                
                # 记录 PLANNING 阶段的输出
                prompt_logger.log_outputs(
                    beat_count=len(beats),
                    beats_preview=[{"id": b.get("beat_id"), "summary": b.get("summary", "")[:100]} for b in beats],
                    chapter_narrative_anchor=chapter_narrative_anchor or None,
                )
                prompt_logger.end_stage(success=True)
            
            # 发送统计帧
            yield _metric_frame("PLANNING_DONE", iteration=1, extra={"beat_count": len(beats), "chapter_narrative_anchor": chapter_narrative_anchor})
            
            # ========================================================================
            # POV_ASSIGNMENT 阶段：视角分配
            # ========================================================================
            try:
                yield f"data: {json.dumps({'event': 'POV_ASSIGNMENT', 'message': '正在为剧情节拍分配 POV 角色...', 'iteration': 1}, ensure_ascii=False)}\n\n"
                
                seen_char_ids: set = set()
                pov_candidates = []
                for e in entities:
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
                    model=request.reasoning_model or request.model,
                    previous_chapter_summary=previous_summary,
                    prompt_logger=prompt_logger,
                    chapter_narrative_anchor=chapter_narrative_anchor,
                )
                
                # 发送 POV prompt 到前端
                yield f"data: {json.dumps({'prompt': pov_prompt_data}, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                logger.error(f"[POV Assignment] {e}")
                # Continue even if assignment fails
            
            anchor_pov = beats[0].get("pov_character") if beats else None
            
            # P1: 构建物理状态锁定
            physical_state_lock = _build_physical_state_lock(beats)
            
            # P2: 保存 StoryBeat 到数据库
            story_beats = await _save_story_beats(db, chapter, beats)
            logger.debug(f"[DualTrack] Saved {len(story_beats)} StoryBeats to database")
            
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
                reasoning_model=request.reasoning_model or request.model,
                creative_model=request.creative_model or request.model,
                config=config,
                prompt_logger=prompt_logger,
            )
            
            yield f"data: {json.dumps({'event': 'DUAL_TRACK_START', 'message': '启动双轨并行生成...'}, ensure_ascii=False)}\n\n"
            
            # 发送 DRAFTING 事件，表示 Track A (节拍扩写) 开始
            yield f"data: {json.dumps({'event': 'DRAFTING', 'message': '主笔 Agent 正在并行扩写节拍...', 'iteration': 1}, ensure_ascii=False)}\n\n"
            
            # P1: 获取 reasoning_config（如果启用）
            reasoning_config = None
            if hasattr(request, 'reasoning_config') and request.reasoning_config and request.reasoning_config.enabled:
                reasoning_config = request.reasoning_config.to_api_params()
            
            # 执行双轨生成
            result: DualTrackResult = await workflow.execute(
                chapter=chapter,
                book=book,
                beats=beats,
                entities=entities,
                relationships=relationships,
                word_count=request.word_count,
                previous_summary=previous_summary,  # P0: 跨章衔接
                relevant_memories=relevant_memories,  # P1: RAG 记忆
                locations=locations,  # P1: 地图位置
                physical_state_lock=physical_state_lock,  # P1: 物理状态锁
                chapter_assets_schema=chapter.chapter_assets_schema or "",  # P1: 章节资产模式
                anchor_pov=anchor_pov,
            )
            
            # 更新最终状态
            prompt_logger._final_text_length = len(result.final_text) if result.final_text else 0
            prompt_logger._review_passed = not (result.adjustment_plan and result.adjustment_plan.needs_adjustment)
            
            # 发送 Track A 完成事件（内部事件，前端主要关注 DRAFTING 状态）
            yield f"data: {json.dumps({'event': 'TRACK_A_DONE', 'message': f'节拍扩写完成，{len(result.beat_drafts)} 个片段'}, ensure_ascii=False)}\n\n"
            
            # 发送 Track B 完成事件（如果有，内部事件）
            if result.sketch_result:
                yield f"data: {json.dumps({'event': 'TRACK_B_DONE', 'message': f'速写生成完成，{result.sketch_result.word_count} 字'}, ensure_ascii=False)}\n\n"
            
            # 发送统稿事件（使用前端期望的 STITCHING 而非 STITCHING_DONE）
            yield f"data: {json.dumps({'event': 'STITCHING', 'message': f'统稿完成，{len(result.stitched_draft)} 字'}, ensure_ascii=False)}\n\n"
            
            # 计算是否需要调整（提前定义以便后续使用）
            needs_adjustment = result.adjustment_plan.needs_adjustment if result.adjustment_plan else False
            
            # 发送审阅事件（使用前端期望的 REVIEWING 而非 ALIGNMENT_DONE）
            if result.adjustment_plan:
                score = result.adjustment_plan.alignment_score
                needs_fix = result.adjustment_plan.needs_adjustment
                yield f"data: {json.dumps({'event': 'REVIEWING', 'message': f'审阅完成，对齐度得分: {score:.1f}', 'score': score, 'needs_fix': needs_fix}, ensure_ascii=False)}\n\n"
            
            # 发送最终文本流事件（模拟流式输出以兼容前端）
            yield f"data: {json.dumps({'event': 'FINAL_TEXT_STREAM', 'message': '正在输出最终文本...', 'passed': not needs_adjustment}, ensure_ascii=False)}\n\n"
            
            # 发送文本内容（分块以支持流式显示效果）
            final_text = result.final_text or ""
            chunk_size = 100  # 每块约100字符
            for i in range(0, len(final_text), chunk_size):
                chunk = final_text[i:i + chunk_size]
                yield f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': chunk}, ensure_ascii=False)}\n\n"
            
            # 发送最终结果（使用前端期望的 DONE 而非 COMPLETE）
            yield f"data: {json.dumps({
                'event': 'DONE',
                'text': result.final_text,
                'stats': result.stats,
                'alignment_score': result.adjustment_plan.alignment_score if result.adjustment_plan else None,
                'passed': not needs_adjustment,
                'iterations': 1,
                'revision_count': 1 if needs_adjustment else 0,
            }, ensure_ascii=False)}\n\n"
            
            # 完成日志记录
            prompt_logger.finalize(
                final_text_length=prompt_logger._final_text_length,
                total_iterations=1,
                review_passed=prompt_logger._review_passed
            )
            prompt_logger._finalized = True
            
        finally:
            # 确保异常时也能保存日志
            if not prompt_logger._finalized:
                logger.warning("[DualTrack] 生成器异常退出，强制保存日志")
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
    chapter = await _load_chapter(db, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # P2: 更新章节设置
    if request.tension_level is not None:
        chapter.tension_level = request.tension_level
    if request.pacing_style:
        chapter.pacing_style = request.pacing_style
    
    book = await _load_book(db, chapter.book_id)
    entities = await _load_entities(db, chapter_id)
    relationships = await _load_relationships(db, entities)
    
    # P1: 加载地图位置
    locations = await _load_locations(db, chapter_id)
    
    # P0: 加载上一章摘要
    previous_summary = await _load_previous_summary(db, chapter)
    
    # P0: 加载开放伏笔
    open_hooks = await _load_open_hooks(db, chapter)
    
    # P1: 加载 RAG 相关记忆
    relevant_memories = await _load_relevant_memories(db, chapter, request)
    
    # 节拍生成（若请求携带 confirmed beats，直接使用；否则调用 LLM 重新规划）
    from backend.services.workflows.planning import generate_beats, assign_pov_to_beats
    
    if request.beats and len(request.beats) > 0:
        beats = []
        for b in request.beats:
            beat_dict = b.model_dump()
            if not beat_dict.get("target_words") or beat_dict["target_words"] <= 0:
                beat_dict["target_words"] = beat_dict.get("word_count_target") or max(200, request.word_count // len(request.beats))
            beats.append(beat_dict)
    else:
        beats, _ = await generate_beats(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            word_count=request.word_count,
            open_hooks=open_hooks,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            previous_chapter_summary=previous_summary,
        )
    
    # POV 分配（confirmed beats 通常已带 pov_character，assign 仍可兜底补全）
    seen_char_ids_simple: set = set()
    pov_candidates = []
    for e in entities:
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
        model=request.model,
        previous_chapter_summary=previous_summary,
    )
    
    anchor_pov = beats[0].get("pov_character") if beats else None
    
    # P1: 构建物理状态锁定
    physical_state_lock = _build_physical_state_lock(beats)
    
    # P2: 保存 StoryBeat 到数据库
    await _save_story_beats(db, chapter, beats)
    
    # 执行双轨生成
    config = DualTrackConfig(
        enable_sketch_track=request.enable_sketch_track,
        enable_adversarial_alignment=request.enable_adversarial_alignment,
    )
    
    workflow = DualTrackWorkflow(
        api_key=request.api_key,
        base_url=request.base_url,
        reasoning_model=request.reasoning_model or request.model,
        creative_model=request.creative_model or request.model,
        config=config,
    )
    
    result = await workflow.execute(
        chapter=chapter,
        book=book,
        beats=beats,
        entities=entities,
        relationships=relationships,
        word_count=request.word_count,
        previous_summary=previous_summary,
        relevant_memories=relevant_memories,
        locations=locations,
        physical_state_lock=physical_state_lock,
        chapter_assets_schema=chapter.chapter_assets_schema or "",
        anchor_pov=anchor_pov,
    )
    
    return {
        "success": True,
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

async def _load_chapter(db: AsyncSession, chapter_id: str) -> Optional[Chapter]:
    """加载章节"""
    result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.story_beats))
        .where(Chapter.id == chapter_id)
    )
    return result.scalar_one_or_none()


async def _load_book(db: AsyncSession, book_id: str) -> Optional[Book]:
    """加载书籍"""
    result = await db.execute(select(Book).where(Book.id == book_id))
    return result.scalar_one_or_none()


async def _load_entities(db: AsyncSession, chapter_id: str) -> list:
    """加载章节实体"""
    result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    return result.scalars().all()


async def _load_relationships(db: AsyncSession, entities: list) -> list:
    """加载角色关系"""
    character_ids = [e.entity_id for e in entities]
    if not character_ids:
        return []
    
    result = await db.execute(
        select(CharacterRelationship)
        .options(
            selectinload(CharacterRelationship.source_character),
            selectinload(CharacterRelationship.target_character)
        )
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    return result.scalars().all()


async def _load_previous_summary(db: AsyncSession, chapter: Chapter) -> Optional[str]:
    """加载上一章摘要
    
    优先级：summary > draft_text > content_text > 章节信息提示
    """
    prev_chapter_result = await db.execute(
        select(Chapter)
        .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    
    if not prev_chapter:
        return None
    
    if prev_chapter.summary:
        return prev_chapter.summary
    elif prev_chapter.draft_text:
        return f"（上一章末尾原文）...{prev_chapter.draft_text[-1000:]}"
    elif prev_chapter.content_text:
        return f"（上一章末尾原文）...{prev_chapter.content_text[-1000:]}"
    else:
        prev_chapter_name = prev_chapter.chapter_name or f"第{prev_chapter.chapter_number}章"
        return f"（上一章【{prev_chapter_name}】内容未生成，标题：{prev_chapter.title or '未命名'}）"


async def _load_previous_world_snapshot(db: AsyncSession, chapter: Chapter) -> Optional[dict]:
    """加载上一章的世界状态快照

    用于跨章状态连续性约束。
    """
    prev_chapter_result = await db.execute(
        select(Chapter)
        .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()

    if not prev_chapter:
        return None

    return prev_chapter.world_snapshot if prev_chapter.world_snapshot else None


async def _load_open_hooks(db: AsyncSession, chapter: Chapter) -> List[Dict[str, str]]:
    """加载开放的伏笔/情节点"""
    hook_max_chapter_number = chapter.chapter_number - 1
    historical_chapter_exists = (
        select(Chapter.id)
        .where(
            Chapter.id == PlotLedger.chapter_id,
            Chapter.chapter_number <= hook_max_chapter_number,
        )
        .exists()
    )
    
    open_hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            or_(
                PlotLedger.created_at_chapter <= hook_max_chapter_number,
                and_(
                    PlotLedger.created_at_chapter.is_(None),
                    or_(PlotLedger.chapter_id.is_(None), historical_chapter_exists),
                ),
            ),
        )
    )
    open_hook_rows = open_hook_result.scalars().all()
    
    open_hooks = []
    for row in open_hook_rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        hook_id = str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip()
        open_hooks.append({
            "hook_id": hook_id,
            "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
            "content": content,
        })
    
    return open_hooks


async def _load_locations(db: AsyncSession, chapter_id: str) -> List[Any]:
    """加载章节地图位置"""
    result = await db.execute(
        select(ChapterMapLocation)
        .options(selectinload(ChapterMapLocation.location))
        .where(ChapterMapLocation.chapter_id == chapter_id)
    )
    return list(result.scalars().all())


async def _load_relevant_memories(
    db: AsyncSession,
    chapter: Chapter,
    request: "DualTrackGenerationRequest"
) -> List[Any]:
    """加载 RAG 相关记忆"""
    relevant_memories = []
    
    if not chapter.outline_text:
        return relevant_memories
    
    try:
        embedding = await get_embedding(chapter.outline_text, request.api_key, request.base_url)
        if embedding:
            memory_repo = MemoryRepository(db)
            relevant_memories = await memory_repo.search_similar(
                embedding,
                chapter.book_id,
                limit=request.rag_top_k,
                alpha=request.rag_alpha,
                beta=request.rag_beta,
                gamma=request.rag_gamma,
                lambda_decay=request.rag_lambda,
                exclude_chapter_id=chapter.id,
                max_chapter_number=chapter.chapter_number - 1,
            )
            logger.debug(f"[RAG Search] Found {len(relevant_memories)} relevant memories")
    except Exception as e:
        logger.error(f"[RAG Search] {e}")
    
    return relevant_memories


def _build_physical_state_lock(beats: List[dict]) -> Optional[str]:
    """构建物理状态锁定描述"""
    if beats and beats[0].get("entry_state"):
        return beats[0].get("entry_state")
    return None


async def _save_story_beats(
    db: AsyncSession,
    chapter: Chapter,
    beats: List[dict]
) -> List[StoryBeat]:
    """保存 StoryBeat 到数据库（先清除该章节的旧记录，再写入新记录，防止多次生成产生重复）"""
    from sqlalchemy import delete as sa_delete
    # 清除旧记录，避免多次生成后前端看到重复 beats
    await db.execute(sa_delete(StoryBeat).where(StoryBeat.chapter_id == chapter.id))
    await db.flush()
    story_beats = []
    for beat_index, beat in enumerate(beats, start=1):
        story_beat = StoryBeat(
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            beat_id=beat.get("beat_id"),
            beat_type="progression",
            position=beat.get("position", beat_index),
            location=beat.get("location"),
            pov_character=beat.get("pov_character"),
            pov_perception_state=beat.get("pov_perception_state", "正常"),
            anchor_pov=beat.get("anchor_pov"),
            original_actor=beat.get("original_actor"),
            action_summary=beat.get("action_summary"),
            worldbuilding_instruction=beat.get("worldbuilding_instruction"),
            entry_state=beat.get("entry_state"),
            exit_state=beat.get("exit_state"),
            red_lines=beat.get("red_lines", []),
            word_count_target=beat.get("word_count_target", beat.get("target_words", 0)),
            summary=beat.get("summary", ""),
            meta={"target_words": beat.get("target_words", 0)},
            status="planned",
        )
        db.add(story_beat)
        story_beats.append(story_beat)
    
    await db.flush()
    return story_beats
