"""
规划提示词模块。

职责：提供章节规划（Planner）阶段的提示词构建和结果解析功能。

子模块：
- planner_prompts_parser: 结果解析函数和常量
"""

import json
from typing import Optional

from backend.models import Chapter, Book
from backend.world_state_schemas import WorldTerminalState
from backend.services.prompts.world_state_prompts import (
    build_world_state_constraint_prompt,
    format_snapshot_for_planner,
)
from backend.services.prompts.planner_prompts_parser import (
    LOW_TENSION_RED_LINES,
    parse_planner_full_result,
    parse_planner_result,
)


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
    previous_world_terminal_state: Optional[WorldTerminalState] = None,  # V3.6: 新增参数
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
    - previous_world_terminal_state: V3.6 结构化世界终端状态，强制物理约束
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
    # =================================================================
    # V3.6: 构建世界终端状态约束段落
    # =================================================================
    world_state_constraint = ""
    if previous_world_terminal_state:
        world_state_constraint = previous_world_terminal_state.to_prompt_format()
    elif previous_chapter_snapshot:
        # 回退到旧版格式
        world_state_constraint = format_snapshot_for_planner(previous_chapter_snapshot)

    # V3.6: 基于目标字数计算推荐 beats 数量
    beats_min = max(2, word_count // 1000)           # 1000字→2, 2000字→2, 2001字→3
    beats_min = min(beats_min, 4)                    # 上限不超过4（避免强制过碎）
    beats_recommended = max(2, min(6, round(word_count / 600)))  # 每beat约600字
    beats_recommended = max(beats_recommended, beats_min)

    system_prompt = f"""{global_sys_prompt}

你是章节规划师。请把章节拆分成可执行的 story beats，并仅输出 JSON。

{worldview_prompt if worldview_prompt else ''}

{final_map_prompt if final_map_prompt else ''}

## 输出 JSON 结构（示例值仅供格式参考，必须替换为本章实际内容）
{{
  "beats": [
    {{
      "position": 1,
      "beat_id": "beat-1",
      "summary": "白霆在实验室发现血嗤已觉醒，两人爆发正面冲突，血嗤以压倒性力量将白霆击退至走廊",
      "location": "0号计划核心实验室",
      "pov_character": "白霆",
      "pov_mode": "single",
      "pov_characters": [],
      "pov_perception_state": "正常",
      "pov_aperture": "subjective_observation",
      "persistent_state_anchors": [
        {{
          "anchor_type": "unresolved_conflict",
          "description": "白霆对血嗤觉醒程度的判断尚未确认，局势主动权在血嗤一侧",
          "involved_characters": ["白霆", "血嗤"]
        }}
      ],
      "action_summary": "白霆拔枪射击，血嗤徒手偏转弹道，反手将白霆摔出三米远",
      "worldbuilding_instruction": "0号计划实验室设有电磁屏蔽层，外部信号无法进入",
      "entry_state": "白霆持枪站在实验室入口，血嗤站在培养舱旁，双方对峙，空气凝滞",
      "exit_state": "白霆倒在走廊地板，血嗤仍在实验室内未追出，双方短暂脱离接触",
      "red_lines": ["禁止白霆在此节拍中获胜或压制血嗤", "禁止血嗤在此节拍中离开实验室"],
      "word_count_target": 600,
      "hook_ids": ["hk-1"],
      "pacing_type": "Medium",
      "weight": 3
    }}
  ],
  "workflow_tier": "TIER_2_STANDARD",
  "chapter_narrative_anchor": "白霆"
}}

⚠️ **严禁照抄示例**：上方 JSON 中的所有字符串值（summary、location、pov_character、entry_state、exit_state、red_lines 等）均为示例，**必须全部替换为本章大纲的真实内容**。

约束：
1. beats 数量：**至少 {beats_min} 个，最多 6 个**。
   基于本章【目标字数 {word_count} 字】，推荐生成 **{beats_recommended} 个 beats**（每个 beat 约 400-800 字）。
   - 严禁在大纲内容足够的情况下只规划 1 个 beat
   - 若大纲包含多个明显的场景切换或视角转移，应按实际场景数拆分，不要强行合并
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
12. 【跨章接缝绝对定标 ($T_{{-1}} \rightarrow T_0$) - 最高优先级】
    **这是最高优先级约束，违反将导致章节无法衔接！**
    
    {world_state_constraint if world_state_constraint else '''你必须仔细分析【上一章情节概要】的最后部分，提取以下关键信息：
    - **上一章结尾的视角角色**：是谁的 POV？
    - **上一章结尾的物理位置**：角色在哪里？做什么？
    - **上一章结尾的角色状态**：意识是否清醒？身体状态如何？
    - **上一章结尾的最后动作**：最后一个发生的事件是什么？'''}
    
    然后，你的第一个节拍（Beat 1）必须满足：
    - `entry_state` 必须与上一章结尾的物理空间、视角角色、角色状态保持 100% 连续性
    - 如果需要切换视角（从角色 A 切换到角色 B），Beat 1 必须是一个明确的【摄像机过渡节拍】，清晰交代物理时间或空间的转移
    - 严禁让角色产生"瞬移"幻觉或状态突变
    
    **【V3.6 强制规则 - 世界状态约束】**
    1. **物理连续性**: Beat 1 的 entry_state 必须严格匹配「前一章末尾世界状态快照」中的位置和状态
    2. **角色离场检查**: 如果 snapshot 中角色的 physical_condition 为 inactive/dead，严禁为其分配任何 Beat
    3. **意图延续**: 角色的 immediate_intention 必须作为 Beat 1 的行为驱动基础
    4. **锚点处理**: physical_anchors 列表中的物品/状态必须在某个 Beat 中被处理或说明
    
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
16. **》V3.5 新增「pov_aperture (叙事光圈)**: 控制 Drafting 阶段的视角景深，仅在 pov_mode="single" 时有效，必须从以下选项中选择：
    - "internal_only": 仅限 {anchor_pov or '视角角色'} 的内心与自我感知，强制屏蔽不可见环境细节。适用于深度心理描写、独处的内省场景。
    - "subjective_observation" (默认): 允许描写其他角色动作，但必须通过 {anchor_pov or '视角角色'} 的认知/判断包裹。适用于常规场景。
    - "systemic_sense": 允许全景感知，但在叙事上依然以 {anchor_pov or '视角角色'} 为锚点。适用于高张力动作场景、需要全局感知的战斗场面。
    选择依据：基于 scene_intent 和 tension_level 自动推断，高张力动作场景用 systemic_sense，深度心理描写用 internal_only。
16b. **》V3.6 新增「pov_mode (叙事视角模式)**: 根据场景类型选择最合适的视角策略：
    - "single"(默认)：单一视角，锁定在 pov_character 的感官范围内。适用：独处内省、单角色是核心的动作场景。
    - "ensemble"：多角色共存视角，摄像机在多个角色间自然游走，每个角色均有内心展现。
      适用：**多人对峙**、**密谋策划**、**多方博弈**等多角色同场且每人动机均重要的场景。
      → 选择 ensemble 时，必须同时填写 pov_characters 列表（2-4 个角色名，按内心权重由高到低排序）。pov_character 填列表中第一个角色名。
    - "omniscient"：全知视角，可自由展现所有角色内心。适用：宏观战场全景、世界性事件。
    ❗注意：pov_mode="ensemble"/"omniscient" 时，pov_aperture 字段可不填写。
17. **【V3.5 新增】persistent_state_anchors (持久状态锚点)**: 每个 beat 必须输出状态锚点列表，用于跨 Beat 状态连贯。必须包含以下类型：
    - unresolved_conflict: 当前未解决的冲突（如"角色A对角色B的怀疑尚未消除"）
    - emotional_tone: 角色情感基调（如"主角处于焦虑但克制的状态"）
    - spatial_attachment: 物理位置依附关系（如"角色C仍在机甲内部，未脱离"）
    这些锚点将在 Drafting 阶段作为结构化数据注入，禁止合并为纯文本。
18. **【V3.6 新增】world_state_constraint (世界状态强制约束)**: 
    - 如果提供了「前一章末尾世界状态快照」，必须将其作为物理现实的金标准
    - Beats 规划严禁违反 snapshot 中的任何物理状态、位置或意图
    - Beat 1 的 entry_state 必须完全锚定 snapshot 中的状态，禁止任何偏离
    - 角色离场检查：physical_condition 为 inactive/dead 的角色严禁分配 Beat"""
    
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




