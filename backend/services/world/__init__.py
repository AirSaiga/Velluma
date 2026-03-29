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
世界状态服务模块 - 统一导出入口。

职责：
- 统一导出世界状态相关函数
- 提供世界状态快照提取和更新

子模块：
- state_service.py: 世界状态服务实现

主要功能：
- 世界状态快照提取
- 角色物理状态更新
- 状态连续性管理

依赖项：
- backend.models: 数据模型
- backend.world_state_schemas: 世界状态 schema
"""

from .state_service import (
    CharacterInfo,
    extract_world_state_snapshot,
    update_character_physical_state,
)

__all__ = [
    "CharacterInfo",
    "extract_world_state_snapshot",
    "update_character_physical_state",
]
