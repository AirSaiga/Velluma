# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
统一配置对象模型 (Unified Generation Configuration)

职责：
- 定义章节生成的核心配置对象
- 将散乱的前端参数收敛为结构化对象
- 支持配置推导、校验、默认值填充

设计层次：
1. StoryConfig - 故事语义层（风格、主题、禁忌）
2. ChapterPlan - 章节规划层（大纲、意图、张力、节奏）
3. LLMConfig - 模型配置层（模型选择、推理配置）
4. RAGPolicy - 检索策略层（向量检索参数）
5. WorkflowPolicy - 工作流策略层（迭代、双轨、精修）
6. ValidationPolicy - 校验策略层（质检规则）
7. FeatureFlags - 功能开关（实验性功能）

使用方式：
    config = GenerationConfig.from_request(request, chapter, book)
    validated_config = config.validate_and_fill_defaults()
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable
from pydantic import BaseModel, Field, field_validator, model_validator
from uuid import UUID

from backend.schemas.enums import PacingStyle, WorkflowTier, ReasoningEffortLevel as ReasoningEffort


# =============================================================================
# 类型别名与枚举
# =============================================================================

class MemoryStrategy(str, Enum):
    """记忆检索策略预设"""
    RECENT_ONLY = "recent_only"        # 仅检索最近章节
    BALANCED_REFERENCE = "balanced_reference"  # 平衡参考
    DEEP_DIVE = "deep_dive"            # 深度挖掘


class CreativityLevel(str, Enum):
    """创作自由度预设"""
    STRICT_PROMPT = "strict_prompt"      # 严格遵循提示
    BALANCED_CREATION = "balanced_creation"  # 平衡创作
    WILD_IMAGINATION = "wild_imagination"   # 自由想象


class RefinementDepth(str, Enum):
    """精修深度预设"""
    LIGHT = "light"        # 轻度精修
    STANDARD = "standard"  # 标准精修
    DEEP = "deep"          # 深度精修


class EditorMode(str, Enum):
    """
    编辑模式
    
    V4.0+ 简化：仅保留意图驱动模式，前端统一使用创意模式
    """
    INTENT = "intent"  # 意图驱动模式（唯一模式）


# =============================================================================
# StoryConfig - 故事语义层
# =============================================================================

class StoryConfig(BaseModel):
    """
    故事语义配置 - 静态世界观与风格设定
    
    职责：
    - 定义故事的语义背景（风格、主题、禁忌）
    - 持久化存储于 Book 表
    - 跨章节稳定，不随章节变化
    
    字段来源：
    - genre: Book.genre
    - styleGuide: Book.global_sys_prompt
    - themesAndTaboos: Book.core_motifs_taboos
    - worldviewSettings: Book.worldview_settings
    """
    genre: str = Field(default="", description="故事类型：奇幻、科幻、都市等")
    style_guide: str = Field(default="", description="写作风格指南")
    themes_and_taboos: str = Field(default="", description="核心主题与禁忌")
    worldview_settings: Dict[str, Any] = Field(default_factory=dict, description="世界观设定集")
    golden_snippets: List[str] = Field(default_factory=list, description="金句模板")
    style_blacklist: List[str] = Field(default_factory=list, description="风格黑名单")
    
    # 推导字段
    style_complexity: float = Field(default=0.5, ge=0.0, le=1.0, description="风格复杂度（影响 prompt 长度）")
    
    @classmethod
    def from_book(cls, book: Any) -> "StoryConfig":
        """从 Book 实体构建配置"""
        return cls(
            genre=getattr(book, "genre", "") or "",
            style_guide=getattr(book, "global_sys_prompt", "") or "",
            themes_and_taboos=getattr(book, "core_motifs_taboos", "") or "",
            worldview_settings=getattr(book, "worldview_settings", {}) or {},
            golden_snippets=getattr(book, "golden_snippets", []) or [],
            style_blacklist=getattr(book, "style_blacklist", []) or [],
        )


# =============================================================================
# ChapterPlan - 章节规划层
# =============================================================================

class ChapterPlan(BaseModel):
    """
    章节规划配置 - 单章创作意图与约束
    
    职责：
    - 定义章节级别的创作意图
    - 控制张力、节奏、字数等核心参数
    - 部分持久化于 Chapter 表
    
    字段来源：
    - outline: Chapter.outline_text
    - authorIntent: 请求传入
    - tensionLevel: 请求传入 或 Chapter.tension_level
    - pacingStyle: 请求传入 或 Chapter.pacing_style
    """
    # 基础信息
    chapter_number: int = Field(..., ge=1, description="章节编号")
    title: str = Field(default="", description="章节标题")
    outline: str = Field(default="", description="章节大纲")
    
    # 创作意图
    author_intent: str = Field(default="", description="作者创作意图")
    target_word_count: int = Field(default=3000, ge=500, le=20000, description="目标字数")
    
    # 高层语义参数（前端传入或自动推导）
    tension_level: int = Field(default=3, ge=1, le=5, description="戏剧张力等级 (1-5)")
    pacing_style: PacingStyle = Field(default="balanced", description="节奏风格")
    forbidden_content: str = Field(default="", description="内容禁区")
    
    # 推导参数（后端自动计算）
    workflow_tier: WorkflowTier = Field(default="TIER_2_STANDARD", description="工作流层级（自动推导）")
    expected_iterations: int = Field(default=2, ge=1, le=5, description="预期迭代次数（自动推导）")
    
    @field_validator('tension_level', mode='before')
    @classmethod
    def clamp_tension_level(cls, v):
        if v is not None:
            try:
                return max(1, min(5, int(v)))
            except (ValueError, TypeError):
                return 3
        return v
    
    def derive_workflow_tier(self) -> WorkflowTier:
        """根据张力等级推导工作流层级"""
        if self.tension_level <= 2:
            return "TIER_1_FAST"
        elif self.tension_level == 3:
            return "TIER_2_STANDARD"
        else:
            return "TIER_3_FORTRESS"
    
    def derive_expected_iterations(self, fast_mode: bool = False) -> int:
        """推导预期迭代次数"""
        if fast_mode:
            return 1
        tier = self.workflow_tier
        if tier == "TIER_1_FAST":
            return 1
        elif tier == "TIER_2_STANDARD":
            return 2
        else:  # TIER_3_FORTRESS
            return 3
    
    @classmethod
    def from_chapter(cls, chapter: Any, request_data: Optional[dict] = None) -> "ChapterPlan":
        """从 Chapter 实体和请求数据构建配置"""
        request_data = request_data or {}
        return cls(
            chapter_number=getattr(chapter, "chapter_number", 1),
            title=getattr(chapter, "title", "") or getattr(chapter, "chapter_name", "") or "",
            outline=getattr(chapter, "outline_text", "") or "",
            author_intent=request_data.get("author_intent", "") or "",
            target_word_count=request_data.get("word_count") or getattr(chapter, "target_word_count", 3000) or 3000,
            tension_level=request_data.get("tension_level") or getattr(chapter, "tension_level", 3) or 3,
            pacing_style=request_data.get("pacing_style") or getattr(chapter, "pacing_style", "balanced") or "balanced",
            forbidden_content=request_data.get("forbidden_content", ""),
        )


# =============================================================================
# LLMConfig - 模型配置层
# =============================================================================

class ReasoningSettings(BaseModel):
    """推理模式配置"""
    enabled: bool = Field(default=False, description="是否启用推理模式")
    effort: ReasoningEffort = Field(default="medium", description="推理强度")
    max_tokens: Optional[int] = Field(default=None, ge=100, le=32000, description="推理 token 上限")
    exclude_process: bool = Field(default=False, description="是否排除推理过程")
    
    def to_api_params(self) -> dict:
        """转换为 API 调用参数"""
        if not self.enabled:
            return {}
        params = {"enabled": True}
        if self.effort:
            params["effort"] = self.effort
        if self.max_tokens is not None:
            params["max_tokens"] = self.max_tokens
        if self.exclude_process:
            params["exclude"] = True
        return {"reasoning": params}


class LLMConfig(BaseModel):
    """
    LLM 模型配置 - API 连接与模型选择
    
    职责：
    - 管理 LLM 调用的技术参数
    - 支持双模型架构（逻辑模型 + 创意模型）
    - 敏感字段不持久化
    
    字段来源：
    - api_key: 请求传入（必填，不持久化）
    - base_url: 请求传入（可选）
    - reasoning_model/creative_model: 请求传入
    """
    # API 连接（敏感字段）
    api_key: str = Field(..., min_length=1, description="LLM API Key")
    base_url: Optional[str] = Field(default=None, description="自定义 API 端点")
    
    # 模型选择
    default_model: str = Field(default="gpt-4o-mini", description="默认模型")
    reasoning_model: Optional[str] = Field(default=None, description="逻辑推理模型")
    creative_model: Optional[str] = Field(default=None, description="创意生成模型")
    
    # 推理配置（三个层级）
    default_reasoning_config: ReasoningSettings = Field(default_factory=ReasoningSettings)
    reasoning_model_config: ReasoningSettings = Field(default_factory=lambda: ReasoningSettings(effort="high"))
    creative_model_config: ReasoningSettings = Field(default_factory=lambda: ReasoningSettings(effort="low"))
    
    def get_effective_reasoning_model(self) -> str:
        """获取有效的逻辑模型"""
        return self.reasoning_model or self.default_model
    
    def get_effective_creative_model(self) -> str:
        """获取有效的创意模型"""
        return self.creative_model or self.reasoning_model or self.default_model
    
    def is_dual_model_mode(self) -> bool:
        """判断是否为双模型模式"""
        return self.reasoning_model is not None and self.creative_model is not None


# =============================================================================
# RAGPolicy - 检索策略层
# =============================================================================

class RAGPolicy(BaseModel):
    """
    RAG 检索策略配置
    
    职责：
    - 控制向量记忆检索行为
    - 支持策略预设和细粒度调整
    
    推导规则：
    - memory_strategy 决定基础参数
    - 高层语义可覆盖具体参数
    """
    # 策略预设（前端传入）
    memory_strategy: MemoryStrategy = Field(
        default=MemoryStrategy.BALANCED_REFERENCE,
        description="记忆检索策略预设"
    )
    
    # 细粒度参数（可由策略推导或手动覆盖）
    top_k: int = Field(default=5, ge=1, le=20, description="检索数量")
    semantic_weight: float = Field(default=0.6, ge=0.0, le=1.0, description="语义相似度权重")
    time_decay_weight: float = Field(default=0.2, ge=0.0, le=1.0, description="时间衰减权重")
    foreshadowing_weight: float = Field(default=0.2, ge=0.0, le=1.0, description="伏笔权重")
    decay_factor: float = Field(default=0.1, ge=0.0, description="时间衰减系数")
    
    # 推导参数
    enable_memory_injection: bool = Field(default=True, description="是否启用记忆注入")
    
    @model_validator(mode="after")
    def validate_weight_sum(self):
        """确保权重和为 1"""
        total = round(self.semantic_weight + self.time_decay_weight + self.foreshadowing_weight, 6)
        if abs(total - 1.0) > 1e-6:
            # 自动归一化
            scale = 1.0 / total
            self.semantic_weight = round(self.semantic_weight * scale, 6)
            self.time_decay_weight = round(self.time_decay_weight * scale, 6)
            self.foreshadowing_weight = round(self.foreshadowing_weight * scale, 6)
        return self
    
    def apply_strategy_preset(self) -> "RAGPolicy":
        """应用策略预设"""
        presets = {
            MemoryStrategy.RECENT_ONLY: {
                "top_k": 3,
                "semantic_weight": 0.4,
                "time_decay_weight": 0.5,
                "foreshadowing_weight": 0.1,
                "decay_factor": 0.3,
            },
            MemoryStrategy.BALANCED_REFERENCE: {
                "top_k": 5,
                "semantic_weight": 0.6,
                "time_decay_weight": 0.2,
                "foreshadowing_weight": 0.2,
                "decay_factor": 0.1,
            },
            MemoryStrategy.DEEP_DIVE: {
                "top_k": 10,
                "semantic_weight": 0.5,
                "time_decay_weight": 0.15,
                "foreshadowing_weight": 0.35,
                "decay_factor": 0.05,
            },
        }
        preset_values = presets.get(self.memory_strategy, {})
        for key, value in preset_values.items():
            if not getattr(self, f"_explicit_{key}", False):
                setattr(self, key, value)
        return self


# =============================================================================
# WorkflowPolicy - 工作流策略层
# =============================================================================

class DualTrackSettings(BaseModel):
    """双轨生成配置"""
    enable_sketch_track: bool = Field(default=True, description="启用 Sketch 轨道")
    enable_adversarial_alignment: bool = Field(default=True, description="启用对抗校对")
    use_sketch_for_refinement: bool = Field(default=True, description="使用 Sketch 指导精修")
    alignment_threshold: float = Field(default=70.0, ge=0.0, le=100.0, description="对齐阈值")
    sketch_ratio: float = Field(default=0.45, ge=0.2, le=0.7, description="Sketch 字数占比")


class WorkflowPolicy(BaseModel):
    """
    工作流策略配置
    
    职责：
    - 控制生成流程的行为
    - 管理迭代、双轨、并行等策略
    
    推导规则：
    - workflow_tier 决定基础策略
    - creativity_level 影响并行度
    - refinement_depth 影响精修强度
    """
    # 高层策略（前端传入）
    creativity_level: CreativityLevel = Field(
        default=CreativityLevel.BALANCED_CREATION,
        description="创作自由度"
    )
    refinement_depth: RefinementDepth = Field(
        default=RefinementDepth.STANDARD,
        description="精修深度"
    )
    
    # 迭代控制
    max_iterations: int = Field(default=2, ge=1, le=5, description="最大迭代次数")
    fast_mode: bool = Field(default=False, description="快速模式")
    skip_minor_refine: bool = Field(default=True, description="跳过轻微问题的精修")
    
    # 并行控制
    force_parallel_prose: bool = Field(default=False, description="强制并行起草")
    semi_parallel_prose: bool = Field(default=True, description="半并行模式")
    beat_concurrency: int = Field(default=6, ge=1, le=12, description="Beat 并行度")
    
    # 双轨配置
    dual_track: DualTrackSettings = Field(default_factory=DualTrackSettings)
    
    def derive_from_tier(self, tier: WorkflowTier) -> "WorkflowPolicy":
        """根据工作流层级推导策略"""
        if tier == "TIER_1_FAST":
            self.max_iterations = 1
            self.fast_mode = True
            self.skip_minor_refine = True
            self.dual_track.enable_sketch_track = False
            self.dual_track.enable_adversarial_alignment = False
        elif tier == "TIER_2_STANDARD":
            self.max_iterations = 2
            self.fast_mode = False
            self.dual_track.enable_sketch_track = True
            self.dual_track.enable_adversarial_alignment = True
        else:  # TIER_3_FORTRESS
            self.max_iterations = 3
            self.fast_mode = False
            self.skip_minor_refine = False
            self.dual_track.enable_sketch_track = True
            self.dual_track.enable_adversarial_alignment = True
            self.dual_track.alignment_threshold = 80.0
        return self
    
    def derive_from_creativity(self) -> "WorkflowPolicy":
        """根据创作自由度推导策略"""
        if self.creativity_level == CreativityLevel.STRICT_PROMPT:
            self.force_parallel_prose = False
            self.semi_parallel_prose = False
        elif self.creativity_level == CreativityLevel.WILD_IMAGINATION:
            self.force_parallel_prose = True
            self.semi_parallel_prose = True
        return self
    
    def derive_from_refinement_depth(self) -> "WorkflowPolicy":
        """
        V4.0: 根据精修深度推导迭代次数
        
        推导规则：
        - light: max_iterations = 1
        - standard: max_iterations = 2
        - deep: max_iterations = 4
        """
        depth_iterations = {
            RefinementDepth.LIGHT: 1,
            RefinementDepth.STANDARD: 2,
            RefinementDepth.DEEP: 4,
        }
        if self.refinement_depth in depth_iterations:
            self.max_iterations = depth_iterations[self.refinement_depth]
        return self


# =============================================================================
# ValidationPolicy - 校验策略层
# =============================================================================

class ValidationPolicy(BaseModel):
    """
    校验策略配置
    
    职责：
    - 控制质检规则和阈值
    - 管理 Fail-Fast 机制
    """
    # Fail-Fast 机制
    enable_fail_fast: bool = Field(default=True, description="启用即时断言检查")
    fail_fast_max_attempts: int = Field(default=2, ge=1, le=3, description="Fail-Fast 最大重试次数")
    fail_fast_temperature_step: float = Field(default=0.2, ge=0.0, le=0.5, description="每次重试温度增量")
    
    # 情绪暂存器
    enable_emotional_scratchpad: bool = Field(default=True, description="启用情绪暂存器更新")
    
    # 校验阈值
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="质量阈值")
    consistency_threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="一致性阈值")
    
    def derive_from_tier(self, tier: WorkflowTier) -> "ValidationPolicy":
        """根据工作流层级推导校验策略"""
        if tier == "TIER_1_FAST":
            self.enable_fail_fast = False
            self.quality_threshold = 0.6
        elif tier == "TIER_2_STANDARD":
            self.enable_fail_fast = True
            self.quality_threshold = 0.7
        else:  # TIER_3_FORTRESS
            self.enable_fail_fast = True
            self.fail_fast_max_attempts = 3
            self.quality_threshold = 0.8
            self.consistency_threshold = 0.9
        return self


# =============================================================================
# FeatureFlags - 功能开关
# =============================================================================

class FeatureFlags(BaseModel):
    """
    功能开关配置
    
    职责：
    - 控制实验性功能
    - 支持灰度发布
    """
    enable_whisper_memory: bool = Field(default=False, description="RAG 记忆暂存（预留）")
    enable_worldbuilding_injection: bool = Field(default=True, description="世界观注入")
    enable_cross_chapter_validation: bool = Field(default=True, description="跨章校验")
    enable_dynamic_state_update: bool = Field(default=True, description="动态状态更新")


# =============================================================================
# GenerationConfig - 统一配置容器
# =============================================================================

class GenerationConfig(BaseModel):
    """
    统一生成配置容器
    
    职责：
    - 聚合所有配置对象
    - 提供配置推导和校验入口
    - 作为生成服务的唯一输入契约
    
    使用方式：
        config = GenerationConfig.from_request(request, chapter, book)
        config.derive_all()  # 执行所有推导
        config.validate_all()  # 执行所有校验
    """
    # 元信息
    editor_mode: EditorMode = Field(default=EditorMode.INTENT, description="编辑模式")
    chapter_id: Optional[UUID] = Field(default=None, description="章节 ID")
    book_id: Optional[UUID] = Field(default=None, description="书籍 ID")
    
    # 核心配置对象
    story: StoryConfig = Field(default_factory=StoryConfig)
    chapter: ChapterPlan = Field(default_factory=ChapterPlan)
    llm: Optional[LLMConfig] = Field(default=None, description="LLM 配置（含敏感字段，不持久化）")
    rag: RAGPolicy = Field(default_factory=RAGPolicy)
    workflow: WorkflowPolicy = Field(default_factory=WorkflowPolicy)
    validation: ValidationPolicy = Field(default_factory=ValidationPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    
    # 运行时数据（不从请求获取）
    runtime_data: Dict[str, Any] = Field(default_factory=dict, description="运行时数据占位")
    
    @classmethod
    def from_request(
        cls,
        request: Any,
        chapter: Optional[Any] = None,
        book: Optional[Any] = None,
    ) -> "GenerationConfig":
        """
        从请求数据构建配置
        
        Args:
            request: 前端请求对象（Pydantic 模型或字典）
            chapter: Chapter 实体（可选，用于填充默认值）
            book: Book 实体（可选，用于填充默认值）
        
        Returns:
            GenerationConfig: 统一配置对象
        """
        # 提取请求数据
        if hasattr(request, "model_dump"):
            req_dict = request.model_dump()
        elif hasattr(request, "dict"):
            req_dict = request.dict()
        else:
            req_dict = dict(request) if request else {}
        
        # 构建 StoryConfig
        story_config = StoryConfig.from_book(book) if book else StoryConfig()
        
        # 构建 ChapterPlan
        chapter_plan = ChapterPlan.from_chapter(chapter, req_dict) if chapter else ChapterPlan(
            chapter_number=req_dict.get("chapter_number", 1),
            title=req_dict.get("title", ""),
            outline=req_dict.get("outline_text", "") or req_dict.get("outline", ""),
            author_intent=req_dict.get("author_intent", ""),
            target_word_count=req_dict.get("word_count", 3000),
            tension_level=req_dict.get("tension_level", 3),
            pacing_style=req_dict.get("pacing_style", "balanced"),
        )
        
        # 构建 LLMConfig
        llm_config = None
        if req_dict.get("api_key"):
            llm_config = LLMConfig(
                api_key=req_dict["api_key"],
                base_url=req_dict.get("base_url"),
                default_model=req_dict.get("model", "gpt-4o-mini"),
                reasoning_model=req_dict.get("reasoning_model"),
                creative_model=req_dict.get("creative_model"),
                default_reasoning_config=_parse_reasoning_config(req_dict.get("reasoning_config")),
                reasoning_model_config=_parse_reasoning_config(req_dict.get("reasoning_model_reasoning_config")),
                creative_model_config=_parse_reasoning_config(req_dict.get("creative_model_reasoning_config")),
            )
        
        # 构建 RAGPolicy
        memory_strategy = req_dict.get("memory_strategy", "balanced_reference")
        if isinstance(memory_strategy, str):
            try:
                memory_strategy = MemoryStrategy(memory_strategy)
            except ValueError:
                memory_strategy = MemoryStrategy.BALANCED_REFERENCE
        
        rag_policy = RAGPolicy(
            memory_strategy=memory_strategy,
            top_k=req_dict.get("rag_top_k", 5),
            semantic_weight=req_dict.get("rag_alpha", 0.6),
            time_decay_weight=req_dict.get("rag_beta", 0.2),
            foreshadowing_weight=req_dict.get("rag_gamma", 0.2),
            decay_factor=req_dict.get("rag_lambda", 0.1),
        )
        
        # 构建 WorkflowPolicy
        creativity_level = req_dict.get("creativity_level", "balanced_creation")
        if isinstance(creativity_level, str):
            try:
                creativity_level = CreativityLevel(creativity_level)
            except ValueError:
                creativity_level = CreativityLevel.BALANCED_CREATION
        
        refinement_depth = req_dict.get("refinement_depth", "standard")
        if isinstance(refinement_depth, str):
            try:
                refinement_depth = RefinementDepth(refinement_depth)
            except ValueError:
                refinement_depth = RefinementDepth.STANDARD
        
        dual_track_data = req_dict.get("dual_track", {})
        workflow_policy = WorkflowPolicy(
            creativity_level=creativity_level,
            refinement_depth=refinement_depth,
            max_iterations=req_dict.get("max_iterations", 2),
            fast_mode=req_dict.get("fast_mode", False),
            skip_minor_refine=req_dict.get("skip_minor_refine", True),
            force_parallel_prose=req_dict.get("force_parallel_prose", False),
            semi_parallel_prose=req_dict.get("semi_parallel_prose", True),
            beat_concurrency=req_dict.get("beat_concurrency", 6),
            dual_track=DualTrackSettings(
                enable_sketch_track=req_dict.get("enable_sketch_track", True),
                enable_adversarial_alignment=req_dict.get("enable_adversarial_alignment", True),
                use_sketch_for_refinement=req_dict.get("use_sketch_for_refinement", True),
                alignment_threshold=req_dict.get("alignment_threshold", 70.0),
                sketch_ratio=req_dict.get("sketch_ratio", 0.45),
            ),
        )
        
        # 构建 ValidationPolicy
        feature_flags_data = req_dict.get("feature_flags", {})
        validation_policy = ValidationPolicy(
            enable_fail_fast=feature_flags_data.get("enable_fail_fast", True),
            fail_fast_max_attempts=feature_flags_data.get("fail_fast_max_attempts", 2),
            fail_fast_temperature_step=feature_flags_data.get("fail_fast_temperature_step", 0.2),
            enable_emotional_scratchpad=feature_flags_data.get("enable_emotional_scratchpad", True),
        )
        
        # 构建 FeatureFlags
        feature_flags = FeatureFlags(
            enable_whisper_memory=feature_flags_data.get("enable_whisper_memory", False),
            enable_worldbuilding_injection=req_dict.get("enable_worldbuilding_injection", True),
            enable_cross_chapter_validation=req_dict.get("enable_cross_chapter_validation", True),
        )
        
        # V4.0+: 编辑模式已简化为仅保留意图驱动模式
        # 忽略 expert_mode 参数，统一使用 INTENT 模式
        editor_mode = EditorMode.INTENT
        
        return cls(
            editor_mode=editor_mode,
            chapter_id=req_dict.get("chapter_id"),
            book_id=getattr(book, "id", None) if book else None,
            story=story_config,
            chapter=chapter_plan,
            llm=llm_config,
            rag=rag_policy,
            workflow=workflow_policy,
            validation=validation_policy,
            features=feature_flags,
        )
    
    def derive_all(self) -> "GenerationConfig":
        """
        执行所有推导
        
        推导顺序：
        1. 根据张力等级推导工作流层级
        2. 根据工作流层级推导工作流策略
        3. 根据工作流层级推导校验策略
        4. 根据记忆策略推导 RAG 参数
        5. 推导预期迭代次数
        """
        # 1. 推导工作流层级
        self.chapter.workflow_tier = self.chapter.derive_workflow_tier()
        
        # 2. 推导工作流策略
        self.workflow.derive_from_tier(self.chapter.workflow_tier)
        self.workflow.derive_from_creativity()
        
        # 3. 推导校验策略
        self.validation.derive_from_tier(self.chapter.workflow_tier)
        
        # 4. 推导 RAG 参数
        self.rag.apply_strategy_preset()
        
        # 5. 推导预期迭代次数
        self.chapter.expected_iterations = self.chapter.derive_expected_iterations(
            fast_mode=self.workflow.fast_mode
        )
        
        return self
    
    def validate_all(self) -> "GenerationConfig":
        """执行所有校验"""
        # 权重和校验在 RAGPolicy 中已自动处理
        return self


def _parse_reasoning_config(data: Optional[dict]) -> ReasoningSettings:
    """解析推理配置"""
    if not data:
        return ReasoningSettings()
    return ReasoningSettings(
        enabled=data.get("enabled", False),
        effort=data.get("effort", "medium"),
        max_tokens=data.get("max_tokens"),
        exclude_process=data.get("exclude", False),
    )
