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
