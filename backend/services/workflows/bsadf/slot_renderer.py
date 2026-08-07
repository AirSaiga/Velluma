"""
BS-ADF 引擎 Phase 4c：槽位渲染器。

职责：把单张 BeatSlotCard 渲染成一段正文（SegmentResult），
     采用"骨架+留白"约束（卡里的 key_anchors/text_carrier
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

import jieba.posseg as pseg

from backend.services.llm import call_llm_with_usage
from backend.services.llm.client import REASONING_DISABLED
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
from backend.services.workflows.adf.segment_writer import _build_hard_constraints_block
from backend.services.prompts.bsadf_prompts import build_slot_render_prompt
from backend.services.workflows.bsadf.types import BeatSlotCard

logger = logging.getLogger(__name__)


def _phrase_covered(phrase: str, text: str) -> bool:
    """宽松命中判定：先整串子串匹配，失败后退化为实词匹配。

    设计意图：LLM 自然改写（"砸下气动扳手" → "抡起扳手砸下去"）语义上覆盖了
    锚点，但裸子串匹配会误判缺失。实词匹配抽取短语中的名词/动词/形容词
    （长度 ≥2），全部出现在正文中即算覆盖；抽不出实词的虚词短语维持严格子串。
    """
    if phrase in text:
        return True
    tokens = [
        w for w, flag in pseg.cut(phrase)
        if len(w) >= 2 and flag[0] in ("n", "v", "a")
    ]
    if not tokens:
        return False
    return all(t in text for t in tokens)


def verify_slot_coverage(text: str, card) -> Tuple[bool, List[str]]:
    """校验渲染产出的正文是否覆盖了槽位卡里的强制元素。

    匹配规则：每个强制元素先按整串子串匹配，失败则按实词（名/动/形，≥2 字）
    全部出现判定（见 _phrase_covered）。

    Args:
        text: 渲染产出的正文
        card: BeatSlotCard

    Returns:
        (passed: bool, missing: List[str]) —— passed=True 表示全覆盖；
        missing 是缺失的元素描述列表（如 "动作词: 气动扳手"）
    """
    missing = []
    # 校验 key_anchors（每个都必须出现）
    for anchor in card.key_anchors:
        if anchor and not _phrase_covered(anchor, text):
            missing.append(f"动作词: {anchor}")
    # 校验 text_carrier（非空时必须出现；载体是对白/铭文，保持严格子串。
    # 多项载体以 "；" 分隔——enforce_outline_entities 注入书名/引文时
    # 用的就是这个约定，逐项独立校验，互不牵连）
    if card.text_carrier:
        for part in card.text_carrier.split("；"):
            part = part.strip()
            if part and part not in text:
                missing.append(f"文本载体: {part}")
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
    retry_feedback: Optional[List[str]] = None,  # 上一次渲染的 issues（重试时注入 prompt）
    knowledge_constraints: Optional[List[str]] = None,  # 知识边界约束（≤8 条，对齐 ADF）
    presence_hint: str = "",  # 在场角色提示（对齐 ADF）
    canon_hint: str = "",  # Canon 事实 compact hint（对齐 ADF，注入 system）
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
        retry_feedback: 上一次渲染失败的 issues 列表（重试时作为修正指令注入
            user prompt，告诉模型上次缺了哪些强制元素；首次渲染传 None）
        knowledge_constraints: 知识边界约束行（ADF _build_knowledge_constraints 输出，
            private 节点/隐藏关系的否定约束，防"流光被抓"式幻觉）
        presence_hint: 在场角色提示（ADF _build_presence_hint 输出）
        canon_hint: Canon 事实 compact 块（ADF _build_compact_canon_hint 输出，
            追加到 system prompt，防设定漂移）

    Returns:
        (SegmentResult, card, issues) —— issues 是后处理发现的问题列表
        （coverage 缺失、闸门违规等；空列表=全通过）
    """
    card.render_attempts += 1
    issues: List[str] = []

    # 1. 构建 prompt
    # 硬约束区块复用 ADF 的组装（专名表 + 知识边界 + 在场提示 + 状态卡），
    # 与 ADF 写作期防线完全对齐（BS-ADF 此前只有专名表 + 状态卡两道）
    hard_constraints = _build_hard_constraints_block(
        registry_block=name_registry_block,
        knowledge_constraints=knowledge_constraints or [],
        presence_hint=presence_hint,
        state_card_block=state_card_block,
    )

    system_prompt, user_prompt = build_slot_render_prompt(
        card=card,
        rolling_prefix=rolling_prefix,
        scene_setting_text=scene_setting_text,
        hard_constraints=hard_constraints,
        emotion_curve_text=emotion_curve_text,
        style_contract=style_contract,
    )

    # Canon 事实注入 system（防设定漂移/幻觉，对齐 ADF 写作期注入）
    if canon_hint:
        system_prompt += f"\n\n{canon_hint}"

    # 重试反馈：把上一次缺失的强制元素显式列给模型，避免盲重试同样失败
    if retry_feedback:
        feedback_lines = "\n".join(f"- {issue}" for issue in retry_feedback)
        user_prompt += (
            "\n\n# 上次渲染未通过的校验（本次必须修正）\n"
            f"{feedback_lines}\n"
            "请确保上述强制元素逐字出现在正文中，且不要与前段重复、不要违背角色状态。"
        )

    # 字数后果提示（硬约束的事前声明）：模型对"会被截断"的后果比"目标 N 字"
    # 的软约束敏感得多。与 downgrade.py 的字数硬闸门（×1.6 重试 / ×1.7 截断）
    # 数值保持一致。
    if card.target_word_count > 0:
        user_prompt += (
            f"\n\n# 字数硬约束\n"
            f"本段正文必须控制在 {card.target_word_count} 字左右"
            f"（上限 {int(card.target_word_count * 1.3)} 字）。"
            f"超过 {int(card.target_word_count * 1.6)} 字将被程序强制要求重写，"
            f"仍超标会被机械截断（可能斩断场景结尾）。"
        )

    # 2. 调 LLM
    # reasoning_config=REASONING_DISABLED：显式关闭 thinking。creative 槽若
    # 配置为推理模型（如 deepseek-v4-pro），thinking 与 max_tokens 共享预算
    # ——思考吃掉预算会导致正文截断（段尾半句话）甚至空输出。必须传
    # REASONING_DISABLED——空 dict 会被 client 的 truthy 检查吞掉，等于没关。
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
                    reasoning_config=REASONING_DISABLED,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                max_tokens=4096,
                reasoning_config=REASONING_DISABLED,
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
                # 洗涤必须保住槽位强制元素，否则洗后 coverage 校验必挂
                # （text_carrier 按 "；" 拆分为独立项，与 verify 约定一致）
                must_keep=(
                    card.key_anchors
                    + ([p.strip() for p in card.text_carrier.split("；") if p.strip()]
                       if card.text_carrier else [])
                ),
            )
            text = wash_result.text
        except Exception as e:
            logger.warning(
                f"[render_slot_to_segment] {card.beat_id} wash 失败，回退 sanitize：{e}"
            )
            text = sanitize_segment(text)
    else:
        text = sanitize_segment(text)

    # 3d. coverage 软指标（方案书对齐：槽位词是扩展种子，缺失不判失败，
    #     仍以 issue 形式随返回值上报，由 downgrade 拆分为软指标）
    passed, missing = verify_slot_coverage(text, card)
    if not passed:
        issues.extend(missing)

    # 3e. 段级闸门：dedup（与 rolling_prefix 比）+ state 矛盾
    if segment_too_similar(text, rolling_prefix):
        issues.append("segment_loop_duplicate")
    gate_violations = check_segment_against_card(text, prev_card_state)
    issues.extend(gate_violations)

    # 3f. POV 名缺失闸门（0 LLM）：状态卡已知 POV 角色时，本段正文必须出现
    # 其名字至少一次——真实事故：渲染器用身份代称替换人名（整段"杂工推开
    # 气动门"，"林尘"零出现），状态卡随后把代称合法化扩散到后续段落。
    pov_name = getattr(prev_card_state, "pov", "") if prev_card_state is not None else ""
    if pov_name and pov_name not in text:
        issues.append(
            f"pov_absent: 本段正文未出现 POV 角色名「{pov_name}」"
            f"（禁止使用身份代称替换人名，如「杂工/工人/男人」）"
        )

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
