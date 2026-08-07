"""
BS-ADF Phase 4d：降级状态机（DOWNGRADE）。

职责：包装 render_slot_to_segment，最多重试 2 次，连续失败则降级回退到槽位卡
业务场景：Phase 4d，渲染失败时的安全网
主要功能：
  - render_with_downgrade：渲染+重试+降级三态状态机
  - 失败时产 DegradedBeat 句柄（供 /rerender-beat 恢复）
依赖项：slot_renderer.render_slot_to_segment、types

降级判据（方案书对齐）：AI 腔、前文重复、角色状态矛盾、LLM 调用错误。
槽位词覆盖（coverage）不再是硬失败——方案书把槽位词定位为"骨架+留白"
的扩展种子，模型改写语序/搭配属预期行为；覆盖缺失降级为软指标，
通过 SSE 事件的 coverage_missing 字段上报，不参与降级判定。

降级哲学（区别于 ADF 现有 gate 弃段）：
  ADF 弃段 = 丢弃 + DEGRADED 记录，章节带缺出版，无恢复路径
  BS-ADF 降级 = 保留槽位卡作可恢复句柄，作者可 /rerender-beat 单卡重渲染
"""
# Velluma - BS-ADF downgrade state machine
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import logging
from typing import Any, Callable, List, Optional, Tuple

from backend.services.observability.run_recorder import RunRecorder
from backend.services.workflows.adf.types import SegmentResult
from backend.services.workflows.adf.state_tracker import SceneStateCard
from backend.services.workflows.bsadf.types import BeatSlotCard, DegradedBeat
from backend.services.workflows.bsadf.slot_renderer import render_slot_to_segment

logger = logging.getLogger(__name__)

MAX_RENDER_ATTEMPTS = 2  # 最多重试次数（含首次）

# 字数硬闸门（0 LLM，不信任 prompt 里的"目标 N 字"软约束——实测段均超写
# 近 2 倍：目标 833 字实写 1400~2000）。首次超限带压缩反馈重试一次；
# 末次仍超限则句子边界硬截断到 TRUNCATE 比例并显式上报。
# ⚠ 末段（结局段）永不截断：截断优先砍掉的正是结尾内容（真实事故：
# 融合/逃离/收束被整段切掉，审计判结局缺失→补写锚丢失→死锁）。
# 结局完整性 > 字数预算，末段超限只重试 + 软标记上报。
WC_HARD_RATIO = 1.6    # 超过 target×1.6 判字数超标（触发压缩重试）
# ⚠ 截断上限必须 ≤ WC_HARD_RATIO：截断分支只在 wc > HARD 时进入，
# 若 TRUNCATE > HARD，_truncate_at_sentence 的 `len(text) <= limit` 会原样返回，
# 截断门空转且 word_truncated=True 误报（曾为 1.7 > 1.6 的倒置事故）。
# 取 1.5：留出压缩余量，确保任何进入此分支的文本都被实际缩短。
WC_TRUNCATE_RATIO = 1.5  # 末次超标时硬截断到 target×1.5（末段豁免）

# coverage 软指标 issue 的前缀（由 verify_slot_coverage 生成）
_COVERAGE_PREFIXES = ("动作词", "文本载体")


def _truncate_at_sentence(text: str, limit: int) -> str:
    """句子边界硬截断：在 limit 内找最后一个句末标点切断。

    找不到句末标点（极端长句）时退化为按字截断——半句可读性差，
    但字数硬闸门的优先级高于单句完整性（超限段会推高全章膨胀）。
    """
    if len(text) <= limit:
        return text
    cut = max(text.rfind(p, 0, limit) for p in ("。", "！", "？", "…"))
    if cut > 0:
        return text[: cut + 1]
    return text[:limit]


def _split_issues(issues: List[str]) -> Tuple[List[str], List[str]]:
    """把 issues 拆成（硬失败, coverage 软指标）两类。

    硬失败参与降级判定；coverage 软指标只上报、不拦截。
    """
    hard = [i for i in issues if not i.startswith(_COVERAGE_PREFIXES)]
    soft = [i for i in issues if i.startswith(_COVERAGE_PREFIXES)]
    return hard, soft


async def render_with_downgrade(
    card: BeatSlotCard,
    rolling_prefix: str,
    scene_setting_text: str,
    name_registry_block: str,
    state_card_block: str,
    emotion_curve_text: str,
    style_contract: str,
    genre: Optional[str] = None,
    recorder: Optional[RunRecorder] = None,
    prev_card_state: Optional[SceneStateCard] = None,
    progress_callback: Optional[Callable[[str, dict], Any]] = None,
    knowledge_constraints: Optional[List[str]] = None,
    presence_hint: str = "",
    canon_hint: str = "",
    is_final_segment: bool = False,
) -> Tuple[SegmentResult, BeatSlotCard, Optional[DegradedBeat]]:
    """渲染单张槽位卡，带降级回退。

    最多尝试 MAX_RENDER_ATTEMPTS 次。任一次 issues 为空即成功。
    连续失败则降级：card.status="degraded"、segment_text=""、产 DegradedBeat。

    Args:
        card: BeatSlotCard（in-place 更新 status/render_attempts）
        其余参数透传给 render_slot_to_segment
        progress_callback: async 回调，推 BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED 事件
        is_final_segment: 是否全章末段（结局段）。末段豁免字数硬截断——
            结局完整性优先于字数预算，超限只重试 + 软标记上报

    Returns:
        (SegmentResult, card, degraded_beat)
        - 成功：degraded_beat=None
        - 降级：degraded_beat 非 None，SegmentResult.text 为空
    """
    last_issues: List[str] = []

    for attempt in range(MAX_RENDER_ATTEMPTS):
        segment, card, issues = await render_slot_to_segment(
            card=card,
            rolling_prefix=rolling_prefix,
            scene_setting_text=scene_setting_text,
            name_registry_block=name_registry_block,
            state_card_block=state_card_block,
            emotion_curve_text=emotion_curve_text,
            style_contract=style_contract,
            genre=genre,
            recorder=recorder,
            prev_card_state=prev_card_state,
            # 第 2 次起把上一次的 issues 注入 prompt，让模型针对性补漏（不再盲重试）
            retry_feedback=last_issues or None,
            knowledge_constraints=knowledge_constraints,
            presence_hint=presence_hint,
            canon_hint=canon_hint,
        )
        last_issues = issues
        hard_issues, coverage_missing = _split_issues(issues)

        # 成功：无硬失败 issue 且文本非空（coverage 缺失仅作软指标上报）
        if not hard_issues and segment.text.strip():
            # 字数硬闸门（0 LLM）：超 target×WC_HARD_RATIO 先带压缩反馈重试；
            # 末次仍超标则句子边界硬截断到 target×WC_TRUNCATE_RATIO
            wc = len(segment.text)
            hard_limit = int(card.target_word_count * WC_HARD_RATIO)
            if wc > hard_limit and card.target_word_count > 0:
                if attempt < MAX_RENDER_ATTEMPTS - 1:
                    logger.info(
                        f"[render_with_downgrade] {card.beat_id} 字数 {wc} 超硬上限 "
                        f"{hard_limit}（目标 {card.target_word_count}），带压缩反馈重试"
                    )
                    last_issues = [
                        f"字数超标: 上次输出 {wc} 字，目标 {card.target_word_count} 字。"
                        f"请压缩到目标的 1.0~1.3 倍以内，删减重复修饰与冗余动作，"
                        f"槽位强制元素必须全部保留。"
                    ]
                    continue
                if is_final_segment:
                    # 结局段豁免截断：截断优先砍掉结尾内容（融合/收束被整段
                    # 切掉的真实事故），结局完整性 > 字数预算，软标记上报
                    word_truncated = False
                    word_overflow = True
                    logger.warning(
                        f"[render_with_downgrade] {card.beat_id} 末段字数 {wc} 超硬上限，"
                        f"结局段豁免截断，按软指标上报"
                    )
                else:
                    truncated_wc = int(card.target_word_count * WC_TRUNCATE_RATIO)
                    segment.text = _truncate_at_sentence(segment.text, truncated_wc)
                    word_truncated = True
                    word_overflow = False
                    logger.warning(
                        f"[render_with_downgrade] {card.beat_id} 字数 {wc} 末次仍超硬上限，"
                        f"句界硬截断到 {len(segment.text)} 字"
                    )
            else:
                word_truncated = False
                word_overflow = False
            card.status = "rendered"
            if coverage_missing:
                logger.info(
                    f"[render_with_downgrade] {card.beat_id} 渲染成功，"
                    f"槽位词未入文（软指标）：{coverage_missing}"
                )
            if progress_callback:
                try:
                    await progress_callback("BEAT_RENDER_PROGRESS", {
                        "beat_id": card.beat_id,
                        "segment_index": card.segment_index,
                        "status": "rendered",
                        "word_count": len(segment.text),
                        "coverage_missing": coverage_missing,
                        "word_truncated": word_truncated,
                        "word_overflow": word_overflow,
                    })
                except Exception as e:
                    logger.warning(f"[render_with_downgrade] progress_callback 失败：{e}")
            return (segment, card, None)

        logger.info(
            f"[render_with_downgrade] {card.beat_id} 第 {attempt + 1} 次渲染失败，"
            f"hard_issues={hard_issues}，coverage_missing={coverage_missing}"
        )

    # 连续失败 → 降级
    card.status = "degraded"
    # 判定降级原因（取最严重的）
    reason = _classify_downgrade_reason(last_issues)

    degraded_beat = DegradedBeat(
        beat_id=card.beat_id,
        segment_index=card.segment_index,
        reason=reason,
        attempts=MAX_RENDER_ATTEMPTS,
        card_snapshot=card,
    )

    empty_segment = SegmentResult(
        index=card.segment_index,
        text="",
        shot_type=card.shot_type,
        transition=card.transition,
    )

    if progress_callback:
        try:
            await progress_callback("BEAT_DOWNGRADED", {
                "beat_id": card.beat_id,
                "segment_index": card.segment_index,
                "reason": reason,
                "attempts": MAX_RENDER_ATTEMPTS,
                "coverage_missing": _split_issues(last_issues)[1],
            })
        except Exception as e:
            logger.warning(f"[render_with_downgrade] progress_callback 失败：{e}")

    return (empty_segment, card, degraded_beat)


def _classify_downgrade_reason(issues: List[str]) -> str:
    """从 issues 列表推断降级原因分类。

    优先级：llm_error > gate_fail（重复/状态矛盾）> coverage_fail > ai_smell（兜底）。
    注：coverage 已降为软指标（见 _split_issues），正常路径下 coverage_fail
    不可达，保留该分支仅为防御旧数据/异常组合。
    """
    issues_str = " ".join(issues).lower()
    if "llm_error" in issues_str:
        return "llm_error"
    if "empty_output" in issues_str:
        return "llm_error"
    if "segment_loop_duplicate" in issues_str:
        return "gate_fail"
    if "pov_absent" in issues_str:
        return "gate_fail"
    if any("已死亡" in i or "离场" in i for i in issues):
        return "gate_fail"
    if any("动作词" in i or "文本载体" in i for i in issues):
        return "coverage_fail"
    # density 触发但 wash 后仍超标、其他未分类问题
    return "ai_smell"
