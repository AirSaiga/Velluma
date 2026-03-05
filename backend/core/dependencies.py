from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.repositories import (
    BookRepository,
    ChapterRepository,
    CharacterRepository,
    RelationshipRepository,
    MemoryRepository,
    MapLocationRepository,
)


# =============================================================================
# 依赖注入层
# =============================================================================
# 设计目的：将数据库会话（Session）与仓储（Repository）的创建逻辑分离
# 生命周期：
#   - get_db：由 FastAPI 管理，每个请求自动创建/关闭会话（副作用）
#   - get_xxx_repository：根据 db 会话创建对应的仓储实例
# 数据流：请求 → Depends(get_db) 创建 Session → Depends(get_book_repository) 创建 Repository → 路由处理
# 优势：每个请求拥有独立的数据库连接，避免并发冲突；请求结束后自动归还连接池


def get_book_repository(db: AsyncSession = Depends(get_db)) -> BookRepository:
    # 用途：书籍管理的数据访问层，绑定到同一个数据库会话
    return BookRepository(db)


def get_chapter_repository(db: AsyncSession = Depends(get_db)) -> ChapterRepository:
    # 用途：章节管理的数据访问层，绑定到同一个数据库会话
    return ChapterRepository(db)


def get_character_repository(db: AsyncSession = Depends(get_db)) -> CharacterRepository:
    # 用途：角色管理的数据访问层，绑定到同一个数据库会话
    return CharacterRepository(db)


def get_relationship_repository(db: AsyncSession = Depends(get_db)) -> RelationshipRepository:
    # 用途：关系管理的数据访问层，绑定到同一个数据库会话
    return RelationshipRepository(db)


def get_memory_repository(db: AsyncSession = Depends(get_db)) -> MemoryRepository:
    # 用途：记忆管理的数据访问层，绑定到同一个数据库会话
    return MemoryRepository(db)


def get_map_repository(db: AsyncSession = Depends(get_db)) -> MapLocationRepository:
    # 用途：地图管理的数据访问层
    return MapLocationRepository(db)
