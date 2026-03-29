from typing import Optional

from backend.models import Chapter, Book
from backend.services.prompts.draft_prompts_utils import (
    _normalize_text,
    _normalize_text_list,
    _render_style_control_prompt,
    _format_entity_spatial_ledger,
)


def build_prose_draft_prompt(
    chapter: Chapter,
    book: Book,
    beat: dict,
    scene_intent: dict,
    subconscious_thought: str,
    previous_tail: str,
    target_words: int,
) -> tuple[str, str]:
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

请直接输出小说正文，从前文尾巴的自然延续开始写起。"""

    return system_prompt, user_prompt


def build_prose_draft_prompt_v25(
    chapter: Chapter,
    book: Book,
    beat: dict,
    scene_intent: dict,
    subconscious_thought: str,
    previous_tail: str,
    target_words: int,
    physical_state_lock: str = "",
    current_emotional_state: str = "",
    accumulated_summary: str = "",
    relational_state_lock: str = "",
    red_lines: Optional[list[str]] = None,
    entity_spatial_ledger: Optional[dict] = None,
    chapter_assets_schema: str = "",
    pov_perception_state: str = "",
    pov_character_profile: str = "",
    pov_aperture: Optional[str] = None,
    persistent_state_anchors: Optional[list[dict]] = None,
    is_first_beat: bool = True,
) -> tuple[str, str]:
    beat_data = beat if isinstance(beat, dict) else {}

    pov_character = _normalize_text(beat_data.get("pov_character"), "我")
    location = _normalize_text(beat_data.get("location"), "")
    beat_summary = _normalize_text(beat_data.get("summary"))

    pov_mode = beat_data.get("pov_mode", "single") or "single"
    pov_characters_list = beat_data.get("pov_characters", []) or []
    is_ensemble = pov_mode == "ensemble" and len(pov_characters_list) >= 2
    is_omniscient = pov_mode == "omniscient"

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

    relational_section = ""
    if relational_state_lock:
        relational_section = f"""## 【在场角色与动态关系 (Relational State)】
当前场景中角色之间的动态关系状态：

{relational_state_lock}

关系约束要求：
- 角色互动必须符合上述关系状态
- 禁止无逻辑的关系突变（如死敌突然友好）
- 关系演变必须是渐进的，有明确的事件驱动"""

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

    book_genre = getattr(book, 'genre', None) or "通用小说"
    tonality_lock_section = f"""
【世界观基调锁 (Tonality Lock) - 极高优先级】
- 本书的核心题材与世界观基调是：【{book_genre}】。
- 你必须严格遵守该题材固有的物理法则与常识，【绝对禁止】发生"题材污染（Genre Bleeding）"。
- 警告范例：如果是科幻文，严禁机甲产生修仙魔法或长出真实血肉内脏；如果是低武武侠，严禁出现现代热兵器或超自然法术。
- 允许使用生动、夸张的比喻来增强文本的画面张力（例如形容机器像"野兽"），但【绝不能】把比喻写成脱离当前世界观的真实物理异变。请死守当前世界的设定边界！
"""

    spatial_ledger_section = ""
    if entity_spatial_ledger:
        formatted_ledger = _format_entity_spatial_ledger(entity_spatial_ledger)
        if formatted_ledger:
            spatial_ledger_section = f"""## 【绝对物理与空间绑定锁 - P0级权重】
当前场景中，核心角色的绝对物理形态与空间从属关系如下，你绝不可篡改：
{formatted_ledger}

【防幻觉警报】：
1. 严禁发生"容器穿透"：如果角色被标记为处于载具/重型装甲内，其所有的对外界交互必须通过面板、操纵杆、受击震荡来体现，【绝对禁止】描写其肉身直接接触环境或徒手战斗。
2. 严禁凭空产生动作：如果角色处于限制状态（如昏迷、被缚），严禁生成其主动发起战术动作的描写。"""

    emotional_section = ""
    if current_emotional_state:
        emotional_section = f"""## 【当前心理状态 (Emotional Scratchpad)】
紧接上一幕，主角当前的心境是：{current_emotional_state}

情绪连贯性要求：
- 让后续的动作选择顺应这一心理惯性
- 情绪转变必须是渐进的，禁止突兀切换
- 通过身体反应和环境感知体现情绪，而非直接陈述"他感到..."""

    if is_ensemble or is_omniscient:
        chars_display = "、".join(pov_characters_list) if pov_characters_list else pov_character
        mode_label = "多角色共存(ensemble)" if is_ensemble else "全知(omniscient)"
        cognitive_aperture_section = f"""
【多角色视角系统 (Multi-POV System) - V3.6】
当前模式: {mode_label}
视角角色: {chars_display}

[核心指令]: 本 Beat 采用多视角叙事，必须遵循以下规则：
1. **摄像机游走**: 视角可在段落边界自由切换，每次切换需有自然过渡（动作/空间/时间）。
2. **角色均衡**: 每个角色（{chars_display}）至少获得一次内心切入，禁止某角色全程无内心独白。
3. **声音区分**: 不同角色的内心独白需体现各自语气/词汇/关注点，禁止同质化。
4. **戏剧反讽**: 充分利用"读者知道多角色想法但单角色不知"的张力，渲染信息不对称。
5. **段落标记**: 视角切换时，用行为动作（非括号标注）自然引导读者识别视角变换。
"""
    else:
        effective_pov_aperture = pov_aperture or beat_data.get("pov_aperture", "subjective_observation")
        if effective_pov_aperture not in ["internal_only", "subjective_observation", "systemic_sense"]:
            effective_pov_aperture = "subjective_observation"

        aperture_mode_descriptions = {
            "internal_only": f"仅限 {pov_character} 的内心与自我感知，强制屏蔽外部可见但不被注意的细节。",
            "subjective_observation": f"允许描写其他角色动作，但必须通过 {pov_character} 的认知/判断包裹。",
            "systemic_sense": f"允许全景感知，但在叙事上依然以 {pov_character} 为锚点（适用于高张力动作场景）。"
        }
        aperture_mode_desc = aperture_mode_descriptions.get(effective_pov_aperture, aperture_mode_descriptions["subjective_observation"])

        cognitive_aperture_section = f"""
【认知视角系统 (Cognitive Aperture System) - V3.5】
当前光圈: {effective_pov_aperture}
模式说明: {aperture_mode_desc}

[核心指令]: 你不必强制排除其他角色，但必须遵循"认知过滤法则"：
1. **视角锚定**: 所有的叙事必须以 {pov_character} 的感知为起点。
2. **动作包裹**: "其他角色的动作"不能独立存在，必须嵌套在视角角色的观察/反应中。
   - 错误示例 (上帝视角): "李四走到门口，捡起枪，开了火。"
   - 正确示例 (认知包裹): "{pov_character} 听到了门口的脚步声（感官输入），紧接着看到李四俯身捡起枪（视觉观察），这让{pov_character}背脊发凉（主观反应），这显然是场处决。"
3. **禁止上帝独白**: 严禁描写任何非视角角色的内心独白、想法或意图。
4. **感知边界**: 若当前光圈为 internal_only，{pov_character} 未注意到或无法感知的细节绝对禁止描写。
"""

    persistent_anchors_section = ""
    effective_anchors = persistent_state_anchors or beat_data.get("persistent_state_anchors", [])
    if effective_anchors:
        anchors_lines = []
        for anchor in effective_anchors:
            if isinstance(anchor, dict):
                anchor_type = anchor.get("anchor_type", "unknown")
                description = anchor.get("description", "")
                involved = anchor.get("involved_characters", [])
                if isinstance(involved, list):
                    involved_str = f" (涉及: {', '.join(involved)})" if involved else ""
                else:
                    involved_str = ""
                if description:
                    anchors_lines.append(f"- [{anchor_type}] {description}{involved_str}")

        if anchors_lines:
            anchors_text = "\n".join(anchors_lines)
            persistent_anchors_section = f"""
【持久状态锚点 (Persistent State Anchors) - V3.5】
以下状态必须在当前 Beat 中保持连贯，禁止突兀改变：
{anchors_text}

锚点约束：
- 情感基调必须渐进演变，禁止无逻辑的情绪突变
- 物理位置依附关系必须保持一致
- 未解决冲突必须在当前 Beat 中维持其未解决状态（除非本 Beat 明确解决它）
"""

    chapter_assets_schema_text = chapter_assets_schema if chapter_assets_schema else "（本章未定义特殊资产）"

    pov_perception_state_text = pov_perception_state if pov_perception_state else (physical_state_lock if physical_state_lock else "正常")

    book_genre = getattr(book, 'genre', '未指定') or '未指定'

    red_lines_list = red_lines or _normalize_text_list(beat_data.get("red_lines"))
    if red_lines_list:
        red_lines_text = "\n".join([f"- {rl}" for rl in red_lines_list])
    else:
        red_lines_text = "（无特殊红线）"

    world_snapshot_constraints = beat_data.get("_world_snapshot_constraints", "")
    if world_snapshot_constraints and is_first_beat:
        cross_chapter_lock_text = f"""
【跨章物理连续性锁 (Cross-Chapter Continuity Lock) - V3.5 P0级】
以下是上一章末尾的世界状态快照，你必须严格遵守其中的物理约束：

{world_snapshot_constraints}

⚠️ 强制规则：
1. Beat 1 的 entry_state 必须与上述「场景位置」和「角色状态」保持100%连续性
2. 严禁让角色产生"瞬移"或状态突变
3. 关键锚点必须在当前 Beat 中被处理或明确说明状态变化
"""
    else:
        cross_chapter_lock_text = ""

    previous_tail_text = previous_tail if previous_tail else "（章节开头，无前文）"

    system_prompt = f"""你是专精长文本渲染的专业小说家。你的任务是根据提供的最优潜意识，极其克制地沉浸式续写正文。

【锁1：核心资产体积锁 (Asset Schema Lock) - P0级特权】
请死死记住以下资产的物理体型与设定，严禁自行魔改其物理形态！
{chapter_assets_schema_text}
> 警告：严禁把重型机甲写成"钻入体内的纳米神经"、"吸附在皮肤上的液体战甲"或"外骨骼"！机甲就是巨大的钢铁造物！

【锁2：知觉与感官遮罩层 (Perception Masking)】
当前POV角色的状态为：【{pov_perception_state_text}】。
> 警告：如果该状态包含"昏迷/重伤/失去控制"，你【绝对禁止】描写该角色做出清醒、精准的主动战术动作（主动挥拳、精准射击、躲避、开口大叫等）。
该角色的一切动作只能是被动的：例如"被惯性抛飞"、"躯体不受控制地痉挛"、"在混沌中感知到震动"、"无意识的喘息"。必须写出命悬一线的巨物支配感！

【锁3：世界观基调锁 (Tonality Lock)】
本书基调：【{book_genre}】。
> 警告：绝不可发生题材污染。允许使用生动比喻（如"像野兽般咆哮"），但【严禁】把比喻当成物理现实写出来（如：机甲绝对不能长出真实的血肉、触手或骨齿；不能施展魔法光效）。

【锁4：大纲红线 (Red Lines) - 撞线即判废】
{red_lines_text}

{cross_chapter_lock_text}

## 【物理边界锁定】
你必须严格遵守主角当前的物理实体状态：{physical_state_lock if physical_state_lock else "未指定"}

## 【当前心理状态 (Emotional Scratchpad)】
紧接上一幕，主角当前的心境是：{current_emotional_state if current_emotional_state else "未指定"}

## 【在场角色与动态关系 (Relational State)】
{relational_state_lock if relational_state_lock else "（无特殊关系约束）"}

{cognitive_aperture_section}

{persistent_anchors_section}

## 【叙事原则】
1. 单一视角锁定：绝对锁定在【{pov_character}】的感官范围内
2. 动作即性格：通过角色的动作选择展现性格
3. 环境即情绪：让环境描写映射角色的心理状态
4. 对话即冲突：每句台词都要有目的

## 【POV角色核心设定】
{pov_character_profile if pov_character_profile else f"（{pov_character} 无额外设定）"}

## 【反AI味协议】
- 禁止设定倾倒（不要解释世界观设定）
- 禁止预告旁白（不要暗示后续剧情）
- 禁止形容词堆砌（用具体动作替代抽象描述）
- 摒弃一切华丽虚词，用具体、短促的动作展现张力

## 【续写要求】
- 目标字数：约 {target_words} 字（允许适度超出，完整性优先）
- 只输出正文，不要解释
- 段落之间用双换行符分隔
- 禁止使用 Markdown 格式
- 直接输出纯文本

【前文尾巴 - 必须无缝衔接】
{previous_tail_text}"""

    user_prompt = f"""请根据以下信息续写小说正文：

【POV角色】
{pov_character}

【当前场景】
{location if location else "未指定具体地点"}

【场景目标】
{intent_goal}

【角色最优潜意识（情感锚点）】
{subconscious_thought}

【本段剧情目标（Beat）】
{beat_summary if beat_summary else "推进剧情"}

【约束条件】
{chr(10).join(intent_constraints) if intent_constraints else "- 无特殊约束"}

【前情累积摘要】
{accumulated_summary if accumulated_summary else "（无前情摘要）"}

请衔接前文尾巴，以极具质感的画面描写和物理碰撞感输出正文。直接输出纯文本，禁用 Markdown 格式。"""

    return system_prompt, user_prompt
