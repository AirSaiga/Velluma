"""
配置推导引擎模块。

职责：执行配置推导逻辑。

包含：
- DerivationEngine: 配置推导引擎

使用场景：
- backend/services/workflow/: 工作流模块使用推导引擎
"""

import logging
from typing import Any, Dict, List, Optional

from backend.schemas import WorkflowTier
from backend.config.schemas import GenerationConfig, MemoryStrategy

from backend.config.rules import (
    TENSION_TO_TIER_RULE,
    TIER_TO_ITERATIONS_RULE,
    TIER_TO_DUAL_TRACK_RULE,
    MEMORY_STRATEGY_PRESETS,
    CREATIVITY_TO_PARALLEL_RULE,
    REFINEMENT_TO_THRESHOLD_RULE,
)

logger = logging.getLogger(__name__)


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

        self._derive_workflow_tier(config)

        self._derive_iteration_params(config)

        self._derive_dual_track_config(config)

        self._derive_rag_params(config)

        return config

    def _derive_workflow_tier(self, config: GenerationConfig) -> None:
        """推导工作流层级"""
        if config.workflow_tier:
            return

        if config.tension_level:
            config.workflow_tier = self._apply_rule(
                TENSION_TO_TIER_RULE, config.tension_level, config
            )

        if not config.workflow_tier:
            config.workflow_tier = "TIER_2_STANDARD"

    def _derive_iteration_params(self, config: GenerationConfig) -> None:
        """推导迭代相关参数"""
        if config.workflow_tier and not config.max_iterations:
            config.max_iterations = self._apply_rule(
                TIER_TO_ITERATIONS_RULE, config.workflow_tier, config
            )

        if config.creativity_level and not config.parallel_beats:
            config.parallel_beats = self._apply_rule(
                CREATIVITY_TO_PARALLEL_RULE, config.creativity_level, config
            )

        if config.refinement_level and not config.qc_threshold:
            config.qc_threshold = self._apply_rule(
                REFINEMENT_TO_THRESHOLD_RULE, config.refinement_level, config
            )

    def _derive_dual_track_config(self, config: GenerationConfig) -> None:
        """推导双轨配置"""
        if config.workflow_tier and config.enable_dual_track is None:
            config.enable_dual_track = self._apply_rule(
                TIER_TO_DUAL_TRACK_RULE, config.workflow_tier, config
            )

    def _derive_rag_params(self, config: GenerationConfig) -> None:
        """推导 RAG 参数"""
        if config.memory_strategy:
            preset = MEMORY_STRATEGY_PRESETS.get(config.memory_strategy)
            if preset:
                if config.rag_top_k is None:
                    config.rag_top_k = preset.get("top_k")
                if config.rag_alpha is None:
                    config.rag_alpha = preset.get("semantic_weight")
                if config.rag_beta is None:
                    config.rag_beta = preset.get("time_decay_weight")
                if config.rag_gamma is None:
                    config.rag_gamma = preset.get("foreshadowing_weight")
                if config.rag_lambda_decay is None:
                    config.rag_lambda_decay = preset.get("decay_factor")

    def _apply_rule(
        self,
        rule: Any,
        value: Any,
        config: GenerationConfig,
    ) -> Any:
        """应用单个推导规则"""
        derived = rule.mapping.get(value, rule.default)
        self._derivation_log.append({
            "rule": rule.name,
            "source_field": rule.source_field,
            "target_field": rule.target_field,
            "input_value": value,
            "derived_value": derived,
        })
        return derived

    def get_derivation_log(self) -> List[Dict[str, Any]]:
        """获取推导日志"""
        return self._derivation_log.copy()
