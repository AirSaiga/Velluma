"""
BS-ADF 引擎核心数据结构。

职责：定义 BeatSlotCard（槽位卡）及其运行时状态
业务场景：Phase 4a 产出 → 4b 作者编辑 → 4c 渲染消费 → 4d 降级追踪
主要功能：结构化中间层，把 anchor+spine 固化为可渲染的物理白描槽位
依赖项：dataclasses、typing

注意：与 adf/types.py 平行，不 import ADF 的 dataclass（避免耦合），
     但字段名与 ADF 兼容（SegmentResult 输出形状一致）。
"""
# Velluma - BS-ADF Engine Types
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BeatSlotCard:
    """单段槽位卡：渲染器的结构化输入。

    每张卡对应一个 segment，含物理动作/感官/载体/冲突槽位 +
    渲染约束 + ADF 集成字段 + 运行时状态。
    """

    # === 标识 ===
    beat_id: str                            # "BS_CH{n}_BEAT_{i:02d}"
    segment_index: int                      # 0-based，对应 SegmentResult.index
    beat_type: str                          # ESTABLISH | CONFRONT | CLIMACTIC | RESOLVE
    target_word_count: int                  # tier 派生，动态再分摊

    # === 槽位（渲染器扩展的"填料"）===
    anchor_actions: List[str] = field(default_factory=list)   # 必须出现的物理动词
    sensory_details: List[str] = field(default_factory=list)  # 必须出现的感官名词
    text_carrier: str = ""                                     # 锚定本段的一句对白/铭文
    conflict_trigger: str = ""                                 # 本段冲突触发事件
    psych_subtext: str = ""  # 只读指令（不渲染进正文）

    # === 渲染约束 ===
    ban_words: List[str] = field(default_factory=list)        # 本章禁词
    sentence_rhythm: str = "VARIED"                            # SHORT_PUNCHY | VARIED | LAYERED
    perspective: str = "THIRD_LIMITED"

    # === ADF 集成字段（复用 ADF prompt 脚手架必需）===
    emotion_register: str = ""
    emotion_energy: int = 5
    landed_preconditions: List[str] = field(default_factory=list)
    shot_type: str = ""                                        # wide | full | medium | close | macro
    transition: str = ""                                       # cut | push_in | pull_out | counter | fade

    # === 运行时状态（Phase 4c/4d 期间变异）===
    status: str = "pending"            # pending | rendered | degraded | author_pending
    edit_count: int = 0
    render_attempts: int = 0
    edited: bool = False


@dataclass
class RenderProgress:
    """单段渲染进度（4c 阶段 SSE 推送用）。"""

    beat_id: str
    segment_index: int
    status: str                        # rendering | rendered | degraded
    word_count: int = 0
    reason: str = ""                   # 降级原因（status=degraded 时填）


@dataclass
class DegradedBeat:
    """降级回退的槽位卡句柄（4d 产出，供 /rerender-beat 恢复）。"""

    beat_id: str
    segment_index: int
    reason: str                        # ai_smell | coverage_fail | gate_fail | llm_error
    attempts: int
    card_snapshot: BeatSlotCard        # 降级时的槽位卡快照（可重新编辑）


def beat_slot_to_dict(card: BeatSlotCard) -> dict:
    """BeatSlotCard → dict（用于 SSE 事件 / DB 持久化）。"""
    return {
        "beat_id": card.beat_id,
        "segment_index": card.segment_index,
        "beat_type": card.beat_type,
        "target_word_count": card.target_word_count,
        "anchor_actions": card.anchor_actions,
        "sensory_details": card.sensory_details,
        "text_carrier": card.text_carrier,
        "conflict_trigger": card.conflict_trigger,
        "psych_subtext": card.psych_subtext,
        "ban_words": card.ban_words,
        "sentence_rhythm": card.sentence_rhythm,
        "perspective": card.perspective,
        "emotion_register": card.emotion_register,
        "emotion_energy": card.emotion_energy,
        "landed_preconditions": card.landed_preconditions,
        "shot_type": card.shot_type,
        "transition": card.transition,
        "status": card.status,
        "edit_count": card.edit_count,
        "render_attempts": card.render_attempts,
        "edited": card.edited,
    }


def beat_slot_from_dict(d: dict) -> BeatSlotCard:
    """dict → BeatSlotCard（从 DB/SSE 载入）。"""
    return BeatSlotCard(
        beat_id=d.get("beat_id", ""),
        segment_index=d.get("segment_index", 0),
        beat_type=d.get("beat_type", ""),
        target_word_count=d.get("target_word_count", 600),
        anchor_actions=d.get("anchor_actions", []),
        sensory_details=d.get("sensory_details", []),
        text_carrier=d.get("text_carrier", ""),
        conflict_trigger=d.get("conflict_trigger", ""),
        psych_subtext=d.get("psych_subtext", ""),
        ban_words=d.get("ban_words", []),
        sentence_rhythm=d.get("sentence_rhythm", "VARIED"),
        perspective=d.get("perspective", "THIRD_LIMITED"),
        emotion_register=d.get("emotion_register", ""),
        emotion_energy=d.get("emotion_energy", 5),
        landed_preconditions=d.get("landed_preconditions", []),
        shot_type=d.get("shot_type", ""),
        transition=d.get("transition", ""),
        status=d.get("status", "pending"),
        edit_count=d.get("edit_count", 0),
        render_attempts=d.get("render_attempts", 0),
        edited=d.get("edited", False),
    )
