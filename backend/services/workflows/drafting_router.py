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
起草路由模块 - 兼容性导出文件。

【已重构】核心逻辑已移至 drafting.py
此文件保留用于向后兼容，避免修改大量导入语句。

迁移说明：
- 2026-04-08: 将 execute_draft_stage 等核心函数从 drafting_router.py 迁移到 drafting.py
- 目的: 消除 drafting.py ↔ drafting_router.py 的循环导入

新代码请从 drafting.py 导入：
    from backend.services.workflows.drafting import execute_draft_stage, BeatDraftResult

旧导入仍兼容（通过此文件重新导出）：
    from backend.services.workflows.drafting_router import execute_draft_stage  # 仍然有效
"""

# 从新的核心模块重新导出所有公开 API
from backend.services.workflows.drafting import (
    BeatDraftResult,
    execute_draft_stage,
    _execute_fast_path,
    _execute_standard_path,
    _execute_fortress_path,
    _build_fast_path_prompt,
    _build_standard_path_prompt,
)

__all__ = [
    "BeatDraftResult",
    "execute_draft_stage",
    "_execute_fast_path",
    "_execute_standard_path",
    "_execute_fortress_path",
    "_build_fast_path_prompt",
    "_build_standard_path_prompt",
]
