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
检索阶段模块 - 各检索阶段的异步函数实现。

职责：
- 实现不同检索阶段的具体逻辑
- 管理检索流程的各个阶段
- 提供阶段结果的后处理

业务场景：
- 检索协调器的各阶段执行
- 分层检索策略的实现
- 检索结果的后处理

主要功能：
- 基础检索阶段
- 增强检索阶段
- 结果后处理

依赖项：
- backend.models: 数据模型
- backend.repositories: 仓储层
- backend.services.rag.enhanced_scoring: 评分器

使用方式：
    results = await phase_enhanced_retrieval(context, db, ...)
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    Book,
    Chapter,
    ChapterEntity,
    ChapterMapLocation,
    CharacterRelationship,
    MemoryChunk,
    StoryBeat,
)
from backend.repositories import MemoryRepository
from backend.services.rag.enhanced_scoring import EnhancedRetrievalScorer
from backend.services.rag.retrieval_builders import (
    build_book_setting,
    build_character_item,
    build_relationship_item,
    build_world_snapshot_item,
    get_beat_chapter_number,
    get_chapter_number_from_chunk,
)
from backend.services.rag.retrieval_types import (
    ContentPriority,
    ContentType,
    MemoryType,
    RetrievedItem,
    RetrievalMethod,
    RetrievalResult,
    RetrievalStrategyConfig,
)


logger = logging.getLogger(__name__)


async def retrieve_mandatory(
    chapter: Chapter,
    book: Book,
    previous_summary: Optional[str],
    result: RetrievalResult,
    scorer: EnhancedRetrievalScorer,
    scoring_context: Dict[str, Any],
) -> None:
    if previous_summary:
        item = RetrievedItem(
            memory_type=MemoryType.PREVIOUS_SUMMARY,
            source_id=f"chapter-{chapter.chapter_number - 1}",
            content=previous_summary,
            chapter_number=chapter.chapter_number - 1,
            priority=ContentPriority.CRITICAL,
            content_type=ContentType.SUMMARY,
            original_length=len(previous_summary),
            retrieval_method=RetrievalMethod.MANDATORY,
            retrieval_reason="跨章连贯性锚点",
        )
        item.score = scorer.compute_score(item, scoring_context)
        result.add_item(item)

    book_setting = build_book_setting(book)
    if book_setting:
        item = RetrievedItem(
            memory_type=MemoryType.BOOK_SETTING,
            source_id=f"book-{book.id}",
            content=book_setting,
            priority=ContentPriority.CRITICAL,
            content_type=ContentType.STRUCTURED,
            original_length=len(book_setting),
            retrieval_method=RetrievalMethod.MANDATORY,
            retrieval_reason="核心设定遵循",
        )
        item.score.total_score = 1.0
        result.add_item(item)


async def retrieve_exact(
    chapter: Chapter,
    entities: List[ChapterEntity],
    relationships: List[CharacterRelationship],
    open_hooks: List[Dict[str, Any]],
    previous_world_state: Optional[Any],
    result: RetrievalResult,
    scorer: EnhancedRetrievalScorer,
    scoring_context: Dict[str, Any],
    max_items_per_type: int = 5,
) -> None:
    for entity in entities:
        if entity.character:
            item = build_character_item(entity.character)
            item.score = scorer.compute_score(item, scoring_context)
            result.add_item(item)

    for rel in relationships:
        item = build_relationship_item(rel)
        item.score = scorer.compute_score(item, scoring_context)
        result.add_item(item)

    sorted_hooks = sorted(
        open_hooks,
        key=lambda h: h.get("priority", "sub_plot"),
        reverse=True
    )

    for hook in sorted_hooks[:max_items_per_type]:
        item = RetrievedItem(
            memory_type=MemoryType.OPEN_HOOK,
            source_id=hook.get("hook_id", ""),
            content=hook.get("content", ""),
            chapter_number=hook.get("chapter_number", 0),
            priority=ContentPriority.HIGH,
            content_type=ContentType.FULL_TEXT,
            original_length=len(hook.get("content", "")),
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="未闭合伏笔",
        )
        item.score = scorer.compute_score(item, scoring_context)
        result.add_item(item)

    if previous_world_state:
        item = build_world_snapshot_item(
            previous_world_state, chapter.chapter_number
        )
        item.score = scorer.compute_score(item, scoring_context)
        result.add_item(item)


async def retrieve_vector(
    chapter: Chapter,
    book: Book,
    result: RetrievalResult,
    scorer: EnhancedRetrievalScorer,
    scoring_context: Dict[str, Any],
    strategy_config: RetrievalStrategyConfig,
    db: AsyncSession,
    get_embedding_func: Optional[Callable] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> None:
    if not chapter.outline_text:
        return

    try:
        if get_embedding_func:
            embedding = await get_embedding_func(
                chapter.outline_text, api_key, base_url
            )
        else:
            from backend.services.llm import get_embedding
            embedding = await get_embedding(
                chapter.outline_text, api_key, base_url
            )

        if not embedding:
            return

        memory_repo = MemoryRepository(db)

        chunks = await memory_repo.search_similar(
            embedding,
            book.id,
            limit=strategy_config.top_k * 2,
            alpha=strategy_config.semantic_weight,
            beta=strategy_config.time_decay_weight,
            gamma=strategy_config.foreshadowing_weight,
            lambda_decay=strategy_config.decay_factor,
            exclude_chapter_id=chapter.id,
            max_chapter_number=chapter.chapter_number - 1,
        )

        for chunk in chunks:
            item = RetrievedItem(
                memory_type=MemoryType.MEMORY_CHUNK,
                source_id=str(chunk.id),
                content=chunk.chunk_text or "",
                chapter_number=get_chapter_number_from_chunk(chunk),
                priority=ContentPriority.NORMAL,
                content_type=ContentType.SUMMARY,
                original_length=len(chunk.chunk_text or ""),
                retrieval_method=RetrievalMethod.VECTOR,
                retrieval_reason="语义相关记忆",
                created_at=chunk.created_at,
            )
            item.score = scorer.compute_score(item, scoring_context)
            result.add_item(item)

    except Exception as e:
        logger.error(f"[RetrievalOrchestrator] 向量检索失败: {e}")


async def retrieve_hybrid(
    chapter: Chapter,
    book: Book,
    entities: List[ChapterEntity],
    result: RetrievalResult,
    scorer: EnhancedRetrievalScorer,
    scoring_context: Dict[str, Any],
    db: AsyncSession,
) -> None:
    await retrieve_relevant_beats(chapter, book, entities, result, scorer, scoring_context, db)
    await retrieve_locations(chapter, result, scorer, scoring_context, db)


async def retrieve_relevant_beats(
    chapter: Chapter,
    book: Book,
    entities: List[ChapterEntity],
    result: RetrievalResult,
    scorer: EnhancedRetrievalScorer,
    scoring_context: Dict[str, Any],
    db: AsyncSession,
) -> None:
    try:
        character_names = set()
        for entity in entities:
            if entity.character and entity.character.name:
                character_names.add(entity.character.name)

        stmt = (
            select(StoryBeat)
            .join(Chapter, StoryBeat.chapter_id == Chapter.id)
            .where(
                Chapter.book_id == book.id,
                Chapter.chapter_number < chapter.chapter_number,
                Chapter.chapter_number >= chapter.chapter_number - 5,
            )
            .order_by(desc(Chapter.chapter_number))
            .limit(30)
        )

        beats_result = await db.execute(stmt)
        beats = beats_result.scalars().all()

        for beat in beats:
            beat_summary = beat.summary or ""

            involves_current_chars = any(
                name.lower() in beat_summary.lower()
                for name in character_names
            )

            pov_in_current = beat.pov_character in character_names if beat.pov_character else False

            if involves_current_chars or pov_in_current:
                item = RetrievedItem(
                    memory_type=MemoryType.STORY_BEAT,
                    source_id=str(beat.id),
                    content=beat_summary[:200],
                    chapter_number=get_beat_chapter_number(beat),
                    character_names=[beat.pov_character] if beat.pov_character else [],
                    priority=ContentPriority.NORMAL,
                    content_type=ContentType.SUMMARY,
                    original_length=len(beat_summary),
                    retrieval_method=RetrievalMethod.HYBRID,
                    retrieval_reason="涉及当前角色的历史节拍",
                )
                item.score = scorer.compute_score(item, scoring_context)
                result.add_item(item)

    except Exception as e:
        logger.error(f"[RetrievalOrchestrator] 节拍检索失败: {e}")


async def retrieve_locations(
    chapter: Chapter,
    result: RetrievalResult,
    scorer: EnhancedRetrievalScorer,
    scoring_context: Dict[str, Any],
    db: AsyncSession,
) -> None:
    try:
        stmt = (
            select(ChapterMapLocation)
            .options(selectinload(ChapterMapLocation.location))
            .where(ChapterMapLocation.chapter_id == chapter.id)
        )

        locations_result = await db.execute(stmt)
        locations = locations_result.scalars().all()

        for loc in locations:
            if loc.location:
                item = RetrievedItem(
                    memory_type=MemoryType.MAP_LOCATION,
                    source_id=str(loc.id),
                    content=loc.location.description or loc.location.name,
                    location_names=[loc.location.name],
                    priority=ContentPriority.LOW,
                    content_type=ContentType.STRUCTURED,
                    original_length=len(loc.location.description or ""),
                    retrieval_method=RetrievalMethod.HYBRID,
                    retrieval_reason="章节场景地点",
                )
                item.score = scorer.compute_score(item, scoring_context)
                result.add_item(item)

    except Exception as e:
        logger.error(f"[RetrievalOrchestrator] 地点检索失败: {e}")
