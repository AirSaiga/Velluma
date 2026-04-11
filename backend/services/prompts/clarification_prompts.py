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
澄清提示词模块。

职责：提供意图与剧情澄清（Clarification）阶段的提示词构建功能，用于解析模糊的用户指令或大纲意图，确保后续生成任务准确无误。

子模块：
- 无
"""

import json
from typing import Optional

from backend.models import Chapter, Book


def build_clarification_agent_prompt(
    book: Book,
    ambiguous_text: str,
    chapter: Optional[Chapter] = None,
    entities: Optional[list] = None,
    global_taboos: Optional[str] = None,
    author_intent: Optional[str] = None,
) -> tuple[str, str]:
    """构建意图澄清阶段的提示词。

    用于分析模糊、矛盾或不完整的剧情指令（大纲或作者要求），并提供清晰、结构化的澄清结果。

    Args:
        book: 书籍实体，包含全局系统提示词、世界观设定等
        ambiguous_text: 需要澄清的模糊文本或用户指令
        chapter: 当前章节实体（可选），提供章节标题与大纲参考
        entities: 相关的角色实体列表（可选），包含角色快照状态
        global_taboos: 全局禁忌/核心母题（可选）
        author_intent: 作者的补充意图（可选）

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
        - system_prompt: 包含世界观设定、角色约束以及 JSON 输出格式要求
        - user_prompt: 包含实际待澄清文本和上下文参考

    提示词设计说明：
    - system_prompt: 定义输出为 JSON，包含提取的问题点、澄清建议和修正后的清晰文本。
    - user_prompt: 将全局禁忌和作者意图作为高优先级指令注入，并提供相关的背景参考。
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None

    # 构建角色上下文参考
    character_prompts = []
    if entities:
        seen_character_ids = set()
        for entity in entities:
            character = entity.character if hasattr(entity, "character") else entity
            if character and character.id not in seen_character_ids:
                seen_character_ids.add(character.id)
                char_desc = f"【{character.name}】"
                if character.static_prompt:
                    char_desc += f"\n静态设定：{character.static_prompt}"
                if character.dynamic_state:
                    char_desc += f"\n当前动态状态：{character.dynamic_state}"
                character_prompts.append(char_desc)

    system_prompt = f"""{global_sys_prompt}

你现在是一个剧情分析与澄清专家。你的任务是分析模糊、矛盾或不完整的剧情指令，结合现有世界观与角色设定，提供清晰、结构化的澄清建议，并仅输出 JSON。

{worldview_prompt if worldview_prompt else ''}

## 输出 JSON 结构（示例值仅供格式参考，必须替换为本章实际内容）
{{
  "is_ambiguous": true,
  "identified_issues": [
    "未说明角色A为何突然出现在此地",
    "指令中对反派动机的描述与世界观设定存在冲突"
  ],
  "clarification_suggestions": [
    "建议增加角色A收到紧急求救信号的铺垫",
    "建议将反派动机修改为为了保护其族人免受能量反噬"
  ],
  "refined_text": "此处输出结合澄清建议后，逻辑自洽、细节清晰的完整指令或大纲文本。"
}}

⚠️ **严禁照抄示例**：上方 JSON 中的所有字符串值均为示例，**必须全部替换为基于实际文本的分析内容**。

约束：
1. is_ambiguous 必须为布尔值，指示原文是否存在逻辑漏洞或模糊不清之处。
2. identified_issues 列表应具体指出问题所在，若无问题可为空列表。
3. clarification_suggestions 列表需给出可执行的补救或澄清建议。
4. refined_text 是必须提供的最终修正文本，确保逻辑连贯并符合所有设定约束。
5. 只输出 JSON，不要额外解释。
"""

    user_prompt_parts = []

    # 0. 绝对最高优先级指令 (Absolute Highest Priority)
    if global_taboos or author_intent:
        user_prompt_parts.append("## 0. 绝对最高优先级指令 (Absolute Highest Priority)")
        if global_taboos:
            user_prompt_parts.append(f"【全局禁忌/核心母题】\n{global_taboos}")
        if author_intent:
            user_prompt_parts.append(f"【作者创作意图】\n{author_intent}")
            user_prompt_parts.append("重要提示：若【作者创作意图】与【待澄清文本】的逻辑存在冲突，请优先满足【作者创作意图】，并在此基础上提供澄清与修正建议。")
        user_prompt_parts.append("")

    user_prompt_parts.append("请分析并澄清以下文本：")
    user_prompt_parts.append(f"【待澄清文本】\n{ambiguous_text}\n")

    # 附加当前章节参考
    if chapter:
        chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
        user_prompt_parts.append(f"【当前章节参考】{chapter_name}")
        if chapter.outline_text:
            user_prompt_parts.append(f"【章节大纲】\n{chapter.outline_text}\n")

    # 附加角色设定参考
    if character_prompts:
        user_prompt_parts.append(f"【相关角色设定】\n{chr(10).join(character_prompts)}\n")

    user_prompt = "\n".join(user_prompt_parts)
    return system_prompt, user_prompt
