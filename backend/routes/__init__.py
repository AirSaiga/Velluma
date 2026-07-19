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
路由层统一出口模块。

职责：聚合所有 API 路由，提供统一的导入入口。

设计模式：分层架构，路由层负责请求路由和参数校验。

模块组织：
- books.py: 书籍管理 API
- chapters.py: 章节 CRUD API
- chapter_entities.py: 章节-角色关联管理
- chapter_publishing.py: 章节发布流程
- characters.py: 角色管理 API
- relationships.py: 角色关系 API
- memories.py: 记忆/RAG API
- text_formatting.py: 文本格式整理 API
- chapter_generation.py: 章节生成 API
- chapter_optimization.py: 章节优化 API
- inspiration.py: 灵感生成 API
- system.py: 系统健康检查 API
- maps.py: 地图/地点管理 API

使用场景：
- main.py: 注册所有路由到 FastAPI 应用

业务规则：
- 所有路由使用 APIRouter 创建，带有 /api 前缀
- 路由按业务域划分，不同业务域使用不同的标签（tags）
- 依赖注入获取仓储实例，确保数据库会话管理
"""

from backend.routes.assets import router as assets_router
from backend.routes.books import router as books_router
from backend.routes.chapters import router as chapters_router
from backend.routes.chapter_entities import router as chapter_entities_router
from backend.routes.chapter_publishing import router as chapter_publishing_router
from backend.routes.characters import router as characters_router
from backend.routes.relationships import router as relationships_router
from backend.routes.memories import router as memories_router
from backend.routes.text_formatting import router as text_formatting_router
# chapter_generation 包提供双轨生成路由
from backend.routes.chapter_generation import router as chapter_generation_router
from backend.routes.chapter_optimization import router as chapter_optimization_router
from backend.routes.inspiration import router as inspiration_router
from backend.routes.critique import router as critique_router
from backend.routes.system import router as system_router
from backend.routes.maps import router as maps_router
from backend.routes.style import router as style_router  # CP2.2b 新增

__all__ = [
    "assets_router",
    "books_router",
    "chapters_router",
    "chapter_entities_router",
    "chapter_publishing_router",
    "characters_router",
    "relationships_router",
    "memories_router",
    "text_formatting_router",
    "chapter_generation_router",
    "chapter_optimization_router",
    "inspiration_router",
    "critique_router",
    "system_router",
    "maps_router",
    "style_router",  # CP2.2b
]
