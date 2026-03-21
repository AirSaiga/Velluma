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
):
    """
    构建用于确定章节核心主角 (Anchor POV) 的 Prompt。
    
    Args:
        story_premise: 故事前提/概要
        characters: 角色列表，每个角色包含 name 和 description/role
        beats: 节拍列表，每个节拍包含 summary 和 action_summary
        previous_chapter_summary: 上一章摘要（可选）
        
    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = """
你是一个精通叙事学的专业小说策划师。你的任务是分析一个章节中所有故事节拍（Beats），推断出本章的"核心主角"（Anchor POV）。

"核心主角"是指在本章中：
1. 占据最多节拍数或最重要节拍的角色
2. 推动本章主要情节发展的角色
3. 在多个节拍中有重要行动或心理描写的角色
4. 章节的核心冲突主要围绕其展开

请仔细分析提供的所有节拍信息，包括每个节拍的 summary 和 action_summary，统计各角色的出现频率和重要性，
结合上一章的情节发展，确定本章最合适的核心主角（Anchor POV）。

请输出 JSON 格式，包含：
- `anchor_pov`: 核心主角的名字（必须是提供的角色列表中的名字之一）
- `reasoning`: 选择该主角的简要推理说明
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

    user_prompt += f"""
本章所有节拍（Beats）：
{beats_str}

请分析上述节拍，确定本章的核心主角（Anchor POV），并解释选择理由。
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
