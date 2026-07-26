"""
BS-ADF 引擎 Phase 4c：槽位渲染器。

职责：把单张 BeatSlotCard 渲染成一段正文（SegmentResult），
     采用"骨架+留白"约束（卡里的 anchor_actions/sensory_details/text_carrier
     作强骨架，LLM 只能在骨架上扩展白描，禁止心理升华）。

业务场景：Phase 4c —— 富化后的槽位卡 → 正文段
主要功能：
- render_slot_to_segment：单卡渲染（LLM + 反 AI 味后处理链 + 段级闸门 + coverage 校验）
- verify_slot_coverage：纯函数校验正文是否覆盖了卡里的强制元素

设计意图：
- 渲染器复用 ADF 反 AI 味链（preprocess/measure/sanitize/wash）和段级闸门
  （dedup_guard/state_tracker），但用独立 prompt（build_slot_render_prompt），
  不复用 build_forward_flow_prompt
- 渲染失败 graceful：返回空 SegmentResult + issues，不抛异常（上层 4d 降级追踪兜底）

依赖项：
- backend.services.llm.call_llm_with_usage（LLM 调用，返回 LLMResult，取 .content）
- backend.services.nlg（反 AI 味后处理链）
- backend.services.workflows.adf.dedup_guard / state_tracker（段级闸门）
- backend.services.prompts.bsadf_prompts.build_slot_render_prompt（独立 prompt）
- backend.services.observability.run_recorder.RunRecorder（计量）
"""
# Velluma - BS-ADF slot_renderer
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import logging
from typing import List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.nlg import (
    measure_ai_taste,
    preprocess_segment,
    sanitize_segment,
    wash_segment_if_too_ai,
)
from backend.services.workflows.adf.types import SegmentResult
from backend.services.workflows.adf.dedup_guard import segment_too_similar
from backend.services.workflows.adf.state_tracker import check_segment_against_card
from backend.services.prompts.bsadf_prompts import build_slot_render_prompt
from backend.services.workflows.bsadf.types import BeatSlotCard

logger = logging.getLogger(__name__)


def verify_slot_coverage(text: str, card) -> Tuple[bool, List[str]]:
    """校验渲染产出的正文是否覆盖了槽位卡里的强制元素。

    Args:
        text: 渲染产出的正文
        card: BeatSlotCard

    Returns:
        (passed: bool, missing: List[str]) —— passed=True 表示全覆盖；
        missing 是缺失的元素描述列表（如 "动作词: 气动扳手"）
    """
    missing = []
    # 校验 anchor_actions（每个都必须作为子串出现）
    for action in card.anchor_actions:
        if action and action not in text:
            missing.append(f"动作词: {action}")
    # 校验 sensory_details
    for sensory in card.sensory_details:
        if sensory and sensory not in text:
            missing.append(f"感官词: {sensory}")
    # 校验 text_carrier（非空时必须出现）
    if card.text_carrier and card.text_carrier not in text:
        missing.append(f"文本载体: {card.text_carrier}")
    return (len(missing) == 0, missing)


async def render_slot_to_segment(
    card: BeatSlotCard,
    rolling_prefix: str,
    scene_setting_text: str,
    name_registry_block: str,
    state_card_block: str,
    emotion_curve_text: str,
    style_contract: str,
    genre: Optional[str] = None,
    recorder: Optional[RunRecorder] = None,
    prev_card_state=None,  # SceneStateCard，用于闸门校验
) -> Tuple[SegmentResult, BeatSlotCard, List[str]]:
    """渲染单张槽位卡为一段正文。

    流程：
    1. 构建 prompt（build_slot_render_prompt）
    2. 调 LLM（recorder.record_call 模式）
    3. 后处理链：jieba 抽脂 → 测密度 → wash/sanitize → coverage 校验 → 闸门
    4. 返回 (SegmentResult, card, issues)

    Args:
        card: BeatSlotCard（in-place 更新 render_attempts）
        rolling_prefix: 前段尾段（≤500 字）
        scene_setting_text: 场景设定文本
        name_registry_block: 专名注册表 prompt 块
        state_card_block: 状态卡 prompt 块（card_to_prompt_block 输出）
        emotion_curve_text: 情绪曲线文本
        style_contract: 文风契约
        genre: 题材（jieba 白名单用）
        recorder: RunRecorder
        prev_card_state: 上一段状态卡（闸门校验用）

    Returns:
        (SegmentResult, card, issues) —— issues 是后处理发现的问题列表
        （coverage 缺失、闸门违规等；空列表=全通过）
    """
    card.render_attempts += 1
    issues: List[str] = []

    # 1. 构建 prompt
    hard_constraints = "# 本段硬约束\n"
    if name_registry_block:
        hard_constraints += name_registry_block + "\n"
    if state_card_block:
        hard_constraints += state_card_block + "\n"

    system_prompt, user_prompt = build_slot_render_prompt(
        card=card,
        rolling_prefix=rolling_prefix,
        scene_setting_text=scene_setting_text,
        hard_constraints=hard_constraints,
        emotion_curve_text=emotion_curve_text,
        style_contract=style_contract,
    )

    # 2. 调 LLM
    try:
        if recorder is not None:
            async with recorder.record_call(
                stage=f"bsadf.render.{card.beat_id}",
                model_slot="creative",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.7,
                    max_tokens=4096,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                max_tokens=4096,
            )
        # LLMResult 实际字段是 .content（不是 .text）
        text = result.content or ""
    except Exception as e:
        logger.warning(f"[render_slot_to_segment] {card.beat_id} LLM 调用失败：{e}")
        return (
            SegmentResult(
                index=card.segment_index,
                text="",
                shot_type=card.shot_type,
                transition=card.transition,
            ),
            card,
            [f"llm_error: {e}"],
        )

    if not text.strip():
        return (
            SegmentResult(
                index=card.segment_index,
                text="",
                shot_type=card.shot_type,
                transition=card.transition,
            ),
            card,
            ["empty_output"],
        )

    # 3. 后处理链
    # 3a. jieba 抽脂
    text = preprocess_segment(text, genre=genre)
    # 3b. 测密度
    density_report = measure_ai_taste(text)
    # 3c. wash 或 sanitize
    if density_report.triggered:
        try:
            wash_result = await wash_segment_if_too_ai(
                text,
                density_report,
                recorder=recorder,
                stage=f"bsadf.wash.{card.beat_id}",
            )
            text = wash_result.text
        except Exception as e:
            logger.warning(
                f"[render_slot_to_segment] {card.beat_id} wash 失败，回退 sanitize：{e}"
            )
            text = sanitize_segment(text)
    else:
        text = sanitize_segment(text)

    # 3d. coverage 校验（BS-ADF 专属）
    passed, missing = verify_slot_coverage(text, card)
    if not passed:
        issues.extend(missing)

    # 3e. 段级闸门：dedup（与 rolling_prefix 比）+ state 矛盾
    if segment_too_similar(text, rolling_prefix):
        issues.append("segment_loop_duplicate")
    gate_violations = check_segment_against_card(text, prev_card_state)
    issues.extend(gate_violations)

    # 4. 返回
    segment = SegmentResult(
        index=card.segment_index,
        text=text,
        emotion_register=card.emotion_register,
        landed_preconditions=card.landed_preconditions,
        shot_type=card.shot_type,
        transition=card.transition,
    )
    return segment, card, issues
