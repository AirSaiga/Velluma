# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""约束治理包（2026-09-02 一期，docs/constraint-governance.md 唯一权威）。

把「约束」从散落的 prompt 文案升格为注册管理的代码资产：
- registry.py   约束登记册（哪条约束住哪层、谁验证、什么状态）+ 强措辞 lint
- events.py     constraint_events.jsonl 事件台账（写侧照抄 collab_events 模式）
- prompt_sections.py  分节 prompt 编译器（数据驱动，dock 是第一个租户）
- persona_drift.py    B5 人称漂移 report-only 检测

执法可靠性序（导师框架）：供给切断 > 输出代码闸 > 确定性改写 > prompt 偏置 > 事后审计。
"""
