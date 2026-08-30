# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
Canon（作者脑中世界图谱）服务包（V4.0 新建）。

包结构（设计文档 §1）：
- consistency.py:  一致性引擎（private 泄露检测 + 事实矛盾 + 悬空伏笔）
- impact.py:       变更连锁分析（BFS 找邻居 + 影响分类）
- extractor.py:    自动提取（从章节正文提取候选节点/边）

业务场景：
- routes/canon.py 调用本包提供的服务
- workflows/adf/ 在 Phase 0 调用 build_canon_context_for_prompt 注入 Canon
- 章节发布后自动触发 extract_from_chapter

使用示例：
    from backend.services.canon import (
        check_consistency, analyze_change_impact,
        extract_from_chapter, build_canon_context_for_prompt,
    )
"""

from backend.services.canon.consistency import (
    check_consistency,
    build_canon_context_for_prompt,
    _extract_key_phrases,
)
from backend.services.canon.impact import analyze_change_impact
from backend.services.canon.extractor import extract_from_chapter

__all__ = [
    # 一致性
    "check_consistency",
    "build_canon_context_for_prompt",
    "_extract_key_phrases",
    # 连锁分析
    "analyze_change_impact",
    # 自动提取
    "extract_from_chapter",
]
