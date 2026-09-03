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
工作流阶段模块（统一出口）。

职责：聚合保留引擎（ADF / Refinery）及共享设施所需的阶段处理函数，提供统一导入入口。

引擎剥离（2026-07）：V3.0 Detonation / V3.1 Unified / V4.0 DualTrack 三套引擎及其专属
模块（drafting / stitching / sketch_generator / adversarial_aligner / fail_fast /
fortress_candidate / dual_track 包 / detonation 包）已整体迁至 backend/_deprecated/。
当前保留的活跃消费者见各文件 docstring。

模块组织（引擎剥离后）：
- refining.py: 精修阶段（refine_draft，服务于 chapter_optimization 路由）
"""

from backend.services.workflows.refining import refine_draft

__all__ = [
    "refine_draft",
    "refine_single_beat",
]
