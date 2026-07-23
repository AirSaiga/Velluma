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
Canon 变更连锁分析（V4.0 新建）。

职责：
- 作者改 Canon 一个节点/边后，找出所有受影响的节点
- 标注每个影响类型（矛盾/性质反转/需要铺垫/无冲突）
- 给出处理建议

设计依据：docs/generation-v4.0-canon.md §3.1 类型 C

业务场景：
- routes/canon.py 的 POST /canon/impact 端点
- 前端即兴变更的弹窗

使用方式：
    result = await analyze_change_impact(db, node_id, proposed_change)
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    CanonNode,
    CanonEdge,
    NODE_TYPE_CHARACTER,
    EDGE_TYPE_CAUSES,
    EDGE_TYPE_SETUPS,
    EDGE_TYPE_HINTS,
    EDGE_TYPE_CALLBACKS,
    VISIBILITY_PUBLIC,
)
from backend.repositories import CanonRepository
from backend.schemas.canon import ImpactItem

logger = logging.getLogger(__name__)


# ============================================================
# 连锁分析主入口
# ============================================================

async def analyze_change_impact(
    db: AsyncSession,
    node_id: UUID,
    proposed_change: Optional[Dict[str, Any]] = None,
    max_depth: int = 2,
) -> Dict[str, Any]:
    """分析节点变更的连锁影响。

    Args:
        db: 数据库会话
        node_id: 被修改的节点 ID
        proposed_change: 拟修改的字段（可选，用于更精确的判断）
        max_depth: BFS 最大深度

    Returns:
        {
            "changed_node": CanonNode,
            "affected": List[ImpactItem],
            "total_affected": int,
        }
    """
    repo = CanonRepository(db)

    # BFS 找邻居
    try:
        graph = await repo.find_neighbors(node_id, max_depth=max_depth)
    except Exception as e:
        logger.exception(f"[Canon] 连锁分析失败: {e}")
        return None

    if not graph:
        return None

    changed_node = graph["center"]
    neighbors = graph["nodes"]
    edges = graph["edges"]

    # 对每个邻居判断影响类型
    affected: List[ImpactItem] = []
    for neighbor in neighbors:
        impact = _classify_impact(changed_node, neighbor, edges, proposed_change)
        if impact.impact_type != "ok":
            affected.append(impact)

    # 按 severity 排序：contradiction > tone_shift > requires_setup
    severity_order = {"contradiction": 0, "tone_shift": 1, "requires_setup": 2, "ok": 3}
    affected.sort(key=lambda x: severity_order.get(x.impact_type, 99))

    logger.info(
        f"[Canon] 连锁分析完成：节点 [{changed_node.label}] 变更影响 {len(affected)} 个邻居"
    )
    return {
        "changed_node": changed_node,
        "affected": affected,
        "total_affected": len(affected),
    }


# ============================================================
# 影响分类（纯算法启发式）
# ============================================================

def _classify_impact(
    changed: CanonNode,
    neighbor: CanonNode,
    edges: List[CanonEdge],
    proposed_change: Optional[Dict[str, Any]],
) -> ImpactItem:
    """分类单个邻居受影响的类型。

    启发式规则：
    - 如果两者通过 causes/setup/callbacks 边连接且邻居是 public → 可能矛盾
    - 如果邻居是 character 且与 changed 是 setup 关系 → 可能需要铺垫
    - 如果两者通过 hints 连接 → 性质可能反转
    """
    # 找 changed 与 neighbor 之间的边
    related_edges = [
        e for e in edges
        if (e.source_id == changed.id and e.target_id == neighbor.id)
        or (e.source_id == neighbor.id and e.target_id == changed.id)
    ]

    # 默认 OK
    impact_type = "ok"
    detail = ""
    suggestions: List[str] = []

    # 判断规则
    for edge in related_edges:
        if edge.type == EDGE_TYPE_CAUSES:
            # 因果链：改了原因，结果可能不成立
            if neighbor.visibility == VISIBILITY_PUBLIC:
                impact_type = "contradiction"
                detail = f"因果链影响：[{changed.label}] 是 [{neighbor.label}] 的原因，改动可能导致后者不成立"
                suggestions = [
                    f"检查 [{neighbor.label}] 是否仍能合理发生",
                    f"或修改 [{neighbor.label}] 的描述以适应新的 [{changed.label}]",
                ]
                break

        elif edge.type == EDGE_TYPE_SETUPS:
            # 强伏笔：改了铺垫，回收点可能需要调整
            impact_type = "requires_setup"
            detail = f"伏笔链影响：[{changed.label}] 是 [{neighbor.label}] 的铺垫"
            suggestions = [
                f"如果 [{changed.label}] 改了，[{neighbor.label}] 的回收方式需要相应调整",
                f"或加一个新的铺垫节点替代",
            ]
            break

        elif edge.type == EDGE_TYPE_CALLBACKS:
            # 回收：改了回收点，铺垫的意义可能改变
            impact_type = "tone_shift"
            detail = f"回收链影响：[{changed.label}] 回收了 [{neighbor.label}] 的铺垫"
            suggestions = [
                f"检查 [{neighbor.label}] 原本的铺垫是否还有意义",
                f"可能需要补充新的铺垫",
            ]
            break

        elif edge.type == EDGE_TYPE_HINTS:
            # 弱伏笔：暗示的方向可能变了
            if impact_type == "ok":  # 不覆盖更严重的
                impact_type = "tone_shift"
                detail = f"暗示链影响：[{changed.label}] 暗示了 [{neighbor.label}]"
                suggestions = [
                    f"新的 [{changed.label}] 是否还能合理暗示 [{neighbor.label}]？",
                ]

    # 如果是角色且没明确分类，看是否需要铺垫
    if impact_type == "ok" and neighbor.type == NODE_TYPE_CHARACTER and neighbor.visibility == VISIBILITY_PUBLIC:
        # 角色的态度/行为可能需要调整
        if proposed_change and _is_behavior_change(proposed_change):
            impact_type = "requires_setup"
            detail = f"角色反应影响：[{neighbor.label}] 对 [{changed.label}] 的态度/行为可能需要调整"
            suggestions = [
                f"检查 [{neighbor.label}] 在前文对 [{changed.label}] 的态度描写",
                f"可能需要补充心理转变的铺垫",
            ]

    return ImpactItem(
        node_id=str(neighbor.id),
        node_label=neighbor.label,
        node_type=neighbor.type,
        impact_type=impact_type,
        detail=detail or "无明显影响",
        suggestions=suggestions,
    )


def _is_behavior_change(proposed_change: Dict[str, Any]) -> bool:
    """判断拟修改是否涉及角色行为/态度（启发式）。"""
    behavior_keys = {"canon_text", "public_text", "metadata"}
    return any(k in proposed_change for k in behavior_keys)
