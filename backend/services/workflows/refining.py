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
精修阶段工作流 - 基于审阅意见重写章节。

职责：
- 根据审阅报告中的 revision_plan 重写章节
- 修复审阅中发现的问题
- 保持章节整体结构和风格一致

业务场景：
- 章节生成的精修阶段（可选）
- 审阅发现质量问题后的修复
- 迭代优化的最后一轮

主要功能：
- 精准修改（基于 revision_plan）
- 保持风格一致性
- 字数控制

依赖项：
- backend.services.prompts: Refine Prompt 模板
- backend.services.llm: LLM 调用接口

使用方式：
    refined_text = await refine_draft(chapter, book, current_draft, revision_plan, ...)
"""

from typing import Any, Optional

from backend.services.prompts import build_refine_agent_prompt
from backend.services.llm import call_llm, call_llm_with_usage
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter, Book, Character, CharacterRelationship
from backend.services.utils.prompt_logger import PromptLogger


async def refine_draft(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    current_draft: str,
    revision_plan: str,
    word_count: int,
    recorder: Optional[Any] = None,
) -> str:
    """根据审阅意见精修章节初稿。

    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        current_draft: 当前草稿文本
        revision_plan: 审阅意见/修改计划
        word_count: 目标字数
        recorder: 可选的 RunRecorder 实例（Phase 0 观测层）

    Returns:
        str: 精修后的正文
    """
    system_prompt, user_prompt = build_refine_agent_prompt(
        chapter, book, entities, relationships, current_draft, revision_plan, word_count
    )

    # T1 观测层 + T2 creative 槽
    if recorder is not None:
        async with recorder.record_call(stage="refining.chapter", model_slot="creative") as ctx:
            llm_result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,
                max_tokens=10000,
                model_type="creative",
            )
            ctx.set_result(llm_result)
        refined_text = llm_result.content
    else:
        refined_text = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=10000,
            model_type="creative",
        )

    return clean_llm_output(refined_text)


