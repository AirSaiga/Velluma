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
工作流层级映射服务。

职责：提供工作流层级（WorkflowTier）相关的业务逻辑映射。

主要功能：
- 将剧情张力等级映射为对应的工作流层级
- 支持 V3.0 智能路由规则

使用场景：
- drafting.py: 根据剧情张力自动选择工作流路径
"""

from backend.schemas import WorkflowTier


def map_tension_to_workflow_tier(tension_level: int) -> WorkflowTier:
    """
    将 tension_level 映射为工作流层级。

    V3.0 智能路由映射规则：
    - Level 1, 2 -> TIER_1_FAST (疾速流)
    - Level 3 -> TIER_2_STANDARD (均衡流)
    - Level 4, 5 -> TIER_3_FORTRESS (堡垒流)

    Args:
        tension_level: 剧情张力等级 (1-5)

    Returns:
        WorkflowTier: 对应的工作流层级
    """
    if tension_level <= 2:
        return "TIER_1_FAST"
    elif tension_level == 3:
        return "TIER_2_STANDARD"
    else:
        return "TIER_3_FORTRESS"
