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
核心配置与依赖注入模块。

职责：聚合核心配置和依赖注入函数，提供统一的导入入口。

模块组织：
- config.py: 运行时配置（如端口持久化）
- dependencies.py: FastAPI 依赖注入函数（数据库会话仓储）

使用场景：
- services/: 需要获取配置时导入
- routes/: 需要获取仓储实例时导入（通过 Depends）

业务规则：
- config 函数管理进程级配置
- dependencies 函数配合 FastAPI 的 Depends 机制，实现请求级依赖注入
"""

from backend.core.config import save_port, load_port, get_actual_port
from backend.core.dependencies import (
    get_book_repository,
    get_chapter_repository,
    get_character_repository,
    get_relationship_repository,
    get_memory_repository,
)
