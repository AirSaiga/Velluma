"""
数据库配置模块。

核心职责：
1. 异步 SQLAlchemy 引擎配置 (连接池管理)
2. 会话依赖注入 (FastAPI 集成)
3. 表结构初始化与迁移

架构设计：
- 使用 asyncpg 驱动实现真正的异步 I/O
- 连接池预检 (pool_pre_ping) 防止连接因空闲超时被 DB 关闭
- 迁移策略：应用启动时检查并添加缺失列 (非生产级，建议使用 Alembic)
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

# 连接池配置说明：
# - pool_size=10: 常规连接数，支撑正常并发请求
# - max_overflow=20: 峰值时可额外创建20个连接 (共30个)
# - pool_pre_ping=True: 每次获取连接前先 ping DB，确认连接可用 (避免空闲连接失效错误)
# 权衡：生产环境需根据 QPS 调整，当前配置适合中小规模部署
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# 会话工厂配置：
# - expire_on_commit=False: 提交后对象不过期，避免再次访问需刷新
# - autocommit=False: 显式事务管理，需手动 commit/rollback
# - autoflush=False: 延迟写入，需显式 flush 或 commit
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
    依赖注入函数：获取数据库会话。

    用法：在 FastAPI 路由函数中通过 Depends(get_db) 注入。

    副作用：
    - 请求结束时自动关闭会话 (通过 async with 上下文管理器)
    - 提交后 connection 归还连接池

    权衡：不支持手动控制事务边界，适合简单 CRUD 场景。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    初始化数据库表结构。

    执行顺序：
    1. 创建 pgvector 扩展 (向量搜索依赖)
    2. 创建所有 ORM 模型对应的表
    3. 执行列迁移 (添加缺失字段)

    警告：run_migrations 使用朴素的条件判断，不支持回滚。
    生产环境应使用 Alembic 或 Flyway 等专业迁移工具。
    """
    from backend.models import Book, Chapter, ChapterEntity, Character, CharacterRelationship, MemoryChunk
    from sqlalchemy import text

    async with engine.begin() as conn:
        # 关键：pgvector 必须在使用向量类型前创建，且需超级用户权限
        # 副作用：IF NOT EXISTS 确保幂等性，但首次失败会中断启动
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)


async def run_migrations(conn):
    """
    执行数据库迁移，自动添加缺失的列。

    朴素迁移策略：
    - 检查 information_schema.columns 是否存在目标列
    - 若不存在则 ALTER TABLE ADD COLUMN

    权衡：
    - 优点：无需外部工具，快速上手
    - 缺点：不支持列重命名、类型变更、数据迁移
    - 警告：多列并发添加可能产生锁竞争

    适配场景：开发阶段或字段较少的项目。
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
        {
            "table": "chapters",
            "column": "summary",
            "definition": "TEXT",
            "check": "SELECT 1 FROM information_schema.columns WHERE table_name = 'chapters' AND column_name = 'summary'"
        },
        {
            "table": "chapters",
            "column": "chapter_name",
            "definition": "VARCHAR(200)",
            "check": "SELECT 1 FROM information_schema.columns WHERE table_name = 'chapters' AND column_name = 'chapter_name'"
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
