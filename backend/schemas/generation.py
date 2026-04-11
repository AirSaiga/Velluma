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

from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import (
    PovAperture,
    PovMode,
    ReasoningEffortLevel,
    WorkflowTier,
)
from .beat import PersistentStateAnchor


class ReasoningConfig(BaseModel):
    enabled: bool = Field(default=False, description="是否启用推理模式")
    effort: Optional[ReasoningEffortLevel] = Field(
        default="medium",
        description="推理努力程度: xhigh/high/medium/low/minimal/none"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=100,
        le=32000,
        description="推理 token 数量限制（用于 Anthropic/Gemini 模型）"
    )
    exclude: bool = Field(
        default=False,
        description="是否在响应中排除推理 tokens"
    )

    def to_api_params(self) -> dict:
        if not self.enabled:
            return {}

        params = {"enabled": True}

        if self.effort:
            params["effort"] = self.effort
        if self.max_tokens is not None:
            params["max_tokens"] = self.max_tokens
        if self.exclude:
            params["exclude"] = True

        return {"reasoning": params}


class DraftingFeatureFlags(BaseModel):
    enable_fail_fast: bool = Field(default=True, description="启用 Fail-Fast 断言检查与回溯重试")
    enable_emotional_scratchpad: bool = Field(default=True, description="启用动态情绪暂存器更新")
    enable_whisper_memory: bool = Field(default=False, description="启用 RAG 记忆暂存（预留）")
    fail_fast_max_attempts: int = Field(default=2, ge=1, le=3, description="Fail-Fast 最大重试次数")
    fail_fast_temperature_step: float = Field(default=0.2, ge=0.0, le=0.5, description="每次重试温度增量")
    workflow_tier: WorkflowTier = Field(default="TIER_2_STANDARD", description="智能路由工作流层级: TIER_1_FAST/均衡流/堡垒流")
    force_parallel_prose: bool = Field(default=False, description="强制正文并发生成（无视连贯性）")
    semi_parallel_prose: bool = Field(default=True, description="半并行生成：Beat 1 串行 → 中间 Beats 并行 → Beat N 串行（平衡连贯性与速度）")


class CharacterPhysicalState(BaseModel):
    is_in_vehicle: bool = Field(default=False, description="是否处于载具/机甲内部")
    vehicle_or_mech_name: Optional[str] = Field(None, description="所在载具/机甲名称")
    equipped_weapons: List[str] = Field(default_factory=list, description="当前装备的武器列表")
    movement_constraints: str = Field(default="无特殊限制", description="移动限制说明，例如'深度昏迷，无法自主移动'")


class DynamicContext(BaseModel):
    previous_tail: str = Field(default="", description="上文尾部（Rolling Prefix）")
    current_emotional_state: str = Field(
        default="初始状态：未知",
        description="主角当前心理状态（随剧情演变）"
    )
    physical_state_lock: str = Field(
        default="",
        description="主角绝对物理状态约束（防幻觉）"
    )
    pov_perception_state: str = ""
    accumulated_summary: str = Field(
        default="",
        max_length=500,
        description="已生成 Beat 的极简剧情摘要（宏观累加器）"
    )
    relational_state_lock: str = Field(
        default="",
        description="在场角色之间的动态关系状态锁"
    )
    active_whispers: dict[str, str] = Field(
        default_factory=dict,
        description="激活的 RAG 记忆片段（预留）"
    )
    entity_spatial_ledger: Dict[str, CharacterPhysicalState] = Field(
        default_factory=dict,
        description="在场核心角色的绝对物理形态与空间从属映射，键为角色名"
    )

    class Config:
        validate_assignment = True

    def update_summary(self, new_beat_summary: str) -> None:
        SEPARATOR = " → "
        MAX_LENGTH = 500

        if not self.accumulated_summary:
            self.accumulated_summary = new_beat_summary[:MAX_LENGTH]
            return

        new_accumulated = self.accumulated_summary + SEPARATOR + new_beat_summary

        if len(new_accumulated) <= MAX_LENGTH:
            self.accumulated_summary = new_accumulated
        else:
            self.accumulated_summary = new_accumulated[-MAX_LENGTH:]
            if SEPARATOR in self.accumulated_summary[1:]:
                first_sep_idx = self.accumulated_summary.find(SEPARATOR, 1)
                self.accumulated_summary = self.accumulated_summary[first_sep_idx + len(SEPARATOR):]


class DynamicStateUpdateResult(BaseModel):
    new_emotional_state: str = Field(
        ...,
        max_length=50,
        description="角色新的心理状态（20字以内）"
    )
    relational_delta: str = Field(
        default="",
        max_length=100,
        description="角色关系变化（如'与XXX的信任度下降'）"
    )
    beat_summary: str = Field(
        ...,
        max_length=80,
        description="本段剧情的一句话摘要（用于宏观累加）"
    )

    @model_validator(mode='after')
    def validate_lengths(self):
        if len(self.new_emotional_state) > 50:
            self.new_emotional_state = self.new_emotional_state[:47] + "..."
        if len(self.relational_delta) > 100:
            self.relational_delta = self.relational_delta[:97] + "..."
        if len(self.beat_summary) > 80:
            self.beat_summary = self.beat_summary[:77] + "..."
        return self


class MicroReviewResult(BaseModel):
    pass_check: bool = Field(..., description="是否通过断言检查")
    reason: str = Field(default="", description="未通过时的原因说明（一句话）")
    failed_checks: list[str] = Field(default_factory=list, description="失败的检查项编号列表")


AGENTIC_DEFAULT_WORD_COUNT = 2000
AGENTIC_DEFAULT_MAX_ITERATIONS = 2
AGENTIC_DEFAULT_RAG_TOP_K = 3
AGENTIC_DEFAULT_RAG_ALPHA = 0.6
AGENTIC_DEFAULT_RAG_BETA = 0.2
AGENTIC_DEFAULT_RAG_GAMMA = 0.2
AGENTIC_DEFAULT_RAG_LAMBDA = 0.1


class GenerateChapterAgenticRequest(BaseModel):
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    generation_run_id: Optional[str] = Field(default=None, min_length=8, max_length=64)
    resume_from_checkpoint: bool = Field(default=False)

    editor_mode: str = Field(
        default="intent",
        description="编辑模式：仅支持 intent（意图驱动模式）"
    )

    memory_strategy: Optional[str] = Field(
        default=None,
        description="记忆检索策略：recent_only/balanced_reference/deep_dive"
    )
    creativity_level: Optional[str] = Field(
        default=None,
        description="创作自由度：strict_prompt/balanced_creation/wild_imagination"
    )
    refinement_depth: Optional[str] = Field(
        default=None,
        description="精修深度：light/standard/deep"
    )

    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini", description="默认模型（向后兼容）")
    reasoning_model: Optional[str] = Field(None, description="高逻辑模型（用于 Scene Intent / Subconscious / Review）")
    creative_model: Optional[str] = Field(None, description="高创意模型（用于 Prose Draft），默认使用 reasoning_model")

    word_count: Optional[int] = Field(default=AGENTIC_DEFAULT_WORD_COUNT, ge=1, description="期望生成的字数")
    author_intent: Optional[str] = Field(None, description="作者的创作意图")
    tension_level: Optional[int] = Field(None, ge=1, le=5, description="剧情张力等级 (1-5)")
    pacing_style: Optional[str] = Field(None, description="叙事节奏偏好")

    max_iterations: int = Field(default=AGENTIC_DEFAULT_MAX_ITERATIONS, ge=1, le=5, description="最大重写次数")
    rag_top_k: int = Field(default=AGENTIC_DEFAULT_RAG_TOP_K, ge=1, le=20, description="RAG 返回记忆数量")
    rag_alpha: float = Field(default=AGENTIC_DEFAULT_RAG_ALPHA, ge=0.0, le=1.0, description="语义相似度权重")
    rag_beta: float = Field(default=AGENTIC_DEFAULT_RAG_BETA, ge=0.0, le=1.0, description="时间衰减权重")
    rag_gamma: float = Field(default=AGENTIC_DEFAULT_RAG_GAMMA, ge=0.0, le=1.0, description="剧情伏笔权重")
    rag_lambda: float = Field(default=AGENTIC_DEFAULT_RAG_LAMBDA, ge=0.0, description="时间衰减系数")
    fast_mode: bool = Field(default=False, description="快速模式：仅生成首轮结果，不进入二轮重写")
    skip_minor_refine: bool = Field(default=True, description="仅轻微问题时跳过整章重写")
    feature_flags: Optional[DraftingFeatureFlags] = Field(
        default_factory=DraftingFeatureFlags,
        description="V2.5 认知流式生成功能开关配置"
    )

    reasoning_config: Optional[ReasoningConfig] = Field(
        default_factory=lambda: ReasoningConfig(),
        description="推理模式配置（单模型模式使用）"
    )
    reasoning_model_reasoning_config: Optional[ReasoningConfig] = Field(
        default_factory=lambda: ReasoningConfig(),
        description="逻辑推理模型的推理模式配置（双模型模式使用）"
    )
    creative_model_reasoning_config: Optional[ReasoningConfig] = Field(
        default_factory=lambda: ReasoningConfig(),
        description="创意生成模型的推理模式配置（双模型模式使用）"
    )

    @field_validator('tension_level', mode='before')
    @classmethod
    def clamp_tension_level(cls, v):
        if v is not None:
            try:
                return max(1, min(5, int(v)))
            except (ValueError, TypeError):
                return None
        return v

    def is_basic_mode(self) -> bool:
        return True


class ConfirmedStoryBeat(BaseModel):
    position: int = Field(..., ge=1)
    beat_id: Optional[str] = Field(None, min_length=1, max_length=120)
    summary: str = Field(..., min_length=1)
    location: Optional[str] = None
    pov_character: Optional[str] = Field(None, min_length=1, max_length=120)
    pov_mode: Optional[PovMode] = Field(
        default=PovMode.SINGLE,
        description="V3.6 叙事视角模式：single/ensemble/omniscient"
    )
    pov_characters: List[str] = Field(
        default_factory=list,
        description="V3.6 ensemble/omniscient模式下的多视角角色列表"
    )
    pov_aperture: Optional[PovAperture] = Field(
        default=None,
        description="叙事光圈：internal_only/subjective_observation/systemic_sense"
    )
    persistent_state_anchors: Optional[List["PersistentStateAnchor"]] = Field(
        default=None,
        description="持久状态锚点列表"
    )
    action_summary: Optional[str] = None
    worldbuilding_instruction: Optional[str] = None
    entry_state: Optional[str] = Field(None, min_length=1)
    exit_state: Optional[str] = Field(None, min_length=1)
    red_lines: List[str] = Field(default_factory=list)
    word_count_target: int = Field(default=0, ge=0)
    target_words: int = Field(default=0, ge=0)
    hook_ids: List[str] = Field(default_factory=list)
    pacing_type: Optional[str] = Field(None, max_length=50)
    weight: Optional[int] = Field(default=1, ge=1)
    workflow_tier: Optional[WorkflowTier] = Field(
        default=None,
        description="工作流层级：TIER_1_FAST/TIER_2_STANDARD/TIER_3_FORTRESS"
    )


class GenerateChapterAgenticPreviewResponse(BaseModel):
    beats: List[ConfirmedStoryBeat] = Field(default_factory=list)
    debug_prompt: Optional[dict] = None


class GenerateChapterAgenticWithBeatsRequest(GenerateChapterAgenticRequest):
    beats: List[ConfirmedStoryBeat] = Field(..., min_length=1, max_length=6)

class ClarificationRequest(BaseModel):
    """
    Agent 澄清请求模型结构
    用于在生成或规划过程中，当 Agent 遇到歧义或缺失必要输入时向用户发起询问。
    """
    question: str = Field(..., description="向用户提出的澄清问题")
    options: Optional[List[str]] = Field(default=None, description="提供给用户的可选回答列表（如有）")
    context: Optional[str] = Field(default=None, description="提出该问题的背景上下文（向用户解释为什么需要澄清）")

class ClarificationResponse(BaseModel):
    """
    用户澄清响应模型结构
    用于接收并验证用户对 Agent 澄清请求的最终回答。
    """
    answer: str = Field(..., description="用户回答的具体内容")
    selected_option: Optional[str] = Field(default=None, description="用户选择的预设选项（如果请求中提供了 options）")

class ClarifyOutlineRequest(BaseModel):
    chapter_id: UUID
    ambiguous_text: str = Field(..., description="需要澄清的模糊文本或大纲")
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini", description="默认模型")
    author_intent: Optional[str] = Field(None, description="作者意图")
