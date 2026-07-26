"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
ADF（Anchor-Driven Flow）引擎 dataclass 类型（V3.2 §3 新建）。

职责：
- 定义 ADF 工作流内部流转用的 dataclass（与 schemas/adf.py 的 Pydantic 模型一一对应）

设计意图：
- dataclass 用于工作流内部（mutable，可在运行时更新 landed 状态）
- Pydantic 模型用于 API 边界（immutable，序列化）
- 两者通过 to_dict / from_dict 互转

业务场景：
- workflows/adf/adf_workflow.py 主类持有 ChapterClimax / StoryContext，执行时产出 List[SegmentResult]
- routes/chapter_generation/adf.py 把结果序列化推 SSE

使用方式：
    from backend.services.workflows.adf import ADFWorkflow, ChapterClimax, StoryContext
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# 远端锚（Layer 1）
# ============================================================

@dataclass
class ClimaxSpec:
    """高潮点规格。"""
    description: str = ""
    emotional_target: str = ""
    payoff_question: str = ""
    open_question: str = ""
    intensity: int = 5


@dataclass
class Precondition:
    """前置条件（核心创新，不对应特定段落）。"""
    id: str
    category: str = "role"
    description: str = ""
    must_use_terms: List[str] = field(default_factory=list)
    min_landing_offset: int = 0
    # 运行时状态
    landed: bool = False
    landed_segment: Optional[int] = None
    landed_evidence: Optional[str] = None


@dataclass
class EmotionCurveSample:
    """情绪曲线采样点。"""
    progress: float
    register: str
    energy: int


@dataclass
class EmotionCurve:
    """情绪曲线。"""
    samples: List[EmotionCurveSample] = field(default_factory=list)

    def sample_at(self, progress: float) -> EmotionCurveSample:
        """在指定进度采样（线性插值找最近的左锚点）。"""
        if not self.samples:
            return EmotionCurveSample(progress=progress, register="未知", energy=5)
        sorted_samples = sorted(self.samples, key=lambda s: s.progress)
        if progress <= sorted_samples[0].progress:
            return sorted_samples[0]
        if progress >= sorted_samples[-1].progress:
            return sorted_samples[-1]
        for i in range(len(sorted_samples) - 1):
            s1, s2 = sorted_samples[i], sorted_samples[i + 1]
            if s1.progress <= progress <= s2.progress:
                # 取较近的
                if progress - s1.progress < s2.progress - progress:
                    return s1
                return s2
        return sorted_samples[-1]

    def next_sample_after(self, progress: float) -> Optional[EmotionCurveSample]:
        """取 progress 之后的下一个采样点（用于提示下一段情绪走向）。"""
        sorted_samples = sorted(self.samples, key=lambda s: s.progress)
        for s in sorted_samples:
            if s.progress > progress + 0.01:
                return s
        return sorted_samples[-1] if sorted_samples else None


@dataclass
class ChapterClimax:
    """本章高潮设计：高潮点 + 必要铺垫要点集合 + 情绪走向。"""
    climax: ClimaxSpec = field(default_factory=ClimaxSpec)
    preconditions: List[Precondition] = field(default_factory=list)
    emotion_curve: EmotionCurve = field(default_factory=EmotionCurve)


# ============================================================
# 脉络轨（Layer 2）
# ============================================================

@dataclass
class EntryState:
    """章节入口状态。"""
    character_positions: Dict[str, str] = field(default_factory=dict)
    emotional_register: str = ""
    open_hooks: List[str] = field(default_factory=list)
    last_scene_image: str = ""
    time_of_day: Optional[str] = None


@dataclass
class ExitExpectation:
    """章节出口预期。"""
    next_chapter_setup: str = ""
    open_question_to_keep: List[str] = field(default_factory=list)


@dataclass
class ChapterPosition:
    """本章在卷中的位置。"""
    volume_arc: str = ""
    offset_from_volume_climax: int = 0
    pacing_tempo: str = "balanced"


@dataclass
class StoryContext:
    """脉络轨。"""
    entry_state: EntryState = field(default_factory=EntryState)
    exit_expectation: ExitExpectation = field(default_factory=ExitExpectation)
    chapter_position: ChapterPosition = field(default_factory=ChapterPosition)
    must_plant_hooks: List[str] = field(default_factory=list)
    must_resolve_hooks: List[str] = field(default_factory=list)
    character_arc_advances: Dict[str, str] = field(default_factory=dict)


# ============================================================
# 正向流写作产出（Layer 3）
# ============================================================

@dataclass
class SegmentResult:
    """正向流的一段产出。"""
    index: int
    text: str = ""
    scene_summary: str = ""
    emotion_register: str = ""
    landed_preconditions: List[str] = field(default_factory=list)
    planted_hooks: List[str] = field(default_factory=list)
    # V4.3 镜头景别
    shot_type: str = ""        # wide | full | medium | close | macro
    transition: str = ""       # cut | push_in | pull_out | counter | fade


# ============================================================
# 审校结论
# ============================================================

@dataclass
class StructureCheck:
    """锚点审计结论。"""
    verdict: str = "unaudited"  # pass | needs_refinement | fail | unaudited
    missing_preconditions: List[str] = field(default_factory=list)
    emotion_mismatches: List[str] = field(default_factory=list)
    spine_violations: List[str] = field(default_factory=list)
    climax_score: Optional[int] = None
    refinement_targets: List[str] = field(default_factory=list)
    # 维度5：文风质量（反 AI 腔）
    style_violations: List[str] = field(default_factory=list)
    style_score: Optional[int] = None  # 1-10，<6 表示需要润色
    # 维度6：大纲节拍覆盖。每项 {beat, status, evidence, insert_position,
    # insert_anchor_quote, patchable}；patchable=False 表示伪锚/无锚，只上报不补写
    missing_beats: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================
# 总结果
# ============================================================

@dataclass
class GenerationResult:
    """ADF 工作流完整结果。"""
    distal_anchor: ChapterClimax = field(default_factory=ChapterClimax)
    spine_track: StoryContext = field(default_factory=StoryContext)
    segments: List[SegmentResult] = field(default_factory=list)
    final_text: str = ""
    audit: StructureCheck = field(default_factory=StructureCheck)
    tier_decision: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    degraded: List[Dict[str, Any]] = field(default_factory=list)
    debug_info: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 转换工具：dataclass ↔ dict（用于 SSE 序列化与持久化）
# ============================================================

def climax_to_dict(anchor: ChapterClimax) -> Dict[str, Any]:
    return {
        "climax": {
            "description": anchor.climax.description,
            "emotional_target": anchor.climax.emotional_target,
            "payoff_question": anchor.climax.payoff_question,
            "open_question": anchor.climax.open_question,
            "intensity": anchor.climax.intensity,
        },
        "setup_points": [
            {
                "id": pc.id,
                "category": pc.category,
                "description": pc.description,
                "must_use_terms": pc.must_use_terms,
                "min_landing_offset": pc.min_landing_offset,
                "landed": pc.landed,
                "landed_segment": pc.landed_segment,
                "landed_evidence": pc.landed_evidence,
            }
            for pc in anchor.preconditions
        ],
        "emotion_flow": {
            "samples": [
                {"progress": s.progress, "register": s.register, "energy": s.energy}
                for s in anchor.emotion_curve.samples
            ]
        },
    }


def story_context_to_dict(spine: StoryContext) -> Dict[str, Any]:
    return {
        "entry_state": {
            "character_positions": spine.entry_state.character_positions,
            "emotional_register": spine.entry_state.emotional_register,
            "open_hooks": spine.entry_state.open_hooks,
            "last_scene_image": spine.entry_state.last_scene_image,
            "time_of_day": spine.entry_state.time_of_day,
        },
        "exit_expectation": {
            "next_chapter_setup": spine.exit_expectation.next_chapter_setup,
            "open_question_to_keep": spine.exit_expectation.open_question_to_keep,
        },
        "chapter_position": {
            "volume_arc": spine.chapter_position.volume_arc,
            "offset_from_volume_climax": spine.chapter_position.offset_from_volume_climax,
            "pacing_tempo": spine.chapter_position.pacing_tempo,
        },
        "must_plant_hooks": spine.must_plant_hooks,
        "must_resolve_hooks": spine.must_resolve_hooks,
        "character_arc_advances": spine.character_arc_advances,
    }


def audit_to_dict(audit: StructureCheck) -> Dict[str, Any]:
    return {
        "verdict": audit.verdict,
        "missing_setup_points": audit.missing_preconditions,
        "emotion_mismatches": audit.emotion_mismatches,
        "structure_issues": audit.spine_violations,
        "climax_score": audit.climax_score,
        "fix_targets": audit.refinement_targets,
        "style_violations": audit.style_violations,
        "style_score": audit.style_score,
        "missing_beats": audit.missing_beats,
    }
