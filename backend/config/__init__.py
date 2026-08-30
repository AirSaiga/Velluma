# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
配置模块 (Configuration Module)

职责：提供统一配置对象的构建、推导、验证能力。

核心组件：
- GenerationConfig: 统一生成配置容器
- DerivationEngine: 配置推导引擎
- ParameterMapper: 参数映射器
- ConfigValidator: 配置验证器

使用方式：
    from backend.config import derive_config, GenerationConfig
    
    # 从请求构建配置
    config = derive_config(request, chapter, book)
    
    # 手动构建配置
    config = GenerationConfig.from_request(request, chapter, book)
    config.derive_all()
"""

from backend.config.schemas.generation_config import (
    # 核心配置对象
    GenerationConfig,
    StoryConfig,
    ChapterPlan,
    LLMConfig,
    RAGPolicy,
    WorkflowPolicy,
    ValidationPolicy,
    FeatureFlags,
    
    # 子配置对象
    ReasoningSettings,
    
    # 枚举类型
    MemoryStrategy,
    CreativityLevel,
    RefinementDepth,
    EditorMode,
    WorkflowTier,
    PacingStyle,
    ReasoningEffort,
)

from backend.config.derivation import (
    DerivationEngine,
    ParameterMapper,
    ConfigValidator,
    derive_config,
    
    # 推导规则
    TENSION_TO_TIER_RULE,
    TIER_TO_ITERATIONS_RULE,
    MEMORY_STRATEGY_PRESETS,
    CREATIVITY_TO_PARALLEL_RULE,
    REFINEMENT_TO_THRESHOLD_RULE,
)

from backend.config.adapter import (
    adapt_request_to_config,
    get_generation_config,
    HighLevelParameterProcessor,
    RuntimeContextBuilder,
)

__all__ = [
    # 核心配置对象
    "GenerationConfig",
    "StoryConfig",
    "ChapterPlan",
    "LLMConfig",
    "RAGPolicy",
    "WorkflowPolicy",
    "ValidationPolicy",
    "FeatureFlags",
    
    # 子配置对象
    "ReasoningSettings",
    
    # 枚举类型
    "MemoryStrategy",
    "CreativityLevel",
    "RefinementDepth",
    "EditorMode",
    "WorkflowTier",
    "PacingStyle",
    "ReasoningEffort",
    
    # 推导引擎
    "DerivationEngine",
    "ParameterMapper",
    "ConfigValidator",
    "derive_config",
    
    # 推导规则
    "TENSION_TO_TIER_RULE",
    "TIER_TO_ITERATIONS_RULE",
    "MEMORY_STRATEGY_PRESETS",
    "CREATIVITY_TO_PARALLEL_RULE",
    "REFINEMENT_TO_THRESHOLD_RULE",
    
    # 适配器
    "adapt_request_to_config",
    "get_generation_config",
    "HighLevelParameterProcessor",
    "RuntimeContextBuilder",
]
