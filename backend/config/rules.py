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
推导规则定义模块。

职责：定义所有推导规则和常量配置。

包含：
- DerivationRule: 推导规则基类
- 规则实例常量
- 内存策略预设

使用场景：
- config/engine.py: DerivationEngine 使用规则执行推导
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from backend.config.schemas.generation_config import MemoryStrategy


@dataclass
class DerivationRule:
    """推导规则定义"""
    name: str
    source_field: str
    target_field: str
    mapping: Dict[Any, Any]
    default: Any = None
    description: str = ""


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
        "top_k": 8,
        "semantic_weight": 0.7,
        "time_decay_weight": 0.1,
        "foreshadowing_weight": 0.2,
        "decay_factor": 0.05,
        "enable_memory_injection": True,
    },
}


CREATIVITY_TO_PARALLEL_RULE = DerivationRule(
    name="creativity_to_parallel",
    source_field="creativity_level",
    target_field="parallel_beats",
    mapping={
        1: 3,
        2: 4,
        3: 5,
        4: 6,
        5: 6,
    },
    default=3,
    description="根据创意等级推导并行节拍数",
)


REFINEMENT_TO_THRESHOLD_RULE = DerivationRule(
    name="refinement_to_threshold",
    source_field="refinement_level",
    target_field="qc_threshold",
    mapping={
        0: 1.0,
        1: 0.8,
        2: 0.6,
        3: 0.4,
        4: 0.3,
        5: 0.2,
    },
    default=0.6,
    description="根据精修等级推导质量检查阈值",
)
