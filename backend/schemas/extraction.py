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
正文逆向提取的 Pydantic 请求/响应模型。

职责：定义 analyze / confirm 两阶段端点使用的数据结构。
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ConfirmExtractionRequest(BaseModel):
    """
    confirm 端点的请求体。

    用户在前端预览面板勾选后，将确认的子集通过此结构传回。
    confirmed 字段是用户保留（未否决）的完整 ExtractionResult 子集。
    """
    run_id: str
    confirmed: Dict[str, List[Dict[str, Any]]]
    """用户确认的提取结果，结构与 ExtractionResult.to_dict() 一致（不含 stats）。"""


class ExtractionStats(BaseModel):
    """各类提取条目计数。"""
    characters: int = 0
    relationships: int = 0
    locations: int = 0
    assets: int = 0
    foreshadows: int = 0


class ExtractionCommitStats(BaseModel):
    """confirm 后各表实际创建计数。"""
    characters: int = 0
    relationships: int = 0
    locations: int = 0
    assets: int = 0
    foreshadows: int = 0
    memories: int = 0
