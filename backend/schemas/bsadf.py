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
BS-ADF（Beat-Slot Anchor-Driven Flow）引擎数据模型。

职责：
- 定义 BS-ADF 引擎对外/对内的 Pydantic 数据结构
- 与 workflows/bsadf/types.py 的 dataclass 一一对应（dataclass 供内部流转，Pydantic 供 API）

模块组织：
- BeatSlotSchema:          单张槽位卡（API 边界版本，对应 BeatSlotCard dataclass）
- BranchOptionSchema / StoryBranchSchema / ChapterDecisionSetSchema:
                           DDE 章节级剧情分叉决策集（对应 dde/types.py dataclass）
- GenerateBSAdfRequest:    POST /api/chapters/{id}/generate-bsadf 请求体
- ConfirmBeatsRequest:     POST /api/chapters/{id}/confirm-beats 请求（Track B 单次暂停恢复，
                           含 branch_choices 分支选择）
- RerenderBeatRequest:     POST /api/chapters/{id}/rerender-beat 请求（降级单卡恢复）

业务场景：
- POST /api/chapters/{id}/generate-bsadf
    SSE 事件序列：BSADF_STAGE / BEAT_SLOTS_BUILT（内嵌 decision_set）/
    DDE_AUTO_APPLIED（Track A）/ BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED /
    ADF_*（共享事件）/ TEXT_CHUNK / COMPLETE
- Track A（默认）：全自动跑完全程（DDE 有分支时静默应用 default_option）
- Track B（track='B'）：跑到 Phase 4b 单次暂停，待 /confirm-beats 恢复

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

    # === 物理硬契约（coverage 可机器验收）===
    core_plot_event: str = Field("", description="本段必须发生的剧情转折")
    key_anchors: List[str] = Field(
        default_factory=list,
        description="画面必现硬焦点（物理动作/名词词）",
    )
    text_carrier: str = Field("", description="锚定本段的一句对白/铭文")
    outline_beat: str = Field(
        "", description="本段大纲节拍（Phase 4a 按序分配，防大纲偏移）"
    )

    # === 叙事走向（DDE 注入，不做 coverage 校验）===
    branch_directive: str = Field(
        "", description="作者选定的剧情分支走向（label + plot_impact）"
    )

    # === 内部渲染约束 ===
    negative_bounds: List[str] = Field(
        default_factory=list,
        description="排他禁忌（DDE 冲突走向否定约束，渲染期禁止出现）",
    )
    sentence_rhythm: str = Field("VARIED", description="SHORT_PUNCHY | VARIED | LAYERED")

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
# DDE 章节级剧情分叉（API 边界版本）
# ============================================================

class BranchOptionSchema(BaseModel):
    """单个剧情分支选项（走向级，非物理动作级）。"""
    option_id: str = Field(..., description="选项 ID，如 A/B/C")
    label: str = Field(..., description="走向标签（≤20字），如 忍辱负重并暗中破坏设备")
    plot_impact: str = Field("", description="剧情后果说明（给作者看 + 注入渲染走向约束）")


class StoryBranchSchema(BaseModel):
    """单个剧情分叉节点（挂在某个 beat 上的一道走向选择题）。"""
    beat_id: str = Field(..., description="目标槽位卡 beat_id")
    node_title: str = Field(..., description="如 面对工头恶意挑衅，林尘的应对分支")
    options: List[BranchOptionSchema] = Field(
        default_factory=list,
        description="2~3 个互斥走向选项",
    )
    default_option: str = Field(
        "", description="默认 option_id（最顺大纲的主路径）"
    )


class ChapterDecisionSetSchema(BaseModel):
    """全章剧情分叉决策集（DDE 单次 LLM 调用的产出）。"""
    has_story_branch: bool = Field(
        False, description="False = 全章无岔路，自动放行"
    )
    decision_nodes: List[StoryBranchSchema] = Field(
        default_factory=list,
        description="剧情分叉节点（硬上限 2 个）",
    )


# ============================================================
# 请求模型
# ============================================================

class GenerateBSAdfRequest(BaseModel):
    """POST /api/chapters/{id}/generate-bsadf 请求。

    track='A'（默认）全自动跑完全程（DDE 有分支时静默应用 default_option，
    emit DDE_AUTO_APPLIED）；track='B' 作者介入（跑到 Phase 4b 单次暂停，
    BEAT_SLOTS_BUILT 内嵌 decision_set，等 /confirm-beats 恢复）。
    其余字段与 GenerateADFRequest 对齐（复用 ADF 的 enable_* 开关）。
    """

    tier: str = Field(
        TIER_AUTO,
        description="章节定档：auto(默认) | climax | turn | progress | transition",
    )
    track: str = Field(
        "A",
        description="A=全自动（跑完全程）| B=作者介入（跑到槽位卡单次暂停）",
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
    enable_dde: bool = Field(
        True,
        description=(
            "DDE 剧情分叉控制器开关（Track A/B 都生效）。Phase 4b 后对全章做一次"
            "剧情走向级岔路判断：Track A 有分支时静默应用 default_option"
            "（emit DDE_AUTO_APPLIED，不暂停）；Track B 把 decision_set 内嵌进"
            " BEAT_SLOTS_BUILT，作者选分支后随 /confirm-beats 一并提交。"
            "无岔路（has_story_branch=false）自动放行，是常态。"
        ),
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
    """POST /api/chapters/{id}/confirm-beats 请求（Track B 单次暂停恢复）。

    作者在分镜面板编辑完槽位卡、选定剧情分支后，用本请求恢复 Phase 4c 渲染。
    run_id 从 generate-bsadf（track='B'）阶段获得的 BEAT_SLOTS_BUILT 事件取得。

    流程：从 _PENDING_BEAT_SLOTS 取回 → SlotMutator 按 branch_choices 突变
    （skipped=True 时全走 default_option）→ 应用 edited_slots 覆盖
    → resume_from_slots 渲染。

    branch_choices 结构：{ beat_id: option_id }
    （option_id 为 "custom:xxx" 前缀时表示作者自定义走向文本）
    """

    run_id: str = Field(..., description="从 generate-bsadf 阶段获得的 run_id")
    edited_slots: List[BeatSlotSchema] = Field(
        default_factory=list,
        description="作者编辑后的全章槽位卡（覆盖服务端暂存的卡）",
    )
    branch_choices: Dict[str, str] = Field(
        default_factory=dict,
        description="作者选定的剧情分支 { beat_id: option_id }",
    )
    skipped: bool = Field(
        False,
        description="作者跳过分支选择；True 时后端全走 default_option",
    )
    chapter_id: Optional[str] = Field(
        None,
        description="章节 ID（由路径参数回填，客户端无需传）",
        exclude=True,
    )


class RerenderBeatRequest(BaseModel):
    """POST /api/chapters/{id}/rerender-beat 请求（降级单卡恢复）。

    Phase 4d 降级的槽位卡（status='degraded'）由作者重新编辑后，
    用本请求单卡重渲染（不重跑全章）。edited_slot 可选：提供时用它
    替代服务端暂存的卡快照重渲染（前端"编辑后再重渲染"路径）；
    缺省时用 _PENDING_BEAT_SLOTS 里该 beat 的卡快照原样重渲。
    """

    beat_id: str = Field(..., description="待重渲染的槽位 ID")
    edited_slot: Optional[BeatSlotSchema] = Field(
        None,
        description="作者重新编辑的单张槽位卡（可选；缺省时用服务端卡快照）",
    )
    run_id: Optional[str] = Field(
        None,
        description=(
            "本次生成的 run_id（GENERATION_RUN 事件获得）。提供时优先用它从 "
            "_PENDING_BEAT_SLOTS 取完整渲染上下文；缺失时按 beat_id 扫描兜底"
        ),
    )


class AdvanceBeatRequest(BaseModel):
    """POST /api/chapters/{id}/advance-beat 请求（NLE-ADF 步进推进）。"""

    run_id: str = Field(..., description="步进运行 ID")
    beat_id: str = Field(..., description="当前裁决的段 ID")
    action: str = Field(..., description="pass | edit | branch | skip")
    edited_slot: Optional[BeatSlotSchema] = Field(None, description="action=edit 时必填")
    branch_choice: Optional[Dict[str, str]] = Field(None, description="action=branch 时必填，{option_id, label, plot_impact}")
    chapter_id: Optional[str] = Field(None, exclude=True)

