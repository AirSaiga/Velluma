"""
BS-ADF Phase 4d：降级状态机（DOWNGRADE）。

职责：包装 render_slot_to_segment，最多重试 2 次，连续失败则降级回退到槽位卡
业务场景：Phase 4d，渲染失败时的安全网
主要功能：
  - render_with_downgrade：渲染+重试+降级三态状态机
  - 失败时产 DegradedBeat 句柄（供 /rerender-beat 恢复）
依赖项：slot_renderer.render_slot_to_segment、types

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
) -> Tuple[SegmentResult, BeatSlotCard, Optional[DegradedBeat]]:
    """渲染单张槽位卡，带降级回退。

    最多尝试 MAX_RENDER_ATTEMPTS 次。任一次 issues 为空即成功。
    连续失败则降级：card.status="degraded"、segment_text=""、产 DegradedBeat。

    Args:
        card: BeatSlotCard（in-place 更新 status/render_attempts）
        其余参数透传给 render_slot_to_segment
        progress_callback: async 回调，推 BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED 事件

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
        )
        last_issues = issues

        # 成功：issues 为空且文本非空
        if not issues and segment.text.strip():
            card.status = "rendered"
            if progress_callback:
                try:
                    await progress_callback("BEAT_RENDER_PROGRESS", {
                        "beat_id": card.beat_id,
                        "segment_index": card.segment_index,
                        "status": "rendered",
                        "word_count": len(segment.text),
                    })
                except Exception as e:
                    logger.warning(f"[render_with_downgrade] progress_callback 失败：{e}")
            return (segment, card, None)

        logger.info(
            f"[render_with_downgrade] {card.beat_id} 第 {attempt + 1} 次渲染失败，issues={issues}"
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
            })
        except Exception as e:
            logger.warning(f"[render_with_downgrade] progress_callback 失败：{e}")

    return (empty_segment, card, degraded_beat)


def _classify_downgrade_reason(issues: List[str]) -> str:
    """从 issues 列表推断降级原因分类。

    优先级：llm_error > gate_fail（重复/状态矛盾）> coverage_fail > ai_smell（兜底）。
    """
    issues_str = " ".join(issues).lower()
    if "llm_error" in issues_str:
        return "llm_error"
    if "empty_output" in issues_str:
        return "llm_error"
    if "segment_loop_duplicate" in issues_str:
        return "gate_fail"
    if any("已死亡" in i or "离场" in i for i in issues):
        return "gate_fail"
    if any("动作词" in i or "感官词" in i or "文本载体" in i for i in issues):
        return "coverage_fail"
    # density 触发但 wash 后仍超标、其他未分类问题
    return "ai_smell"
