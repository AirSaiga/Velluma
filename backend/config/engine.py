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
配置推导引擎模块。

职责：执行配置推导逻辑。

包含：
- DerivationEngine: 配置推导引擎

使用场景：
- backend/services/workflow/: 工作流模块使用推导引擎
"""

__all__ = ["DerivationEngine"]

import logging
from typing import Any, Dict, List, Optional

from backend.schemas import WorkflowTier
from backend.config.schemas import GenerationConfig, MemoryStrategy

from backend.config.rules import (
    TENSION_TO_TIER_RULE,
    TIER_TO_ITERATIONS_RULE,
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
        logger.info("[DerivationEngine.derive] 开始执行推导")
        self._derivation_log = []

        logger.info("[DerivationEngine.derive] 开始 _derive_workflow_tier")
        self._derive_workflow_tier(config)
        logger.info("[DerivationEngine.derive] _derive_workflow_tier 完成")

        logger.info("[DerivationEngine.derive] 开始 _derive_iteration_params")
        self._derive_iteration_params(config)
        logger.info("[DerivationEngine.derive] _derive_iteration_params 完成")

        logger.info("[DerivationEngine.derive] 开始 _derive_rag_params")
        self._derive_rag_params(config)
        logger.info("[DerivationEngine.derive] _derive_rag_params 完成")

        logger.info("[DerivationEngine.derive] 推导完成，返回 config")
        return config

    def _derive_workflow_tier(self, config: GenerationConfig) -> None:
        """推导工作流层级"""
        if not config.chapter:
            return

        if config.chapter.workflow_tier:
            return

        if config.chapter.tension_level:
            config.chapter.workflow_tier = self._apply_rule(
                TENSION_TO_TIER_RULE, config.chapter.tension_level, config
            )

        if not config.chapter.workflow_tier:
            config.chapter.workflow_tier = "TIER_2_STANDARD"

    def _derive_iteration_params(self, config: GenerationConfig) -> None:
        """推导迭代相关参数"""
        if not config.chapter:
            return

        if config.chapter.workflow_tier and not config.workflow.max_iterations:
            config.workflow.max_iterations = self._apply_rule(
                TIER_TO_ITERATIONS_RULE, config.chapter.workflow_tier, config
            )

    def _derive_rag_params(self, config: GenerationConfig) -> None:
        """推导 RAG 参数"""
        if config.rag.memory_strategy:
            preset = MEMORY_STRATEGY_PRESETS.get(config.rag.memory_strategy)
            if preset:
                if config.rag.top_k is None:
                    config.rag.top_k = preset.get("top_k")
                if config.rag.semantic_weight is None:
                    config.rag.semantic_weight = preset.get("semantic_weight")
                if config.rag.time_decay_weight is None:
                    config.rag.time_decay_weight = preset.get("time_decay_weight")
                if config.rag.foreshadowing_weight is None:
                    config.rag.foreshadowing_weight = preset.get("foreshadowing_weight")
                if config.rag.decay_factor is None:
                    config.rag.decay_factor = preset.get("decay_factor")

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
