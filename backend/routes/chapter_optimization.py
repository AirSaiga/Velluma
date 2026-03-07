from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.core.dependencies import get_chapter_repository
from backend.repositories import ChapterRepository
from backend.models import Chapter, ChapterEntity, CharacterRelationship
from backend.schemas import OptimizeChapterRequest, OptimizeSelectionRequest
from backend.services.chapter_generation import refine_draft
from backend.services.llm_client import optimize_selection_with_llm

router = APIRouter(prefix="/api", tags=["chapter_optimization"])


@router.post("/optimize_chapter")
async def optimize_chapter(
    request: OptimizeChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：根据用户反馈优化章节内容。

    参数来源：
    - request: 包含 chapter_id, optimization_feedback, api_key 等

    数据流：
    1. 获取章节、书籍、角色、关系上下文
    2. 调用 Refine Agent 进行重写
    3. 返回优化后的内容

    注意：此操作不会直接修改数据库，需要用户确认后保存
    """
    db = chapter_repo.db
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
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
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
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    
    return {"optimized_text": optimized_text}
