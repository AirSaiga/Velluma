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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.core.dependencies import get_chapter_repository
from backend.repositories import ChapterRepository
from backend.models import Chapter, ChapterEntity, CharacterRelationship
from backend.schemas import OptimizeChapterRequest, OptimizeSelectionRequest
from backend.services.generation.chapter import refine_draft
from backend.services.llm import optimize_selection_with_llm

router = APIRouter(prefix="/api", tags=["chapter_optimization"])


@router.post("/optimize_chapter")
async def optimize_chapter(
    request: OptimizeChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：根据用户反馈优化章节内容。

    参数来源：
    - request: 包含 chapter_id, optimization_feedback（V4.1: 模型配置已从 model_config.json 读取）

    数据流：
    1. 获取章节、书籍、角色、关系上下文
    2. 调用 Refine Agent 进行重写
    3. 返回优化后的内容

    注意：此操作不会直接修改数据库，需要用户确认后保存
    """
    db = chapter_repo.get_session()
    chapter_id = request.chapter_id

    result = await db.execute(
        select(Chapter)
        .options(
            selectinload(Chapter.book),
            selectinload(Chapter.story_beats)
        )
        .where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    book = chapter.book

    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()
    
    character_ids = []
    seen_ids = set()
    for e in entities:
        if e.character and e.character.id not in seen_ids:
            seen_ids.add(e.character.id)
            character_ids.append(e.character.id)
            
    relationships = []
    if character_ids:
        relationships_result = await db.execute(
            select(CharacterRelationship)
            .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
            .where(
                CharacterRelationship.source_char_id.in_(character_ids),
                CharacterRelationship.target_char_id.in_(character_ids),
            )
        )
        relationships = relationships_result.scalars().all()

    current_draft = chapter.content_text or chapter.draft_text or ""
    if not current_draft:
        raise HTTPException(status_code=400, detail="当前章节没有内容可优化")
    
    refined_text = await refine_draft(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        current_draft=current_draft,
        revision_plan=request.optimization_feedback,
        word_count=request.word_count,
    )
    
    return {"optimized_content": refined_text}


@router.post("/optimize_selection")
async def optimize_selection(
    request: OptimizeSelectionRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """
    对用户选中的文本进行优化。
    """
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
        
    outline = chapter.outline_text or "（暂无大纲）"
    
    optimized_text = await optimize_selection_with_llm(
        selected_text=request.selected_text,
        context_before=request.context_before,
        context_after=request.context_after,
        outline=outline,
        user_instruction=request.user_instruction,
    )
    
    return {"optimized_text": optimized_text}
