"""
上下文加载模块。

职责：提供章节上下文加载功能，包括书籍、角色、关系、伏笔和 RAG 记忆。

主要功能：
- load_chapter_context: 加载章节完整上下文
- _load_basic_context: 加载章节和书籍基本信息
- _load_entities_and_relationships: 加载角色和关系
- _load_open_hooks: 加载开放伏笔
- _load_relevant_memories: 加载 RAG 记忆
"""

import json
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, PlotLedger
from backend.repositories import MemoryRepository
from backend.services.llm_client import get_embedding


async def load_chapter_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    rag_top_k: int = 3,
    rag_alpha: float = 0.6,
    rag_beta: float = 0.2,
    rag_gamma: float = 0.2,
    rag_lambda: float = 0.1,
) -> Optional[dict[str, Any]]:
    """加载章节上下文，包括书籍、角色、关系、伏笔和 RAG 记忆。

    这是 Agentic 工作流的入口函数，负责组装生成章节所需的全部上下文信息。

    Args:
        chapter_id: 章节 UUID
        db: 数据库会话
        api_key: LLM API Key（用于 RAG 向量检索）
        base_url: LLM Base URL
        rag_top_k: RAG 检索返回的记忆条数
        rag_alpha: RAG 权重 - 向量相似度
        rag_beta: RAG 权重 - 时间衰减
        rag_gamma: RAG 权重 - 位置接近度
        rag_lambda: RAG 权重 - 章节相关性

    Returns:
        Optional[dict]: 包含以下键的字典：
        - chapter: 章节实体
        - book: 书籍实体
        - entities: 章节关联的角色实体列表
        - relationships: 角色关系列表
        - previous_summary: 上一章摘要
        - open_hooks: 开放伏笔列表
        - relevant_memories: RAG 检索到的相关记忆列表
        如果章节不存在则返回 None
    """
    basic = await _load_basic_context(chapter_id, db)
    if not basic:
        return None

    chapter, book = basic["chapter"], basic["book"]

    entities = await _load_entities(chapter_id, db)
    relationships = await _load_relationships(entities, db)
    previous_summary = await _load_previous_summary(chapter, db)
    open_hooks = await _load_open_hooks(chapter, db)
    relevant_memories = await _load_relevant_memories(
        chapter, api_key, base_url, db,
        rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda
    )

    return {
        "chapter": chapter,
        "book": book,
        "entities": entities,
        "relationships": relationships,
        "previous_summary": previous_summary,
        "open_hooks": open_hooks,
        "relevant_memories": relevant_memories,
    }


async def _load_basic_context(chapter_id: Any, db: AsyncSession) -> Optional[dict[str, Any]]:
    """加载章节和书籍基本信息。

    Args:
        chapter_id: 章节 UUID
        db: 数据库会话

    Returns:
        Optional[dict]: 包含 chapter 和 book 的字典
    """
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        return None

    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()

    return {"chapter": chapter, "book": book}


async def _load_entities(chapter_id: Any, db: AsyncSession) -> list[Any]:
    """加载章节关联的角色实体列表。

    Args:
        chapter_id: 章节 UUID
        db: 数据库会话

    Returns:
        list: 章节关联的角色实体列表
    """
    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    return list(entities_result.scalars().all())


async def _load_relationships(entities: list[Any], db: AsyncSession) -> list[Any]:
    """加载角色之间的关系列表。

    Args:
        entities: 章节关联的角色实体列表
        db: 数据库会话

    Returns:
        list: 角色关系列表
    """
    if not entities:
        return []

    character_ids = [e.entity_id for e in entities]
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(
            selectinload(CharacterRelationship.source_character),
            selectinload(CharacterRelationship.target_character),
        )
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    return list(relationships_result.scalars().all())


async def _load_previous_summary(chapter: Chapter, db: AsyncSession) -> Optional[str]:
    """加载上一章的摘要。

    Args:
        chapter: 当前章节实体
        db: 数据库会话

    Returns:
        Optional[str]: 上一章摘要，不存在则返回 None
    """
    if chapter.chapter_number <= 1:
        return None

    prev_chapter_result = await db.execute(
        select(Chapter).where(
            Chapter.book_id == chapter.book_id,
            Chapter.chapter_number == chapter.chapter_number - 1
        )
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    return prev_chapter.summary if prev_chapter else None


async def _load_open_hooks(chapter: Chapter, db: AsyncSession) -> list[dict[str, str]]:
    """加载当前章节之前的所有开放伏笔。

    Args:
        chapter: 当前章节实体
        db: 数据库会话

    Returns:
        list[dict]: 开放伏笔列表，每项包含 hook_id, ledger_key, content
    """
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

    open_hooks = []
    for row in open_hook_result.scalars().all():
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


async def _load_relevant_memories(
    chapter: Chapter,
    api_key: Optional[str],
    base_url: Optional[str],
    db: AsyncSession,
    rag_top_k: int,
    rag_alpha: float,
    rag_beta: float,
    rag_gamma: float,
    rag_lambda: float,
) -> list[Any]:
    """使用 RAG 检索与章节大纲相关的记忆。

    Args:
        chapter: 当前章节实体
        api_key: LLM API Key
        base_url: LLM Base URL
        db: 数据库会话
        rag_top_k: 检索返回的记忆条数
        rag_alpha: 向量相似度权重
        rag_beta: 时间衰减权重
        rag_gamma: 位置接近度权重
        rag_lambda: 章节相关性权重

    Returns:
        list: 相关记忆列表
    """
    if not chapter.outline_text or not api_key:
        return []

    try:
        embedding = await get_embedding(chapter.outline_text, api_key, base_url)
        if not embedding:
            return []

        memory_repo = MemoryRepository(db)
        return await memory_repo.search_similar(
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
        return []
