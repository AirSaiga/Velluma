# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
章节生成服务模块 (Facade)。

职责：统一导出所有章节生成相关的服务函数，供上层 (API 路由) 消费。
内部实现分布在：
- llm/: LLM 调用封装
- prompts/: 提示词构建（按Agent类型拆分）
- orchestration/: 代理工作流

设计模式：Facade Pattern，隐藏底层复杂度，提供统一入口。
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from backend.models import Character, Chapter
from backend.services.workflows.refining import refine_draft
from backend.services.llm import call_llm, generate_stream_response

if TYPE_CHECKING:
    from backend.repositories.character_repository import CharacterRepository
from backend.services.prompts import (
    build_chapter_prompt,
    build_draft_agent_prompt,
    build_review_agent_prompt,
    build_refine_agent_prompt,
    parse_review_result,
)

logger = logging.getLogger(__name__)


async def update_character_dynamic_state(
    character: Character,
    chapter: Chapter,
    character_repository: "CharacterRepository",
    manual_current_state: Optional[str] = None,
) -> dict:
    """
    更新角色动态状态 (角色在特定章节中的心理/情感变化)。

    迁移说明 (2026-03-30)：
    - 已迁移到使用 character_repository 参数
    - 所有数据库操作通过 Repository 执行

    业务规则：
    1. 动态状态 = 角色当前的心理状态、情感、与其他角色的关系变化
    2. 每次更新记录到 history (最多保留10条)，支持追溯
    3. 仅分析涉及该角色的章节，未出场则不更新
    4. manual_current_state: 若提供，则以此作为"当前状态"进行更新，而非数据库中的值
    """

    old_dynamic_state = manual_current_state if manual_current_state is not None else (character.dynamic_state or "暂无动态状态")
    history_states = []
    if character.dynamic_state_history:
        for item in character.dynamic_state_history[-3:]:
            state = item.get("state", "")
            updated_at = item.get("updated_at", "")
            if state:
                history_states.append(f"- {updated_at}: {state}")
    history_str = "\n".join(history_states) if history_states else "暂无历史状态"

    system_prompt = "你是一个专业的小说写作助手，擅长分析角色心理和情感变化。"
    user_prompt = f"""角色动态状态更新提示词：

【角色信息】
角色名：{character.name}
角色设定：{character.static_prompt or "暂无设定"}

【当前动态状态】
{old_dynamic_state}

【历史动态状态】
{history_str}

【本章情节】
章节标题：{chapter.title or "未命名"}
章节大纲：{chapter.outline_text or "暂无大纲"}
章节正文：{chapter.content_text or "暂无正文"}

【任务】
请基于"当前动态状态"，结合"本章情节"中的新发展，更新角色的动态状态描述。

【核心要求】
1. **必须保留**关键身份信息（如年龄、家族、核心能力、职业等），不要丢失上下文。
2. **整合**本章中发生的重大事件、心理变化和人际关系进展。
3. 保持角色性格一致性。
4. 字数控制在 100-200 字之间，内容要充实但精炼。
5. 严禁罗列流水账，侧重于"状态"和"影响"。
6. 直接输出更新后的段落，不要包含"更新后："等前缀。
"""

    new_state = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.7,
        max_tokens=1000,
    )

    if new_state:
        llm_content = new_state
        if not llm_content:
            return {}

        new_dynamic_state = llm_content.strip()

        new_dynamic_state = re.sub(r"^[【\[].*?[】\]]\s*", "", new_dynamic_state.strip())
        new_dynamic_state = re.sub(r"^角色动态状态[：:]\s*", "", new_dynamic_state)
        new_dynamic_state = re.sub(r"^更新后的动态状态[：:]\s*", "", new_dynamic_state)
        new_dynamic_state = new_dynamic_state.strip()

        character.dynamic_state = new_dynamic_state
        history = character.dynamic_state_history or []
        history.append({"state": new_dynamic_state, "updated_at": datetime.now(timezone.utc).isoformat()})
        if len(history) > 10:
            history = history[-10:]
        character.dynamic_state_history = history

        await character_repository.commit_and_refresh(character)
        return {"old_dynamic_state": old_dynamic_state, "new_dynamic_state": new_dynamic_state}

    return {}


__all__ = [
    "build_chapter_prompt",
    "generate_stream_response",
    "build_draft_agent_prompt",
    "build_review_agent_prompt",
    "build_refine_agent_prompt",
    "parse_review_result",
    "call_llm",
    "update_character_dynamic_state",
    "refine_draft",
]
