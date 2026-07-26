"""
BS-ADF 引擎 prompt 模板。

职责：定义 slot enrichment（4a）和 slot rendering（4c）的 prompt 构建函数
业务场景：Phase 4a enrich_slots、Phase 4c render_slot_to_segment
依赖项：无（纯字符串模板）

注意：与 adf_prompts.py 平行，复用其反 AI 腔指令文本（import 引用，不复制）。
"""
# Velluma - BS-ADF prompts
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import json
from typing import List


# ============================================================================
# Phase 4a：Slot Enrichment prompt
# ============================================================================

_SLOT_ENRICH_SYSTEM = """你是中文长篇小说的"分镜槽位扩写师"。给你稀疏的槽位种子词，扩展成丰富的物理动作词和感官词列表。

硬约束：
1. 每个词必须是具体的物理名词或动词（如"砸下气动扳手"、"刺鼻柴油味"）。
2. 禁止抽象词（如"复杂"、"深邃"、"难以言喻"）。
3. 禁止心理词（如"心痛"、"愤怒"、"纠结"）—— 只写物理可观测的。
4. 每个词不超过 20 字。
5. 每类返回 3-6 个词。

输出 JSON：
{"anchor_actions": ["词1", "词2", ...], "sensory_details": ["词1", "词2", ...]}
"""


def build_slot_enrich_prompt(
    seed_actions: List[str],
    seed_sensory: List[str],
    shot_type: str,
    emotion_register: str,
    scene_entities: List[str],
):
    """构建槽位扩写 prompt。

    Args:
        seed_actions: anchor_actions 种子词（来自 must_use_terms）
        seed_sensory: sensory_details 种子词（来自 locations/assets 名）
        shot_type: 本段景别（wide/full/medium/close/macro）
        emotion_register: 本段情绪基调（如"入口"、"收束"）
        scene_entities: 场景内实体名列表（地点/资产名）

    Returns:
        (system_prompt, user_prompt) 元组
    """
    user_prompt = f"""本段景别：{shot_type}
本段情绪基调：{emotion_register}
场景内实体：{', '.join(scene_entities) if scene_entities else '（无）'}

动作种子词（必须保留并扩展，至少包含这些）：{json.dumps(seed_actions, ensure_ascii=False)}
感官种子词（必须保留并扩展，至少包含这些）：{json.dumps(seed_sensory, ensure_ascii=False)}

请扩展为更丰富的物理动作词和感官词列表。记住：只写具体、物理可观测的词。"""
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

# 本段骨架（强约束区）
你必须让以下元素自然出现在正文里：
- 必须出现的动作词：{anchor_actions}
- 必须出现的感官词：{sensory_details}
- 必须锚定的文本载体：{text_carrier}
- 本段冲突触发：{conflict_trigger}

心理潜文本（指导你写，禁止直接写进正文）：{psych_subtext}

# 渲染规则（骨架+留白）
你只能扩展上面骨架里的名词/动词为白描场景。可以添加连接性动作与有限感官细节，但禁止添加骨架外的心理总结、抽象修饰、套路比喻。目标 {target_word_count} 字，{sentence_rhythm} 句式节奏。
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
        card: BeatSlotCard（含 anchor_actions/sensory_details/text_carrier/conflict_trigger/psych_subtext/target_word_count/sentence_rhythm/ban_words）
        rolling_prefix: 前一段正文尾段（≤500 字，已 detox）
        scene_setting_text: 场景设定文本（来自 setting_resolver.build_scene_setting_text）
        hard_constraints: 硬约束块（name registry + knowledge constraints + state card）
        emotion_curve_text: 情绪曲线文本（来自 format_emotion_curve）
        style_contract: 文风契约（来自 _build_style_contract）

    Returns:
        (system_prompt, user_prompt) 元组
    """
    actions_str = "、".join(card.anchor_actions) if card.anchor_actions else "（无强制动作词）"
    sensory_str = "、".join(card.sensory_details) if card.sensory_details else "（无强制感官词）"
    carrier_str = card.text_carrier if card.text_carrier else "（无强制文本载体）"
    conflict_str = card.conflict_trigger if card.conflict_trigger else "（无强制冲突触发）"
    psych_str = card.psych_subtext if card.psych_subtext else "用物理动作呈现情感，禁止心理升华。"

    system_prompt = _SLOT_RENDER_SYSTEM.format(
        anchor_actions=actions_str,
        sensory_details=sensory_str,
        text_carrier=carrier_str,
        conflict_trigger=conflict_str,
        psych_subtext=psych_str,
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
