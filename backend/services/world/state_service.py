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
世界状态服务模块。

职责：提供世界状态快照提取和更新的相关服务。

主要功能：
- 从章节内容中提取世界状态快照
- 更新角色物理状态

使用场景：
- routes/chapter_generation.py: 章节生成后更新世界状态
"""

import json
import logging
from typing import List, Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Character, Chapter
from backend.services.llm import call_llm
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_WORKFLOW

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)


class CharacterInfo:
    """角色信息数据类"""

    def __init__(
        self,
        character_id: str,
        character_name: str,
        old_state: str,
        new_state: str,
    ):
        self.character_id = character_id
        self.character_name = character_name
        self.old_state = old_state
        self.new_state = new_state

    def to_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "old_state": self.old_state,
            "new_state": self.new_state,
        }


async def extract_world_state_snapshot(
    chapter_text: str,
    characters: List[Any],
    model: Optional[str] = None,
) -> Optional[dict]:
    """
    从章节内容中提取世界状态快照。

    Args:
        chapter_text: 章节文本内容
        characters: 角色列表
        model: 模型名称（可选，默认从 model_config.json 读取）

    Returns:
        世界状态快照字典或 None
    """
    if not characters or not chapter_text:
        return None

    character_names = [c.name for c in characters if hasattr(c, "name") and c.name]
    characters_text = ", ".join(character_names) if character_names else "无"

    system_prompt = """你是一个专业的叙事分析助手。你的任务是从小说章节文本中提取"世界终端状态"（World Terminal State）。

世界终端状态是指：章节结束时，世界的主要状态快照，包括：
1. 角色位置：各角色当前所在的位置
2. 角色状态：各角色的情绪/状态
3. 关键物品：重要物品的位置或状态变化
4. 时间线：章节结束时的时间点
5. 剧情标记：重要的剧情进度标记

请以JSON格式返回，包含以下字段：
- character_locations: 角色位置 {"角色名": "位置"}
- character_states: 角色状态 {"角色名": "状态描述"}
- time_info: 时间线信息（字符串）
- plot_flags: 剧情标记列表 ["标记1", "标记2", ...]
- summary: 一句话总结本章结局

请确保分析准确，提取的信息应该与文本内容高度一致。"""

    user_prompt = f"""请分析以下小说章节，提取世界终端状态：

角色列表：{characters_text}

章节文本：
{chapter_text[:4000]}

请提取本章结束时的世界状态：
"""

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model or "google/gemini-2.0-flash-001",
            response_format={"type": "json_object"},
        )

        if response:
            return json.loads(response)
        return None
    except Exception as e:
        svc_logger.error("Failed to extract world state", error=str(e))
        return None


async def update_character_physical_state(
    character_repository: "CharacterRepository",
    chapter_id: str,
    character_id: str,
    new_location: str,
) -> bool:
    """
    更新角色的物理状态（位置）。

    迁移说明 (2026-03-30)：
    - 已迁移到使用 character_repository 参数

    Args:
        character_repository: CharacterRepository 实例
        chapter_id: 章节 ID
        character_id: 角色 ID
        new_location: 新位置

    Returns:
        是否更新成功
    """
    try:
        character = await character_repository.get_by_id(character_id)

        if character:
            current_snapshot = json.loads(character.world_snapshot or "{}")
            current_snapshot["current_location"] = new_location
            character.world_snapshot = json.dumps(current_snapshot)
            await character_repository.commit()
            return True
        return False
    except Exception as e:
        svc_logger.error("Failed to update character physical state", error=str(e))
        return False
