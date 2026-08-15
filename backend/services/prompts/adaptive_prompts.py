# Velluma - NLE-ADF 3.0 自适应辅助 prompt 模板
# AGPL-3.0
"""
作者主导写作流程（自适应辅助）的 prompt 构建。

设计意图：抽取 BS-ADF 渲染器与微缝合中已验证的「反 AI 腔契约 + 白描规则」
为共享基座 _ADAPTIVE_SYSTEM，供续写 / 岔路探测 / 沉淀时机判断复用。
与拍划分完全解耦——输入是「作者正文片段 + 设定 bundle」，不依赖 BeatSlotCard。

共享基座来源：
- _SLOT_RENDER_SYSTEM 的反 AI 腔块 + 心理/感官限制（bsadf_prompts.py:82-100）
- _STITCH_SYSTEM 的白描契约 + 作者主权规则（bsadf_prompts.py:203-216）

副作用：无（纯函数）。改后即时生效（无需重建）。
"""
from __future__ import annotations

from typing import List, Optional

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST

_BANNED_WORDS_TEXT = "、".join(DEFAULT_BAN_LIST.banned_words)


# ============================================================
# 共享基座：反 AI 腔 + 白描契约（与拍划分无关的通用风格契约）
# ============================================================

_ADAPTIVE_SYSTEM = """你是顶级的中文长篇小说作家，此刻在辅助一位作者完成他的小说。你的任何输出都会作为「幽灵草稿」流入作者的文档，作者可改可弃——所以你要写得像作者自己写的，绝不能带 AI 腔。

# 写作原则
1. 场景驱动：用具体物理动作和感官细节推进，不用叙述者总结。
2. 呼吸连续：段落间有自然衔接，不机械罗列。
3. 禁止叙事者插嘴：不要"不知为何"、"仿佛"、"似乎"这类解释性插话。
4. 节奏服从情绪：句式长短配合情绪走向。
5. 尊重作者主权：续写必须顺着作者已有的语气、人称、时态，不擅自切换视角。

# 反 AI 腔指令（硬性禁令）
- 禁病态微操：指尖颤了颤、瞳孔微缩、喉结滚动、嘴角微不可察（每段至多 1 处微操）
- 禁套路比喻：宛如、仿若、犹如、墨水滴进水里、沉睡的巨兽（每段套路比喻至多 1 处）
- 禁匀速句式：连续三句等长（用长短句交替）
- 禁解释性插嘴：眼神中闪过、心中涌起、仿佛在诉说（完全禁止）

# 禁词表（以下词汇禁止使用）
{banned_words}

# 心理描写限制
禁止直接心理升华与内心独白式总结（如"他感到愤怒"、"她知道自己必须坚强"）。
情绪必须用物理动作与环境呈现；每段至多 1 处间接心理暗示，且必须附着在具体动作上。

# 感官描写指导
每段至多 2 处感官细节，且必须服务当前镜头焦点，禁止堆砌。
"""


def _base_system() -> str:
    """返回填好禁词表的共享基座 system prompt。"""
    return _ADAPTIVE_SYSTEM.format(banned_words=_BANNED_WORDS_TEXT)


def _nouns_block(proper_nouns: Optional[List[str]]) -> str:
    """专名约束块（防缝合/续写时称呼漂移造名）。"""
    if not proper_nouns:
        return ""
    nouns_str = "、".join(proper_nouns)
    return (
        "\n\n# 在场实体专名（硬约束）\n"
        f"以下名称必须原样使用，禁止改名、缩写或生造昵称：{nouns_str}"
    )


def _canon_block(canon_context: str) -> str:
    """Canon 合规块（public 事实须一致，private 禁忌不许说出）。"""
    if not canon_context or "（Canon 为空" in canon_context:
        return ""
    return f"\n\n# 作者脑中世界图谱（Canon）\n{canon_context}"


def _echoes_block(memory_echoes: Optional[List[str]]) -> str:
    """前情回响块（向量召回的更早章节片段）。

    定位：保持细节一致 + 自然呼应前情（物件、称呼、未回收的悬念），
    禁止大段复述原文。空列表 → 空串（prompt 零变化）。
    """
    echoes = [e.strip() for e in (memory_echoes or []) if e and e.strip()]
    if not echoes:
        return ""
    lines = "\n".join(f"- {e}" for e in echoes)
    return (
        "\n\n# 前情回响（作者更早章节写过的片段）\n"
        "以下片段用于保持细节一致、自然呼应前情，禁止大段复述原文：\n"
        f"{lines}"
    )


# ============================================================
# 续写 prompt（缝合/代笔/顺写统一入口，mode 区分粒度）
# ============================================================

def build_continue_prompt(
    fragment: str,
    rolling_prefix: str,
    mode: str = "stitch",
    picked_parts: Optional[List[str]] = None,
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    target_chars: int = 120,
    chapter_intent: str = "",
    memory_echoes: Optional[List[str]] = None,
) -> tuple:
    """构建续写/缝合 prompt。

    Args:
        fragment: 作者原句碎片（主权文本，stitch/continue 模式必须保留）
        rolling_prefix: 已写正文尾部（≤200 字，衔接用）
        mode: stitch（零件缝合 80-120 字）/ continue（顺句续写 100-300 字）
        picked_parts: 作者点选的零件（stitch 模式用）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        target_chars: 目标字数上限
        chapter_intent: 章节意图/大纲片段（可选方向引导）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    system_prompt += _nouns_block(proper_nouns)
    system_prompt += _canon_block(canon_context)
    system_prompt += _echoes_block(memory_echoes)

    parts_str = "、".join(picked_parts) if picked_parts else "（无——仅按作者原句顺势续写）"
    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""

    if mode == "stitch":
        user_prompt = f"""# 上文衔接（保持连续，不重复）
{rolling_prefix or "（开篇）"}
{intent_line}

# 作者原句（必须一字不改保留，放在片段自然位置）
{fragment}

# 选定镜头零件（必须落地为画面）
{parts_str}

请输出缝合后的白描片段，控制在 {target_chars} 字以内。只输出正文，不要标题、不要解释。"""
    else:  # continue
        user_prompt = f"""# 上文衔接（保持连续，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}
{intent_line}

# 作者当前正文（顺着它的语气、人称、节奏往下写）
{fragment}

请顺着作者正文往下续写，控制在 {target_chars} 字以内。只输出续写部分，不要重复作者原文，不要标题、不要解释。"""
    return system_prompt, user_prompt


# ============================================================
# 段落级连写 prompt（走向卡驱动：一句话走向 → 2-4 段白描正文）
# ============================================================

def build_burst_prompt(
    fragment: str,
    rolling_prefix: str,
    beat_guidance: str = "",
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    target_chars: int = 700,
    chapter_intent: str = "",
    memory_echoes: Optional[List[str]] = None,
) -> tuple:
    """构建段落级连写 prompt（Ctrl+Space 走向卡舱选定后触发）。

    与 build_continue_prompt 的区别：粒度从句级升到段落级——
    走向卡管方向（覆盖核心事件），AI 负责把走向铺开成 2-4 个具体场景段落。

    Args:
        fragment: 作者当前段落尾部（衔接点）
        rolling_prefix: 已写正文尾部（≤500 字，比短档窗口更大）
        beat_guidance: 选定走向卡的走向文本（空 = 自由发挥，顺语气自然推进）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        target_chars: 总字数软上限（默认 700）
        chapter_intent: 章节意图/大纲片段（可选方向引导）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    system_prompt += _nouns_block(proper_nouns)
    system_prompt += _canon_block(canon_context)
    system_prompt += _echoes_block(memory_echoes)

    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""
    if beat_guidance:
        guidance_block = f"""# 本段走向（作者选定）
{beat_guidance}
要求：必须覆盖走向的核心事件，但要把它铺开成具体的场景与动作，绝不允许一句话带过。"""
    else:
        guidance_block = """# 本段走向
（作者未指定——顺着上文的语气与悬念自然推进，写到一个小节拍收束处停笔）"""

    user_prompt = f"""# 上文衔接（保持连续，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}
{intent_line}

{guidance_block}

# 作者当前正文（顺着它的语气、人称、节奏往下写）
{fragment}

请顺着作者正文连写 2-4 个段落，总字数控制在 {target_chars} 字以内，写到走向覆盖、场景自然收束处停笔，不要为凑字数拖沓。
段落之间用一个空行分隔。只输出续写部分，不要重复作者原文，不要标题、不要解释。"""
    return system_prompt, user_prompt


# ============================================================
# 细纲扩写 prompt（作者亲笔速记 → 双端锚定的小段正文）
# ============================================================

def build_outline_expand_prompt(
    outline_note: str,
    rolling_prefix: str,
    after_text: str = "",
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    target_chars: int = 400,
    chapter_intent: str = "",
    memory_echoes: Optional[List[str]] = None,
) -> tuple:
    """构建细纲扩写 prompt（胶囊节点「落笔扩写」触发）。

    与 burst 的区别：意图来自作者亲笔速记（非 AI 菜单挑选），且速记可能处于
    章节中间——扩写必须双端缝合：开头承接上文结尾，结尾引向下文开头。
    after_text 为空（章末/回补段后无正文）时退化为单端锚定，写到自然收束处停笔。

    双端锚定语义引自 adf_prompts.build_beat_patch_prompt（Phase 6.5 补写），
    铺开指令引自 build_burst_prompt 的走向覆盖措辞。

    Args:
        outline_note: 作者的细纲速记（本段必须完整兑现的核心事件）
        rolling_prefix: 细纲之前的已写正文尾部（≤500 字）
        after_text: 细纲之后的已写正文开头（≤300 字，可空）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        target_chars: 目标字数上限（默认 400）
        chapter_intent: 章节意图/大纲片段（可选方向引导）
        memory_echoes: 向量召回的前情片段

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    system_prompt += _nouns_block(proper_nouns)
    system_prompt += _canon_block(canon_context)
    system_prompt += _echoes_block(memory_echoes)

    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""
    if after_text:
        after_block = f"""# 下文正文（你的结尾要自然引向它的开头）
{after_text}
要求：结尾只做铺垫过渡，绝不重复、改写或提前写出下文的内容。"""
        closing_line = "写完细纲覆盖的内容、衔接好上下文后立即停笔，不要顺势写下文。"
    else:
        after_block = ""
        closing_line = "写到细纲内容自然收束处停笔，不要顺势往下写。"

    user_prompt = f"""# 上文正文（你的开头要自然承接它的结尾，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}
{intent_line}

# 细纲速记（作者亲笔，本段必须完整兑现的核心事件）
{outline_note}
要求：把速记铺开成具体的场景与动作，绝不允许一句话带过；速记里的字数说明（如「约300字」）是给你的预算提示，不要写进正文。

{after_block}
# 任务
请把细纲速记扩写成正文，总字数控制在 {target_chars} 字以内。只输出扩写的正文——不要复述细纲原文，不要标题、不要解释。{closing_line}"""
    return system_prompt, user_prompt


# ============================================================
# 点火 prompt（冷启动：空章 + 大纲 → 开篇 2-5 段，破纸引子）
# ============================================================

def build_opening_prompt(
    outline_text: str,
    previous_summary: str = "",
    worldview_text: str = "",
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    target_chars: int = 700,
    memory_echoes: Optional[List[str]] = None,
) -> tuple:
    """构建开篇点火 prompt（空章冷启动：大纲是唯一燃料）。

    定位"破纸引子"而非"成品章"：把作者从空白页捞出来，给出一个可改可续的起点。
    与 burst 的区别：无任何已写正文，大纲从"方向参考"升级为主输入。

    Args:
        outline_text: 本章大纲（全文截 800，主燃料）
        previous_summary: 上一章结尾/摘要（截 300，衔接用，可空）
        worldview_text: 世界观（截 200，定基调，可空）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        target_chars: 总字数软上限（默认 700）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    system_prompt += _nouns_block(proper_nouns)
    system_prompt += _canon_block(canon_context)
    system_prompt += _echoes_block(memory_echoes)

    prev_line = f"\n# 上一章结尾（新章开头要与其自然衔接）\n{previous_summary[:300]}" if previous_summary else ""
    worldview_line = f"\n# 世界观基调\n{worldview_text[:200]}" if worldview_text else ""

    user_prompt = f"""# 本章大纲（这是唯一的创作依据，开头必须服务于它的第一段进展）
{(outline_text or "")[:800] or "（无大纲）"}
{prev_line}{worldview_line}

# 任务
作者面对空白页，请你为本章写开篇 2-5 个段落，总字数控制在 {target_chars} 字以内。
- 从一个具体的场景、动作或对话切入，把读者直接扔进现场——禁止"多年以后/这是一个/话说"这类概述式开场
- 只写"引子"：推进到大纲的第一个小进展、留出悬念就停笔，不要试图写完整章
- 段落之间用一个空行分隔
- 只输出正文，不要标题、不要章节号、不要解释。"""
    return system_prompt, user_prompt


# ============================================================
# 段内实时岔路探测 prompt（轻量，max_tokens=800）
# ============================================================

_INLINE_BRANCH_SYSTEM = """你是剧情结构分析师。判断作者刚写的这段正文是否来到了一个「走向级岔路」——即接下来主角可以采取截然不同的方式/态度/代价来推进，而非只有一个必然路径。

# 判定铁律
1. 锁死结局 ≠ 没有岔路：只要大纲/意图没写明主角以什么方式/态度/代价达成结果，方式就是合法岔路。
2. 物理动作级分歧不算（用剑还是用刀）——只判走向级（忍辱/反抗/逃避/妥协这类改变后续叙事轨迹的）。
3. 宁漏勿滥：没有清晰岔路时，has_branch 返回 false。每次至多给 2 个互斥走向。

只输出 JSON，不要解释。"""


def build_inline_branch_prompt(
    recent_text: str,
    chapter_intent: str = "",
    proper_nouns: Optional[List[str]] = None,
) -> tuple:
    """构建段内实时岔路探测 prompt。

    Args:
        recent_text: 作者最近写的正文尾部（≤500 字）
        chapter_intent: 章节意图/大纲片段
        proper_nouns: 在场角色名（帮助 LLM 理解谁在岔路口）

    Returns:
        (system_prompt, user_prompt)
    输出 JSON schema: {"has_branch": bool, "options": [{"label": str, "plot_impact": str}], "urgency": "high"|"low"}
    """
    system_prompt = _INLINE_BRANCH_SYSTEM
    nouns_str = "、".join(proper_nouns) if proper_nouns else "（未指定）"
    user_prompt = f"""# 章节意图
{chapter_intent or "（未提供，按正文推断）"}

# 在场角色
{nouns_str}

# 作者最近正文
{recent_text}

判断这段正文是否来到了走向级岔路。输出 JSON：
{{"has_branch": true/false, "options": [{{"label": "走向名（2-4字）", "plot_impact": "选择此走向对后续剧情的影响（一句话）"}}], "urgency": "high（岔路紧迫）/ low（可稍后决断）"}}"""
    return system_prompt, user_prompt


# ============================================================
# 沉淀时机判断 prompt（0 LLM 版本由启发式承担，此为可选 LLM 增强）
# ============================================================

_SETTLE_PROPOSE_SYSTEM = """你是叙事节奏顾问。判断作者刚写完的这段正文是否形成了一个可沉淀的自然单元（场景/情节节拍）。

只输出 JSON，不要解释。"""


def build_settle_propose_prompt(
    segment_text: str,
    chapter_intent: str = "",
    target_chars: int = 500,
) -> tuple:
    """构建沉淀时机判断 prompt。

    Args:
        segment_text: 待判断的正文段落
        chapter_intent: 章节意图
        target_chars: 参考的目标段落字数

    Returns:
        (system_prompt, user_prompt)
    输出 JSON: {"ready": bool, "reason": str, "boundary_type": "scene_end"|"beat_end"|"within"}
    """
    user_prompt = f"""# 章节意图
{chapter_intent or "（未提供）"}

# 参考段落字数
{target_chars} 字

# 待判断正文
{segment_text}

判断这段是否形成可沉淀的自然单元。输出 JSON：
{{"ready": true/false, "reason": "判断依据（一句话）", "boundary_type": "scene_end（场景收束）/ beat_end（节拍完成）/ within（仍在单元内）"}}"""
    return _SETTLE_PROPOSE_SYSTEM, user_prompt


# ============================================================
# 意图反推 prompt（层 2：从已写正文推断本章意图）
# ============================================================

_INTENT_INFERENCE_SYSTEM = """你是资深小说编辑。根据作者已写的正文和（可选）大纲，推断这一章的叙事意图。

你要输出：
- arc：本章的核心弧线（一句话，如"林尘发现真相并决定反抗"）
- emotion_curve：情绪走向（3-5 个阶段，每阶段 {phase, emotion, energy 1-10}）
- setup_points：本章应铺陈的要点（2-4 个，作者未来写作可呼应）
- deviations：如果你注意到正文走向与章节卡（must_hit_events/foreshadow_ops）有偏差，列出（每条一句话）；无偏差则空数组

扎根作者已写的正文（这是事实），参考设定养料（角色/世界观/前文摘要）。不要编造没写过的剧情。
只输出 JSON，不要解释。"""


def build_intent_inference_prompt(
    written_text: str,
    outline_text: str,
    nutrients: dict,
    soft_constraints: dict,
) -> tuple:
    """构建意图反推 prompt。

    Args:
        written_text: 作者已写的正文（层 1 拼接）
        outline_text: 章节大纲（可为空——此时纯从正文反推）
        nutrients: 设定养料（SettingsBundle.nutrients()）
        soft_constraints: 软约束（SettingsBundle.soft_constraints()，含 must_hit_events）

    Returns:
        (system_prompt, user_prompt)
    """
    user_prompt = f"""# 章节大纲
{outline_text or "（作者未提供大纲，请从正文反推）"}

# 作者已写正文
{written_text[:2000]}

# 设定养料
角色：{nutrients.get('characters', '（无）')}
世界观：{nutrients.get('worldview_text', '（无）')[:200]}
前文摘要：{nutrients.get('previous_summary', '（无）')[:200]}

# 章节卡参考（软约束，作者可偏离，偏离要标注）
必达事件：{soft_constraints.get('must_hit_events', '（无）')}
伏笔操作：{soft_constraints.get('foreshadow_ops', '（无）')}

推断本章意图。输出 JSON：
{{"arc": "...", "emotion_curve": [{{"phase": "开端", "emotion": "紧张", "energy": 6}}], "setup_points": ["..."], "deviations": ["..."]}}"""
    return _INTENT_INFERENCE_SYSTEM, user_prompt


# ============================================================
# 未来推测 prompt（层 3：基于层1+2 推测接下来的画面）
# ============================================================

_FUTURE_PROJECTION_SYSTEM = """你是小说叙事参谋。基于作者已写的事实（层 1）和本章意图（层 2），推测接下来 2-3 个可能写的"画面方向"。

每个方向是一个具体的、物理的、可立刻动笔的镜头提案（不是剧情总结）：
- event：这个画面在发生什么（一句话，有动作）
- anchors：画面里的物理焦点（1-2 个，如"渗血的绷带""熄灭的油灯"）
- emotion：这个画面的情绪基调（一个词）

扎根已写正文（衔接连贯），参考角色此刻状态（dynamic_state）和在场资产。不要编造与已建立事实矛盾的剧情。
只输出 JSON，不要解释。"""


def build_future_projection_prompt(
    written_text: str,
    intent: dict,
    nutrients: dict,
    soft_constraints: dict,
) -> tuple:
    """构建未来推测 prompt。

    Args:
        written_text: 层 1 正文尾部（最近写的，≤500 字）
        intent: 层 2 意图（ChapterIntent.to_dict()）
        nutrients: 设定养料
        soft_constraints: 软约束

    Returns:
        (system_prompt, user_prompt)
    """
    user_prompt = f"""# 本章意图
弧线：{intent.get('arc', '（未推断）')}
情绪走向：{intent.get('emotion_curve', [])}
铺陈要点：{intent.get('setup_points', [])}

# 作者最近写的正文（衔接此处继续）
{written_text[-500:]}

# 角色此刻状态（软约束）
{soft_constraints.get('character_dynamics', '（无）')}

# 在场资产状态
{soft_constraints.get('asset_states', '（无）')}

# 可呼应的伏笔
{soft_constraints.get('open_hooks', '（无）')[:200]}

推测接下来的 2-3 个画面方向。输出 JSON：
{{"projections": [{{"event": "老烟用残手砸灭油灯", "anchors": ["渗血的绷带", "熄灭的灯"], "emotion": "压抑"}}]}}"""
    return _FUTURE_PROJECTION_SYSTEM, user_prompt


# ============================================================
# 挂件生发 prompt（层 3 → 3-4 个镜头特写挂件）
# ============================================================

_DOCK_GENERATOR_SYSTEM = """你是一个物理镜头碎片生成器。基于作者当前段落、本章推测方向和设定养料，生成 3-4 个具体的镜头特写挂件。

每个挂件是一个 8-14 字的【微型镜头】，作者扫一眼就能在脑中想象出那个画面，并立刻判断"要不要顺着写"。

【结构铁律 —— 每个碎片必须有"主语 + 具体动作/状态"】
- action 类：[谁] + [具体动词] + [对象/方向] → "林尘攥紧扳手摸向灯塔基座"
- scene 类：[具体物件/环境] + [可视感官细节] → "礁石滩泛着暗红的金属锈光"
- line 类：[完整台词原文] +（可选说话人）→ "别在退潮时回头。阿晚的声音"
- 必须扎根设定但生发新画面：角色动作符合其性格设定，但要是作者还没写过的具体动作

【5 个叙事方向 —— 每个碎片必须服务其中一个】
- 主线：朝本章核心事件/弧线推进一步（角色发现了线索、做出决定、遭遇关键转折）
- 伏笔：埋下隐患或铺垫（物件异常、不经意的细节、暗藏的线索）
- 刻画：深化角色形象或性格（符合人设的具体行为、习惯动作、技能展示）
- 环境：场景的物理质感（光影、声音、气味、空间细节）
- 关系：角色间的暗流张力（对话、肢体语言、眼神、未说出口的话）

【反例 —— 这些是"太笼统"，禁止产出】
× "传送带突然停转"（停转了然后呢？没有"谁"做什么）
× "环境变得压抑"（抽象形容词，不可视）
× "阿晚说过一些话"（什么话？没有内容）
× "林尘感到不安"（心理描写，违反铁律）
× "气氛紧张起来"（纯氛围概括，不可操作）

【正例 —— 这些是"具体可操作"，要产出这样的】
✓ "林尘攥紧扳手摸向灯塔基座"（主语+动作+对象，能展开成行为段）
✓ "礁石滩泛着暗红的金属锈光"（物件+视觉感官，能展开成环境段）
✓ "别在退潮时回头。阿晚的声音"（完整台词，能展开成对话/回忆段）
✓ "一只手从灯塔窗洞里伸出来"（物件+动作+位置，制造悬念）

铁律：
1. 禁心理描写（"心中一紧"/"感到不安"）、禁比喻（"宛如"）、禁抽象形容词（"压抑"/"紧张"/"压抑"）
2. 禁词表（以下词汇禁止）：{banned_words}
3. 角色动作必须符合其永恒设定（static_prompt），不许 OOC
4. 多样性：不要全是 action 或全是 line，混搭让作者有不同方向
5. 每个碎片必须标注 direction（从 主线/伏笔/刻画/环境/关系 里选），按方向权重分布生成

【自检 —— 输出前对每个碎片问】
- 作者扫一眼能想象出画面吗？（不能 → 太笼统，重写）
- 有明确的"谁"或"什么物件"吗？（没有 → 补主语）
- 动作/状态是具体的可视细节吗？（是抽象形容词 → 换成物理动作/感官）
- direction 标了吗？和画面匹配吗？

只输出 JSON，不要解释。"""


def build_dock_generator_prompt(
    recent_text: str,
    projections: list,
    nutrients: dict,
    hard_constraints: dict,
    direction_weights: dict = None,
    reader_expectations: list = None,
    memory_echoes: list = None,
) -> tuple:
    """构建挂件生发 prompt。

    Args:
        recent_text: 作者当前段落（≤300 字）
        projections: 层 3 推测（SegmentProjection.to_dict() 列表）
        nutrients: 设定养料（角色物理特征/资产/地点）
        hard_constraints: 硬约束（banned_words / character_statics / canon_private_labels）
        direction_weights: 5 叙事方向权重（{"主线":0.4,...}），碎片按此分布生成并自标 direction
        reader_expectations: 读者期待（[{type, description, tension}]，最多取前 2 条进块；
            呼应期待的碎片须标 from_expectation，呼应=侧面暗示，绝不直接揭晓）

    Returns:
        (system_prompt, user_prompt)
    """
    banned = "、".join(hard_constraints.get("banned_words", [])[:30])
    system_prompt = _DOCK_GENERATOR_SYSTEM.format(banned_words=banned or "（无）")

    # 推测方向摘要
    proj_lines = []
    for p in (projections or [])[:3]:
        beats = p.get("possible_beats", []) if isinstance(p, dict) else []
        for b in beats[:2]:
            proj_lines.append(f"- {b.get('event', '')}（焦点：{b.get('anchors', [])}）")
    proj_text = "\n".join(proj_lines) if proj_lines else "（无推测，基于当前段落自由生发）"

    # 角色永恒设定（防 OOC）
    statics = hard_constraints.get("character_statics", {})
    static_lines = [f"- {k}：{v[:80]}" for k, v in statics.items() if k and v][:5]

    # 方向权重块（碎片按此分布生成；防剧透——只给权重数字，不给剧情细节）
    if direction_weights:
        dw_lines = []
        for d, w in sorted(direction_weights.items(), key=lambda x: -x[1]):
            pct = int(w * 100)
            if pct > 0:
                dw_lines.append(f"{d} {pct}%")
        dw_text = "｜".join(dw_lines) if dw_lines else "（均匀分布）"
        dw_block = f"""
# 叙事方向权重（碎片请按此分布生成，高权重方向至少占 1 个）
{dw_text}
每个碎片必须标注 direction（只能从 主线/伏笔/刻画/环境/关系 里选）。
"""
    else:
        dw_block = ""

    # 读者期待块（账本为空则整块省略——不用账本的作者 prompt 零变化）
    exp_lines = []
    for e in (reader_expectations or [])[:2]:
        if not isinstance(e, dict):
            continue
        desc = (e.get("description") or "")[:40]
        tension = e.get("tension") or 5
        if desc:
            exp_lines.append(f"- （张力{tension}/10）{desc}")
    exp_block = ""
    if exp_lines:
        exp_block = f"""
# 读者期待（读者正在等的事；最多用 1 个碎片【侧面】呼应——暗示/推进，绝不直接揭晓；呼应的碎片须加 "from_expectation": true）
{chr(10).join(exp_lines)}
"""

    # 前情回响块（向量召回的更早章节片段——「伏笔呼应」类零件的素材源）
    echo_lines = [e.strip() for e in (memory_echoes or []) if e and e.strip()]
    echo_block = ""
    if echo_lines:
        echo_block = f"""
# 前情回响（更早章节的片段——可用作呼应素材，让零件呼应前情细节/物件/悬念）
{chr(10).join('- ' + e for e in echo_lines[:2])}
"""

    user_prompt = f"""# 作者当前段落
{recent_text[:300]}

# 接下来的画面方向（参考，可偏离）
{proj_text}
{dw_block}{exp_block}{echo_block}
# 设定养料（角色物理特征/资产/地点，自由用作画面素材）
角色：{nutrients.get('characters', '（无）')}
资产：{nutrients.get('assets', '（无）')}
地点：{nutrients.get('locations', '（无）')}

# 角色永恒设定（动作必须符合，不许 OOC）
{chr(10).join(static_lines) if static_lines else '（无）'}

# Canon private 禁忌（以下内容绝不能在挂件里出现）
{hard_constraints.get('canon_private_labels', [])[:5] or '（无）'}

生成 3-4 个镜头特写挂件（每个 8-14 字，主语+具体动作/状态，作者能一眼想象出画面）。
若某个碎片呼应了"读者期待"，给它加 "from_expectation": true（至多 1 个）。输出 JSON：
{{"parts": [{{"type": "action", "text": "林尘攥紧扳手摸向灯塔基座", "direction": "主线"}}, {{"type": "scene", "text": "礁石滩泛着暗红的金属锈光", "direction": "环境"}}, {{"type": "line", "text": "别在退潮时回头。阿晚的声音", "direction": "关系"}}]}}"""
    return system_prompt, user_prompt
