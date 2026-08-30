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
上下文加载模块 - 统一导出入口。

职责：
- 统一导出上下文加载相关函数
- 提供章节生成前的上下文准备

子模块：
- loader.py: 上下文加载实现

主要功能：
- 章节上下文加载
- 角色/关系上下文加载
- 伏笔上下文加载
- 世界快照加载

依赖项：
- backend.models: 数据模型
- backend.repositories: 数据访问层
"""

from .loader import (
    load_chapter,
    load_book,
    load_chapter_entities,
    load_character_relationships,
    load_previous_chapter_summary,
    load_previous_world_snapshot,
    load_open_hooks,
    load_chapter_locations,
    load_relevant_memories,
    load_full_chapter_context,
    ChapterContext,
)

from backend.services.orchestration.beat_manager import (
    save_story_beats,
    build_physical_state_lock,
)

__all__ = [
    "load_chapter",
    "load_book",
    "load_chapter_entities",
    "load_character_relationships",
    "load_previous_chapter_summary",
    "load_previous_world_snapshot",
    "load_open_hooks",
    "load_chapter_locations",
    "load_relevant_memories",
    "load_full_chapter_context",
    "ChapterContext",
    "save_story_beats",
    "build_physical_state_lock",
]
