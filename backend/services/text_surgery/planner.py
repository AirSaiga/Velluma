# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""手术规划（Planner，自 services/refinery/planner.py 抽迁，2026-09-12）。

职责：纯算法，把确认的问题清单转化为手术计划（0 LLM）。

核心算法：
1. 过滤：只保留 status=confirmed 或 status=auto 的 issue
2. 排序：按 severity 排序（high > medium > low）
3. 合并：影响范围重叠的 issue 合并为一个 Operation
4. context_summary/canon_constraints：调用方透传（本函数不生成）
"""

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def merge_overlapping_issues(
    issues: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """合并段范围重叠的 issue 为一组（每个组将成为一个 Operation）。

    Args:
        issues: 已确认的 issue 列表

    Returns:
        List[List[issue]]：每个内层 list 是合并到一起的 issue 组
    """
    if not issues:
        return []

    # 先计算每个 issue 的段范围 [start, end]
    def _get_range(issue: Dict[str, Any]) -> Tuple[int, int]:
        loc = issue.get("location") or {}
        if loc.get("paragraph_range"):
            r = loc["paragraph_range"]
            if isinstance(r, (list, tuple)) and len(r) == 2:
                return (int(r[0]), int(r[1]))
        p = loc.get("paragraph")
        if p is not None:
            return (int(p), int(p))
        # 没有段落信息（如 weak_hook 是 global），用 -1 表示
        return (-1, -1)

    # 按起始段排序
    sorted_issues = sorted(issues, key=lambda x: _get_range(x)[0])

    # 合并重叠
    groups: List[List[Dict[str, Any]]] = []
    current_group: List[Dict[str, Any]] = []
    current_range: Tuple[int, int] = (-1, -1)

    for issue in sorted_issues:
        r = _get_range(issue)
        if r[0] == -1:
            # 全局问题，独立成组
            if current_group:
                groups.append(current_group)
                current_group = []
                current_range = (-1, -1)
            groups.append([issue])
            continue

        if not current_group:
            current_group = [issue]
            current_range = r
        elif r[0] <= current_range[1] + 1:  # 重叠或相邻
            current_group.append(issue)
            current_range = (current_range[0], max(current_range[1], r[1]))
        else:
            groups.append(current_group)
            current_group = [issue]
            current_range = r

    if current_group:
        groups.append(current_group)

    return groups


def plan_operations(
    confirmed_issues: List[Dict[str, Any]],
    context_summary_template: str = "",
    canon_constraints: str = "",
) -> List[Dict[str, Any]]:
    """手术规划（纯算法）。

    Args:
        confirmed_issues: 作者确认（或自动确认）的 issue 列表
        context_summary_template: 全文摘要模板（每个 operation 复用）
        canon_constraints: Canon 约束文本

    Returns:
        operation dict 列表（每个含 id/issue_ids/operation_type/target_paragraphs/...）
    """
    if not confirmed_issues:
        return []

    # 按 severity 排序
    sorted_issues = sorted(
        confirmed_issues,
        key=lambda x: SEVERITY_ORDER.get(x.get("severity", "medium"), 1),
    )

    # 合并重叠
    groups = merge_overlapping_issues(sorted_issues)

    # 生成 Operation
    operations = []
    for i, group in enumerate(groups):
        # 决定 operation_type
        op_type = "rewrite"
        if len(group) > 1:
            op_type = "merge"
        elif any(iss.get("type") == "redundancy" and "删除" in (iss.get("suggestion") or "") for iss in group):
            op_type = "delete"
        elif any(iss.get("type") == "weak_hook" for iss in group):
            op_type = "insert"

        # 目标段
        target_paragraphs = set()
        for iss in group:
            loc = iss.get("location") or {}
            if loc.get("paragraph_range"):
                r = loc["paragraph_range"]
                for p in range(int(r[0]), int(r[1]) + 1):
                    target_paragraphs.add(p)
            elif loc.get("paragraph") is not None:
                target_paragraphs.add(int(loc["paragraph"]))

        operations.append({
            "id": f"OP{i+1:03d}",
            "issue_ids": [iss.get("id", f"I?") for iss in group],
            "operation_type": op_type,
            "target_paragraphs": sorted(target_paragraphs) if target_paragraphs else [],
            "context_summary": context_summary_template,
            "canon_constraints": canon_constraints,
            "issues": group,  # 保留 issue 详情供 surgeon 用
        })

    logger.info(
        f"[TextSurgery] 手术规划完成：{len(confirmed_issues)} 个 issue → {len(operations)} 个 operation"
    )
    return operations
