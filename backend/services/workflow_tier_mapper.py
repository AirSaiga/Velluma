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
