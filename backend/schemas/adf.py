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
ADF（Anchor-Driven Flow）引擎数据模型（V3.2 §3 新建）。

职责：
- 定义 V3.2 ADF 引擎对外/对内的 Pydantic 数据结构
- 与 workflows/adf/types.py 的 dataclass 一一对应（dataclass 供内部流转，Pydantic 供 API）

模块组织：
- GenerateADFRequest:        POST /api/chapters/{id}/generate-adf 请求体
- ClimaxSpec / Precondition / EmotionCurveSample: 远端锚组成
- SpineTrack / EntryState / ExitExpectation / ChapterPosition: 脉络轨组成
- ADFCompletePayload:        COMPLETE SSE 事件 payload

业务场景：
- POST /api/chapters/{id}/generate-adf
- SSE v3.2 事件序列：ADF_STAGE / ADF_SPINE_BUILT / ADF_ANCHOR_DESIGNED /
  ADF_PROGRESS / ADF_PRECONDITION_LANDED / ADF_AUDIT / TEXT_CHUNK / COMPLETE

依赖项：
- pydantic.BaseModel
- backend.models.TIER_* 常量
"""

# 抑制 Pydantic 关于 EmotionCurveSample.register 字段遮蔽 BaseModel.register 的无害警告
# （register 是情绪基调的语义命名，与 Pydantic BaseModel 的内部 register 方法在运行时不冲突）
import warnings
warnings.filterwarnings(
    "ignore",
    message='Field name "register" in "EmotionCurveSample" shadows an attribute in parent "BaseModel"',
)

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.models import TIER_AUTO


# ============================================================
# 远端锚（Layer 1）组成
# ============================================================

class ClimaxSpec(BaseModel):
    """高潮点规格。"""

    description: str = Field(..., description="高潮场景描述")
    emotional_target: str = Field(..., description="目标情绪（如：屈辱到爆发的临界点）")
    payoff_question: str = Field("", description="本章回收的悬念")
    open_question: str = Field("", description="本章打开的新悬念（钩子）")
    intensity: int = Field(5, ge=1, le=10, description="高潮强度自评（供 tier 决策）")


class Precondition(BaseModel):
    """前置条件：高潮落地前必须满足的状态（核心创新，不对应特定段落）。"""

    id: str = Field(..., description="条件 ID，如 PC_REAL_POWER")
    category: str = Field(
        "role",
        description="条件类别：role | worldbuilding | foreshadow | motivation | relationship",
    )
    description: str = Field(..., description="条件描述")
    must_use_terms: List[str] = Field(
        default_factory=list,
        description="必须出现的设定词（用于代码级关键词落地检测）",
    )
    min_landing_offset: int = Field(
        0,
        ge=0,
        description="距高潮至少多少字之前埋下（避免临高潮才补）",
    )
    # 运行时状态（由 ForwardFlowWriter 更新）
    landed: bool = Field(False, description="是否已落地")
    landed_segment: Optional[int] = Field(None, description="落地段序号")
    landed_evidence: Optional[str] = Field(None, description="落地证据引文")


class EmotionCurveSample(BaseModel):
    """情绪曲线采样点。"""

    progress: float = Field(..., ge=0.0, le=1.0, description="章节进度 0.0~1.0")
    register: str = Field(..., alias="register", description="情绪基调（如：压抑隐忍 / 临界 / 爆发）")
    energy: int = Field(..., ge=1, le=10, description="情绪势能 1-10")


# ============================================================
# 脉络轨（Layer 2）组成
# ============================================================

class EntryState(BaseModel):
    """章节入口状态（从前章继承）。"""

    character_positions: Dict[str, str] = Field(
        default_factory=dict, description="{角色名: 位置}"
    )
    emotional_register: str = Field("", description="情绪基调")
    open_hooks: List[str] = Field(default_factory=list, description="悬挂的伏笔")
    last_scene_image: str = Field("", description="上一章结尾画面（≤200 字）")
    time_of_day: Optional[str] = Field(None, description="时间")


class ExitExpectation(BaseModel):
    """章节出口预期（通往后章）。"""

    next_chapter_setup: str = Field("", description="为下章铺设什么")
    open_question_to_keep: List[str] = Field(
        default_factory=list, description="故意留开的悬念"
    )


class ChapterPosition(BaseModel):
    """本章在卷中的位置。"""

    volume_arc: str = Field("", description="本卷主题")
    offset_from_volume_climax: int = Field(
        0, description="距卷高潮的章数（负=已过）"
    )
    pacing_tempo: str = Field(
        "balanced", description="节奏：slow_burn | balanced | fast_paced"
    )


class SpineTrack(BaseModel):
    """脉络轨（Layer 2）：把章节从孤岛接回全书脉络。"""

    entry_state: EntryState = Field(default_factory=EntryState)
    exit_expectation: ExitExpectation = Field(default_factory=ExitExpectation)
    chapter_position: ChapterPosition = Field(default_factory=ChapterPosition)
    must_plant_hooks: List[str] = Field(
        default_factory=list,
        description="必须埋的钩子（为后章埋，与 Precondition 互补）",
    )
    must_resolve_hooks: List[str] = Field(
        default_factory=list, description="必须回收的伏笔"
    )
    character_arc_advances: Dict[str, str] = Field(
        default_factory=dict, description="{角色名: 本章弧线推进到}"
    )


# ============================================================
# 请求模型
# ============================================================

class GenerateADFRequest(BaseModel):
    """POST /api/chapters/{id}/generate-adf 请求（ADF 引擎入口）。

    与 GenerateUnifiedRequest 并存。tier 语义相同；额外支持
    target_word_count（由用户或前端覆盖）与 max_segments 上限。
    """

    tier: str = Field(
        TIER_AUTO,
        description="章节定档：auto(默认) | climax | turn | progress | transition",
    )
    target_word_count: Optional[int] = Field(
        None,
        ge=500,
        le=15000,
        description="目标字数（None 时由 tier 自动推导：climax=5000/turn=3500/progress=2500/transition=1500）",
    )
    max_segments: int = Field(
        6,
        ge=3,
        le=10,
        description="正向流段数上限（实际段数由 tier + word_count 推导，但不超此值）",
    )
    enable_spine: bool = Field(True, description="是否启用脉络轨构建")
    enable_anchor_audit: bool = Field(True, description="是否启用锚点审计")
    enable_refinement: bool = Field(True, description="是否启用条件补埋")
    user_tier_hint: Optional[str] = Field(
        None, description="用户预期档位提示（弱信号）"
    )
    # V4.2 介入点 1：作者意图（来自 PlanConfirmModal 的决策汇总）
    author_intent: Optional[str] = Field(
        None,
        description=(
            "作者在介入点 1 的意图汇总（如'本章释放爽点；期待 EXP_X 释放；"
            "作者补充：让兰星表现得更骄傲'）。作为强约束注入 anchor_design 与 forward_flow 的 prompt。"
        ),
    )
    expectation_actions: Optional[Dict[str, str]] = Field(
        None,
        description=(
            "作者对每个期待的明确处理决策 {expectation_id: 'accumulate'|'payoff'|'ignore'}。"
            "来自介入点 1 的逐条决策，覆盖 Reader Mirror 的自动推断。"
        ),
    )


# ============================================================
# SSE 事件 payload
# ============================================================

class ADFAuditPayload(BaseModel):
    """ADF_AUDIT 事件 payload（Phase 5 锚点审计结论）。"""

    verdict: str = Field(..., description="pass | needs_refinement | fail")
    missing_preconditions: List[str] = Field(default_factory=list)
    emotion_mismatches: List[str] = Field(default_factory=list)
    spine_violations: List[str] = Field(default_factory=list)
    climax_score: Optional[int] = Field(None, ge=1, le=10)
    refinement_targets: List[str] = Field(default_factory=list)


class ADFCompletePayload(BaseModel):
    """ADF COMPLETE 事件 payload。"""

    text: str = Field("")
    engine: str = Field("adf", description="引擎标识")
    tier: Optional[str] = None
    tier_reason: Optional[str] = None
    target_word_count: Optional[int] = None
    segment_count: int = 0
    preconditions_total: int = 0
    preconditions_landed: int = 0
    climax_score: Optional[int] = None
    audit_verdict: Optional[str] = None
    generation_run_id: str = ""
    stats: Dict[str, Any] = Field(default_factory=dict)
