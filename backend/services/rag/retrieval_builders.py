import logging
from typing import Any, Dict, List, Set

from backend.models import (
    Book,
    Character,
    CharacterRelationship,
    MemoryChunk,
    StoryBeat,
)
from backend.services.rag.retrieval_types import (
    ContentPriority,
    ContentType,
    MemoryType,
    RetrievedItem,
    RetrievalMethod,
)


logger = logging.getLogger(__name__)


def build_book_setting(book: Book) -> str:
    parts = []

    if book.global_sys_prompt:
        parts.append(f"风格指南：{book.global_sys_prompt}")

    if book.core_motifs_taboos:
        parts.append(f"主题禁忌：{book.core_motifs_taboos}")

    if book.worldview_settings:
        world_info = book.worldview_settings
        if isinstance(world_info, dict):
            for key, value in world_info.items():
                parts.append(f"{key}：{value}")

    return "\n".join(parts)


def build_character_item(character: Character) -> RetrievedItem:
    content_parts = []

    if character.name:
        content_parts.append(f"【{character.name}】")

    if character.static_prompt:
        content_parts.append(character.static_prompt[:300])

    if character.dynamic_state:
        content_parts.append(f"当前状态：{character.dynamic_state[:200]}")

    return RetrievedItem(
        memory_type=MemoryType.CHARACTER_STATE,
        source_id=str(character.id),
        content="\n".join(content_parts),
        character_names=[character.name] if character.name else [],
        priority=ContentPriority.HIGH,
        content_type=ContentType.STRUCTURED,
        original_length=len("\n".join(content_parts)),
        retrieval_method=RetrievalMethod.EXACT,
        retrieval_reason="出场角色设定",
    )


def build_relationship_item(rel: CharacterRelationship) -> RetrievedItem:
    source_name = rel.source_character.name if rel.source_character else ""
    target_name = rel.target_character.name if rel.target_character else ""

    content = f"【{source_name} ↔ {target_name}】"
    if rel.relation_type:
        content += f"\n关系：{rel.relation_type}"
    if rel.affinity_score is not None:
        content += f"\n亲密度：{rel.affinity_score}"
    if rel.interaction_prompt:
        content += f"\n互动约束：{rel.interaction_prompt[:100]}"

    return RetrievedItem(
        memory_type=MemoryType.RELATIONSHIP_STATE,
        source_id=str(rel.id),
        content=content,
        character_names=[source_name, target_name],
        priority=ContentPriority.HIGH,
        content_type=ContentType.STRUCTURED,
        original_length=len(content),
        retrieval_method=RetrievalMethod.EXACT,
        retrieval_reason="角色关系设定",
    )


def build_world_snapshot_item(
    world_state: Any,
    chapter_number: int,
) -> RetrievedItem:
    content_parts = ["=== 前一章世界状态 ==="]

    if hasattr(world_state, "scene") and world_state.scene:
        scene = world_state.scene
        if hasattr(scene, "location_summary"):
            content_parts.append(f"场景：{scene.location_summary}")

    if hasattr(world_state, "characters") and world_state.characters:
        content_parts.append("角色状态：")
        for char_state in world_state.characters[:5]:
            if hasattr(char_state, "name"):
                state_str = f"  - {char_state.name}"
                if hasattr(char_state, "location"):
                    state_str += f" @ {char_state.location}"
                content_parts.append(state_str)

    return RetrievedItem(
        memory_type=MemoryType.WORLD_SNAPSHOT,
        source_id=f"world-{chapter_number - 1}",
        content="\n".join(content_parts),
        priority=ContentPriority.HIGH,
        content_type=ContentType.STRUCTURED,
        original_length=len("\n".join(content_parts)),
        retrieval_method=RetrievalMethod.EXACT,
        retrieval_reason="世界状态连续性",
    )


def deduplicate_items(items: List[RetrievedItem]) -> List[RetrievedItem]:
    seen_content: Set[str] = set()
    unique_items: List[RetrievedItem] = []

    for item in items:
        content_key = item.content.strip().lower()[:100]

        if content_key not in seen_content:
            seen_content.add(content_key)
            unique_items.append(item)

    return unique_items


def sort_items(items: List[RetrievedItem]) -> List[RetrievedItem]:
    priority_order = {
        "critical": 0,
        "high": 1,
        "normal": 2,
        "low": 3,
    }

    return sorted(
        items,
        key=lambda x: (
            priority_order.get(x.priority.value, 2),
            -x.score.total_score,
            -(x.chapter_number or 0),
        )
    )


def get_chapter_number_from_chunk(chunk: MemoryChunk) -> int:
    return 0


def get_beat_chapter_number(beat: StoryBeat) -> int:
    if beat.chapter:
        return beat.chapter.chapter_number
    return 0
