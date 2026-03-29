import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chapter
from backend.world_state_schemas import WorldTerminalState
from backend.services.context_loader import (
    load_chapter as _load_chapter,
    load_book as _load_book,
    load_chapter_entities as _load_chapter_entities,
    load_character_relationships as _load_char_relationships,
    load_previous_chapter_summary as _load_prev_summary,
    load_open_hooks as _load_open_hooks,
    load_relevant_memories as _load_relevant_memories,
    load_previous_world_snapshot as _load_prev_world_snapshot_context_loader,
)

logger = logging.getLogger(__name__)


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

    previous_world_state = await _load_previous_world_terminal_state(chapter, db)
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


async def _load_basic_context(chapter_id: Any, db: AsyncSession) -> Optional[dict[str, Any]]:
    chapter = await _load_chapter(db, str(chapter_id))
    if not chapter:
        return None
    book = await _load_book(db, str(chapter.book_id))
    return {"chapter": chapter, "book": book}


async def _load_entities(chapter_id: Any, db: AsyncSession) -> list[Any]:
    return await _load_chapter_entities(db, str(chapter_id))


async def _load_relationships(entities: list[Any], db: AsyncSession) -> list[Any]:
    if not entities:
        return []
    return await _load_char_relationships(db, entities)


async def _load_previous_summary(chapter: Chapter, db: AsyncSession) -> Optional[str]:
    return await _load_prev_summary(db, chapter)


async def _load_open_hooks(chapter: Chapter, db: AsyncSession) -> list[dict[str, str]]:
    return await _load_open_hooks(db, chapter)


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
    return await _load_relevant_memories(
        db=db,
        book_id=str(chapter.book_id),
        query_text=chapter.outline_text or "",
        api_key=api_key,
        base_url=base_url,
        top_k=rag_top_k,
        alpha=rag_alpha,
        beta=rag_beta,
        gamma=rag_gamma,
        lambda_decay=rag_lambda,
        exclude_chapter_id=str(chapter.id),
        max_chapter_number=chapter.chapter_number - 1,
    )


async def _load_previous_world_terminal_state(
    chapter: Chapter,
    db: AsyncSession
) -> Optional[WorldTerminalState]:
    if chapter.chapter_number <= 1:
        logger.debug(f"[WorldState] Chapter {chapter.chapter_number} is first chapter, no previous state")
        return None

    try:
        world_snapshot = await _load_prev_world_snapshot_context_loader(db, chapter)

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
