import json
from typing import Optional, List

from backend.models import Chapter, Book


def _normalize_text(value, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_text_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _render_boundary_constraints(entry_state: str, exit_state: str, red_lines: list[str]) -> str:
    red_line_text = "；".join(red_lines) if red_lines else "无"
    return (
        "## 【边界约束与剧情完整性 - 最高优先级】\n"
        "1. 本区块优先级高于其他所有写作建议。\n"
        f"2. 切入状态（entry_state）：{entry_state}\n"
        f"3. 目标收束状态（exit_state）：{exit_state}\n"
        f"4. 绝对禁忌（red_lines）：{red_line_text}\n"
        "5. 请确保本节拍的核心冲突和情感铺垫得到充分演绎，再自然收束于 exit_state。切勿为了赶进度而在高潮处突然中断！"
    )


def _render_scene_intent_prompt(scene_intent_data) -> Optional[str]:
    if isinstance(scene_intent_data, dict):
        constraints = _normalize_text_list(scene_intent_data.get("constraints"))
        return (
            "## SceneIntent\n"
            f"标签：{_normalize_text(scene_intent_data.get('intent_label'), '推进剧情')}\n"
            f"目标：{_normalize_text(scene_intent_data.get('goal'), '推进剧情')}\n"
            f"风险：{_normalize_text(scene_intent_data.get('stakes'), '无')}\n"
            f"约束：{', '.join(constraints) if constraints else '无'}"
        )
    if isinstance(scene_intent_data, list) and scene_intent_data:
        latest_intent = scene_intent_data[-1]
        if isinstance(latest_intent, dict):
            constraints = _normalize_text_list(latest_intent.get("constraints"))
            return (
                "## SceneIntent\n"
                f"标签：{_normalize_text(latest_intent.get('intent_label'), '推进剧情')}\n"
                f"目标：{_normalize_text(latest_intent.get('goal'), '推进剧情')}\n"
                f"风险：{_normalize_text(latest_intent.get('stakes'), '无')}\n"
                f"约束：{', '.join(constraints) if constraints else '无'}"
            )
        normalized_latest_intent = _normalize_text(latest_intent)
        return f"## SceneIntent\n{normalized_latest_intent}" if normalized_latest_intent else None
    normalized_scene_intent = _normalize_text(scene_intent_data)
    return f"## SceneIntent\n{normalized_scene_intent}" if normalized_scene_intent else None


def _render_style_control_prompt(book: Book) -> Optional[str]:
    golden_snippets = getattr(book, 'golden_snippets', None) or []
    style_blacklist = getattr(book, 'style_blacklist', None) or []

    if isinstance(golden_snippets, list):
        golden_snippets = [s for s in golden_snippets if s]
    else:
        golden_snippets = []

    if isinstance(style_blacklist, list):
        style_blacklist = [s for s in style_blacklist if s]
    else:
        style_blacklist = []

    if not golden_snippets and not style_blacklist:
        return None

    sections = []

    if golden_snippets:
        snippets_text = "\n\n".join(golden_snippets)
        sections.append(
            "### [表情] 必须模仿的文风基准（黄金锚点）：\n"
            "请仔细分析以下片段的**句式长短、信息密度、克制的情绪张力以及修辞手法**。\n"
            "你接下来的扩写，必须在咬字和语感上无限逼近这段文字的质感：\n"
            f"{snippets_text}"
        )

    if style_blacklist:
        blacklist_text = "、".join(style_blacklist)
        sections.append(
            "### [表情] 绝对禁止触发的黑名单词库（通电铁丝网）：\n"
            "由于 LLM 存在滥用烂俗网文词汇的倾向，以下词汇/句式已被原作者拉入黑名单。\n"
            "**若在生成文本中触发以下任意一词，系统将判定生成彻底失败：**\n"
            f"{blacklist_text}"
        )

    if sections:
        return (
            "[特级文风走廊协议：防御大模型均值回归]\n"
            "为了防止文风漂移，你必须绝对服从以下\"一正一反\"的文风控制准则：\n\n"
            + "\n\n".join(sections)
        )
    return None


# ========================================================================
# 新增：冰山模型 - Subconscious 层 Prompt
# ========================================================================

def build_subconscious_prompt(
    chapter: Chapter,
    beat: dict,
    scene_intent: dict,
    entities: list,
) -> tuple[str, str]:
    """
    构建潜意识层提示词。
    
    职责：生成 POV 角色的内心独白，为后续 Prose 生成提供情感锚点。
    
    设计原则：
    - 50-100 字第一人称内心独白
    - 无需华丽辞藻，专注感官直觉
    - 回答三个核心问题：
      1. "我现在感觉如何？"
      2. "环境里最刺眼的是什么？"
      3. "我接下来的本能反应是什么？"
    
    Args:
        chapter: 章节实体
        beat: Beat 数据字典
        scene_intent: Scene Intent 分析结果（目标/风险/约束）
        entities: 角色实体列表（用于提取 POV 角色特征）
    
    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
    """
    beat_data = beat if isinstance(beat, dict) else {}
    pov_character = _normalize_text(beat_data.get("pov_character"), "我")
    entry_state = _normalize_text(beat_data.get("entry_state"), "")
    location = _normalize_text(beat_data.get("location"), "当前场景")
    
    # 提取 POV 角色的基础特征
    pov_traits = ""
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.name == pov_character:
            if character.static_prompt:
                pov_traits = character.static_prompt
            break
    
    # Scene Intent 信息
    intent_goal = _normalize_text(scene_intent.get("goal"), beat_data.get("summary", ""))
    intent_stakes = _normalize_text(scene_intent.get("stakes"), "")
    
    system_prompt = f"""你是{chapter.chapter_name or '本章'}中角色【{pov_character}】的潜意识。

你的任务是生成一段50-100字的内心独白，代表角色在当前场景下的即时感官直觉。

【核心要求】
1. **第一人称视角**：必须是{ pov_character }的内心独白，用"我"开头
2. **感官直觉**：专注回答三个问题：
   - 我现在感觉如何？（情绪、身体反应）
   - 环境里最刺眼/最异常的是什么？（视觉、听觉、触觉、气味）
   - 我接下来的本能反应是什么？（直觉、冲动、下意识动作）
3. **简洁直接**：无需华丽辞藻，像_raw_的意识流，不要文学修饰
4. **长度限制**：严格控制在50-100个汉字之间

【禁止事项】
- 禁止解释背景设定
- 禁止预告未来剧情
- 禁止使用第三人称描述
- 禁止超过100字"""

    user_prompt = f"""请生成【{pov_character}】在当前场景下的内心独白。

【切入状态】
{entry_state}

【当前场景】
{location}

【场景目标】
{intent_goal}

【失败风险】
{intent_stakes if intent_stakes else "暂无特定风险"}

【角色特征】
{pov_traits if pov_traits else "普通角色，无特殊设定"}

请直接输出内心独白（50-100字），不要任何解释或标题。"""

    return system_prompt, user_prompt


# ========================================================================
# 新增：冰山模型 - Prose Draft 层 Prompt
# ========================================================================

def build_prose_draft_prompt(
    chapter: Chapter,
    book: Book,
    beat: dict,
    scene_intent: dict,
    subconscious_thought: str,
    previous_tail: str,
    target_words: int,
) -> tuple[str, str]:
    """
    构建沉浸式正文生成提示词。
    
    职责：基于潜意识独白和前文尾巴，生成连贯的小说正文。
    
    设计原则：
    - **极简输入**：只传入 subconscious_thought、场景环境、previous_tail
    - **严禁传入**：red_lines、exit_state、庞大的世界观设定
    - **沉浸式续写**：让模型专注于动作和对话的自然流动
    - **Rolling Prefix**：接收前一个 Beat 的末尾 300 字符作为语气衔接
    
    Args:
        chapter: 章节实体
        book: 书籍实体
        beat: Beat 数据字典
        scene_intent: Scene Intent 分析结果
        subconscious_thought: 来自 subconscious 层的内心独白
        previous_tail: 前一个 Beat 的末尾文本（Rolling Prefix，约300字符）
        target_words: 目标字数
    
    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
    """
    beat_data = beat if isinstance(beat, dict) else {}
    
    # 基础信息
    pov_character = _normalize_text(beat_data.get("pov_character"), "我")
    location = _normalize_text(beat_data.get("location"), "")
    beat_summary = _normalize_text(beat_data.get("summary"))
    
    # Scene Intent
    intent_goal = _normalize_text(scene_intent.get("goal"), beat_summary)
    intent_constraints = _normalize_text_list(scene_intent.get("constraints"))
    
    # 节奏控制
    pacing_type = beat_data.get("pacing_type", "Medium")
    pacing_instructions = {
        "Fast": "多用短句、动词，减少修饰语。强调动作的紧凑衔接，营造紧张感或速度感。",
        "Medium": "平衡长短句，叙事节奏平稳。交替使用动作描写与心理/环境描写。",
        "Slow": "多用长句、感官细节描写。强调氛围渲染与内心独白，放慢叙事速度。",
    }
    pacing_instruction = pacing_instructions.get(pacing_type, pacing_instructions["Medium"])
    
    # 文风控制（黄金锚点 + 黑名单）
    style_control = _render_style_control_prompt(book)
    
    # Rolling Prefix 上下文
    continuity_section = ""
    if previous_tail:
        continuity_section = f"""【前文尾巴 - 必须无缝衔接】
{previous_tail}

**关键要求**：
- 第一句话必须紧接上文尾巴的语气、节奏和动作状态
- 禁止任何突兀的时间/空间跳跃
- 禁止使用"与此同时"、"就在这时"等转场词
- 通过环境细节或角色反应自然过渡"""
    
    system_prompt = f"""你是专业小说写手。请根据提供的潜意识独白，沉浸式续写小说正文。

## 【核心任务】
将角色的内心独白转化为具象化的动作、对话和环境描写。

## 【叙事原则】
1. **单一视角锁定**：绝对锁定在【{pov_character}】的感官范围内
2. **动作即性格**：通过角色的动作选择展现性格，不要直接解释
3. **环境即情绪**：让环境描写映射角色的心理状态
4. **对话即冲突**：对话推动剧情，每句台词都要有目的

## 【节奏控制 ({pacing_type})】
{pacing_instruction}

## 【反AI味协议 - 必须遵守】
1. **禁止设定倾倒**：不要在动作中打断解释世界观
2. **禁止预告片旁白**：严禁"命运的齿轮"、"时代的洪流"这类虚词
3. **禁止形容词堆砌**：一个名词前最多一个修饰语
4. **Show, Don't Tell**：直接描写物理反应，不要总结情绪
5. **短句制造紧张**：危机时刻用少于10个字的短句，甚至词组片段

{style_control if style_control else ''}

## 【续写要求】
- 目标字数：约 {target_words} 字（允许适度超出，完整性优先）
- 只输出正文，不要解释
- 段落之间用双换行符（\\n\\n）分隔
- 禁止使用 Markdown 格式

{continuity_section if continuity_section else ''}"""

    user_prompt = f"""请根据以下信息续写小说正文：

【POV角色】
{pov_character}

【当前场景】
{location if location else "未指定具体地点"}

【场景目标】
{intent_goal}

【角色潜意识独白 - 情感锚点】
{subconscious_thought}

【约束条件】
{chr(10).join(intent_constraints) if intent_constraints else "- 无特殊约束"}

{accumulated_section}

请直接输出小说正文，从前文尾巴的自然延续开始写起。"""

    return system_prompt, user_prompt


# ========================================================================
# 兼容性保留：原有的 Draft Prompt 函数
# ========================================================================

def build_draft_agent_prompt(
    chapter: Chapter,
    book: Book,
    entities: list,
    relationships: list,
    word_count: int,
    previous_summary: str = None,
    relevant_memories: list = None,
    beat: dict = None,
    scene_intent: dict = None,
    hook_contexts: list = None,
    locations: list = None,
    anchor_pov: str = None,
):
    """
    【兼容性保留】构建主笔 Agent (Draft Agent) 的提示词，负责初稿创作。

    警告：此函数为旧版实现，输入包含大量约束条件（red_lines、exit_state、世界观）。
    新项目请使用 build_subconscious_prompt + build_prose_draft_prompt 组合。

    核心任务：根据章节大纲生成符合角色设定和关系约束的初稿。
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None

    style_control_prompt = _render_style_control_prompt(book)

    map_activity_range = getattr(chapter, "map_activity_range", None)
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

    tone_instruction = (
        getattr(chapter, "tone", None)
        or getattr(book, "tone", None)
        or "整体基调保持与章节冲突和人物状态一致。"
    )
    beat_data = beat if isinstance(beat, dict) else {}
    beat_summary = _normalize_text(beat_data.get("summary"))
    beat_action_summary = _normalize_text(beat_data.get("action_summary"), beat_summary)
    entry_state = _normalize_text(beat_data.get("entry_state"), f"承接上文并切入：{beat_summary[:40]}" if beat_summary else "承接上文并切入当前节拍。")
    exit_state = _normalize_text(beat_data.get("exit_state"), f"停在本节拍收束点：{beat_action_summary[:40]}" if beat_action_summary else "停在当前节拍收束状态，不越界推进。")
    red_lines = _normalize_text_list(beat_data.get("red_lines"))
    if not red_lines:
        red_lines = ["不得越过本节拍 exit_state 指向的剧情停点"]
    boundary_constraints_prompt = _render_boundary_constraints(entry_state, exit_state, red_lines)

    anchor_pov_protocol = None
    if anchor_pov:
        anchor_pov_protocol = f"""## 绝对锚点视界与动作接续协议
1. **单一摄影机法则**：你的文字必须像VR游戏一样，绝对锁定在【{anchor_pov}】的大脑中。只能描写他可见、可听、可触之事。严禁开启上帝视角跨越空间。
2. **直接动作起手**：第一句话必须严格基于 `entry_state` 的物理姿态或环境状态开始。禁止凭空回顾上文。
3. **毒性词库硬拦截**：禁止使用任何破坏连续性的时间/空间转场副词作为段落起手。
   - ❌ 绝对禁用："与此同时"、"此时"、"画面一转"、"殊不知"、"在另一边"、"而在这时"。
   - ✅ 正确做法：利用环境音、光线变化或角色的动作反应自然过渡。"""

    worldbuilding_instruction = (
        beat_data.get("worldbuilding_instruction")
        or getattr(chapter, "worldbuilding_instruction", None)
        or getattr(book, "worldbuilding_instruction", None)
    )
    worldbuilding_prompt = f"## 世界构建指令\n{worldbuilding_instruction}" if worldbuilding_instruction else None

    prev_summary_prompt = f"## 前情提要\n{previous_summary}" if previous_summary else None

    memories_prompt = None
    if relevant_memories:
        memories_text = "\n".join([f"- {m.chunk_text}" for m in relevant_memories])
        memories_prompt = f"## 相关记忆/伏笔（RAG）\n{memories_text}"

    scene_intent_data = scene_intent if isinstance(scene_intent, dict) else (
        getattr(chapter, "scene_intent", None)
        or getattr(chapter, "scene_intent_data", None)
        or getattr(chapter, "scene_intents", None)
    )
    scene_intent_prompt = _render_scene_intent_prompt(scene_intent_data)

    static_states = []
    dynamic_states = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
            if character.dynamic_state:
                dynamic_states.append(f"【{character.name}】{character.dynamic_state}")
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")

    system_prompt = f"""{global_sys_prompt}

{worldview_prompt if worldview_prompt else ''}

{style_control_prompt if style_control_prompt else ''}

{final_map_prompt if final_map_prompt else ''}

{prev_summary_prompt if prev_summary_prompt else ''}

{memories_prompt if memories_prompt else ''}

## 基调
{tone_instruction}

{worldbuilding_prompt if worldbuilding_prompt else ''}

{scene_intent_prompt if scene_intent_prompt else ''}

## 角色静态设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色动态状态
{chr(10).join(dynamic_states) if dynamic_states else '暂无动态状态'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

{boundary_constraints_prompt}

## 【字数与内容完整性建议】
★ 目标字数：约 {word_count} 字 (允许根据剧情需要适度超出)
★ 优先级说明：请优先保证本节拍的剧情完整性、情感铺垫和动作细节。如果为了把故事讲好、讲透，导致字数超出预期，是完全可以接受的。切勿为了压缩字数而牺牲关键细节！

{anchor_pov_protocol if anchor_pov_protocol else ''}

## 🛑 危机递进与物理预警法则 (Escalation & Sensory Bridge Protocol)

在处理"日常平静状态"向"突发危机/激烈动作"转换的剧情点时，**绝对禁止从 0 直接跳到 100**。必须通过局部的微观物理变化来建立情绪的压迫感。

### ❌ 绝对禁止的转场方式：
1. **禁用偷懒的声明式过渡句**：严禁使用"这种宁静在下一秒被打破"、"突然"、"就在这时"、"毫无征兆地"作为段落的开头。
2. **禁止瞬间爆发**：禁止上一句话还在写微风和月光，下一句话立刻变成导弹爆炸。

### ✅ 必须执行的三段式危机爬升（Rule of Three）：
当剧变即将发生时，你的文字必须放慢速度，拆解为以下三个层次：
1. **微弱的异常（Anomaly）**：危机到来前的一两秒，先写极其细微的物理异样。（如：水杯里不自然的波纹、空气中突然刺耳的高频静电音、飞虫的惊落，气压气味的变化）。
2. **角色的错愕（Disconnect）**：主角的第一反应不应该是立刻明白发生了战争，而是短暂的疑惑或误判（如：以为是机器故障、以为是错觉），目光顺着异常看过去。
3. **彻底的爆发（Impact）**：在极度的安静或错愕中，真正的灾难或动作才以最猛烈的具象化形态砸在主角脸上。

## 🛑 海明威极致叙事与反AI味协议（最高优先级约束）

在扩写时，你的文字必须像手术刀一样干净利落，充满高密度的画面感。一旦触发以下"AI味"特征，将被系统判定为不及格：

### ❌ 绝对禁止（触发即失败）：
1. **禁止设定倾倒（Info-dumping）**：绝不准在动作或紧张情节发生时，打断节奏去大段解释世界观名词（如解释某个阶级、某种武器的背景）。让世界观自然消融在物理环境和对话中。
2. **禁止预告片式说教旁白**：严禁出现"命运的齿轮开始转动"、"时代的洪流"、"他此时还不知道自己将卷入怎样的旋涡"、"一场改变世界格局的战争开始了"这类上帝视角的虚词和评价词。主角只关注眼前的生死！
3. **禁止"紫壶文风（Purple Prose）"与形容词堆砌**：一个名词前最多只能有一个修饰语。绝对禁止诸如"廉价的、生锈的、过滤不彻底的空气"这类连环定语。做减法！

### ✅ 必须执行的句式编排：
1. **极致短句与碎镜式排版**：在面对危机爆发（如防空警报骤响、爆炸、遇袭）时，必须大量使用短句（字数少于10个字），甚至使用只有主谓结构的词组片段，并频繁使用回车键单独换行，以制造呼吸急促的压迫感。
   - *反面示例*：突然，一种毫无征兆的悸动从脚下的金属地板深处传了过来，那是一种低频的、足以引起内脏共鸣的颤栗。
   - *正面示例*：地板深处传来悸动。一种低频的颤栗。足以引起内脏共鸣。
2. **行为视角的局限性**：主角拥有强烈的认知局限。如果主角是底层劳工，他不会去思考"防线被饱和式轰炸瓦解"，他只会感受到"头顶的混凝土砸了下来，灰尘堵住了喉咙"。
3. **冰山理论（Show, Don't Tell）**：不要总结情绪（如"他感到无比绝望"），直接描写物理反应（如"汗水流进眼睛带来火辣辣的刺痛，他死死咬住发抖的牙关"）。

## 🛑 原住民视角与设定名词脱敏协议（In-Universe Protocol）

在使用设定集中的专有名词（如特定的机甲名、势力、术语）时，必须绝对摒弃"百科全书式的科普"，采取"原住民盲视原则"。

### ❌ 绝对禁止的名词出场方式：
1. **禁止"定语贴标签"**：严禁出现 `[等级/定语] + [名词]` 直接贴脸的句式。
   - *反面典型*："那是苏璃驾驶的A级机甲苍穹。" / "作为基因劣质者的底层劳工…"
2. **禁止突兀的说明**：不要在动作进行中突然停下来解释这个名词的来历、参数或社会地位。如果你必须要让读者知道它的特殊性，请通过**角色的反应、对话或系统UI的反馈**来侧面展现。

### ✅ 必须执行的名词出场方式：
1. **冰山式抛出（脱敏态）**：直接以代称或裸词出现，假装读者已经认识它。
   - *正面典型*："启动第二阶段防御方案。"白霆的声音低沉而冷静，"让'红月'待命。"（利用对话极其自然地抛出名字，绝不加多余解释）。
2. **先有形，后有名**：如果一台机甲首次登场，先写它造成的物理压迫感或视觉特征（如：巨大的阴影遮蔽了穹顶、液态核心在搏动），最后再通过角色的意识流或战术面板的锁定信息自然带出它的名字。
3. **常识词免检（豁免名录）**：对于具有现实认知基础的"软科幻复合词"（如：相位干扰弹、高周波震动刃、全息隐匿涂层），请直接当作日常用品写出，作者和读者都有常识，**绝对不要停下来解释它们是什么。**

## 核心规则
1. 严格遵循章节大纲进行创作
2. 保持角色性格和互动方式的连贯性
3. 根据角色关系约束调整互动氛围
4. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等
5. 生成内容应尽可能符合上述字数建议
6. 段落之间请使用双换行符（\\n\\n）分隔，以确保排版清晰。
7. 严禁使用 Markdown 格式（如加粗、斜体、列表等），仅输出纯文本。"""
    action_summary = (
        beat_action_summary
        or getattr(chapter, "action_summary", None)
        or beat_summary
        or chapter.outline_text
        or "围绕本段冲突推进关键动作。"
    )
    hook_text = beat_data.get("hook") or getattr(chapter, "hook", None) or getattr(chapter, "opening_hook", None)
    normalized_hooks = []
    if isinstance(hook_contexts, list):
        for item in hook_contexts:
            if isinstance(item, dict):
                hook_id = str(item.get("hook_id") or item.get("ledger_key") or "").strip()
                content = str(item.get("content") or "").strip()
                if content:
                    normalized_hooks.append({"hook_id": hook_id, "content": content})
            elif item:
                normalized_hooks.append({"hook_id": "", "content": str(item).strip()})
    action_summary_prompt = f"【动作摘要】\n{action_summary}"
    hook_prompt = f"【开篇钩子】\n{hook_text}" if hook_text else None
    ledger_hooks_prompt = None
    if normalized_hooks:
        hook_lines = []
        for hook in normalized_hooks[:3]:
            if hook["hook_id"]:
                hook_lines.append(f"- {hook['hook_id']}: {hook['content']}")
            else:
                hook_lines.append(f"- {hook['content']}")
        ledger_hooks_prompt = f"【开放伏笔】\n{chr(10).join(hook_lines)}"
    user_prompt = f"""请根据以下章节大纲进行扩写:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
{action_summary_prompt}
{hook_prompt if hook_prompt else ''}
{ledger_hooks_prompt if ledger_hooks_prompt else ''}
【字数建议】约 {word_count} 字（内容完整性优先）

写作方法：
- Show, don't tell：优先通过动作、感官、对话与细节呈现情绪和信息，避免直接讲解。
- hook 自然注入：将钩子信息融入情境、冲突或悬念，不要生硬贴标签。
- 若存在开放伏笔，必须通过环境细节或角色动作自然植入，不要显式解释"这是伏笔"。

请直接输出小说正文，不需要任何额外说明或标记。请确保剧情完整连贯。"""
    return system_prompt, user_prompt


def build_chunk_draft_prompt(
    chapter: Chapter,
    book: Book,
    entities: list,
    relationships: list,
    beat: dict,
    scene_intent: dict,
    target_words: int,
    previous_chunks: list[str],
    previous_summary: str = None,
    relevant_memories: list = None,
    hook_contexts: list = None,
    context_beat_summaries: dict = None,
    locations: list = None,
    anchor_pov: str = None,
    sensory_translation_rule: str = None,
):
    """
    【兼容性保留】构建分段 Draft Prompt。
    
    警告：此函数为旧版实现，新项目请使用 build_prose_draft_prompt。
    """
    beat_data = beat if isinstance(beat, dict) else {}
    scene_intent_data = scene_intent if isinstance(scene_intent, dict) else {}
    beat_summary = _normalize_text(beat_data.get("summary"))
    beat_action_summary = _normalize_text(beat_data.get("action_summary"), beat_summary)
    entry_state = _normalize_text(beat_data.get("entry_state"), f"承接上文并切入：{beat_summary[:40]}" if beat_summary else "承接上文并切入当前节拍。")
    exit_state = _normalize_text(beat_data.get("exit_state"), f"停在本节拍收束点：{beat_action_summary[:40]}" if beat_action_summary else "停在当前节拍收束状态，不越界推进。")
    red_lines = _normalize_text_list(beat_data.get("red_lines"))
    if not red_lines:
        red_lines = ["不得越过本节拍 exit_state 指向的剧情停点"]
    chunk_boundary_section = (
        "【Chunk 边界约束（剧情完整性优先）】\n"
        f"- 切入状态 entry_state：{entry_state}\n"
        f"- 目标收束状态 exit_state：{exit_state}\n"
        f"- 绝对禁忌 red_lines：{'；'.join(red_lines)}\n"
        "- 请平滑过渡至 exit_state，确保本节拍内的事件和冲突已完整闭环。\n"
        f"- 此段落必须严格锁定在【{beat_data.get('pov_character', '未指定')}】的第一/第三人称有限视角！"
    )
    intent_constraints = _normalize_text_list(scene_intent_data.get("constraints"))

    # Extract pacing_type and define instructions
    pacing_type = beat_data.get("pacing_type", "Medium")
    pacing_instructions = {
        "Fast": "多用短句、动词，减少修饰语。强调动作的紧凑衔接，营造紧张感或速度感。避免过长的心理描写或静态环境描写。",
        "Medium": "平衡长短句，叙事节奏平稳。交替使用动作描写与心理/环境描写，推动情节稳步发展。",
        "Slow": "多用长句、感官细节描写（视觉、听觉、嗅觉等）。强调氛围渲染与内心独白，放慢叙事速度，通过细节堆叠增强沉浸感。",
    }
    pacing_instruction = pacing_instructions.get(pacing_type, pacing_instructions["Medium"])
    pacing_section = f"【节奏与句式控制 (Pacing: {pacing_type})】\n{pacing_instruction}"

    system_prompt, user_prompt = build_draft_agent_prompt(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=target_words,
        previous_summary=previous_summary,
        relevant_memories=relevant_memories,
        beat=beat_data,
        scene_intent=scene_intent_data,
        hook_contexts=hook_contexts,
        locations=locations,
        anchor_pov=anchor_pov,
    )
    
    if sensory_translation_rule:
        sensory_constraint = f"## 【最高优先级约束：感官转化法则】\n{sensory_translation_rule}"
        system_prompt = f"{sensory_constraint}\n\n{system_prompt}"
    
    continuity_section = ""
    if previous_chunks:
        continuity_text = "\n\n".join(previous_chunks[-2:])
        continuity_section = f"【连贯性参考（最近已生成内容）】\n{continuity_text}"
    else:
        context_parts = []
        if context_beat_summaries:
            if context_beat_summaries.get('prev'):
                context_parts.append(f"前一节拍梗概：{context_beat_summaries['prev']}")
            if context_beat_summaries.get('next'):
                context_parts.append(f"后一节拍梗概：{context_beat_summaries['next']}")
        
        if context_parts:
            continuity_section = "【上下文情节参考】\n" + "\n".join(context_parts) + "\n请根据上下文梗概，确保本段落的开头和结尾能与前后情节自然衔接。"
        else:
            continuity_section = "【连贯性参考】\n暂无已生成内容"

    chunk_user_prompt = f"""{user_prompt}

【当前 Story Beat】
位置：{beat_data.get("position", 1)}
BeatID：{_normalize_text(beat_data.get("beat_id"))}
摘要：{beat_summary}
动作摘要：{beat_action_summary}
场景：{_normalize_text(beat_data.get("location"), "未指定")}
视角角色：{_normalize_text(beat_data.get("pov_character"), "未指定")}
建议字数：{target_words}

{chunk_boundary_section}

【Scene Intent】
标签：{_normalize_text(scene_intent_data.get("intent_label"), "推进剧情")}
目标：{_normalize_text(scene_intent_data.get("goal"), "推进剧情")}
风险：{_normalize_text(scene_intent_data.get("stakes"), "无")}
约束：{", ".join(intent_constraints) if intent_constraints else "无"}

{continuity_section}

{pacing_section}

请只输出当前 beat 对应的正文 chunk，不要重复前文，不要输出解释。"""
    return system_prompt, chunk_user_prompt


# ========================================================================
# V2.5 Cognitive Streaming - 增强版 Prose Draft Prompt
# ========================================================================

def build_prose_draft_prompt_v25(
    chapter: Chapter,
    book: Book,
    beat: dict,
    scene_intent: dict,
    subconscious_thought: str,
    previous_tail: str,
    target_words: int,
    physical_state_lock: str,
    current_emotional_state: str,
    # ========================================
    # NEW PARAMETERS for V2.5+
    # ========================================
    accumulated_summary: str = "",
    relational_state_lock: str = "",
    red_lines: Optional[list[str]] = None,
    # ========================================
) -> tuple[str, str]:
    """
    V2.5+ 认知流式生成 - 增强版正文生成提示词（关系感知版）
    
    新增特性：
    - **物理边界锁定 (Physical State Lock)**：绝对物理状态约束
    - **情绪暂存器 (Emotional Scratchpad)**：动态心理状态
    - **宏观剧情累加器 (Accumulated Summary)**：跨 Beat 剧情记忆
    - **关系状态锁 (Relational State Lock)**：防止人物关系错乱
    - **红线约束 (Red Lines)**：最高优先级边界限制
    
    约束传播公式:
    $$Prompt_{effective} = Prompt_{base} \oplus Constraints_{red\_lines} \oplus State_{relational}$$
    """
    beat_data = beat if isinstance(beat, dict) else {}
    
    pov_character = _normalize_text(beat_data.get("pov_character"), "我")
    location = _normalize_text(beat_data.get("location"), "")
    beat_summary = _normalize_text(beat_data.get("summary"))
    
    intent_goal = _normalize_text(scene_intent.get("goal"), beat_summary)
    intent_constraints = _normalize_text_list(scene_intent.get("constraints"))
    
    pacing_type = beat_data.get("pacing_type", "Medium")
    pacing_instructions = {
        "Fast": "多用短句、动词，减少修饰语。强调动作的紧凑衔接，营造紧张感或速度感。",
        "Medium": "平衡长短句，叙事节奏平稳。交替使用动作描写与心理/环境描写。",
        "Slow": "多用长句、感官细节描写。强调氛围渲染与内心独白，放慢叙事速度。",
    }
    pacing_instruction = pacing_instructions.get(pacing_type, pacing_instructions["Medium"])
    
    style_control = _render_style_control_prompt(book)
    
    # ========================================
    # NEW: 红线约束区块（最高优先级）
    # ========================================
    red_lines_list = red_lines or _normalize_text_list(beat_data.get("red_lines"))
    red_lines_section = ""
    if red_lines_list:
        red_lines_text = "\n".join([f"  - {rl}" for rl in red_lines_list])
        red_lines_section = f"""## 【红线绝对约束 (Red Lines) - 最高优先级】
以下约束具有**绝对优先权**，任何情况下都不得违反：

{red_lines_text}

违规判定：
- 任何触碰红线的生成内容将被立即判定为无效
- 必须完全重写生成的 Beat，直到满足所有红线约束"""
    
    # ========================================
    # NEW: 在场角色与动态关系区块
    # ========================================
    relational_section = ""
    if relational_state_lock:
        relational_section = f"""## 【在场角色与动态关系 (Relational State)】
当前场景中角色之间的动态关系状态：

{relational_state_lock}

关系约束要求：
- 角色互动必须符合上述关系状态
- 禁止无逻辑的关系突变（如死敌突然友好）
- 关系演变必须是渐进的，有明确的事件驱动"""
    
    # ========================================
    # UPDATED: 前情累积摘要（紧贴 Rolling Prefix）
    # ========================================
    accumulated_section = ""
    if accumulated_summary:
        accumulated_section = f"""【前情累积摘要】
{accumulated_summary}

注：以上是对前文剧情的极简回顾，用于保持宏观剧情连贯性。"""
    
    continuity_section = ""
    if previous_tail:
        continuity_section = f"""【前文尾巴 - 必须无缝衔接】
{previous_tail}

关键要求：
- 第一句话必须紧接上文尾巴的语气、节奏和动作状态
- 禁止任何突兀的时间/空间跳跃
- 禁止使用"与此同时"、"就在这时"等转场词
- 通过环境细节或角色反应自然过渡"""
    
    physical_lock_section = ""
    if physical_state_lock:
        physical_lock_section = f"""## 【物理边界锁定 (Physical State Lock) - 最高优先级】
你必须严格遵守主角当前的物理实体状态：{physical_state_lock}

绝对禁止的行为：
- 给主角凭空变出不属于该状态的能力或装备
- 肉身状态使用机械/机甲功能（如推进器、扫描器）
- 受伤状态下做出超出身体能力的动作
- 当前场景不存在的道具/武器突然出现在手中

检查清单：在生成每一个动作前，问自己："以当前的物理状态，这个动作可能吗？"""

    emotional_section = ""
    if current_emotional_state:
        emotional_section = f"""## 【当前心理状态 (Emotional Scratchpad)】
紧接上一幕，主角当前的心境是：{current_emotional_state}

情绪连贯性要求：
- 让后续的动作选择顺应这一心理惯性
- 情绪转变必须是渐进的，禁止突兀切换
- 通过身体反应和环境感知体现情绪，而非直接陈述"他感到..."""

    system_prompt = f"""你是专业小说写手。请根据提供的潜意识独白，沉浸式续写小说正文。

## 【核心任务】
将角色的内心独白转化为具象化的动作、对话和环境描写。

## 【叙事原则】
1. **单一视角锁定**：绝对锁定在【{pov_character}】的感官范围内
2. **动作即性格**：通过角色的动作选择展现性格，不要直接解释
3. **环境即情绪**：让环境描写映射角色的心理状态
4. **对话即冲突**：对话推动剧情，每句台词都要有目的

## 【节奏控制 ({pacing_type})】
{pacing_instruction}

{physical_lock_section}

{emotional_section}

{relational_section}

{red_lines_section}

## 【反AI味协议 - 必须遵守】
1. **禁止设定倾倒**：不要在动作中打断解释世界观
2. **禁止预告片旁白**：严禁"命运的齿轮"、"时代的洪流"这类虚词
3. **禁止形容词堆砌**：一个名词前最多一个修饰语
4. **Show, Don't Tell**：直接描写物理反应，不要总结情绪
5. **短句制造紧张**：危机时刻用少于10个字的短句，甚至词组片段

{style_control if style_control else ''}

## 【续写要求】
- 目标字数：约 {target_words} 字（允许适度超出，完整性优先）
- 只输出正文，不要解释
- 段落之间用双换行符分隔
- 禁止使用 Markdown 格式

{continuity_section if continuity_section else ''}"""

    user_prompt = f"""请根据以下信息续写小说正文：

【POV角色】
{pov_character}

【当前场景】
{location if location else "未指定具体地点"}

【场景目标】
{intent_goal}

【角色潜意识独白 - 情感锚点】
{subconscious_thought}

【约束条件】
{chr(10).join(intent_constraints) if intent_constraints else "- 无特殊约束"}

请直接输出小说正文，从前文尾巴的自然延续开始写起。"""

    return system_prompt, user_prompt


# ========================================================================
# V2.5 Cognitive Streaming - Fail-Fast 断言检查 Prompt
# ========================================================================

def build_micro_review_prompt(
    chunk_text: str,
    physical_state_lock: str,
    pov_character: str = "主角",
    # ========================================
    # NEW PARAMETERS
    # ========================================
    red_lines: Optional[list[str]] = None,
    relational_state_lock: str = "",
    character_static_prompts: Optional[dict[str, str]] = None,
) -> tuple[str, str]:
    """
    构建增强版 Fail-Fast 微审查提示词（V2.5+）。
    
    职责：极速检查生成的文本是否存在物理/逻辑/关系/OOC 硬伤。
    
    检查项扩展：
    1. 物理状态冲突（原有）
    2. 装备/能力幻觉（原有）
    3. 实体混淆（原有）
    4. 时空错乱（原有）
    5. **人物关系硬伤（NEW）**
    6. **OOC 行为检测（NEW）**
    7. **红线约束违反（NEW）**
    
    断言评分公式:
    $$Pass_{total} = \bigwedge_{i=1}^{n} Pass_{check_i} \land \neg Violate_{red\_lines}$$
    """
    
    # ========================================
    # NEW: 关系检查区块
    # ========================================
    relationship_check = ""
    if relational_state_lock:
        relationship_check = """
5. **人物关系硬伤检查**：
   - 死敌之间是否突然无逻辑地友好互动？
   - 信任度极低的角色是否突然共享敏感信息？
   - 角色互动是否符合当前关系状态描述？
   - 关系变化是否有明确的事件驱动？（禁止无逻辑突变）"""
    
    # ========================================
    # NEW: OOC 检查区块
    # ========================================
    ooc_check = ""
    if character_static_prompts:
        char_traits = "\n".join([f"     - {name}: {traits[:50]}..." 
                                for name, traits in character_static_prompts.items()])
        ooc_check = f"""
6. **OOC（偏离角色设定）检查**：
   角色静态设定参考：
{char_traits}
   
   检查项：
   - 角色的言行是否符合其性格设定？
   - 角色是否做出了违背其价值观的决定？
   - 角色的反应是否与其过往行为模式一致？
   - 是否出现了"性格突变"而无合理铺垫？"""
    
    # ========================================
    # NEW: 红线检查区块
    # ========================================
    red_lines_check = ""
    if red_lines:
        red_lines_text = "\n     - ".join([""] + list(red_lines))
        red_lines_check = f"""
7. **红线绝对约束检查**：
   以下红线绝对禁止触碰：{red_lines_text}
   
   判定标准：
   - 任何触碰红线的内容，无论其他检查是否通过，均判定为失败
   - 红线具有最高优先级"""
    
    system_prompt = f"""你是一个无情的物理、逻辑与角色一致性断言机（Assertion Checker）。

你的任务：快速检查小说片段是否发生了极其荒谬的物理、逻辑、关系或角色设定崩塌。

【检查项列表】
仔细寻找以下毁灭级幻觉：

1. **物理状态冲突**：肉身喷火、血肉之躯发射激光、徒手举起重物等
2. **装备/能力幻觉**：当前不存在的装备突然使用、未提及的能力突然出现
3. **实体混淆**：已被摧毁的物体重新出现、当前场景不存在的角色突然说话
4. **时空错乱**：时间线跳跃无逻辑、场景切换无过渡{relationship_check}{ooc_check}{red_lines_check}

【重要原则】
- 只查硬伤：文字不优美、修辞平淡、节奏拖沓 —— 这些都不属于错误
- 聚焦物理与逻辑：重点关注物理状态、逻辑连贯性、角色一致性
- 关系红线：人物关系的突变必须有明确的事件驱动
- OOC 红线：角色行为必须与其设定一致
- 不评文笔：不要评价写得是否生动、是否有文学性

【输出格式】
必须返回严格的 JSON 格式，不要有任何其他内容：
{{
  "pass_check": true/false,
  "reason": "如果为false，用一句话指出荒谬之处。如果为true则留空。",
  "failed_checks": ["列出失败的检查项编号，如['5', '7']"]
}}"""

    # 构建关系状态描述
    rel_state_section = ""
    if relational_state_lock:
        rel_state_section = f"""
【在场角色关系状态】
{relational_state_lock}"""

    # 构建红线描述
    red_lines_section = ""
    if red_lines:
        red_lines_section = f"""
【红线约束（最高优先级）】
{chr(10).join(['- ' + rl for rl in red_lines])}"""

    user_prompt = f"""【已知合法状态】
视角角色：{pov_character}
物理状态约束：{physical_state_lock if physical_state_lock else "无特殊约束"}{rel_state_section}{red_lines_section}

【待检片段】
{chunk_text}

请执行断言检查，返回 JSON 结果。"""

    return system_prompt, user_prompt


# ========================================================================
# V2.5 Cognitive Streaming - 情绪暂存器更新 Prompt
# ========================================================================

def build_emotional_update_prompt(
    chunk_text: str,
    previous_emotional_state: str,
    pov_character: str = "主角",
) -> tuple[str, str]:
    """
    构建情绪暂存器更新提示词。
    
    职责：基于刚生成的剧情，总结主角心理状态的微小演变。
    """
    system_prompt = """你是一个心理学观察员，专门追踪角色的心理状态演变。

你的任务：用极为简短的一句话（20字以内），总结角色经历了剧情后，心理状态发生了怎样的微小偏移或演变。

【核心要求】
1. **聚焦演变**：重点描述"变化"，而非静态状态
2. **因果明确**：体现"因为经历了 X，所以现在 Y"的逻辑
3. **字数限制**：严格控制在20个汉字以内
4. **第一人称感**：用角色的视角描述，而非外部评价

【优秀示例】
- "从之前的惊恐万分，转变为肾上腺素飙升后的疯狂求生欲。"
- "挫败感逐渐被冷静的计算所取代，开始寻找反击的机会。"
- "原本的犹豫在生死瞬间凝固为决绝的一搏。"
- "愤怒并未消退，而是沉淀为一种冰冷的专注。"

【禁止事项】
- 超过20字
- 静态描述（如"他很害怕"）
- 外部评价（如"这表现了他的勇敢"）
- 预告未来（如"他将面临更大的挑战"）

直接输出总结句，不要任何解释。"""

    user_prompt = f"""【角色】{pov_character}

【前情中心理状态】
{previous_emotional_state}

【刚刚发生的剧情】
{chunk_text[:500] if len(chunk_text) > 500 else chunk_text}

请总结心理状态演变（20字以内）："""

    return system_prompt, user_prompt


# ========================================================================
# V2.5+ Cognitive Streaming - 动态状态更新 Prompt（升级版）
# ========================================================================

def build_dynamic_state_update_prompt(
    chunk_text: str,
    previous_emotional_state: str,
    pov_character: str = "主角",
    relational_state_lock: str = "",
    beat_context: Optional[dict] = None,
) -> tuple[str, str]:
    """
    构建动态状态更新提示词（V2.5+ 升级版）。
    
    职责：基于刚生成的剧情，输出结构化状态更新：
    1. 新的心理状态 $E_{new}$
    2. 关系变化 $R_{delta}$  
    3. 剧情摘要 $S_{new}$
    
    输出格式：严格的 JSON，符合 DynamicStateUpdateResult 结构
    """
    beat_info = ""
    if beat_context:
        beat_summary = beat_context.get("summary", "")
        beat_location = beat_context.get("location", "")
        beat_pov = beat_context.get("pov_character", pov_character)
        beat_info = f"""
【当前 Beat 信息】
- 摘要：{beat_summary}
- 地点：{beat_location}
- 视角：{beat_pov}"""

    system_prompt = """你是一个专业的小说剧情分析器，负责追踪角色状态和关系演变。

你的任务：分析刚生成的剧情片段，提取三类信息并以严格的 JSON 格式返回。

【输出格式】
必须返回以下结构的 JSON，不要有任何其他内容：

```json
{
  "new_emotional_state": "角色当前的心理状态（20字以内，强调演变）",
  "relational_delta": "角色关系的变化（如'与盟友的信任度上升'，无变化则留空）",
  "beat_summary": "本段剧情的极简一句话摘要（用于宏观剧情累加）"
}
```

【分析要求】

1. **new_emotional_state ($E_{new}$)**：
   - 聚焦心理状态的变化，而非静态描述
   - 格式："从[之前状态]转变为[新状态]"
   - 字数限制：严格控制在 20 个汉字以内
   - 示例："从恐惧的僵直转变为肾上腺素驱动的求生本能"

2. **relational_delta ($R_{delta}$)**：
   - 分析角色间关系的微妙变化
   - 记录信任度、敌意、合作意愿等的升降
   - 如果无显著变化，返回空字符串
   - 示例："与李铭的互不信任加深，但共同利益维系着脆弱的同盟"

3. **beat_summary ($S_{new}$)**：
   - 将本段剧情压缩为一句话
   - 保留核心冲突和关键转折
   - 用于宏观剧情累加器，帮助后续 Beat 理解前文
   - 示例："楚言在废墟中遭遇敌方巡逻队，被迫躲入下水道"
   - 字数限制：40 字以内

【禁止事项】
- 禁止输出 JSON 以外的任何内容
- 禁止超过字数限制
- 禁止静态描述（如"他很害怕"）
- 禁止预告未来剧情"""

    user_prompt = f"""【POV角色】{pov_character}

【前情中心理状态】
{previous_emotional_state}

{beat_info}

【当前在场角色关系状态】
{relational_state_lock if relational_state_lock else "未指定"}

【刚刚生成的剧情片段】
{chunk_text[:800] if len(chunk_text) > 800 else chunk_text}

请分析上述剧情，返回 JSON 格式的状态更新结果。"""

    return system_prompt, user_prompt
