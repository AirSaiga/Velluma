"""
数据访问层统一出口模块。

职责：聚合所有仓储（Repository）类，提供统一的导入入口。

设计模式：Repository Pattern，封装数据库访问逻辑。

模块组织：
- book_repository.py: 书籍数据访问
- chapter_repository.py: 章节数据访问（含关联管理）
- character_repository.py: 角色数据访问
- relationship_repository.py: 角色关系数据访问
- memory_repository.py: 记忆块数据访问（RAG 检索）
- map_repository.py: 地图/地点数据访问
- base.py: 泛型基类（包含 QuerySpec 构建器）

使用场景：
- routes/: 业务路由层，通过依赖注入获取仓储实例
- core/dependencies.py: 定义仓储的依赖注入函数

业务规则：
- 所有仓储继承 BaseRepository，提供统一的 CRUD 接口
- 仓储绑定到同一个数据库会话，确保事务一致性
- 复杂查询使用 QuerySpec 构建器，避免硬编码 SQL
"""

from backend.repositories.book_repository import BookRepository
from backend.repositories.chapter_repository import ChapterRepository
from backend.repositories.character_repository import CharacterRepository
from backend.repositories.relationship_repository import RelationshipRepository
from backend.repositories.memory_repository import MemoryRepository
from backend.repositories.map_repository import MapLocationRepository
