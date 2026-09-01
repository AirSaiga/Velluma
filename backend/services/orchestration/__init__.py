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
编排模块 - 统一导出入口。

2026-09-01 死代码归档：agentic.py / beat_manager.py（V4.0 编排遗存，零运行
路径）迁至 `backend/_deprecated/services/orchestration/`。仅存 tier_mapper
（schemas 懒加载消费：张力值 → 工作流层级映射）。

子模块：
- tier_mapper.py: 层级映射
"""

from .tier_mapper import map_tension_to_workflow_tier

__all__ = [
    "map_tension_to_workflow_tier",
]
