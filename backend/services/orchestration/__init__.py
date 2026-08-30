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

职责：
- 统一导出 Agentic 工作流编排相关函数
- 提供节拍管理和层级映射

子模块：
- agentic.py: Agentic 工作流编排
- beat_manager.py: 节拍管理
- tier_mapper.py: 层级映射

主要功能：
- 高层参数解析
- 节拍预览
- 节拍保存
- 张力层级映射

依赖项：
- backend.models: 数据模型
- backend.services.workflows: 工作流阶段
"""

from .agentic import (
    resolve_high_level_params,
    normalize_confirmed_beats,
)
from .beat_manager import (
    save_story_beats,
    build_physical_state_lock,
)
from .tier_mapper import map_tension_to_workflow_tier

__all__ = [
    "resolve_high_level_params",
    "normalize_confirmed_beats",
    "save_story_beats",
    "build_physical_state_lock",
    "map_tension_to_workflow_tier",
]
