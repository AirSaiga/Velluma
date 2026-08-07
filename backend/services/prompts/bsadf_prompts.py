"""
BS-ADF 引擎 prompt 模板。

职责：定义 slot enrichment（4b）和 slot rendering（4c）的 prompt 构建函数
业务场景：Phase 4b enrich_slots、Phase 4c render_slot_to_segment
依赖项：backend.services.nlg.anti_ai_rules.DEFAULT_BAN_LIST（静态禁词表注入）

设计要点（DDE-BS 重构后）：
- 软性风格指令（禁词表、心理描写限制、感官描写指导）对每章恒定，
  已下沉为本模块的静态 system prompt 规则，不再逐卡复制进 BeatSlotCard。
- 槽位卡只承载物理硬契约（core_plot_event / key_anchors / text_carrier /
  outline_beat）与 DDE 剧情走向约束（branch_directive）。
- 与 adf_prompts.py 平行，复用其反 AI 腔指令文本（import 引用，不复制）。
"""
# Velluma - BS-ADF prompts
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import json
from typing import List

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST


# 静态禁词表（本章恒定禁令）：一次性常量注入渲染 system prompt，
# 替代旧版逐卡复制的 BeatSlotCard.ban_words 死字段
_BANNED_WORDS_TEXT = "、".join(DEFAULT_BAN_LIST.banned_words)


# ============================================================================
# Phase 4b：Slot Enrichment prompt
# ============================================================================

_SLOT_ENRICH_SYSTEM = """你是中文长篇小说的"分镜槽位扩写师"。给你稀疏的画面锚点种子词，扩展成丰富的物理动作/名词词列表。

硬约束：
1. 每个词必须是具体的物理名词或动词（如"砸下气动扳手"、"刺鼻柴油味"）。
2. 禁止抽象词（如"复杂"、"深邃"、"难以言喻"）。
3. 禁止心理词（如"心痛"、"愤怒"、"纠结"）—— 只写物理可观测的。
4. 每个词不超过 20 字。
5. 返回 3-6 个词。

输出 JSON：
{"key_anchors": ["词1", "词2", ...]}
"""


def build_slot_enrich_prompt(
    seed_anchors: List[str],
    shot_type: str,
    emotion_register: str,
    scene_entities: List[str],
):
    """构建槽位扩写 prompt。

    Args:
        seed_anchors: key_anchors 种子词（来自 must_use_terms）
        shot_type: 本段景别（wide/full/medium/close/macro）
        emotion_register: 本段情绪基调（如"入口"、"收束"）
        scene_entities: 场景内实体名列表（地点/资产名）

    Returns:
        (system_prompt, user_prompt) 元组
    """
    user_prompt = f"""本段景别：{shot_type}
本段情绪基调：{emotion_register}
场景内实体：{', '.join(scene_entities) if scene_entities else '（无）'}

锚点种子词（必须保留并扩展，至少包含这些）：{json.dumps(seed_anchors, ensure_ascii=False)}

请扩展为更丰富的物理动作词/名词列表。记住：只写具体、物理可观测的词。"""
    return _SLOT_ENRICH_SYSTEM, user_prompt


# ============================================================================
# Phase 4c：Slot Rendering prompt
# ============================================================================

_SLOT_RENDER_SYSTEM = """你是顶级的中文长篇小说作家。你的任务是把"槽位骨架"渲染成一段白描正文。

# 写作原则
1. 场景驱动：用具体物理动作和感官细节推进，不用叙述者总结。
2. 呼吸连续：段落间有自然衔接，不机械罗列。
3. 禁止叙事者插嘴：不要"不知为何"、"仿佛"、"似乎"这类解释性插话。
4. 节奏服从情绪：句式长短配合情绪走向。

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
每段至多 2 处感官细节，且必须服务当前镜头焦点（本段景别锁定的画面中心），禁止堆砌。

# 本段骨架（强约束区）
你必须让以下元素自然出现在正文里：
- 本段必须发生的剧情转折：{core_plot_event}
- 画面必现硬焦点：{key_anchors}
- 必须锚定的文本载体：{text_carrier}

# 本段大纲节拍（最高叙事约束）
{outline_beat}
本段正文必须推进上述大纲节拍，不得提前写后续节拍的内容，不得遗漏节拍的核心事件。

# 本段剧情走向约束（DDE 导演决策注入，强约束）
{branch_directive}

# 本段排他禁忌（DDE 决策注入；以下事件绝不能在正文中发生）
{negative_bounds}

# 渲染规则（骨架+留白）
你只能扩展上面骨架里的名词/动词为白描场景。可以添加连接性动作与有限感官细节（遵守上面的感官描写指导），但禁止添加骨架外的心理总结、抽象修饰、套路比喻。目标 {target_word_count} 字，{sentence_rhythm} 句式节奏。
"""


def build_slot_render_prompt(
    card,
    rolling_prefix: str,
    scene_setting_text: str,
    hard_constraints: str,
    emotion_curve_text: str,
    style_contract: str,
):
    """构建槽位渲染 prompt。

    Args:
        card: BeatSlotCard（含 core_plot_event/key_anchors/text_carrier/outline_beat/
            branch_directive/negative_bounds/target_word_count/sentence_rhythm）
        rolling_prefix: 前一段正文尾段（≤500 字，已 detox）
        scene_setting_text: 场景设定文本（来自 setting_resolver.build_scene_setting_text）
        hard_constraints: 硬约束块（name registry + knowledge constraints + state card）
        emotion_curve_text: 情绪曲线文本（来自 format_emotion_curve）
        style_contract: 文风契约（来自 _build_style_contract）

    Returns:
        (system_prompt, user_prompt) 元组
    """
    event_str = card.core_plot_event if card.core_plot_event else "（无强制剧情转折）"
    anchors_str = "、".join(card.key_anchors) if card.key_anchors else "（无强制锚点词）"
    carrier_str = card.text_carrier if card.text_carrier else "（无强制文本载体）"
    outline_str = card.outline_beat if getattr(card, "outline_beat", "") else "（未指定，按本段骨架自由发挥）"
    # branch_directive：DDE 剧情走向约束；空则显示无约束说明
    branch_str = (
        card.branch_directive
        if getattr(card, "branch_directive", "")
        else "（无——按大纲节拍与骨架顺势推进）"
    )
    # negative_bounds：DDE 决策注入的排他禁忌；空则显示"（无）"
    negative_bounds = getattr(card, "negative_bounds", []) or []
    negative_str = (
        "\n".join(f"- 禁止：{nb}" for nb in negative_bounds)
        if negative_bounds else "（无）"
    )

    system_prompt = _SLOT_RENDER_SYSTEM.format(
        banned_words=_BANNED_WORDS_TEXT,
        core_plot_event=event_str,
        key_anchors=anchors_str,
        text_carrier=carrier_str,
        outline_beat=outline_str,
        branch_directive=branch_str,
        negative_bounds=negative_str,
        target_word_count=card.target_word_count,
        sentence_rhythm=card.sentence_rhythm,
    )
    # 文风契约 + 情绪曲线附加到 system 末尾
    if style_contract:
        system_prompt += f"\n\n# 文风契约\n{style_contract}"
    if emotion_curve_text:
        system_prompt += f"\n\n# 本章情绪走向\n{emotion_curve_text}"

    user_prompt = f"""# 当前进度
第 {card.segment_index + 1} 段（{card.beat_type}），目标 {card.target_word_count} 字。
本段情绪：{card.emotion_register}（能量 {card.emotion_energy}/10）。

# 前文衔接
{rolling_prefix or "（本章开篇）"}

# 本章场景设定
{scene_setting_text or "（无额外设定）"}

{hard_constraints}

# 要求
写下一段正文。只输出正文，不要段标题、不要 markdown、不要解释。"""
    return system_prompt, user_prompt


# ============================================================================
# NLE-ADF 2.0：微缝合（stitch）prompt
# ============================================================================
# 与 4c 整段渲染的区别：缝合的"骨架主权"在作者——原句一字不改，
# AI 只补物理质感零件。轻量调用（REASONING_DISABLED + 小 max_tokens），
# 不挂降级状态机/字数闸门（深护栏在拍锁死与后处理时统一跑）。

_STITCH_SYSTEM = """你是一个物理镜头缝合引擎，不是文学作家。你的唯一任务：把作者的粗糙碎片与选定的镜头零件，缝合成 80~120 字的白描片段。

# 绝对禁令（违反即废品）
1. 禁心理描写与情绪副词（心中一紧、无比、复杂的眼神、仿佛、似乎、暗暗）。
2. 禁比喻句与夸张修饰（宛如、犹如、像……一样）。
3. 禁总结、升华、旁白式解释。
4. 严格白描：只写物理动作、空间位移、材质接触、环境声音。
5. 禁词表（以下词汇禁止出现）：{banned_words}

# 缝合规则
1. 作者原句必须完整保留、一字不改，放在片段的自然位置（通常开头）。
2. 选定的镜头零件必须落地为具体画面（融入动作，不罗列、不堆砌）。
3. 与上文衔接处不重复已写过的动作与意象。
4. 输出严格控制在 80~120 字。只输出正文：不要标题、不要解释、不要给全段加引号。"""


def build_stitch_prompt(
    fragment: str,
    picked_parts: List[str],
    rolling_prefix: str,
    core_plot_event: str = "",
    text_carrier: str = "",
    proper_nouns: List[str] = None,
):
    """构建微缝合 prompt。

    Args:
        fragment: 作者原句碎片（主权文本，一字不改保留）
        picked_parts: 作者点选的镜头零件（拍卡 key_anchors/text_carrier 或资产词）
        rolling_prefix: 当前拍已写正文尾部（≤200 字，衔接用）
        core_plot_event: 本拍导演意图（拍卡硬契约，方向约束而非内容指令）
        text_carrier: 本拍锚定对白（拍卡硬契约；作者未选时仅作背景方向）
        proper_nouns: 在场实体专名表（角色/资产名；防小调用称呼漂移造名）

    Returns:
        (system_prompt, user_prompt) 元组
    """
    parts_str = "、".join(picked_parts) if picked_parts else "（无——仅按作者原句顺势缝合）"
    direction_lines = []
    if core_plot_event:
        direction_lines.append(f"- 本拍导演意图（片段应朝它推进，但不要写满整拍）：{core_plot_event}")
    if text_carrier:
        direction_lines.append(f"- 本拍锚定对白（如与原句气场相合可自然带出）：{text_carrier}")
    direction_str = "\n".join(direction_lines) if direction_lines else "（无额外方向约束）"
    nouns_str = "、".join(proper_nouns) if proper_nouns else ""

    system_prompt = _STITCH_SYSTEM.format(banned_words=_BANNED_WORDS_TEXT)
    if nouns_str:
        system_prompt += (
            f"\n\n# 在场实体专名（硬约束）\n以下名称必须原样使用，"
            f"禁止改名、缩写或生造昵称：{nouns_str}"
        )
    user_prompt = f"""# 上文衔接（保持连续，不重复）
{rolling_prefix or "（本拍开篇）"}

# 本拍方向
{direction_str}

# 作者原句（必须一字不改保留）
{fragment}

# 选定镜头零件（必须落地为画面）
{parts_str}

请输出缝合后的 80~120 字白描片段。"""
    return system_prompt, user_prompt
