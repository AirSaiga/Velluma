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
基础上下文组装模块 - V1/V2 版本上下文加载。

迁移说明 (2026-03-30)：
- 已迁移到使用 Repository 模式
- 所有函数现在接受 repositories 字典参数

使用方式：
    repos = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        ...
    }
    context = await load_chapter_context(chapter_id, repos)
"""

import logging
from typing import Any, Optional, Dict

from backend.models import Chapter
from backend.world_state_schemas import WorldTerminalState
from backend.services.context import (
    load_chapter,
    load_book,
    load_chapter_entities,
    load_character_relationships,
    load_previous_chapter_summary,
    load_open_hooks,
    load_relevant_memories,
    load_previous_world_snapshot,
)

logger = logging.getLogger(__name__)


async def load_chapter_context(
    chapter_id: Any,
    repositories: Dict[str, Any],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    rag_top_k: int = 3,
    rag_alpha: float = 0.6,
    rag_beta: float = 0.2,
    rag_gamma: float = 0.2,
    rag_lambda: float = 0.1,
) -> Optional[dict[str, Any]]:
    basic = await _load_basic_context(chapter_id, repositories)
    if not basic:
        return None

    chapter, book = basic["chapter"], basic["book"]

    entities = await load_chapter_entities(repositories, str(chapter_id))
    relationships = await load_character_relationships(repositories, entities)
    previous_summary = await load_previous_chapter_summary(repositories, chapter)
    open_hooks = await load_open_hooks(repositories, chapter)
    relevant_memories = await load_relevant_memories(
        repositories,
        chapter,
        chapter.outline_text or "",
        str(chapter.book_id),
        chapter.chapter_number,
        api_key or "",
        base_url,
        {"top_k": rag_top_k, "alpha": rag_alpha, "beta": rag_beta, "gamma": rag_gamma, "lambda": rag_lambda}
    )

    entity_spatial_ledger = {}
    for entity in entities:
        character = entity.character
        if character and character.name:
            entity_spatial_ledger[character.name] = {
                "is_in_vehicle": False,
                "vehicle_or_mech_name": "",
                "equipped_weapons": [],
                "movement_constraints": ""
            }

    previous_world_state = await _load_previous_world_terminal_state(chapter, repositories)
    if previous_world_state:
        logger.debug(f"[Context] Loaded previous world state: {previous_world_state.scene.location_summary}")
    else:
        logger.debug(f"[Context] No previous world state (chapter {chapter.chapter_number})")

    return {
        "chapter": chapter,
        "book": book,
        "entities": entities,
        "relationships": relationships,
        "previous_summary": previous_summary,
        "open_hooks": open_hooks,
        "relevant_memories": relevant_memories,
        "chapter_assets_schema": chapter.chapter_assets_schema or "",
        "entity_spatial_ledger": entity_spatial_ledger,
        "previous_world_state": previous_world_state,
    }


async def _load_basic_context(chapter_id: Any, repositories: Dict[str, Any]) -> Optional[dict[str, Any]]:
    chapter = await load_chapter(repositories, str(chapter_id))
    if not chapter:
        return None
    book = await load_book(repositories, str(chapter.book_id))
    return {"chapter": chapter, "book": book}


async def _load_entities(chapter_id: Any, repositories: Dict[str, Any]) -> list[Any]:
    return await load_chapter_entities(repositories, str(chapter_id))


async def _load_relationships(entities: list[Any], repositories: Dict[str, Any]) -> list[Any]:
    if not entities:
        return []
    return await load_character_relationships(repositories, entities)


async def _load_previous_summary(chapter: Chapter, repositories: Dict[str, Any]) -> Optional[str]:
    return await load_previous_chapter_summary(repositories, chapter)


async def _load_open_hooks(chapter: Chapter, repositories: Dict[str, Any]) -> list[dict[str, str]]:
    return await load_open_hooks(repositories, chapter)


async def _load_relevant_memories(
    chapter: Chapter,
    api_key: Optional[str],
    base_url: Optional[str],
    repositories: Dict[str, Any],
    rag_top_k: int,
    rag_alpha: float,
    rag_beta: float,
    rag_gamma: float,
    rag_lambda: float,
) -> list[Any]:
    return await load_relevant_memories(
        repositories,
        chapter,
        chapter.outline_text or "",
        str(chapter.book_id),
        chapter.chapter_number,
        api_key or "",
        base_url,
        {"top_k": rag_top_k, "alpha": rag_alpha, "beta": rag_beta, "gamma": rag_gamma, "lambda": rag_lambda}
    )


async def _load_previous_world_terminal_state(
    chapter: Chapter,
    repositories: Dict[str, Any]
) -> Optional[WorldTerminalState]:
    if chapter.chapter_number <= 1:
        logger.debug(f"[WorldState] Chapter {chapter.chapter_number} is first chapter, no previous state")
        return None

    try:
        world_snapshot = await load_previous_world_snapshot(repositories, chapter)

        if not world_snapshot:
            logger.debug(f"[WorldState] Chapter {chapter.chapter_number} has no world_snapshot")
            return None

        world_state = WorldTerminalState.from_chapter_snapshot(world_snapshot)
        if world_state:
            logger.info(
                f"[WorldState] Loaded state from chapter {chapter.chapter_number - 1}: "
                f"{len(world_state.characters)} characters, "
                f"location: {world_state.scene.location_summary[:30]}..."
            )
            return world_state
        else:
            logger.warning(f"[WorldState] Failed to parse world_snapshot")
            return None

    except Exception as e:
        logger.error(f"[WorldState] Error loading previous world state: {e}")
        return None
