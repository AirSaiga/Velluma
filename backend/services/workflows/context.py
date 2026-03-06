import json

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, PlotLedger
from backend.repositories import MemoryRepository
from backend.services.llm_client import get_embedding


async def load_chapter_context(chapter_id, db: AsyncSession, api_key: str = None, base_url: str = None, rag_top_k: int = 3, rag_alpha: float = 0.6, rag_beta: float = 0.2, rag_gamma: float = 0.2, rag_lambda: float = 0.1):
    """
    加载章节上下文，包括书籍、角色、关系、伏笔和RAG记忆。
    
    返回:
        dict: 包含 chapter, book, entities, relationships, previous_summary, open_hooks, relevant_memories
    """
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        return None
    
    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()
    
    entities_result = await db.execute(
        select(ChapterEntity).options(selectinload(ChapterEntity.character)).where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()
    character_ids = [e.entity_id for e in entities]
    
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    relationships = relationships_result.scalars().all()
    
    prev_chapter_result = await db.execute(
        select(Chapter).where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    previous_summary = prev_chapter.summary if prev_chapter else None
    
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
    
    relevant_memories = []
    if chapter.outline_text and api_key:
        try:
            embedding = await get_embedding(chapter.outline_text, api_key, base_url)
            if embedding:
                memory_repo = MemoryRepository(db)
                relevant_memories = await memory_repo.search_similar(
                    embedding,
                    chapter.book_id,
                    limit=rag_top_k,
                    alpha=rag_alpha,
                    beta=rag_beta,
                    gamma=rag_gamma,
                    lambda_decay=rag_lambda,
                    exclude_chapter_id=chapter.id,
                    max_chapter_number=chapter.chapter_number - 1,
                )
        except Exception as e:
            print(f"[RAG Error] {e}")
    
    return {
        "chapter": chapter,
        "book": book,
        "entities": entities,
        "relationships": relationships,
        "previous_summary": previous_summary,
        "open_hooks": open_hooks,
        "relevant_memories": relevant_memories,
    }
