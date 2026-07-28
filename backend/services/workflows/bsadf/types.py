"""
BS-ADF 引擎核心数据结构（瘦身版，22 → 13+ 字段）。

职责：定义 BeatSlotCard（槽位卡）及其运行时状态
业务场景：Phase 4a 产出 → 4b 作者编辑 → 4c 渲染消费 → 4d 降级追踪
主要功能：结构化中间层，把 anchor+spine 固化为可渲染、可机器验收的物理硬契约
依赖项：dataclasses、typing

设计要点（DDE-BS 重构后）：
- 槽位卡是"渲染验收的物理硬契约"，不是 prompt 载体：core_plot_event /
  key_anchors / text_carrier 三件事都能在正文里被代码客观核验。
- 软性风格指令（禁词、心理描写限制、感官指导）已下沉为渲染器静态
  system prompt（见 services/prompts/bsadf_prompts.py），不逐卡复制。
- branch_directive 是 DDE 注入的剧情走向约束（注入渲染 prompt，
  不做 coverage 校验）。

注意：与 adf/types.py 平行，不 import ADF 的 dataclass（避免耦合），
     但字段名与 ADF 兼容（SegmentResult 输出形状一致）。
"""
# Velluma - BS-ADF Engine Types
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

from dataclasses import dataclass, field
from typing import List


@dataclass
class BeatSlotCard:
    """单段槽位卡：渲染器的结构化输入 + 可机器验收的物理硬契约。

    每张卡对应一个 segment，含物理硬契约槽位 + 剧情走向约束 +
    内部渲染约束 + ADF 集成字段 + 运行时状态。
    """

    # === 标识 ===
    beat_id: str                            # "BS_CH{n}_BEAT_{i:02d}"
    segment_index: int                      # 0-based，对应 SegmentResult.index
    beat_type: str                          # ESTABLISH | CONFRONT | CLIMACTIC | RESOLVE
    target_word_count: int                  # tier 派生，动态再分摊

    # === 物理硬契约（UI 可见，coverage 可机器验收）===
    core_plot_event: str = ""                                # 本段必须发生的剧情转折（原 conflict_trigger）
    key_anchors: List[str] = field(default_factory=list)     # 画面必现硬焦点（原 anchor_actions）
    text_carrier: str = ""                                   # 锚定本段的一句对白/铭文
    outline_beat: str = ""                                   # 本段大纲节拍（UI 只读展示，防大纲偏移）

    # === 叙事走向（DDE 注入；注入渲染 prompt，不做 coverage 校验）===
    branch_directive: str = ""              # 作者选定的剧情分支走向（label + plot_impact）

    # === 内部渲染约束 ===
    negative_bounds: List[str] = field(default_factory=list)  # 排他禁忌（渲染期禁出现）
    sentence_rhythm: str = "VARIED"                            # SHORT_PUNCHY | VARIED | LAYERED

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


@dataclass
class EmergentFacts:
    """Loop 3 涌现实体抽取结果（单段）。"""

    new_entities: List[dict] = field(default_factory=list)
    relationship_changes: List[dict] = field(default_factory=list)
    new_locations: List[dict] = field(default_factory=list)
    outline_addenda: List[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.new_entities
            and not self.relationship_changes
            and not self.new_locations
            and not self.outline_addenda
        )

    def to_dict(self) -> dict:
        return {
            "new_entities": self.new_entities,
            "relationship_changes": self.relationship_changes,
            "new_locations": self.new_locations,
            "outline_addenda": self.outline_addenda,
        }


def beat_slot_to_dict(card: BeatSlotCard) -> dict:
    """BeatSlotCard → dict（用于 SSE 事件 / DB 持久化）。"""
    return {
        "beat_id": card.beat_id,
        "segment_index": card.segment_index,
        "beat_type": card.beat_type,
        "target_word_count": card.target_word_count,
        "core_plot_event": card.core_plot_event,
        "key_anchors": card.key_anchors,
        "text_carrier": card.text_carrier,
        "outline_beat": card.outline_beat,
        "branch_directive": card.branch_directive,
        "negative_bounds": card.negative_bounds,
        "sentence_rhythm": card.sentence_rhythm,
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
        core_plot_event=d.get("core_plot_event", ""),
        key_anchors=d.get("key_anchors", []),
        text_carrier=d.get("text_carrier", ""),
        outline_beat=d.get("outline_beat", ""),
        branch_directive=d.get("branch_directive", ""),
        negative_bounds=d.get("negative_bounds", []),
        sentence_rhythm=d.get("sentence_rhythm", "VARIED"),
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
