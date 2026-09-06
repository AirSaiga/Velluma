# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
精修流水线（Refinery）服务包（V4.1 新建）。

包结构（设计文档 §6）：
- diagnostician.py:  工序 4.5.1 诊断（1 次 reasoning LLM）
- planner.py:        工序 4.5.3 手术规划（纯算法）
- surgeon.py:        工序 4.5.4 局部手术（N 次 creative LLM）
- holistic_reader.py:工序 4.5.5 整体回读（1 次 reasoning）
- polisher.py:       工序 4.5.6 抛光（1 次 creative）
- refinery.py:       主类 Refinery（编排四工序）

业务场景：
- routes/chapter_generation/refinery.py 调用（/refinery/diagnose + /refinery/confirm）

使用示例：
    from backend.services.refinery import Refinery
    refinery = Refinery(chapter=chapter, recorder=recorder)
    diag = await refinery.diagnose(raw_text, ctx)
    # ★ 等待作者确认（对话式介入点 2，由路由层处理）
    result = await refinery.refine(confirmed_decisions, ctx)
"""

from backend.services.refinery.diagnostician import diagnose
from backend.services.refinery.planner import plan_operations, merge_overlapping_issues
from backend.services.refinery.surgeon import execute_surgery
from backend.services.refinery.holistic_reader import holistic_read
from backend.services.refinery.polisher import polish
from backend.services.refinery.refinery import Refinery, RefineryContext
from backend.services.refinery.reader_feedback import generate_reader_feedback

__all__ = [
    "diagnose",
    "plan_operations",
    "merge_overlapping_issues",
    "execute_surgery",
    "holistic_read",
    "polish",
    "Refinery",
    "RefineryContext",
    "generate_reader_feedback",
]
