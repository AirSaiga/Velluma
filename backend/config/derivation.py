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
配置推导引擎 (Configuration Derivation Engine)

职责：
- 从高层语义输入推导底层技术参数
- 实现策略预设与参数覆盖规则
- 提供默认值填充与校验

推导规则设计：
1. 张力等级 → 工作流层级
2. 工作流层级 → 迭代次数、双轨配置、校验强度
3. 记忆策略 → RAG 参数
4. 创作自由度 → 并行策略
5. 精修深度 → 校验阈值

使用方式：
    engine = DerivationEngine()
    derived_config = engine.derive(raw_config)
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import logging

from backend.config.schemas.generation_config import (
    GenerationConfig,
    StoryConfig,
    ChapterPlan,
    LLMConfig,
    RAGPolicy,
    WorkflowPolicy,
    ValidationPolicy,
    FeatureFlags,
    DualTrackSettings,
    ReasoningSettings,
    MemoryStrategy,
    CreativityLevel,
    RefinementDepth,
    WorkflowTier,
    PacingStyle,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 推导规则定义
# =============================================================================

@dataclass
class DerivationRule:
    """推导规则定义"""
    name: str
    source_field: str
    target_field: str
    mapping: Dict[Any, Any]
    default: Any = None
    description: str = ""


# 张力等级 → 工作流层级映射
TENSION_TO_TIER_RULE = DerivationRule(
    name="tension_to_tier",
    source_field="tension_level",
    target_field="workflow_tier",
    mapping={
        1: "TIER_1_FAST",
        2: "TIER_1_FAST",
        3: "TIER_2_STANDARD",
        4: "TIER_3_FORTRESS",
        5: "TIER_3_FORTRESS",
    },
    default="TIER_2_STANDARD",
    description="根据张力等级推导工作流层级",
)

# 工作流层级 → 迭代次数映射
TIER_TO_ITERATIONS_RULE = DerivationRule(
    name="tier_to_iterations",
    source_field="workflow_tier",
    target_field="max_iterations",
    mapping={
        "TIER_1_FAST": 1,
        "TIER_2_STANDARD": 2,
        "TIER_3_FORTRESS": 3,
    },
    default=2,
    description="根据工作流层级推导最大迭代次数",
)

# 工作流层级 → 双轨启用映射
TIER_TO_DUAL_TRACK_RULE = DerivationRule(
    name="tier_to_dual_track",
    source_field="workflow_tier",
    target_field="enable_dual_track",
    mapping={
        "TIER_1_FAST": False,
        "TIER_2_STANDARD": True,
        "TIER_3_FORTRESS": True,
    },
    default=True,
    description="根据工作流层级推导是否启用双轨",
)

# 记忆策略 → RAG 参数预设
MEMORY_STRATEGY_PRESETS = {
    MemoryStrategy.RECENT_ONLY: {
        "top_k": 3,
        "semantic_weight": 0.4,
        "time_decay_weight": 0.5,
        "foreshadowing_weight": 0.1,
        "decay_factor": 0.3,
        "enable_memory_injection": True,
    },
    MemoryStrategy.BALANCED_REFERENCE: {
        "top_k": 5,
        "semantic_weight": 0.6,
        "time_decay_weight": 0.2,
        "foreshadowing_weight": 0.2,
        "decay_factor": 0.1,
        "enable_memory_injection": True,
    },
    MemoryStrategy.DEEP_DIVE: {
        "top_k": 10,
        "semantic_weight": 0.5,
        "time_decay_weight": 0.15,
        "foreshadowing_weight": 0.35,
        "decay_factor": 0.05,
        "enable_memory_injection": True,
    },
}

# 创作自由度 → 并行策略映射
CREATIVITY_TO_PARALLEL_RULE = DerivationRule(
    name="creativity_to_parallel",
    source_field="creativity_level",
    target_field="parallel_mode",
    mapping={
        CreativityLevel.STRICT_PROMPT: "sequential",
        CreativityLevel.BALANCED_CREATION: "semi_parallel",
        CreativityLevel.WILD_IMAGINATION: "full_parallel",
    },
    default="semi_parallel",
    description="根据创作自由度推导并行模式",
)

# 精修深度 → 校验阈值映射
REFINEMENT_TO_THRESHOLD_RULE = DerivationRule(
    name="refinement_to_threshold",
    source_field="refinement_depth",
    target_field="quality_threshold",
    mapping={
        RefinementDepth.LIGHT: 0.6,
        RefinementDepth.STANDARD: 0.7,
        RefinementDepth.DEEP: 0.85,
    },
    default=0.7,
    description="根据精修深度推导质量阈值",
)

# 张力等级 + 节奏风格 → 字数分配权重
PACING_WEIGHT_MATRIX = {
    ("slow_burn", 1): 1.2,
    ("slow_burn", 2): 1.1,
    ("slow_burn", 3): 1.0,
    ("slow_burn", 4): 0.9,
    ("slow_burn", 5): 0.8,
    ("balanced", 1): 1.0,
    ("balanced", 2): 1.0,
    ("balanced", 3): 1.0,
    ("balanced", 4): 1.0,
    ("balanced", 5): 1.0,
    ("fast_paced", 1): 0.8,
    ("fast_paced", 2): 0.9,
    ("fast_paced", 3): 1.0,
    ("fast_paced", 4): 1.1,
    ("fast_paced", 5): 1.2,
}


# =============================================================================
# 推导引擎
# =============================================================================

class DerivationEngine:
    """
    配置推导引擎
    
    职责：
    - 执行所有推导规则
    - 处理策略预设与覆盖
    - 验证推导结果
    """
    
    def __init__(self):
        self._rules = [
            TENSION_TO_TIER_RULE,
            TIER_TO_ITERATIONS_RULE,
            TIER_TO_DUAL_TRACK_RULE,
            CREATIVITY_TO_PARALLEL_RULE,
            REFINEMENT_TO_THRESHOLD_RULE,
        ]
        self._derivation_log: List[Dict[str, Any]] = []
    
    def derive(self, config: GenerationConfig) -> GenerationConfig:
        """
        执行完整推导流程
        
        Args:
            config: 原始配置
        
        Returns:
            GenerationConfig: 推导后的配置
        """
        self._derivation_log = []
        
        # 1. 推导工作流层级
        self._derive_workflow_tier(config)
        
        # 2. 推导迭代相关参数
        self._derive_iteration_params(config)
        
        # 3. 推导双轨配置
        self._derive_dual_track_config(config)
        
        # 4. 推导 RAG 参数
        self._derive_rag_params(config)
        
        # 5. 推导并行策略
        self._derive_parallel_strategy(config)
        
        # 6. 推导校验阈值
        self._derive_validation_params(config)
        
        # 7. 推导字数分配
        self._derive_word_allocation(config)
        
        # 8. 记录推导结果
        if self._derivation_log:
            logger.debug(f"[DerivationEngine] 推导完成: {len(self._derivation_log)} 项")
        
        return config
    
    def _derive_workflow_tier(self, config: GenerationConfig) -> None:
        """推导工作流层级"""
        tension = config.chapter.tension_level
        tier = TENSION_TO_TIER_RULE.mapping.get(tension, TENSION_TO_TIER_RULE.default)
        config.chapter.workflow_tier = tier
        
        self._log_derivation(
            "tension_to_tier",
            f"tension_level={tension} → workflow_tier={tier}"
        )
    
    def _derive_iteration_params(self, config: GenerationConfig) -> None:
        """推导迭代参数"""
        tier = config.chapter.workflow_tier
        
        # 如果已是 fast_mode，迭代次数强制为 1
        if config.workflow.fast_mode:
            config.chapter.expected_iterations = 1
            self._log_derivation(
                "fast_mode_override",
                "fast_mode=True → iterations=1"
            )
            return
        
        # 根据层级推导迭代次数
        iterations = TIER_TO_ITERATIONS_RULE.mapping.get(tier, TIER_TO_ITERATIONS_RULE.default)
        config.workflow.max_iterations = iterations
        config.chapter.expected_iterations = iterations
        
        self._log_derivation(
            "tier_to_iterations",
            f"workflow_tier={tier} → max_iterations={iterations}"
        )
    
    def _derive_dual_track_config(self, config: GenerationConfig) -> None:
        """推导双轨配置"""
        tier = config.chapter.workflow_tier
        
        # TIER_1_FAST 不启用双轨
        if tier == "TIER_1_FAST":
            config.workflow.dual_track.enable_sketch_track = False
            config.workflow.dual_track.enable_adversarial_alignment = False
            self._log_derivation(
                "tier_to_dual_track",
                f"workflow_tier={tier} → dual_track disabled"
            )
        else:
            config.workflow.dual_track.enable_sketch_track = True
            config.workflow.dual_track.enable_adversarial_alignment = True
            
            # TIER_3_FORTRESS 使用更严格的对齐阈值
            if tier == "TIER_3_FORTRESS":
                config.workflow.dual_track.alignment_threshold = 80.0
                config.workflow.dual_track.use_sketch_for_refinement = True
            
            self._log_derivation(
                "tier_to_dual_track",
                f"workflow_tier={tier} → dual_track enabled, threshold={config.workflow.dual_track.alignment_threshold}"
            )
    
    def _derive_rag_params(self, config: GenerationConfig) -> None:
        """推导 RAG 参数"""
        strategy = config.rag.memory_strategy
        preset = MEMORY_STRATEGY_PRESETS.get(strategy, {})
        
        # 只覆盖未被显式设置的参数
        if preset:
            # 检查是否使用了默认值（而非显式设置）
            if config.rag.top_k == 5:  # 默认值
                config.rag.top_k = preset.get("top_k", 5)
            if abs(config.rag.semantic_weight - 0.6) < 1e-6:  # 默认值
                config.rag.semantic_weight = preset.get("semantic_weight", 0.6)
            if abs(config.rag.time_decay_weight - 0.2) < 1e-6:  # 默认值
                config.rag.time_decay_weight = preset.get("time_decay_weight", 0.2)
            if abs(config.rag.foreshadowing_weight - 0.2) < 1e-6:  # 默认值
                config.rag.foreshadowing_weight = preset.get("foreshadowing_weight", 0.2)
            
            config.rag.decay_factor = preset.get("decay_factor", 0.1)
            config.rag.enable_memory_injection = preset.get("enable_memory_injection", True)
            
            self._log_derivation(
                "rag_strategy_preset",
                f"memory_strategy={strategy.value} → top_k={config.rag.top_k}"
            )
        
        # 归一化权重
        config.rag.model_validate(config.rag.model_dump())
    
    def _derive_parallel_strategy(self, config: GenerationConfig) -> None:
        """推导并行策略"""
        creativity = config.workflow.creativity_level
        parallel_mode = CREATIVITY_TO_PARALLEL_RULE.mapping.get(
            creativity, CREATIVITY_TO_PARALLEL_RULE.default
        )
        
        if parallel_mode == "sequential":
            config.workflow.force_parallel_prose = False
            config.workflow.semi_parallel_prose = False
        elif parallel_mode == "full_parallel":
            config.workflow.force_parallel_prose = True
            config.workflow.semi_parallel_prose = True
        else:  # semi_parallel
            config.workflow.force_parallel_prose = False
            config.workflow.semi_parallel_prose = True
        
        self._log_derivation(
            "creativity_to_parallel",
            f"creativity_level={creativity.value} → parallel_mode={parallel_mode}"
        )
    
    def _derive_validation_params(self, config: GenerationConfig) -> None:
        """推导校验参数"""
        refinement = config.workflow.refinement_depth
        threshold = REFINEMENT_TO_THRESHOLD_RULE.mapping.get(
            refinement, REFINEMENT_TO_THRESHOLD_RULE.default
        )
        config.validation.quality_threshold = threshold
        
        # 根据工作流层级调整 Fail-Fast
        tier = config.chapter.workflow_tier
        if tier == "TIER_1_FAST":
            config.validation.enable_fail_fast = False
        elif tier == "TIER_3_FORTRESS":
            config.validation.enable_fail_fast = True
            config.validation.fail_fast_max_attempts = 3
        
        self._log_derivation(
            "refinement_to_threshold",
            f"refinement_depth={refinement.value} → quality_threshold={threshold}"
        )
    
    def _derive_word_allocation(self, config: GenerationConfig) -> None:
        """推导字数分配策略"""
        pacing = config.chapter.pacing_style
        tension = config.chapter.tension_level
        weight = PACING_WEIGHT_MATRIX.get((pacing, tension), 1.0)
        
        # 存储到运行时数据
        config.runtime_data["pacing_weight"] = weight
        
        self._log_derivation(
            "pacing_weight",
            f"pacing={pacing}, tension={tension} → weight={weight}"
        )
    
    def _log_derivation(self, rule_name: str, result: str) -> None:
        """记录推导日志"""
        self._derivation_log.append({
            "rule": rule_name,
            "result": result,
        })
    
    def get_derivation_log(self) -> List[Dict[str, Any]]:
        """获取推导日志"""
        return self._derivation_log.copy()


# =============================================================================
# 参数映射器
# =============================================================================

class ParameterMapper:
    """
    参数映射器
    
    职责：
    - 将前端请求参数映射到统一配置对象
    - 处理字段名转换（友好命名 → 技术命名）
    - 处理类型转换与默认值填充
    """
    
    # 前端友好命名 → 后端技术命名映射
    FIELD_MAPPING = {
        # StoryConfig
        "styleGuide": "style_guide",
        "themesAndTaboos": "themes_and_taboos",
        "worldviewSettings": "worldview_settings",
        
        # ChapterPlan
        "targetWordCount": "target_word_count",
        "authorIntent": "author_intent",
        "tensionLevel": "tension_level",
        "pacingStyle": "pacing_style",
        "forbiddenContent": "forbidden_content",
        "workflowTier": "workflow_tier",
        "expectedIterations": "expected_iterations",
        
        # LLMConfig
        "baseUrl": "base_url",
        "defaultModel": "default_model",
        "reasoningModel": "reasoning_model",
        "creativeModel": "creative_model",
        "reasoningConfig": "default_reasoning_config",
        
        # RAGPolicy
        "topK": "top_k",
        "semanticWeight": "semantic_weight",
        "timeDecayWeight": "time_decay_weight",
        "foreshadowingWeight": "foreshadowing_weight",
        "decayFactor": "decay_factor",
        "enableMemoryInjection": "enable_memory_injection",
        
        # WorkflowPolicy
        "maxIterations": "max_iterations",
        "fastMode": "fast_mode",
        "skipMinorRefine": "skip_minor_refine",
        "forceParallelProse": "force_parallel_prose",
        "semiParallelProse": "semi_parallel_prose",
        "beatConcurrency": "beat_concurrency",
        "creativityLevel": "creativity_level",
        "refinementDepth": "refinement_depth",
        
        # DualTrackSettings
        "enableSketchTrack": "enable_sketch_track",
        "enableAdversarialAlignment": "enable_adversarial_alignment",
        "useSketchForRefinement": "use_sketch_for_refinement",
        "alignmentThreshold": "alignment_threshold",
        "sketchRatio": "sketch_ratio",
        
        # ValidationPolicy
        "enableFailFast": "enable_fail_fast",
        "failFastMaxAttempts": "fail_fast_max_attempts",
        "failFastTemperatureStep": "fail_fast_temperature_step",
        "enableEmotionalScratchpad": "enable_emotional_scratchpad",
        "qualityThreshold": "quality_threshold",
        "consistencyThreshold": "consistency_threshold",
        
        # FeatureFlags
        "enableWhisperMemory": "enable_whisper_memory",
        "enableWorldbuildingInjection": "enable_worldbuilding_injection",
        "enableCrossChapterValidation": "enable_cross_chapter_validation",
        "enableDynamicStateUpdate": "enable_dynamic_state_update",
        
        # ReasoningSettings
        "excludeProcess": "exclude_process",
    }
    
    # 默认值表
    DEFAULTS = {
        "tension_level": 3,
        "pacing_style": "balanced",
        "target_word_count": 3000,
        "max_iterations": 2,
        "top_k": 5,
        "semantic_weight": 0.6,
        "time_decay_weight": 0.2,
        "foreshadowing_weight": 0.2,
        "decay_factor": 0.1,
        "quality_threshold": 0.7,
        "beat_concurrency": 6,
        "alignment_threshold": 70.0,
        "sketch_ratio": 0.45,
    }
    
    @classmethod
    def map_request_to_config(
        cls,
        request_data: Dict[str, Any],
        chapter: Optional[Any] = None,
        book: Optional[Any] = None,
    ) -> GenerationConfig:
        """
        将请求字典映射到配置对象
        
        Args:
            request_data: 前端请求字典
            chapter: Chapter 实体
            book: Book 实体
        
        Returns:
            GenerationConfig: 统一配置对象
        """
        # 1. 转换字段名
        normalized = cls._normalize_field_names(request_data)
        
        # 2. 填充默认值
        filled = cls._fill_defaults(normalized)
        
        # 3. 构建配置对象
        config = GenerationConfig.from_request(filled, chapter, book)
        
        return config
    
    @classmethod
    def _normalize_field_names(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """转换字段名"""
        result = {}
        for key, value in data.items():
            # 检查是否有映射
            mapped_key = cls.FIELD_MAPPING.get(key, key)
            # 转换为下划线命名（处理驼峰）
            if mapped_key == key and any(c.isupper() for c in key):
                mapped_key = cls._camel_to_snake(key)
            result[mapped_key] = value
        return result
    
    @classmethod
    def _fill_defaults(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """填充默认值"""
        result = data.copy()
        for key, default_value in cls.DEFAULTS.items():
            if key not in result or result[key] is None:
                result[key] = default_value
        return result
    
    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """驼峰转下划线"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# =============================================================================
# 配置验证器
# =============================================================================

class ConfigValidator:
    """
    配置验证器
    
    职责：
    - 校验配置完整性和一致性
    - 检查参数范围和依赖关系
    - 收集验证错误
    """
    
    @classmethod
    def validate(cls, config: GenerationConfig) -> Tuple[bool, List[str]]:
        """
        验证配置
        
        Args:
            config: 统一配置对象
        
        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误列表)
        """
        errors = []
        
        # 1. 验证 LLM 配置
        if config.llm:
            if not config.llm.api_key:
                errors.append("api_key 不能为空")
        else:
            errors.append("LLM 配置缺失")
        
        # 2. 验证章节配置
        if config.chapter.target_word_count < 500:
            errors.append("目标字数不能少于 500")
        if config.chapter.target_word_count > 20000:
            errors.append("目标字数不能超过 20000")
        
        # 3. 验证张力等级
        if not 1 <= config.chapter.tension_level <= 5:
            errors.append("张力等级必须在 1-5 之间")
        
        # 4. 验证 RAG 权重和
        total_weight = (
            config.rag.semantic_weight + 
            config.rag.time_decay_weight + 
            config.rag.foreshadowing_weight
        )
        if abs(total_weight - 1.0) > 1e-6:
            errors.append(f"RAG 权重和必须为 1.0，当前为 {total_weight:.4f}")
        
        # 5. 验证迭代次数
        if config.workflow.max_iterations < 1 or config.workflow.max_iterations > 5:
            errors.append("迭代次数必须在 1-5 之间")
        
        # 6. 验证工作流层级与迭代次数一致性
        expected_iterations = {
            "TIER_1_FAST": 1,
            "TIER_2_STANDARD": 2,
            "TIER_3_FORTRESS": 3,
        }.get(config.chapter.workflow_tier, 2)
        
        if not config.workflow.fast_mode and config.workflow.max_iterations < expected_iterations:
            errors.append(
                f"工作流层级 {config.chapter.workflow_tier} 建议至少 {expected_iterations} 次迭代"
            )
        
        return len(errors) == 0, errors
    
    @classmethod
    def validate_for_generation(cls, config: GenerationConfig) -> Tuple[bool, List[str]]:
        """
        验证生成前配置（更严格）
        
        Args:
            config: 统一配置对象
        
        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误列表)
        """
        valid, errors = cls.validate(config)
        
        if not valid:
            return False, errors
        
        # 额外的生成前检查
        if not config.chapter_id:
            errors.append("chapter_id 不能为空")
        
        if not config.chapter.outline:
            errors.append("章节大纲不能为空")
        
        return len(errors) == 0, errors


# =============================================================================
# 便捷函数
# =============================================================================

def derive_config(
    request: Any,
    chapter: Optional[Any] = None,
    book: Optional[Any] = None,
) -> GenerationConfig:
    """
    便捷函数：从请求推导完整配置
    
    Args:
        request: 前端请求对象
        chapter: Chapter 实体
        book: Book 实体
    
    Returns:
        GenerationConfig: 完整推导后的配置
    """
    # 1. 映射参数
    if hasattr(request, "model_dump"):
        request_data = request.model_dump()
    elif hasattr(request, "dict"):
        request_data = request.dict()
    else:
        request_data = dict(request) if request else {}
    
    config = ParameterMapper.map_request_to_config(request_data, chapter, book)
    
    # 2. 执行推导
    engine = DerivationEngine()
    config = engine.derive(config)
    
    # 3. 验证
    valid, errors = ConfigValidator.validate(config)
    if not valid:
        logger.warning(f"[derive_config] 配置验证警告: {errors}")
    
    return config
