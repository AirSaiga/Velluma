# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""文本手术原语包（2026-09-12 写后检查收敛 · Phase A 自 services/refinery 抽迁）。

这里住的是**与 Refinery 引擎无关的纯文本手术原语**：手术规划（纯算法）、
局部手术（每 operation 1 次 creative LLM）与结果应用。Refinery 引擎拔除后，
唯一在役消费方是 ADF 一致性守卫（workflows/adf/consistency_guard.py，其实现
比 Refinery 本体多两道安全网：_surgery_safe 手术安全网 + 复验回滚）。

迁移动机见 docs/post-writing-checks-audit.md 与 Phase 0 红队审查报告：
services/refinery 整体退役时，被反向依赖的 planner/surgeon 三件必须先落到
中立包，否则 import 链断裂。算法与 prompt 与 Refinery 时代逐字节同源。
"""

from backend.services.text_surgery.planner import (
    SEVERITY_ORDER,
    merge_overlapping_issues,
    plan_operations,
)
from backend.services.text_surgery.surgeon import (
    apply_surgeries_to_text,
    execute_surgery,
)

__all__ = [
    "SEVERITY_ORDER",
    "merge_overlapping_issues",
    "plan_operations",
    "apply_surgeries_to_text",
    "execute_surgery",
]
