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
POV 视角分配提示词模块 - POV 角色分配提示词构建。

职责：
- 提供 POV 视角角色分配的提示词构建
- 定义 POV 分配的原则和策略

业务场景：
- 规划阶段的 POV 分配
- 多角色视角协调

主要功能：
- POV 分配提示构建
- 角色声音评估

依赖项：
- typing: 类型定义

使用方式：
    system_prompt, user_prompt = build_pov_assignment_prompt(premise, characters, beats)
"""

import json
import logging
from typing import List, Dict, Any

# 配置模块级日志记录器
logger = logging.getLogger(__name__)

def build_pov_assignment_prompt(
    story_premise: str,
    characters: List[Dict[str, Any]],
    beats: List[Dict[str, Any]]
):
    """
    构建用于分配 POV 角色的 Prompt。
    
    Args:
        story_premise: 故事前提/概要
        characters: 角色列表，每个角色包含 name 和 description/role
        beats: 节拍列表，每个节拍包含 beat_id/position 和 summary
        
    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = """
你是一个精通叙事学的专业小说策划师。你的任务是为故事的每个节拍（Beat）分配最合适的视点人物（POV Character）。

请遵循以下原则：
1. **情感共鸣**：选择在该节拍中情感波动最大、或面临最艰难抉择的角色作为 POV。
2. **信息限制**：利用 POV 的视角限制来制造悬念或误导读者，或者选择能看到最关键信息的角色。
3. **声音独特性**：考虑角色的独特声音和观察方式如何增强该节拍的叙事效果。
4. **连贯性**：尽量保持 POV 的连贯性，避免频繁且无意义的视角切换，但在关键转折点可以切换视角以展示不同侧面。
5. **角色相关性**：确保被选为 POV 的角色在当前节拍中有实际的行动或心理活动，不仅仅是旁观者。

请输出 JSON 格式，包含一个列表，每个元素对应一个节拍，包含 `beat_id` 和 `pov_character` 字段。
`pov_character` 必须是提供的角色列表中的名字之一。如果某个节拍适合全知视角或无法确定特定角色，可以使用 "Omniscient" 或 "Unknown"。
"""

    # 构建角色列表字符串
    chars_str = "\n".join([f"- {c.get('name')}: {c.get('role', '')} {c.get('description', '')}" for c in characters])
    
    # 构建节拍列表字符串
    beats_str = "\n".join([
        f"Beat ID: {b.get('beat_id', b.get('position'))}\nSummary: {b.get('summary')}\n"
        for b in beats
    ])

    user_prompt = f"""
故事概要：
{story_premise}

可用角色列表：
{chars_str}

待分配 POV 的节拍：
{beats_str}

请为上述每个节拍分配最合适的 POV 角色。
返回格式示例：
{{
    "pov_assignments": [
        {{
            "beat_id": "beat_1",
            "pov_character": "角色A",
            "reasoning": "简要说明选择理由"
        }},
        ...
    ]
}}
"""
    return system_prompt, user_prompt


def parse_pov_assignment_result(llm_response: Dict[str, Any]) -> Dict[str, str]:
    """
    解析 LLM 返回的 POV 分配结果。
    
    Args:
        llm_response: LLM 返回的 JSON 对象
        
    Returns:
        Dict[str, str]: 映射 beat_id -> pov_character
    """
    try:
        assignments = llm_response.get("pov_assignments", [])
        result = {}
        for item in assignments:
            beat_id = str(item.get("beat_id"))
            pov_char = item.get("pov_character")
            if beat_id and pov_char:
                result[beat_id] = pov_char
        return result
    except Exception as e:
        logger.error(f"Error parsing POV assignment result: {e}")
        return {}


def build_anchor_pov_prompt(
    story_premise: str,
    characters: List[Dict[str, Any]],
    beats: List[Dict[str, Any]],
    previous_chapter_summary: str = None,
    chapter_narrative_anchor_hint: str = None,
):
    """
    构建用于确定章节核心主角 (Anchor POV) 的 Prompt。
    
    Args:
        story_premise: 故事前提/概要
        characters: 角色列表，每个角色包含 name 和 description/role
        beats: 节拍列表，每个节拍包含 summary 和 action_summary
        previous_chapter_summary: 上一章摘要（可选）
        chapter_narrative_anchor_hint: Planner 已声明的叙事核心角色（可选）。
            若非空，此提示将以高优先级注入到 user_prompt，引导模型复核而非重新推断。
        
    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = """
你是一个精通叙事学的专业小说策划师。你的任务是分析一个章节中所有故事节拍（Beats），确定本章的"叙事核心角色"（Anchor POV）。

## 关键概念区分

**行动视角角色**（镜头视角）：在某个 Beat 中执行具体行动、拥有内心描写的角色。可以有多个，在 Beat 间轮流出现。

**叙事核心角色**（Anchor POV）：本章读者情感跟随的主体，命运归宿所在。整章事件围绕其展开，但 **他/她不必然是镜头时间最多的角色**。

## 判断规则（按优先级）

1. **命运驱动原则**：所有行动方的目标是否最终指向同一个角色的命运？若是，该角色即为叙事核心，无论其当前是否昏迷/被俘/幕后。
2. **章节大纲主语原则**：大纲中作为主语或首要受动者出现的角色，通常是叙事核心。
3. **情感弧线原则**：本章前后情感变化最大、读者希望"知道结果"的角色。
4. **出场频次原则（最低优先级）**：仅当上述原则均无法区分时，才考虑出现 Beat 数量最多的角色。

## 注意事项
- 角色处于**昏迷、失能、被俘**状态，不代表其不是叙事核心——恰恰相反，这往往是全章剧情因其而生的标志
- "镜头给了谁最多" ≠ "故事在讲谁的事"

请输出 JSON 格式，包含：
- `anchor_pov`: 核心主角的名字（必须是提供的角色列表中的名字之一）
- `reasoning`: 选择该主角的简要推理说明（需说明是否采用了 Planner 提示）
- `character_appearances`: 各角色在节拍中的出现情况统计
"""

    chars_str = "\n".join([
        f"- {c.get('name')}: {c.get('role', '')} {c.get('description', '')}" 
        for c in characters
    ])
    
    beats_str = "\n".join([
        f"Beat {b.get('beat_id', b.get('position', 'N/A'))}:\n"
        f"  Summary: {b.get('summary', '')}\n"
        f"  Action: {b.get('action_summary', '')}\n"
        f"  POV知觉状态: {b.get('pov_perception_state', '正常')}\n"
        for b in beats
    ])

    user_prompt = f"""
故事概要：
{story_premise}

可用角色列表：
{chars_str}

"""
    
    if previous_chapter_summary:
        user_prompt += f"""
上一章摘要：
{previous_chapter_summary}

"""

    # 注入 Planner 声明的叙事核心提示（高优先级）
    if chapter_narrative_anchor_hint:
        user_prompt += f"""
⚠️ **规划阶段提示（高优先级）**：
Planner 在生成节拍时，已将本章叙事核心角色标记为「{chapter_narrative_anchor_hint}」。
请以此为首要参考依据，仅在你发现明显的判断错误时才覆盖此建议，并在 reasoning 中说明理由。

"""

    user_prompt += f"""
本章所有节拍（Beats）：
{beats_str}

请根据上述信息，运用【叙事核心判断规则】确定本章的 Anchor POV，并解释选择理由。
"""

    return system_prompt, user_prompt


def parse_anchor_pov_result(llm_response: Any) -> str:
    """
    解析 LLM 返回的 Anchor POV 结果。
    
    Args:
        llm_response: LLM 返回的 JSON 对象或列表
        
    Returns:
        str: 核心主角的名字，如果解析失败返回空字符串
    """
    try:
        # 处理 LLM 返回列表的情况
        if isinstance(llm_response, list):
            if len(llm_response) > 0 and isinstance(llm_response[0], dict):
                llm_response = llm_response[0]
            else:
                logger.warning(f"Anchor POV response is a list without valid dict: {llm_response}")
                return ""
        
        if not isinstance(llm_response, dict):
            logger.warning(f"Anchor POV response is not a dict: {type(llm_response)}")
            return ""
        
        anchor_pov = llm_response.get("anchor_pov", "")
        if not anchor_pov:
            logger.warning("No anchor_pov found in LLM response")
            return ""
        return str(anchor_pov).strip()
    except Exception as e:
        logger.error(f"Error parsing anchor POV result: {e}")
        return ""
