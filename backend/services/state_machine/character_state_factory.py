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
角色状态机工厂 - 从实体创建状态机实例。

职责：
- 从数据库角色实体创建状态机
- 解析静态设定和动态状态
- 提供便捷的工厂方法

业务场景：
- 章节生成时加载角色状态机
- 从实体创建完整的状态机实例

主要功能：
- 实体到状态机转换
- 静态设定解析
- 动态状态解析

依赖项：
- backend.services.state_machine.character_state_machine: 状态机
- backend.services.state_machine.character_state_types: 类型定义

使用方式：
    machine = create_character_state_machine_from_entity(character_entity)
"""

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
