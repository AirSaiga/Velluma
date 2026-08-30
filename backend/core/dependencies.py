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

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.repositories.asset_repository import AssetRepository, ChapterAssetRepository
from backend.repositories import (
    BookRepository,
    ChapterRepository,
    CharacterRepository,
    RelationshipRepository,
    MemoryRepository,
    MapLocationRepository,
    PlotLedgerRepository,
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
    return BookRepository(db)


def get_chapter_repository(db: AsyncSession = Depends(get_db)) -> ChapterRepository:
    return ChapterRepository(db)


def get_character_repository(db: AsyncSession = Depends(get_db)) -> CharacterRepository:
    return CharacterRepository(db)


def get_relationship_repository(db: AsyncSession = Depends(get_db)) -> RelationshipRepository:
    return RelationshipRepository(db)


def get_memory_repository(db: AsyncSession = Depends(get_db)) -> MemoryRepository:
    return MemoryRepository(db)


def get_map_repository(db: AsyncSession = Depends(get_db)) -> MapLocationRepository:
    return MapLocationRepository(db)


def get_plot_ledger_repository(db: AsyncSession = Depends(get_db)) -> PlotLedgerRepository:
    """伏笔账本仓储依赖注入函数。
    
    用于 RAG 服务层获取伏笔数据。
    """
    return PlotLedgerRepository(db)


def get_asset_repository(db: AsyncSession = Depends(get_db)) -> AssetRepository:
    return AssetRepository(db)


def get_chapter_asset_repository(db: AsyncSession = Depends(get_db)) -> ChapterAssetRepository:
    return ChapterAssetRepository(db)
