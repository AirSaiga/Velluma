# Velluma - Loop 1 Outline Self-Check Tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""Loop 1 大纲自检单元测试。"""

import pytest

from backend.services.workflows.bsadf.outline_self_check import (
    diagnose_gaps,
    OutlineCheckResult,
)


def test_diagnose_gaps_micro_gap_low_impact():
    hard_facts = [
        {"category": "action", "content": "林尘进入仓库"},
        {"category": "event", "content": "触发血噬融合"},
    ]
    gaps = diagnose_gaps(hard_facts, total_segments=5)
    micro_gaps = [g for g in gaps if g["type"] == "micro"]
    assert len(micro_gaps) >= 0
    for g in micro_gaps:
        assert g["impact"] == "low"


def test_diagnose_gaps_macro_motivation_gap():
    hard_facts = [
        {"category": "action", "content": "白霆撤退"},
    ]
    gaps = diagnose_gaps(hard_facts, total_segments=5)
    macro_gaps = [g for g in gaps if g["type"] == "macro"]
    assert isinstance(macro_gaps, list)


def test_outline_check_result_pass_when_no_violations():
    result = OutlineCheckResult(pass_=True, violations=[], hard_facts=[], gaps=[])
    assert result.pass_ is True
    assert result.violations == []


def test_outline_check_result_fail_with_violation():
    result = OutlineCheckResult(
        pass_=False,
        violations=[{"beat_id": "B01", "field": "core_plot_event", "content": "脑补事件", "reason": "大纲未提及"}],
        hard_facts=[], gaps=[],
    )
    assert result.pass_ is False
    assert len(result.violations) == 1
