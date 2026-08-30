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
潜意识提示词模块 - 起草阶段的潜意识提示构建。

职责：
- 构建潜意识层面的写作指导提示
- 提供 POV 角色的内心独白指导
- 整合场景意图和边界约束

业务场景：
- 起草阶段的提示词构建
- 深层写作指导

主要功能：
- 潜意识提示构建
- POV 角色内心描写指导
- 边界约束整合

依赖项：
- backend.models: 数据模型
- backend.services.prompts.draft_prompts_utils: 工具函数
"""

from typing import Optional, List

from backend.models import Chapter
from backend.services.prompts.draft_prompts_utils import (
    _normalize_text,
)


def build_subconscious_prompt(
    chapter: Chapter,
    beat: dict,
    scene_intent: dict,
    entities: list,
    pov_perception_state: str = "",
    red_lines: list[str] = None,
    previous_tail: str = "",
    present_characters: Optional[List[dict]] = None,
) -> tuple[str, str]:
    beat_data = beat if isinstance(beat, dict) else {}
    pov_character = _normalize_text(beat_data.get("pov_character"), "我")
    entry_state = _normalize_text(beat_data.get("entry_state"), "")
    location = _normalize_text(beat_data.get("location"), "当前场景")
    beat_summary = _normalize_text(beat_data.get("summary") or beat_data.get("action_summary"), "")

    effective_perception_state = pov_perception_state if pov_perception_state else entry_state

    effective_red_lines = red_lines if red_lines is not None else beat_data.get("red_lines", [])
    if effective_red_lines:
        red_lines_text = "\n".join([f"- {rl}" for rl in effective_red_lines])
    else:
        red_lines_text = "- 无特定红线"

    effective_previous_tail = previous_tail if previous_tail else "（无前文）"

    pov_traits = ""
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.name == pov_character:
            if character.static_prompt:
                pov_traits = character.static_prompt
            break

    intent_goal = _normalize_text(scene_intent.get("goal"), beat_summary)

    present_chars_section = ""
    if present_characters:
        char_lines = []
        for char in present_characters:
            if isinstance(char, dict):
                char_name = char.get("name", "")
                char_state = char.get("state", "")
                char_location = char.get("location", "")
                if char_name and char_name != pov_character:
                    desc = f"- {char_name}"
                    if char_state:
                        desc += f": 状态[{char_state}]"
                    if char_location:
                        desc += f", 位置[{char_location}]"
                    char_lines.append(desc)

        if char_lines:
            present_chars_section = """
## 【在场角色状态感知 - V4.0】
当前场景中，POV 角色感知到其他角色的存在和状态：
""" + "\n".join(char_lines) + """

**强制指令**：
1. 在潜意识独白中，必须包含对在场角色状态的感知和评估
2. 将其他角色的存在作为 POV 角色心理反应的刺激源
3. 即使不直接互动，也要有"感知到对方存在"的心理痕迹
4. 其他角色的状态（受伤/紧张/敌意）必须影响 POV 角色的心理推演
"""

    system_prompt = f"""你是擅长捕捉人物内心状态的作家。

当前附身角色：【{pov_character}】
当前物理知觉：【{effective_perception_state}】

【前情提要】：{effective_previous_tail}
【本段剧情目标】：{beat_summary}

【内心速写任务】：
请在角色的脑海中展开 3 条不同方向的心理流动。不需要打分，不需要评判哪条"更好"，只需让三条路径自然呈现：

• 路径 A（本能层）：角色最冲动、最原始的反应——可能是恐惧、愤怒、欲望，甚至是与理性相悖的念头。
• 路径 B（知觉层）：角色身体当下的真实感受——疼痛、疲惫、眩晕、某种气味或触感带来的联想。
• 路径 C（性格层）：基于角色固有性格的思维方式——如果角色是谨慎的，这里可能是权衡；如果是偏执的，可能是猜疑。

然后，不要"选择最优"，而是让这三条路径**自然交织**成一段完整的内心独白。真实的内心从来不是单一、清晰的，它是混乱的、层叠的、充满矛盾的。

注意：
- 潜意识中不出现主动战术动作（如果物理知觉受限）。
- 不直接触碰红线，但允许在红线边缘徘徊、挣扎。
- 允许语无伦次、中途断掉的念头、与当前无关的记忆闪回。

{present_chars_section}

输出一段 150-200 字的自由内心流动文本。不要 JSON，不要分点，不要编号。直接输出纯文本。"""

    user_prompt = f"""请为角色【{pov_character}】写一段内心流动。

【角色特征】
{pov_traits if pov_traits else "普通角色，无特殊设定"}

【切入状态】
{entry_state}

【当前场景】
{location}

【场景意图】
{intent_goal}

请直接输出内心独白的纯文本（150-200字）。不要 JSON，不要分点编号。"""

    return system_prompt, user_prompt
