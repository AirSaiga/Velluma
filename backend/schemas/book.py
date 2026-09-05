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

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .enums import PacingStyle


class BookBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    # global_sys_prompt 已退役（2026-09-05）：原「创作笔记」写入、V3 生成链消费，
    # 唯一在役消费点（refine 精修）同批掐断。字段不再进出 API；DB 列冻结只读
    # （历史数据保留在 books 表，见 models.Book）。
    core_motifs_taboos: Optional[str] = None
    worldview_settings: Optional[dict] = Field(default_factory=dict)
    golden_snippets: Optional[list] = Field(default_factory=list)
    style_blacklist: Optional[list] = Field(default_factory=list)
    # CP2.3a：书级大纲 + 滚动摘要
    outline: Optional[str] = None
    rolling_summary: Optional[str] = None
    # D4 比例尺标定（未标定为 None——前端距离功能据此静默降级）
    map_scale: Optional[dict] = None


class BookCreate(BookBase):
    pass


class BookUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    # global_sys_prompt 不再接受更新（2026-09-05 退役，见 BookBase 注）
    core_motifs_taboos: Optional[str] = None
    worldview_settings: Optional[dict] = None
    golden_snippets: Optional[list] = None
    outline: Optional[str] = None
    rolling_summary: Optional[str] = None
    # D4 比例尺标定（docs/map-scale-spatial.md §2.1）：refs ≤5 取均值；None=不动，
    # 显式空 dict = 清除标定（未标定书距离功能静默降级）
    map_scale: Optional[dict] = None
    # 双写收敛（任务包 B）：style_blacklist 不再接受更新——历史书级黑名单已启动
    # 迁移并入 style_cards.negative_list，该列冻结只读（BookBase/BookResponse 保留
    # 该字段仅作只读输出）


class BookResponse(BookBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class WorldviewUpdate(BaseModel):
    worldview_settings: dict = Field(default_factory=dict)
