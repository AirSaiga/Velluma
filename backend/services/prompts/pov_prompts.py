import json
from typing import List, Dict, Any

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
        print(f"Error parsing POV assignment result: {e}")
        return {}
