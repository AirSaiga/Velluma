"""
数据库配置模块
配置异步 SQLAlchemy 引擎，提供依赖注入的会话管理
"""

import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    依赖注入函数：获取数据库会话

    用于 FastAPI 路由中注入数据库会话，确保请求结束后自动关闭

    Yields:
        AsyncSession: 异步数据库会话
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    初始化数据库表结构

    在 FastAPI 应用启动时调用，创建所有表并确保 pgvector 扩展可用
    同时执行必要的数据库迁移
    """
    from backend.models import Book, Chapter, ChapterEntity, Character, CharacterRelationship, MemoryChunk
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)


async def run_migrations(conn):
    """
    执行数据库迁移，自动添加缺失的列
    """
    from sqlalchemy import text
    
    migrations = [
        {
            "table": "books",
            "column": "worldview_settings",
            "definition": "JSONB DEFAULT '{}'",
            "check": "SELECT 1 FROM information_schema.columns WHERE table_name = 'books' AND column_name = 'worldview_settings'"
        },
        {
            "table": "characters",
            "column": "dynamic_state_history",
            "definition": "JSONB DEFAULT '[]'",
            "check": "SELECT 1 FROM information_schema.columns WHERE table_name = 'characters' AND column_name = 'dynamic_state_history'"
        },
        {
            "table": "chapters",
            "column": "draft_text",
            "definition": "TEXT",
            "check": "SELECT 1 FROM information_schema.columns WHERE table_name = 'chapters' AND column_name = 'draft_text'"
        },
        {
            "table": "chapters",
            "column": "review_feedback",
            "definition": "JSONB DEFAULT '{}'",
            "check": "SELECT 1 FROM information_schema.columns WHERE table_name = 'chapters' AND column_name = 'review_feedback'"
        },
        {
            "table": "chapters",
            "column": "revision_count",
            "definition": "INTEGER DEFAULT 0",
            "check": "SELECT 1 FROM information_schema.columns WHERE table_name = 'chapters' AND column_name = 'revision_count'"
        },
    ]
    
    for migration in migrations:
        try:
            result = await conn.execute(text(migration["check"]))
            if result.fetchone() is None:
                await conn.execute(text(
                    f"ALTER TABLE {migration['table']} ADD COLUMN {migration['column']} {migration['definition']};"
                ))
                print(f"[MIGRATION] Added column {migration['table']}.{migration['column']}")
        except Exception as e:
            print(f"[MIGRATION] Skipped {migration['table']}.{migration['column']}: {e}")
