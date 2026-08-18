# -*- coding: utf-8 -*-
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
SQLite 异步引擎与会话工厂（对应 backend/database.py 的 SQLite 侧实现）。

与 PG 引擎的三点刻意差异（勿照抄 database.py 配置）：
1. NullPool：SQLite 文件库单用户场景用连接池是反模式——多连接并发写会触发
   "database is locked"。每连接独立打开文件的开销（微秒级）可忽略，
   从根上消除锁竞争。写并发本就只有"单作者编辑器保存 + 低频后台沉淀"。
2. 连接级 pragma 必须逐连接设置（SQLite 的 PRAGMA 是连接作用域而非库作用域，
   journal_mode 除外）：foreign_keys=ON 保证全部 ORM 表的 ondelete CASCADE/SET NULL
   真正生效（默认 OFF，级联静默失效留孤儿数据——最大的隐性坑）；
   busy_timeout 兜底偶发的写锁等待；synchronous=NORMAL 是 WAL 的推荐档。
3. WAL：读写不互斥，作者打字保存（写）不会被后台读取（心跳/RAG 检索）阻塞。
   ⚠ :memory: 库上 WAL 不适用（SQLite 自动回落 memory 模式，不报错），
   自测用文件库验证。
"""

import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.db_sqlite.type_compat import register_sqlite_type_compat


def sqlite_url(db_path: str | os.PathLike) -> str:
    """构造 aiosqlite 连接串。父目录不存在时由调用方负责创建。"""
    return f"sqlite+aiosqlite:///{db_path}"


def build_sqlite_engine(
    db_path: str | os.PathLike,
    *,
    echo: bool = False,
):
    """创建带完整 pragma 钩子的 SQLite 异步引擎。

    副作用：注册方言类型编译（幂等）；确保父目录存在。
    """
    register_sqlite_type_compat()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        sqlite_url(db_path),
        echo=echo,
        future=True,
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover - 驱动回调
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine


def build_sqlite_sessionmaker(engine) -> async_sessionmaker:
    """会话工厂：参数语义与 backend/database.py 的 AsyncSessionLocal 对齐
    （expire_on_commit=False / autocommit=False / autoflush=False），
    保证切换日后仓储层代码在两个后端行为一致。"""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
