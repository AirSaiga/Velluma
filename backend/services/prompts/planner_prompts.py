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
from backend.services.prompts.world_state_prompts import (
    build_world_state_constraint_prompt,
    format_snapshot_for_planner,
)


# 低张力章节的默认红线约束
# V3.0: 用于 tension_level <= 2 时的自动注入
LOW_TENSION_RED_LINES = ["禁止发生任何武力冲突或战斗升级", "避免正面冲突"]


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
    previous_chapter_snapshot: Optional[dict] = None,
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
        previous_chapter_snapshot: 上一章的世界状态快照（用于跨章状态连续性约束）

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
        - system_prompt: 包含角色设定、关系约束、世界观、输出格式要求
        - user_prompt: 包含实际章节内容，global_taboos 和 author_intent 作为绝对最高优先级注入

    提示词设计说明：
    - system_prompt: 定义 JSON 输出格式、beat 数量限制、pacing_type 约束等
    - user_prompt: 包含实际章节内容，global_taboos 和 author_intent 作为绝对最高优先级注入
    - previous_chapter_snapshot: 注入世界状态约束，确保跨章物理连续性
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    tension_level = getattr(chapter, "tension_level", 5)
    if not isinstance(tension_level, int):
        tension_level = 5
    pacing_style = str(getattr(chapter, "pacing_style", "balanced") or "balanced").strip() or "balanced"
    
    # 获取叙事锚定视角角色
    anchor_pov = getattr(chapter, "anchor_pov", None)
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
    # V3.0: 低张力规则改为 tension_level <= 2
    low_tension_rule = ""
    if tension_level <= 2:
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
      "pov_perception_state": "正常",
      "pov_aperture": "subjective_observation",
      "persistent_state_anchors": [
        {{
          "anchor_type": "unresolved_conflict",
          "description": "描述当前未解决的冲突",
          "involved_characters": ["角色名"]
        }}
      ],
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
  ],
  "workflow_tier": "TIER_2_STANDARD",
  "chapter_narrative_anchor": "角色名"
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
11. workflow_tier 必须基于 tension_level 自动计算：
    - tension_level 为 1 或 2 时 → "TIER_1_FAST" (疾速流)
    - tension_level 为 3 时 → "TIER_2_STANDARD" (均衡流)
    - tension_level 为 4 或 5 时 → "TIER_3_FORTRESS" (堡垒流)
11. pov_perception_state: 当前视角角色的意识清醒程度与物理行动力。必须从以下标准化描述中选择或组合：
    "正常" / "轻伤但行动自如" / "重伤行动受限" / "半昏迷" / "失去身体控制权" / "完全昏迷" / "神经过载"
    也可以自由描述，但必须明确表达角色的意识状态和身体可控程度。
    如果角色在本节拍处于受伤/昏迷等状态，pov_perception_state 必须如实反映，不能默认写"正常"。
12. 【跨章接缝绝对定标 ($T_{{-1}} \\rightarrow T_0$) - 最高优先级】
    **这是最高优先级约束，违反将导致章节无法衔接！**
    
    你必须仔细分析【上一章情节概要】的最后部分，提取以下关键信息：
    - **上一章结尾的视角角色**：是谁的 POV？
    - **上一章结尾的物理位置**：角色在哪里？做什么？
    - **上一章结尾的角色状态**：意识是否清醒？身体状态如何？
    - **上一章结尾的最后动作**：最后一个发生的事件是什么？
    
    然后，你的第一个节拍（Beat 1）必须满足：
    - `entry_state` 必须与上一章结尾的物理空间、视角角色、角色状态保持 100% 连续性
    - 如果需要切换视角（从角色 A 切换到角色 B），Beat 1 必须是一个明确的【摄像机过渡节拍】，清晰交代物理时间或空间的转移
    - 严禁让角色产生"瞬移"幻觉或状态突变
    
    **示例（错误 vs 正确）**：
    - ❌ 错误：上一章结尾"楚言昏迷"，本章 Beat 1 entry_state 写"楚言意识清醒站立"
    - ✅ 正确：上一章结尾"楚言昏迷"，本章 Beat 1 entry_state 写"楚言昏迷倒地，白霆在远处观察台目睹这一切"（视角切换+状态延续）
13. 【跨 Beat 状态过渡动作强制规则】
    当角色的物理形态或空间位置在两个相邻 Beat 之间发生突变（如：从肉身登入机甲、拔出重型武器、从高处坠落、角色登场/退场等），当前 Beat 的【summary 或 action_summary】必须显式包含具体的【状态过渡动作】（如："白霆跃入舱门，机甲系统启动"、"他拔出腰间的重剑"、"她推开门走了进来"）。
    - ❌ 严禁直接描写突变后的动作结果而不交代过渡过程
    - ✅ 必须先写过渡动作，再写突变后的状态
    - 目的：避免动作突变和空间瞬移的幻觉，保持叙事的物理连续性
14. 只输出 JSON，不要额外解释
15. chapter_narrative_anchor: 本章的**叙事核心角色**（读者情感跟随、命运归宿所在的主体）。
    - 叙事核心 ≠ 镜头时间最多：若某角色在大部分 beat 中处于昏迷/被动/幕后状态，但所有事件均因其命运而发生、所有行动方的目标均指向其时，仍应将其填为叙事核心
    - 必须从【角色设定】中的角色名中选择一个，若多人均等则填 "Ensemble"
    - 此字段由你作为规划师主动判断，优先级高于 beat 出现频次
16. **【V3.5 新增】pov_aperture (叙事光圈)**: 控制 Drafting 阶段的视角景深，必须从以下选项中选择：
    - "internal_only": 仅限 {anchor_pov or '视角角色'} 的内心与自我感知，强制屏蔽不可见环境细节。适用于深度心理描写、独处的内省场景。
    - "subjective_observation" (默认): 允许描写其他角色动作，但必须通过 {anchor_pov or '视角角色'} 的认知/判断包裹。适用于常规场景。
    - "systemic_sense": 允许全景感知，但在叙事上依然以 {anchor_pov or '视角角色'} 为锚点。适用于高张力动作场景、需要全局感知的战斗场面。
    选择依据：基于 scene_intent 和 tension_level 自动推断，高张力动作场景用 systemic_sense，深度心理描写用 internal_only。
17. **【V3.5 新增】persistent_state_anchors (持久状态锚点)**: 每个 beat 必须输出状态锚点列表，用于跨 Beat 状态连贯。必须包含以下类型：
    - unresolved_conflict: 当前未解决的冲突（如"角色A对角色B的怀疑尚未消除"）
    - emotional_tone: 角色情感基调（如"主角处于焦虑但克制的状态"）
    - spatial_attachment: 物理位置依附关系（如"角色C仍在机甲内部，未脱离"）
    这些锚点将在 Drafting 阶段作为结构化数据注入，禁止合并为纯文本。"""
    
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

    # 添加世界状态快照约束（如果存在）
    world_snapshot_section = ""
    if previous_chapter_snapshot:
        world_snapshot_section = format_snapshot_for_planner(previous_chapter_snapshot)
        if world_snapshot_section:
            world_snapshot_section = f"\n{world_snapshot_section}\n"

    user_prompt_parts.append(f"""请规划以下章节：

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【剧情张力等级】{tension_level}
【叙事节奏偏好】{pacing_style}
【上一章情节概要】
{previous_chapter_summary if previous_chapter_summary else '暂无上一章概要（这是第一章或上一章未生成）'}
{world_snapshot_section}
⚠️ **跨章接缝提醒**：
请仔细分析上述【上一章情节概要】的最后 200 字，提取：
1. 结尾视角角色是谁？
2. 结尾时角色的物理状态（位置、姿势、意识清醒程度）？
3. 最后一个动作是什么？

你的 Beat 1 的 `entry_state` 必须与上述信息保持 100% 连续性！

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


def parse_planner_full_result(
    planner_result_raw: str,
    chapter_outline: str,
    word_count: int,
) -> tuple[list[dict], str]:
    """解析规划结果，返回 beats 列表和章节叙事核心角色。

    在 parse_planner_result 的基础上，额外返回 chapter_narrative_anchor 字段，
    供 POV_ASSIGNMENT 阶段优先使用，避免仅凭 beat 出现频次错误判断叙事核心。

    Args:
        planner_result_raw: LLM 返回的原始文本
        chapter_outline: 章节大纲（用于 fallback）
        word_count: 目标字数（用于 fallback 计算）

    Returns:
        tuple[list[dict], str]: (beats 列表, chapter_narrative_anchor 角色名或空字符串)
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

    # V3.0: 解析 workflow_tier，默认为 TIER_2_STANDARD
    workflow_tier = "TIER_2_STANDARD"
    if isinstance(parsed_obj, dict):
        tier = parsed_obj.get("workflow_tier")
        if tier in ["TIER_1_FAST", "TIER_2_STANDARD", "TIER_3_FORTRESS"]:
            workflow_tier = tier

    # 解析叙事核心角色（Planner 主动声明，优先于 beat 频次统计）
    chapter_narrative_anchor = ""
    if isinstance(parsed_obj, dict):
        chapter_narrative_anchor = str(parsed_obj.get("chapter_narrative_anchor", "")).strip()

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
            # POV 角色知觉状态：由 Planner 显式输出
            pov_perception_state = str(beat.get("pov_perception_state") or "正常").strip() or "正常"
            # V3.5: 解析叙事光圈，默认为 subjective_observation
            pov_aperture = str(beat.get("pov_aperture") or "subjective_observation").strip()
            if pov_aperture not in ["internal_only", "subjective_observation", "systemic_sense"]:
                pov_aperture = "subjective_observation"
            # V3.5: 解析持久状态锚点
            persistent_state_anchors = []
            raw_anchors = beat.get("persistent_state_anchors")
            if isinstance(raw_anchors, list):
                for anchor in raw_anchors:
                    if isinstance(anchor, dict):
                        anchor_type = str(anchor.get("anchor_type") or "").strip()
                        description = str(anchor.get("description") or "").strip()
                        involved_chars = anchor.get("involved_characters", [])
                        if isinstance(involved_chars, list):
                            involved_characters = [str(c).strip() for c in involved_chars if str(c).strip()]
                        else:
                            involved_characters = []
                        if anchor_type and description:
                            persistent_state_anchors.append({
                                "anchor_type": anchor_type,
                                "description": description,
                                "involved_characters": involved_characters
                            })
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
                    "pov_perception_state": pov_perception_state,
                    "pov_aperture": pov_aperture,  # V3.5: 叙事光圈
                    "persistent_state_anchors": persistent_state_anchors,  # V3.5: 持久状态锚点
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
                    "workflow_tier": workflow_tier,  # V3.0: 注入工作流层级
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
                "pov_perception_state": "正常",
                "pov_aperture": "subjective_observation",  # V3.5: 默认叙事光圈
                "persistent_state_anchors": [],  # V3.5: 默认空锚点列表
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
                "workflow_tier": workflow_tier,  # V3.0: fallback 也注入工作流层级
            }
        ]
    beats.sort(key=lambda item: item["position"])
    return beats, chapter_narrative_anchor


def parse_planner_result(
    planner_result_raw: str,
    chapter_outline: str,
    word_count: int,
) -> list[dict]:
    """解析规划结果的 JSON 输出（向后兼容包装器）。

    仅返回 beats 列表，忽略 chapter_narrative_anchor。
    新代码应使用 parse_planner_full_result 以获取叙事核心角色信息。

    Args:
        planner_result_raw: LLM 返回的原始文本
        chapter_outline: 章节大纲（用于 fallback）
        word_count: 目标字数（用于 fallback 计算）

    Returns:
        list[dict]: 结构化的 beats 列表
    """
    beats, _ = parse_planner_full_result(planner_result_raw, chapter_outline, word_count)
    return beats
