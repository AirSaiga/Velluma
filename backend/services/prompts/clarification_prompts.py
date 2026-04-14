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
from backend.world_state_schemas import WorldTerminalState
from backend.services.prompts.world_state_prompts import (
    format_snapshot_for_planner,
)


def build_clarification_agent_prompt(
    book: Book,
    ambiguous_text: str,
    chapter: Optional[Chapter] = None,
    entities: Optional[list] = None,
    relationships: Optional[list] = None,
    open_hooks: Optional[list] = None,
    previous_chapter_summary: Optional[str] = None,
    locations: Optional[list] = None,
    global_taboos: Optional[str] = None,
    author_intent: Optional[str] = None,
    user_instruction: Optional[str] = None,
    previous_issues: Optional[list] = None,
    previous_chapter_snapshot: Optional[dict] = None,
    previous_world_terminal_state: Optional[WorldTerminalState] = None,
) -> tuple[str, str]:
    """构建意图澄清阶段的提示词。

    用于分析模糊、矛盾或不完整的剧情指令（大纲或作者要求），并提供清晰、结构化的澄清结果。

    Args:
        book: 书籍实体，包含全局系统提示词、世界观设定等
        ambiguous_text: 需要澄清的模糊文本或用户指令
        chapter: 当前章节实体（可选），提供章节标题与大纲参考
        entities: 相关的角色实体列表（可选），包含角色快照状态
        relationships: 角色关系列表（可选）
        open_hooks: 开放伏笔列表（可选）
        previous_chapter_summary: 上一章摘要（可选）
        locations: 章节关联的地点列表（可选）
        global_taboos: 全局禁忌/核心母题（可选）
        author_intent: 作者的补充意图（可选）
        user_instruction: 用户的补充回答（交互式流程用）
        previous_issues: 之前识别出的问题（交互式流程用）
        previous_chapter_snapshot: 上一章的世界状态快照（可选）
        previous_world_terminal_state: V4.0 结构化世界终端状态（可选）

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

    # 构建地图与地点上下文
    map_activity_range = getattr(chapter, "map_activity_range", None) if chapter else None
    map_prompt = f"【地图活动范围】\n{map_activity_range}" if map_activity_range else None
    
    location_prompts = []
    if locations:
        for loc_rel in locations:
            location = getattr(loc_rel, "location", None)
            if location:
                desc = f"【{location.name}】{location.description or ''}"
                location_prompts.append(desc)
    
    if map_prompt:
        location_prompts.append(map_prompt)
    
    final_map_prompt = "\n".join(location_prompts) if location_prompts else None

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

    # 构建角色关系上下文
    relationship_prompts = []
    if relationships:
        for rel in relationships:
            if hasattr(rel, "interaction_prompt") and rel.interaction_prompt:
                source_name = rel.source_character.name if hasattr(rel, "source_character") and rel.source_character else "角色"
                target_name = rel.target_character.name if hasattr(rel, "target_character") and rel.target_character else "角色"
                relationship_prompts.append(f"{source_name}↔{target_name}: {rel.interaction_prompt}")

    # 构建开放伏笔上下文
    normalized_hooks = []
    if isinstance(open_hooks, list):
        for item in open_hooks:
            if not isinstance(item, dict):
                continue
            hook_id = str(item.get("hook_id") or item.get("ledger_key") or "").strip()
            content = str(item.get("content") or "").strip()
            if content:
                normalized_hooks.append({"hook_id": hook_id, "content": content})
    open_hooks_text = (
        chr(10).join(
            [
                f"- {hook['hook_id']}: {hook['content']}" if hook["hook_id"] else f"- {hook['content']}"
                for hook in normalized_hooks[:6]
            ]
        )
        if normalized_hooks
        else None
    )

    # 构建世界状态快照约束
    world_snapshot_section = ""
    if previous_world_terminal_state:
        world_snapshot_section = previous_world_terminal_state.to_prompt_format()
    elif previous_chapter_snapshot:
        world_snapshot_section = format_snapshot_for_planner(previous_chapter_snapshot)

    system_prompt = f"""{global_sys_prompt}

你现在是一个剧情分析与澄清专家。你的任务是分析模糊、矛盾或不完整的剧情指令，结合现有世界观与角色设定，找出信息空白，并通过提问引导作者补充细节，最后仅输出 JSON。

{worldview_prompt if worldview_prompt else ''}

{final_map_prompt if final_map_prompt else ''}

## 输出 JSON 结构（示例值仅供格式参考，必须替换为本章实际内容）
{{
  "is_ambiguous": true,
  "identified_issues": [
    "未说明角色A为何突然出现在此地",
    "指令中对反派动机的描述与世界观设定存在冲突"
  ],
  "clarifying_questions": [
    {{
      "id": "q1_motivation",
      "question": "关于角色A的出现，您倾向于哪种解释？",
      "options": [
        {{ "label": "收到紧急求救信号", "value": "角色A收到了紧急求救信号才赶来" }},
        {{ "label": "追踪线索而来", "value": "角色A一路追踪反派留下的线索来到这里" }}
      ]
    }}
  ],
  "refined_text": "如果 user_instruction 为空（第一轮），此处返回空字符串或原始大纲；如果 user_instruction 有值（第二轮），则基于用户回答生成完整的修正大纲。"
}}

⚠️ **严禁照抄示例**：上方 JSON 中的所有字符串值均为示例，**必须全部替换为基于实际文本的分析内容**。

约束：
1. is_ambiguous 必须为布尔值，指示原文是否存在逻辑漏洞或模糊不清之处。如果用户已经通过 user_instruction 回答了所有问题，或者原文已足够清晰，请设为 false。
2. identified_issues 列表应具体指出目前仍然存在的问题所在，若无问题可为空列表。
3. clarifying_questions 是为交互式流程准备的，针对每个核心问题提供带有 2-4 个具体选项的问题，以便向用户提问。如果没有未解决的歧义可为空列表。
4. options 里的 value 必须是完整的情节设定句子，而不是简单的词语。
5. refined_text 规则：
   - 如果 user_instruction 为空（第一轮询问）：返回空字符串 ""，不要生成任何修正大纲
   - 如果 user_instruction 有值（第二轮，用户已回答）：基于用户的选择生成完整、详细的修正大纲，融合所有回答
6. 只输出 JSON，不要额外解释。
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

    # 1. 前情与世界状态参考
    if previous_chapter_summary:
        user_prompt_parts.append(f"【上一章情节概要】\n{previous_chapter_summary}\n")
    if world_snapshot_section:
        user_prompt_parts.append(f"【上一章结尾世界状态】\n{world_snapshot_section}\n")

    user_prompt_parts.append("请分析并澄清以下文本：")
    user_prompt_parts.append(f"【初始待澄清文本】\n{ambiguous_text}\n")
    
    if previous_issues:
        user_prompt_parts.append(f"【之前识别出的问题】\n{chr(10).join(previous_issues)}\n")
        
    if user_instruction:
        user_prompt_parts.append(f"【用户的补充回答与指令】\n{user_instruction}\n请根据上述回答修正大纲，并检查是否还有其他未澄清的重大问题。")

    # 附加当前章节参考
    if chapter:
        chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
        user_prompt_parts.append(f"【当前章节参考】{chapter_name}")
        if chapter.outline_text:
            user_prompt_parts.append(f"【章节大纲】\n{chapter.outline_text}\n")

    # 附加角色设定参考
    if character_prompts:
        user_prompt_parts.append(f"【相关角色设定】\n{chr(10).join(character_prompts)}\n")

    # 附加关系约束参考
    if relationship_prompts:
        user_prompt_parts.append(f"【关系约束】\n{chr(10).join(relationship_prompts)}\n")
        
    # 附加开放伏笔参考
    if open_hooks_text:
        user_prompt_parts.append(f"【开放伏笔】\n{open_hooks_text}\n")

    user_prompt = "\n".join(user_prompt_parts)
    return system_prompt, user_prompt
