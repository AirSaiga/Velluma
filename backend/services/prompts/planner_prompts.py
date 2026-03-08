"""
规划提示词模块。

职责：提供章节规划（Planner）阶段的提示词构建和结果解析功能。

业务场景：
- 将章节大纲拆分为可执行的 story beats（剧情节拍）
- 每个 beat 包含位置、视角角色、动作摘要、进入/退出状态、红线约束等
- 支持低张力模式、伏笔绑定、POV 分配等高级功能

工作流位置：
- 位于 Agentic 工作流的起始阶段
- 输入：章节信息、角色列表、关系约束、开放伏笔、目标字数
- 输出：结构化的 beats 列表，用于后续的并行生成

常量说明：
- LOW_TENSION_RED_LINES: 低张力章节的默认红线约束
"""

import json
import re
from typing import Optional

from backend.models import Chapter, Book


# 低张力章节的默认红线约束
# 用于 tension_level <= 3 时的自动注入
LOW_TENSION_RED_LINES = ["避免正面冲突", "避免战斗升级"]


def build_planner_agent_prompt(
    chapter: Chapter,
    book: Book,
    entities: list,
    relationships: list,
    word_count: int,
    open_hooks: Optional[list] = None,
    previous_chapter_summary: Optional[str] = None,
    locations: Optional[list] = None,
    global_taboos: Optional[str] = None,
    author_intent: Optional[str] = None,
) -> tuple[str, str]:
    """构建规划阶段的提示词。

    将章节大纲拆分为可执行的 story beats。

    Args:
        chapter: 章节实体，包含章节名、大纲、张力等级、节奏偏好等信息
        book: 书籍实体，包含全局系统提示词、世界观设定、核心母题禁忌等
        entities: 章节关联的角色实体列表（ChapterEntity）
        relationships: 角色关系列表
        word_count: 目标字数
        open_hooks: 开放伏笔列表，用于绑定到 beats
        previous_chapter_summary: 上一章摘要，用于上下文连贯性
        locations: 章节关联的地点列表
        global_taboos: 全局禁忌/核心母题（Book 级别）
        author_intent: 作者创作意图（Request 级别）

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
        - system_prompt: 包含角色设定、关系约束、世界观、输出格式要求
        - user_prompt: 包含章节信息、大纲、目标字数、绝对最高优先级指令

    提示词设计说明：
    - system_prompt: 定义 JSON 输出格式、beat 数量限制、pacing_type 约束等
    - user_prompt: 包含实际章节内容，global_taboos 和 author_intent 作为绝对最高优先级注入
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    tension_level = getattr(chapter, "tension_level", 5)
    if not isinstance(tension_level, int):
        tension_level = 5
    pacing_style = str(getattr(chapter, "pacing_style", "balanced") or "balanced").strip() or "balanced"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    
    map_activity_range = getattr(chapter, "map_activity_range", None)
    map_prompt = f"【地图活动范围】\n{map_activity_range}" if map_activity_range else None
    
    location_prompts = []
    if locations:
        for loc_rel in locations:
            # Handle both ChapterMapLocation object or dict/mock
            location = getattr(loc_rel, "location", None)
            if location:
                desc = f"【{location.name}】{location.description or ''}"
                location_prompts.append(desc)
    
    if map_prompt:
        location_prompts.append(map_prompt)
    
    final_map_prompt = "\n".join(location_prompts) if location_prompts else None

    character_prompts = []
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
    
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"{source_name}↔{target_name}: {rel.interaction_prompt}")
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
        else "暂无开放伏笔"
    )
    low_tension_rule = ""
    if tension_level <= 3:
        low_tension_rule = (
            f"\n8. 当前章节张力等级为 {tension_level}（低张力），每个 beat 的 red_lines 必须包含："
            f"{'、'.join(LOW_TENSION_RED_LINES)}\n"
            "9. 低张力章节禁止设计直接爆发式冲突，剧情推进以铺垫与悬停为主"
        )
    system_prompt = f"""{global_sys_prompt}

你是章节规划师。请把章节拆分成可执行的 story beats，并仅输出 JSON。

{worldview_prompt if worldview_prompt else ''}

{final_map_prompt if final_map_prompt else ''}

## 输出 JSON 结构
{{
  "beats": [
    {{
      "position": 1,
      "beat_id": "beat-1",
      "summary": "本段剧情概述",
      "location": "场景地点",
      "pov_character": "视角角色",
      "action_summary": "动作化执行摘要",
      "worldbuilding_instruction": "本段生效的世界构建约束",
      "entry_state": "本段切入时角色与局面的起始状态",
      "exit_state": "本段必须停住的收束状态（不得越界）",
      "red_lines": ["本段禁止发生1", "本段禁止发生2"],
      "word_count_target": 600,
      "hook_ids": ["hk-1"],
      "pacing_type": "Medium",
      "weight": 3
    }}
  ]
}}

约束：
1. beats 至少 1 个，最多 6 个
2. position 从 1 开始递增
3. summary 具体、可执行，不要空泛
4. action_summary 必须可执行、动作化
5. word_count_target 为正整数，总和接近章节目标字数
6. 若存在开放伏笔，至少在一个 beat 的 hook_ids 中绑定
7. 每个 beat 必须显式填写 entry_state、exit_state、red_lines，且 red_lines 至少 1 条
8. pacing_type 必须是 Fast, Medium, Slow 之一
9. weight 必须是 1-5 之间的整数
{low_tension_rule if low_tension_rule else ''}
10. exit_state 是本 beat 的硬停点，不能把后续 beat 事件提前写进当前 beat
11. 只输出 JSON，不要额外解释"""
    
    user_prompt_parts = []
    
    # 0. 绝对最高优先级指令 (Absolute Highest Priority)
    if global_taboos or author_intent:
        user_prompt_parts.append("## 0. 绝对最高优先级指令 (Absolute Highest Priority)")
        if global_taboos:
            user_prompt_parts.append(f"【全局禁忌/核心母题】\n{global_taboos}")
        if author_intent:
            user_prompt_parts.append(f"【作者创作意图】\n{author_intent}")
            user_prompt_parts.append("重要提示：若【作者创作意图】与【章节大纲】的内容顺序或逻辑存在冲突，请优先满足【作者创作意图】。你可以调整大纲事件的顺序、改写开头或重新设计情节结构（例如采用倒叙、直接切入冲突等），以确保创作意图得到完美执行。")
        user_prompt_parts.append("")

    user_prompt_parts.append(f"""请规划以下章节：

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【剧情张力等级】{tension_level}
【叙事节奏偏好】{pacing_style}
【上一章情节概要】
{previous_chapter_summary if previous_chapter_summary else '暂无上一章概要'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【目标字数】{word_count}
【角色设定】
{chr(10).join(character_prompts) if character_prompts else "暂无角色详情"}
【关系约束】
{chr(10).join(relationship_prompts) if relationship_prompts else "暂无互动约束"}
【开放伏笔】
{open_hooks_text}""")

    user_prompt = "\n".join(user_prompt_parts)
    return system_prompt, user_prompt


def parse_planner_result(
    planner_result_raw: str,
    chapter_outline: str,
    word_count: int,
) -> list[dict]:
    """解析规划结果的 JSON 输出。

    从 LLM 返回的原始文本中提取 beats 列表，并进行数据清洗和类型转换。

    解析策略（优先级从高到低）：
    1. 尝试直接解析整个文本为 JSON
    2. 尝试提取 Markdown 代码块中的 JSON
    3. 尝试提取 { } 包裹的 JSON 对象
    4. 若全部失败，使用章节大纲作为 fallback beat

    Args:
        planner_result_raw: LLM 返回的原始文本
        chapter_outline: 章节大纲（用于 fallback）
        word_count: 目标字数（用于 fallback 计算）

    Returns:
        list[dict]: 结构化的 beats 列表，每个 beat 包含：
        - position: 位置索引
        - beat_id: 节拍唯一标识
        - summary: 剧情概述
        - location: 场景地点
        - pov_character: 视角角色
        - action_summary: 动作化执行摘要
        - entry_state: 进入状态
        - exit_state: 退出状态
        - red_lines: 红线约束列表
        - word_count_target: 目标字数
        - hook_ids: 关联的伏笔 ID 列表
        - pacing_type: 节奏类型 (Fast/Medium/Slow)
        - weight: 权重 (1-5)
    """
    text = (planner_result_raw or "").strip()
    candidates = [text] if text else []
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    parsed_obj = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    beats = []
    if isinstance(parsed_obj, dict) and isinstance(parsed_obj.get("beats"), list):
        for idx, beat in enumerate(parsed_obj["beats"], start=1):
            if not isinstance(beat, dict):
                continue
            summary = str(beat.get("summary") or "").strip()
            if not summary:
                continue
            position = beat.get("position")
            if not isinstance(position, int) or position <= 0:
                position = idx
            target_words = beat.get("target_words")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = max(200, word_count // max(1, len(parsed_obj["beats"])))
            word_count_target = beat.get("word_count_target")
            if not isinstance(word_count_target, int) or word_count_target <= 0:
                word_count_target = target_words
            beat_id = str(beat.get("beat_id") or f"beat-{position}").strip() or f"beat-{position}"
            location = str(beat.get("location") or "").strip() or None
            pov_character = str(beat.get("pov_character") or "").strip() or None
            action_summary = str(beat.get("action_summary") or "").strip() or summary
            worldbuilding_instruction = str(beat.get("worldbuilding_instruction") or "").strip() or None
            entry_state = str(beat.get("entry_state") or "").strip()
            if not entry_state:
                entry_state = f"承接上文并切入：{summary[:40]}"
            exit_state = str(beat.get("exit_state") or "").strip()
            if not exit_state:
                exit_state = f"停在本节拍收束点：{action_summary[:40]}"
            raw_hook_ids = beat.get("hook_ids")
            raw_red_lines = beat.get("red_lines")
            hook_ids = [str(item).strip() for item in raw_hook_ids if str(item).strip()] if isinstance(raw_hook_ids, list) else []
            red_lines = [str(item).strip() for item in raw_red_lines if str(item).strip()] if isinstance(raw_red_lines, list) else []
            if not red_lines:
                red_lines = ["不得越过本节拍 exit_state 指向的剧情停点"]
            
            pacing_type = str(beat.get("pacing_type") or "Medium").strip()
            if pacing_type not in ["Fast", "Medium", "Slow"]:
                pacing_type = "Medium"
            
            weight = beat.get("weight")
            if not isinstance(weight, int):
                weight = 3
            else:
                weight = max(1, min(5, weight))

            beats.append(
                {
                    "position": position,
                    "beat_id": beat_id,
                    "summary": summary,
                    "location": location,
                    "pov_character": pov_character,
                    "action_summary": action_summary,
                    "worldbuilding_instruction": worldbuilding_instruction,
                    "entry_state": entry_state or None,
                    "exit_state": exit_state or None,
                    "red_lines": red_lines,
                    "word_count_target": word_count_target,
                    "target_words": word_count_target,
                    "hook_ids": hook_ids,
                    "pacing_type": pacing_type,
                    "weight": weight,
                }
            )
    if not beats:
        fallback_summary = (chapter_outline or "").strip() or "按章节大纲推进剧情并完成关键冲突。"
        beats = [
            {
                "position": 1,
                "beat_id": "beat-1",
                "summary": fallback_summary,
                "location": None,
                "pov_character": None,
                "action_summary": fallback_summary,
                "worldbuilding_instruction": None,
                "entry_state": "承接上文并切入本节拍",
                "exit_state": "停在本节拍收束点，不推进后续事件",
                "red_lines": ["不得越过本节拍 exit_state 指向的剧情停点"],
                "word_count_target": word_count,
                "target_words": word_count,
                "hook_ids": [],
                "pacing_type": "Medium",
                "weight": 3,
            }
        ]
    beats.sort(key=lambda item: item["position"])
    return beats
