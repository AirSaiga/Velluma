import re
from typing import Any, List

from backend.services.state_machine.character_state_types import (
    CharacterStaticPortrait,
    CharacterDynamicState,
    CharacterCurrentState,
)
from backend.services.state_machine.character_state_machine import CharacterStateMachine


def create_character_state_machine_from_entity(
    character_entity: Any,
) -> CharacterStateMachine:
    static_prompt = getattr(character_entity, "static_prompt", "") or ""
    static_portrait = _parse_static_prompt(
        getattr(character_entity, "name", "未知角色"),
        static_prompt,
        getattr(character_entity, "aliases", []) or [],
    )

    dynamic_state_str = getattr(character_entity, "dynamic_state", "") or ""
    dynamic_state = _parse_dynamic_state(dynamic_state_str)

    current_state_str = getattr(character_entity, "current_state", "") or ""
    current_state = _parse_current_state(current_state_str)

    return CharacterStateMachine(static_portrait, dynamic_state, current_state)


def _parse_static_prompt(
    name: str,
    prompt: str,
    aliases: List[str],
) -> CharacterStaticPortrait:
    return CharacterStaticPortrait(
        name=name,
        aliases=aliases,
        appearance=_extract_section(prompt, "外貌"),
        personality=_extract_section(prompt, "性格"),
        background=_extract_section(prompt, "背景"),
        core_traits=_extract_list_section(prompt, "核心特质"),
    )


def _extract_section(text: str, section_name: str) -> str:
    pattern = rf"【{section_name}】(.+?)(?=【|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_list_section(text: str, section_name: str) -> List[str]:
    content = _extract_section(text, section_name)
    if not content:
        return []
    return [item.strip() for item in content.split("、") if item.strip()]


def _parse_dynamic_state(state_str: str) -> CharacterDynamicState:
    if not state_str:
        return CharacterDynamicState()
    return CharacterDynamicState()


def _parse_current_state(state_str: str) -> CharacterCurrentState:
    if not state_str:
        return CharacterCurrentState()
    return CharacterCurrentState()
