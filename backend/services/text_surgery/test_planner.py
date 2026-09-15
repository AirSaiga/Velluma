# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""手术规划单测——services/text_surgery/planner.py（纯算法，0 LLM）。

对拍口径：
- merge_overlapping_issues：段范围重叠或相邻（end+1）合并为一组，全局问题
  （无段落信息，range=-1）独立成组；
- plan_operations：severity 排序、op_type 判定（多 issue 合并组=merge /
  redundancy+删除建议=delete / weak_hook=insert / 默认 rewrite）、
  paragraph_range 展开为连续目标段。
"""

from backend.services.text_surgery.planner import (
    merge_overlapping_issues,
    plan_operations,
)


def _issue(id, severity="medium", para=None, para_range=None, type="consistency", suggestion=""):
    location = {}
    if para is not None:
        location["paragraph"] = para
    if para_range is not None:
        location["paragraph_range"] = para_range
    return {
        "id": id,
        "severity": severity,
        "type": type,
        "suggestion": suggestion,
        "location": location or None,
    }


class TestMergeOverlappingIssues:
    def test_empty(self):
        assert merge_overlapping_issues([]) == []

    def test_disjoint_ranges_stay_separate(self):
        issues = [_issue("A", para=1), _issue("B", para=5)]
        groups = merge_overlapping_issues(issues)
        assert len(groups) == 2

    def test_overlapping_ranges_merged(self):
        issues = [_issue("A", para_range=(1, 3)), _issue("B", para_range=(3, 5))]
        groups = merge_overlapping_issues(issues)
        assert len(groups) == 1
        assert {i["id"] for i in groups[0]} == {"A", "B"}

    def test_adjacent_ranges_merged(self):
        # 相邻（end+1）也算重叠：段 1-2 与段 3-4 合并
        issues = [_issue("A", para_range=(1, 2)), _issue("B", para_range=(3, 4))]
        groups = merge_overlapping_issues(issues)
        assert len(groups) == 1

    def test_gap_not_merged(self):
        issues = [_issue("A", para_range=(1, 2)), _issue("B", para_range=(4, 5))]
        groups = merge_overlapping_issues(issues)
        assert len(groups) == 2

    def test_global_issue_isolated(self):
        # 全局问题（无段落信息 → range=-1）排序恒居首且独立成组，
        # 不参与后续段落合并
        issues = [
            _issue("A", para_range=(1, 2)),
            _issue("G", type="weak_hook"),  # 无 location → -1
            _issue("B", para_range=(2, 3)),
        ]
        groups = merge_overlapping_issues(issues)
        assert len(groups) == 2
        assert [g[0]["id"] for g in groups] == ["G", "A"]
        assert {i["id"] for i in groups[1]} == {"A", "B"}

    def test_single_paragraph_issues_merge(self):
        issues = [_issue("A", para=2), _issue("B", para=2)]
        groups = merge_overlapping_issues(issues)
        assert len(groups) == 1


class TestPlanOperations:
    def test_empty_input(self):
        assert plan_operations([]) == []

    def test_operation_ids_sequential(self):
        ops = plan_operations([_issue("A", para=1), _issue("B", para=5), _issue("C", para=9)])
        assert [op["id"] for op in ops] == ["OP001", "OP002", "OP003"]

    def test_severity_order_high_first(self):
        ops = plan_operations([
            _issue("LOW", severity="low", para=1),
            _issue("HIGH", severity="high", para=1),
        ])
        # 同段合并为一组，组内按 severity 排序
        assert ops[0]["issue_ids"][0] == "HIGH"

    def test_group_of_multiple_becomes_merge(self):
        ops = plan_operations([_issue("A", para=2), _issue("B", para=2)])
        assert len(ops) == 1
        assert ops[0]["operation_type"] == "merge"

    def test_redundancy_with_delete_suggestion(self):
        ops = plan_operations([
            _issue("R", para=3, type="redundancy", suggestion="删除重复的说明"),
        ])
        assert ops[0]["operation_type"] == "delete"

    def test_redundancy_without_delete_word_stays_rewrite(self):
        ops = plan_operations([
            _issue("R", para=3, type="redundancy", suggestion="改写此处"),
        ])
        assert ops[0]["operation_type"] == "rewrite"

    def test_weak_hook_becomes_insert(self):
        ops = plan_operations([_issue("W", type="weak_hook")])
        assert ops[0]["operation_type"] == "insert"
        # 全局问题无目标段
        assert ops[0]["target_paragraphs"] == []

    def test_paragraph_range_expanded(self):
        ops = plan_operations([_issue("A", para_range=(2, 4))])
        assert ops[0]["target_paragraphs"] == [2, 3, 4]

    def test_context_passthrough(self):
        ops = plan_operations(
            [_issue("A", para=1)],
            context_summary_template="全文摘要",
            canon_constraints="Canon 约束",
        )
        assert ops[0]["context_summary"] == "全文摘要"
        assert ops[0]["canon_constraints"] == "Canon 约束"

    def test_issues_attached_for_surgeon(self):
        ops = plan_operations([_issue("A", para=1)])
        assert ops[0]["issues"][0]["id"] == "A"
