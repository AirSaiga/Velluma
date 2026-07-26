"""
BS-ADF Phase 4a：槽位卡生成（SLOT_BUILD）。

职责：把 ADF Phase 1-3 产出的 anchor + spine 派生为 List[BeatSlotCard]
业务场景：Phase 4a，纯算法（0 LLM）+ 可选 1× enrichment LLM（见 enrich_slots）
主要功能：
  - soft_assign_preconditions：把无序 preconditions 软分配到各段
  - shot_type/transition/rhythm 映射
  - emotion 采样
  - target_word_count 动态分摊
依赖项：ADF types、storyboard、anti_ai_rules

注意：本模块纯算法，enrich_slots（LLM 扩写）单独在 P1.4 加入。
"""
# Velluma - BS-ADF slot_builder
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import json
import logging
from typing import Any, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.bsadf_prompts import build_slot_enrich_prompt
from backend.services.workflows.adf.types import (
    ChapterClimax, Precondition, StoryContext,
)
from backend.services.workflows.adf.storyboard import plan_storyboard
from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
from backend.services.workflows.bsadf.types import BeatSlotCard

logger = logging.getLogger(__name__)

_MAX_WORD_LEN = 20  # enrichment 单词长度上限


# ============================================================================
# 映射函数（纯算法）
# ============================================================================

_SHOT_TO_BEAT_TYPE = {
    "wide": "ESTABLISH",
    "full": "ESTABLISH",
    "medium": "CONFRONT",
    "close": "CONFRONT",
    "macro": "CLIMACTIC",
}

_TRANSITION_TO_RHYTHM = {
    "cut": "SHORT_PUNCHY",
    "fade": "LAYERED",
    "push_in": "VARIED",
    "pull_out": "VARIED",
    "counter": "VARIED",
}


def shot_type_to_beat_type(shot_type: str) -> str:
    """storyboard shot_type → beat_type。"""
    return _SHOT_TO_BEAT_TYPE.get(shot_type, "CONFRONT")


def transition_to_rhythm(transition: str) -> str:
    """storyboard transition → sentence_rhythm。"""
    return _TRANSITION_TO_RHYTHM.get(transition, "VARIED")


def dynamic_spread(total_target: int, segment_index: int, total_segments: int) -> int:
    """把总字数目标均摊到单段，最小 300。"""
    per_segment = max(300, total_target // total_segments)
    return per_segment


# ============================================================================
# precondition 软分配
# ============================================================================

def soft_assign_preconditions(
    preconditions: List[Precondition],
    segment_index: int,
    progress: float,
    total_segments: int,
) -> List[Precondition]:
    """把无序 preconditions 软分配到当前段。

    策略：基于 min_landing_offset（前置字数门槛）判断该 PC 是否可能在本段落地。
    假设每段约 600 字均值，PC 的"建议最早段位"= offset // 600。
    """
    if not preconditions:
        return []
    result = []
    for pc in preconditions:
        earliest_segment = max(0, pc.min_landing_offset // 600)
        if segment_index >= earliest_segment:
            result.append(pc)
    return result


# ============================================================================
# 主函数：build_beat_slots（纯算法版，enrichment 在 P1.4 加）
# ============================================================================

def build_beat_slots(
    anchor: ChapterClimax,
    spine: StoryContext,
    total_segments: int,
    target_word_count: int,
    chapter_number: int,
    locations: List[Any] = None,
    assets: List[Any] = None,
    chapter: Any = None,
) -> List[BeatSlotCard]:
    """从 anchor+spine 派生全章 BeatSlotCard 列表（纯算法，0 LLM）。

    Args:
        anchor: ADF Phase 2 产出的 ChapterClimax
        spine: ADF Phase 1 产出的 StoryContext
        total_segments: 段数（来自 tier_decide）
        target_word_count: 全章目标字数
        chapter_number: 章节号（用于 beat_id）
        locations: setting_resolver 的地点数据（可选）
        assets: setting_resolver 的资产数据（可选）
        chapter: chapter ORM 对象（可选，用于 ban_words 派生）

    Returns:
        List[BeatSlotCard]，长度 == total_segments
    """
    locations = locations or []
    assets = assets or []

    storyboard = plan_storyboard(
        total_segments=total_segments,
        emotion_curve=anchor.emotion_curve,
        has_multiple_pov=len(spine.character_arc_advances) >= 2,
    )

    cards: List[BeatSlotCard] = []
    for i in range(total_segments):
        progress = (i + 1) / total_segments
        shot_type, transition = storyboard[i]

        sample_progress = max(0.0, progress - 0.5 / total_segments)
        emotion_sample = anchor.emotion_curve.sample_at(sample_progress)

        landed_pcs = soft_assign_preconditions(
            anchor.preconditions, segment_index=i, progress=progress,
            total_segments=total_segments,
        )

        anchor_action_seeds = []
        for pc in landed_pcs:
            anchor_action_seeds.extend(pc.must_use_terms or [])

        sensory_seeds = []
        for loc in locations[:3]:
            name = getattr(loc, "name", None) or (loc.get("name") if isinstance(loc, dict) else None)
            if name:
                sensory_seeds.append(name)
        for asset in assets[:2]:
            name = getattr(asset, "name", None) or (asset.get("name") if isinstance(asset, dict) else None)
            if name:
                sensory_seeds.append(name)

        psych = _build_psych_directive(shot_type, emotion_sample.register)

        ban_words = list(DEFAULT_BAN_LIST.banned_words) if hasattr(DEFAULT_BAN_LIST, "banned_words") else []

        card = BeatSlotCard(
            beat_id=f"BS_CH{chapter_number}_BEAT_{i:02d}",
            segment_index=i,
            beat_type=shot_type_to_beat_type(shot_type),
            target_word_count=dynamic_spread(target_word_count, i, total_segments),
            anchor_actions=anchor_action_seeds,
            sensory_details=sensory_seeds,
            text_carrier="",
            conflict_trigger=_pick_conflict_trigger(landed_pcs, anchor.climax, i, total_segments),
            psych_subtext=psych,
            ban_words=ban_words,
            sentence_rhythm=transition_to_rhythm(transition),
            perspective="THIRD_LIMITED",
            emotion_register=emotion_sample.register,
            emotion_energy=emotion_sample.energy,
            landed_preconditions=[pc.id for pc in landed_pcs],
            shot_type=shot_type,
            transition=transition,
        )
        cards.append(card)

    return cards


def _build_psych_directive(shot_type: str, register: str) -> str:
    """基于景别生成心理潜文本指令（只读，不渲染进正文）。"""
    base = "用物理动作与环境呈现情感，禁止直接心理升华。"
    if shot_type in ("wide", "full"):
        return f"{base}远景/全景以环境氛围承载情绪。"
    elif shot_type == "macro":
        return f"{base}特写以微小动作（手部、眼神物理变化）承载情绪爆发。"
    return base


def _pick_conflict_trigger(
    landed_pcs: List[Precondition],
    climax: Any,
    segment_index: int,
    total_segments: int,
) -> str:
    """从 preconditions 或 climax 派生本段冲突触发（纯算法，可能为空）。"""
    if segment_index == total_segments - 1:
        return getattr(climax, "description", "") or ""
    for pc in landed_pcs:
        if pc.description:
            return pc.description
    return ""


# ============================================================================
# Phase 4a：Slot Enrichment（可选 1× creative LLM/卡）
# ============================================================================

async def enrich_slots(
    cards: List[BeatSlotCard],
    recorder: Optional[RunRecorder] = None,
    enable: bool = True,
) -> List[BeatSlotCard]:
    """对全章槽位卡跑 1× LLM 扩写（每张卡独立扩写，串行）。

    失败判定（任一即视为该卡失败，保留原种子）：
    (a) LLM 抛异常/超时
    (b) 返回无法 JSON 解析
    (c) 解析出的动作词/感官词为空
    (d) 任一词超过 _MAX_WORD_LEN 字

    Args:
        cards: 待扩写的槽位卡列表（in-place 修改 anchor_actions/sensory_details）
        recorder: RunRecorder（记 token 用量，可选）
        enable: 是否启用（False 则直接返回原卡）

    Returns:
        扩写后的 cards（同一引用，in-place 修改）
    """
    if not enable:
        return cards

    for card in cards:
        try:
            system_prompt, user_prompt = build_slot_enrich_prompt(
                seed_actions=card.anchor_actions,
                seed_sensory=card.sensory_details,
                shot_type=card.shot_type,
                emotion_register=card.emotion_register,
                scene_entities=[],
            )
            # 用 recorder.record_call 上下文管理器（与 climax_designer 一致）
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"bsadf.enrich.{card.beat_id}",
                    model_slot="creative",
                ) as call_ctx:
                    result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="creative",
                        temperature=0.7,
                        max_tokens=512,
                        response_format={"type": "json_object"},
                    )
                    call_ctx.set_result(result)
            else:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.7,
                    max_tokens=512,
                    response_format={"type": "json_object"},
                )

            data = json.loads(result.text)
            new_actions = data.get("anchor_actions", [])
            new_sensory = data.get("sensory_details", [])

            # 失败判定
            if not new_actions and not new_sensory:
                logger.warning(f"[enrich_slots] {card.beat_id} 扩写结果为空，保留种子")
                continue
            if any(len(w) > _MAX_WORD_LEN for w in new_actions + new_sensory):
                logger.warning(f"[enrich_slots] {card.beat_id} 扩写结果含超长词，保留种子")
                continue

            # 合并：扩写词 + 原种子（去重，保序）
            card.anchor_actions = list(dict.fromkeys(new_actions + card.anchor_actions))
            card.sensory_details = list(dict.fromkeys(new_sensory + card.sensory_details))
        except json.JSONDecodeError as e:
            logger.warning(f"[enrich_slots] {card.beat_id} JSON 解析失败：{e}，保留种子")
        except Exception as e:
            logger.warning(f"[enrich_slots] {card.beat_id} LLM 调用失败：{e}，保留种子")

    return cards
