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
配置推导引擎 (Configuration Derivation Engine)

职责：
- 从高层语义输入推导底层技术参数
- 实现策略预设与参数覆盖规则
- 提供默认值填充与校验

本模块是 Facade 层，实际实现已拆分到：
- config/rules.py: 推导规则定义
- config/engine.py: 推导引擎
- config/mapper.py: 参数映射和验证

使用方式：
    from backend.config.derivation import DerivationEngine, ParameterMapper, ConfigValidator

    engine = DerivationEngine()
    derived_config = engine.derive(raw_config)
"""

from typing import Any, Optional

from backend.config.rules import (
    DerivationRule,
    TENSION_TO_TIER_RULE,
    TIER_TO_ITERATIONS_RULE,
    MEMORY_STRATEGY_PRESETS,
    CREATIVITY_TO_PARALLEL_RULE,
    REFINEMENT_TO_THRESHOLD_RULE,
)

from backend.config.engine import DerivationEngine
from backend.config.mapper import ParameterMapper, ConfigValidator
from backend.config.schemas import GenerationConfig


def derive_config(
    request: Any,
    chapter: Optional[Any] = None,
    book: Optional[Any] = None,
) -> GenerationConfig:
    """
    从请求数据构建并推导配置。

    这是一个便捷函数，组合了配置构建和推导两个步骤。

    Args:
        request: 前端请求对象（Pydantic 模型或字典）
        chapter: Chapter 实体（可选）
        book: Book 实体（可选）

    Returns:
        GenerationConfig: 已推导的配置对象
    """
    config = GenerationConfig.from_request(request, chapter, book)
    config.derive_all()
    return config


__all__ = [
    "DerivationEngine",
    "DerivationRule",
    "ParameterMapper",
    "ConfigValidator",
    "derive_config",
    "TENSION_TO_TIER_RULE",
    "TIER_TO_ITERATIONS_RULE",
    "MEMORY_STRATEGY_PRESETS",
    "CREATIVITY_TO_PARALLEL_RULE",
    "REFINEMENT_TO_THRESHOLD_RULE",
]
