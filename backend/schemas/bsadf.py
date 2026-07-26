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
BS-ADF（Beat-Slot Anchor-Driven Flow）引擎数据模型（P2.4 新建）。

职责：
- 定义 BS-ADF 引擎对外/对内的 Pydantic 数据结构
- 与 workflows/bsadf/types.py 的 dataclass 一一对应（dataclass 供内部流转，Pydantic 供 API）

模块组织：
- BeatSlotSchema:          单张槽位卡（API 边界版本，对应 BeatSlotCard dataclass）
- GenerateBSAdfRequest:    POST /api/chapters/{id}/generate-bsadf 请求体
- ConfirmBeatsRequest:     POST /api/chapters/{id}/confirm-beats 请求（Track B 恢复）
- RerenderBeatRequest:     POST /api/chapters/{id}/rerender-beat 请求（降级单卡恢复）

业务场景：
- POST /api/chapters/{id}/generate-bsadf
    SSE 事件序列：BSADF_STAGE / BEAT_SLOTS_BUILT / BEAT_RENDER_PROGRESS /
    BEAT_DOWNGRADED / ADF_*（共享事件）/ TEXT_CHUNK / COMPLETE
- Track A（默认）：全自动跑完全程
- Track B（track='B'）：跑到 Phase 4a 暂停，待 /confirm-beats 恢复（P3 实现）

依赖项：
- pydantic.BaseModel
- backend.models.TIER_AUTO 常量
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.models import TIER_AUTO


# ============================================================
# 槽位卡（API 边界版本）
# ============================================================

class BeatSlotSchema(BaseModel):
    """单张槽位卡（API 边界版本，对应 BeatSlotCard dataclass）。

    与 workflows/bsadf/types.py 的 BeatSlotCard 字段一一对应；
    dataclass 供工作流内部流转（mutable），Pydantic 模型供 API 序列化（immutable）。
    """

    # === 标识 ===
    beat_id: str = Field(..., description="槽位 ID，如 BS_CH12_BEAT_03")
    segment_index: int = Field(..., ge=0, description="0-based 段序号，对应 SegmentResult.index")
    beat_type: str = Field("ESTABLISH", description="ESTABLISH | CONFRONT | CLIMACTIC | RESOLVE")
    target_word_count: int = Field(600, ge=100, le=5000, description="tier 派生，动态再分摊")

    # === 槽位（渲染器扩展的"填料"）===
    anchor_actions: List[str] = Field(
        default_factory=list,
        description="必须出现的物理动词",
    )
    sensory_details: List[str] = Field(
        default_factory=list,
        description="必须出现的感官名词",
    )
    text_carrier: str = Field("", description="锚定本段的一句对白/铭文")
    conflict_trigger: str = Field("", description="本段冲突触发事件")
    psych_subtext: str = Field("", description="只读指令（不渲染进正文）")

    # === 渲染约束 ===
    ban_words: List[str] = Field(default_factory=list, description="本章禁词")
    sentence_rhythm: str = Field("VARIED", description="SHORT_PUNCHY | VARIED | LAYERED")
    perspective: str = Field("THIRD_LIMITED", description="叙事视角")

    # === ADF 集成字段（复用 ADF prompt 脚手架必需）===
    emotion_register: str = Field("", description="情绪基调")
    emotion_energy: int = Field(5, ge=1, le=10, description="情绪势能 1-10")
    landed_preconditions: List[str] = Field(
        default_factory=list,
        description="本段需落地的 precondition ID",
    )
    shot_type: str = Field("", description="wide | full | medium | close | macro")
    transition: str = Field("", description="cut | push_in | pull_out | counter | fade")

    # === 运行时状态 ===
    status: str = Field(
        "pending",
        description="pending | rendered | degraded | author_pending",
    )
    edit_count: int = Field(0, ge=0, description="作者编辑次数")
    render_attempts: int = Field(0, ge=0, description="渲染尝试次数（含首次）")
    edited: bool = Field(False, description="作者是否编辑过")


# ============================================================
# 请求模型
# ============================================================

class GenerateBSAdfRequest(BaseModel):
    """POST /api/chapters/{id}/generate-bsadf 请求。

    track='A'（默认）全自动跑完全程；track='B' 作者介入（跑到 Phase 4a 暂停，
    等 /confirm-beats 恢复——P3 实现，本版本 Track B 暂时也跑完全程）。
    其余字段与 GenerateADFRequest 对齐（复用 ADF 的 enable_* 开关）。
    """

    tier: str = Field(
        TIER_AUTO,
        description="章节定档：auto(默认) | climax | turn | progress | transition",
    )
    track: str = Field(
        "A",
        description="A=全自动（跑完全程）| B=作者介入（跑到槽位卡暂停）",
    )
    target_word_count: Optional[int] = Field(
        None,
        ge=500,
        le=15000,
        description="目标字数（None 时由 tier 自动推导）",
    )
    max_segments: int = Field(
        6,
        ge=3,
        le=10,
        description="槽位卡数量上限（实际由 tier + word_count 推导，但不超此值）",
    )
    enable_slot_enrichment: bool = Field(
        True,
        description="是否启用 Phase 4b 槽位扩写 LLM（失败保留种子）",
    )
    enable_anchor_audit: bool = Field(True, description="复用 ADF Phase 5 锚点审计")
    enable_refinement: bool = Field(True, description="复用 ADF Phase 6 条件补埋")
    enable_consistency_guard: bool = Field(
        True,
        description="复用 ADF Phase 7 一致性守卫（设定幻觉审计 + 定点手术修复）",
    )
    enable_state_tracker: bool = Field(
        True,
        description="复用 Agent Loop 1 段级状态卡（每段抽取场景状态卡注入下一段）",
    )
    enable_edit_verify: bool = Field(
        True,
        description="复用 Agent Loop 2 手术复验回滚（Phase 7 手术后复验，不通过则回滚）",
    )
    enable_beat_coverage: bool = Field(
        True,
        description="复用 ADF Phase 6.5 节拍补写（大纲节拍覆盖校验 + 缺失补写）",
    )
    user_tier_hint: Optional[str] = Field(
        None, description="用户预期档位提示（弱信号）"
    )
    # V4.2 介入点 1：作者意图（来自 PlanConfirmModal 的决策汇总）
    author_intent: Optional[str] = Field(
        None,
        description="作者在介入点 1 的意图汇总，作为强约束注入 anchor_design 与 forward_flow 的 prompt",
    )
    expectation_actions: Optional[Dict[str, str]] = Field(
        None,
        description=(
            "作者对每个期待的明确处理决策 {expectation_id: 'accumulate'|'payoff'|'ignore'}。"
            "来自介入点 1 的逐条决策，覆盖 Reader Mirror 的自动推断。"
        ),
    )


class ConfirmBeatsRequest(BaseModel):
    """POST /api/chapters/{id}/confirm-beats 请求（Track B 恢复）。

    作者在前端编辑完槽位卡后，用本请求恢复 Phase 4c 渲染。
    run_id 从 generate-bsadf（track='B'）阶段获得的 GENERATION_RUN 事件取得。
    """

    run_id: str = Field(..., description="从 generate-bsadf 阶段获得的 run_id")
    edited_slots: List[BeatSlotSchema] = Field(
        default_factory=list,
        description="作者编辑后的全章槽位卡（覆盖服务端暂存的卡）",
    )


class RerenderBeatRequest(BaseModel):
    """POST /api/chapters/{id}/rerender-beat 请求（降级单卡恢复）。

    Phase 4d 降级的槽位卡（status='degraded'）由作者重新编辑后，
    用本请求单卡重渲染（不重跑全章）。
    """

    beat_id: str = Field(..., description="待重渲染的槽位 ID")
    edited_slot: BeatSlotSchema = Field(..., description="作者重新编辑的单张槽位卡")
