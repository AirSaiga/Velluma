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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.core.dependencies import get_db
from backend.models import Chapter, Book, ChapterEntity, CharacterRelationship, ChapterMapLocation
from backend.schemas import GenerateChapterAgenticRequest
from backend.services.workflows.dual_track import (
    DualTrackWorkflow,
    DualTrackConfig,
    DualTrackResult,
)
from backend.services.workflows.sketch_generator import SketchGeneratorConfig
from backend.services.workflows.adversarial_aligner import AdversarialAlignerConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-dual-track"])


class DualTrackGenerationRequest(GenerateChapterAgenticRequest):
    """双轨生成请求（扩展原有请求）"""
    
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
        # 加载上下文
        yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '加载章节上下文...'}, ensure_ascii=False)}\n\n"
        
        chapter = await _load_chapter(db, chapter_id)
        if not chapter:
            yield f"data: {json.dumps({'error': '章节不存在'}, ensure_ascii=False)}\n\n"
            return
        
        book = await _load_book(db, chapter.book_id)
        entities = await _load_entities(db, chapter_id)
        relationships = await _load_relationships(db, entities)
        
        yield f"data: {json.dumps({'event': 'CONTEXT_LOADED', 'message': f'加载 {len(entities)} 个角色, {len(relationships)} 组关系'}, ensure_ascii=False)}\n\n"
        
        # 节拍生成（复用原有逻辑）
        yield f"data: {json.dumps({'event': 'PLANNING', 'message': '生成故事节拍...'}, ensure_ascii=False)}\n\n"
        
        from backend.services.workflows.planning import generate_beats, assign_pov_to_beats
        
        beats, story_beats = await generate_beats(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            word_count=request.word_count,
            open_hooks=[],  # 简化示例
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        )
        
        yield f"data: {json.dumps({'event': 'PLANNING_DONE', 'message': f'生成 {len(beats)} 个节拍'}, ensure_ascii=False)}\n\n"
        
        # POV 分配
        pov_candidates = [
            {"name": e.character.name, "role": "Main" if e.character.importance_level >= 8 else "Supporting", "description": e.character.static_prompt or ""}
            for e in entities if e.character
        ]
        
        beats, _ = await assign_pov_to_beats(
            beats=beats,
            characters=pov_candidates,
            story_premise=book.title if book else "",
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        )
        
        anchor_pov = beats[0].get("pov_character") if beats else None
        
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
        
        # 创建双轨工作流
        workflow = DualTrackWorkflow(
            api_key=request.api_key,
            base_url=request.base_url,
            reasoning_model=request.reasoning_model or request.model,
            creative_model=request.creative_model or request.model,
            config=config,
        )
        
        yield f"data: {json.dumps({'event': 'DUAL_TRACK_START', 'message': '启动双轨并行生成...'}, ensure_ascii=False)}\n\n"
        
        # 执行双轨生成
        result: DualTrackResult = await workflow.execute(
            chapter=chapter,
            book=book,
            beats=beats,
            entities=entities,
            relationships=relationships,
            word_count=request.word_count,
            anchor_pov=anchor_pov,
        )
        
        # 发送 Track A 完成事件
        yield f"data: {json.dumps({'event': 'TRACK_A_DONE', 'message': f'节拍扩写完成，{len(result.beat_drafts)} 个片段'}, ensure_ascii=False)}\n\n"
        
        # 发送 Track B 完成事件（如果有）
        if result.sketch_result:
            yield f"data: {json.dumps({'event': 'TRACK_B_DONE', 'message': f'速写生成完成，{result.sketch_result.word_count} 字'}, ensure_ascii=False)}\n\n"
        
        # 发送统稿完成事件
        yield f"data: {json.dumps({'event': 'STITCHING_DONE', 'message': f'统稿完成，{len(result.stitched_draft)} 字'}, ensure_ascii=False)}\n\n"
        
        # 发送对抗校对结果
        if result.adjustment_plan:
            score = result.adjustment_plan.alignment_score
            needs_fix = result.adjustment_plan.needs_adjustment
            yield f"data: {json.dumps({'event': 'ALIGNMENT_DONE', 'message': f'对齐度得分: {score:.1f}', 'score': score, 'needs_fix': needs_fix}, ensure_ascii=False)}\n\n"
        
        # 发送最终结果
        needs_adjustment = result.adjustment_plan.needs_adjustment if result.adjustment_plan else False
        yield f"data: {json.dumps({
            'event': 'COMPLETE',
            'text': result.final_text,
            'stats': result.stats,
            'alignment_score': result.adjustment_plan.alignment_score if result.adjustment_plan else None,
            'passed': not needs_adjustment,
            'iterations': 1,
            'revision_count': 1 if needs_adjustment else 0,
        }, ensure_ascii=False)}\n\n"
    
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
    
    book = await _load_book(db, chapter.book_id)
    entities = await _load_entities(db, chapter_id)
    relationships = await _load_relationships(db, entities)
    
    # 节拍生成
    from backend.services.workflows.planning import generate_beats, assign_pov_to_beats
    
    beats, _ = await generate_beats(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=request.word_count,
        open_hooks=[],
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    
    # POV 分配
    pov_candidates = [
        {"name": e.character.name, "role": "Main" if e.character.importance_level >= 8 else "Supporting", "description": e.character.static_prompt or ""}
        for e in entities if e.character
    ]
    
    beats, _ = await assign_pov_to_beats(
        beats=beats,
        characters=pov_candidates,
        story_premise=book.title if book else "",
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    
    anchor_pov = beats[0].get("pov_character") if beats else None
    
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
