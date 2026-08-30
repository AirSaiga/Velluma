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
伏笔类型定义模块 - 伏笔系统相关类型定义。

职责：
- 定义伏笔状态枚举
- 定义伏笔优先级枚举
- 定义伏笔闭合类型
- 定义伏笔元数据结构

业务场景：
- 伏笔生命周期管理
- 伏笔检索和追踪
- 伏笔遗漏检测

主要功能：
- 伏笔状态定义（创建/开放/闭合/归档）
- 伏笔优先级定义（主线/支线/氛围等）
- 闭合类型定义（显式/隐式/部分/放弃）

依赖项：
- pydantic: 数据验证
"""

import logging
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class HookStatus(str, Enum):
    CREATED = "created"
    OPEN = "open"
    ADDRESSED = "addressed"
    CLOSED = "closed"
    DROPPED = "dropped"


class HookPriority(str, Enum):
    MAIN_PLOT = "main_plot"
    SUB_PLOT = "sub_plot"
    ATMOSPHERE = "atmosphere"
    DETAIL = "detail"
    WORLD_BUILDING = "world_building"


class HookClosureType(str, Enum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    PARTIAL = "partial"
    ABANDONED = "abandoned"


class HookMetadata(BaseModel):
    hook_id: str = Field(default="", description="伏笔 ID")
    ledger_key: str = Field(default="", description="账本键")
    content: str = Field(default="", description="伏笔内容")

    status: HookStatus = Field(default=HookStatus.OPEN, description="状态")
    priority: HookPriority = Field(default=HookPriority.SUB_PLOT, description="优先级")
    closure_type: Optional[HookClosureType] = Field(None, description="闭合类型")

    created_at_chapter: int = Field(default=0, description="创建章节")
    addressed_at_chapters: List[int] = Field(default_factory=list, description="提及章节")
    closed_at_chapter: Optional[int] = Field(None, description="闭合章节")

    character_names: List[str] = Field(default_factory=list, description="涉及角色")
    location_names: List[str] = Field(default_factory=list, description="涉及地点")
    keywords: List[str] = Field(default_factory=list, description="关键词")

    mention_count: int = Field(default=0, description="提及次数")
    last_mention_chapter: Optional[int] = Field(None, description="最后提及章节")

    urgency_score: float = Field(default=0.0, description="紧急度")
    relevance_score: float = Field(default=0.0, description="相关度")


class HookDetectionResult(BaseModel):
    hook_id: str
    ledger_key: str = ""
    content: str

    detected_in_chapter: int = 0
    detection_confidence: float = 0.0
    detection_method: str = ""

    matched_text: str = ""
    match_type: str = ""

    suggested_status: Optional[HookStatus] = None
    is_closure: bool = False


class HookClosureCheckResult(BaseModel):
    hook_id: str
    hook_content: str

    is_addressed: bool = False
    is_closed: bool = False

    addressed_in_text: str = ""
    closure_type: str = ""

    suggestion: str = ""
    severity: str = "info"


@dataclass
class HookScoringConfig:
    open_duration_weight: float = 0.3
    priority_weight: float = 0.25
    mention_count_weight: float = 0.15

    main_plot_score: float = 1.0
    sub_plot_score: float = 0.7
    atmosphere_score: float = 0.4
    detail_score: float = 0.2

    urgent_threshold: int = 10
    attention_threshold: int = 5

    character_match_bonus: float = 0.2
