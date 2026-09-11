# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""文风路由的仓储依赖提供者（各子模块端点 Depends 共用）。"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.repositories import (
    AuthorSampleRepository,
    BookRepository,
    StyleCardRepository,
    SystemClicheRepository,
)


# ============================================================
# 辅助：依赖注入工厂（最小侵入，避免改 core/dependencies.py）
# ============================================================

def get_style_card_repo(db: AsyncSession = Depends(get_db)) -> StyleCardRepository:
    return StyleCardRepository(db)


def get_author_sample_repo(db: AsyncSession = Depends(get_db)) -> AuthorSampleRepository:
    return AuthorSampleRepository(db)


def get_system_cliche_repo(db: AsyncSession = Depends(get_db)) -> SystemClicheRepository:
    return SystemClicheRepository(db)


def get_book_repo(db: AsyncSession = Depends(get_db)) -> BookRepository:
    return BookRepository(db)


