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

import logging
import os
import sys
from typing import Any, AsyncGenerator, Optional, Sequence
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

load_dotenv()

# 配置模块级日志记录器
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver"
)

# 连接池预检配置：
# - 默认在 Windows 上禁用（asyncpg + greenlet 兼容性问题）
# - 在其他平台默认启用，避免空闲连接失效
# - 可通过环境变量 DB_POOL_PRE_PING 强制覆盖
_DEFAULT_POOL_PRE_PING = False if sys.platform == "win32" else True
POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", str(_DEFAULT_POOL_PRE_PING)).lower() in ("true", "1", "yes")

# 连接池配置说明：
# - pool_size=10: 常规连接数，支撑正常并发请求
# - max_overflow=20: 峰值时可额外创建20个连接 (共30个)
# - pool_pre_ping=True: 每次获取连接前先 ping DB，确认连接可用 (避免空闲连接失效错误)
# 权衡：生产环境需根据 QPS 调整，当前配置适合中小规模部署
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=POOL_PRE_PING,
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

MIGRATIONS: list[dict[str, Any]] = [
    {
        "table": "books",
        "column": "worldview_settings",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "characters",
        "column": "dynamic_state_history",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "draft_text",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "chapters",
        "column": "review_feedback",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "revision_count",
        "definition": "INTEGER DEFAULT 0",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "chapters",
        "column": "summary",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "chapters",
        "column": "map_activity_range",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "chapters",
        "column": "chapter_name",
        "definition": "VARCHAR(200)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "beat_id",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "location",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "pov_character",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "action_summary",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "worldbuilding_instruction",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "word_count_target",
        "definition": "INTEGER DEFAULT 0",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "story_beats",
        "column": "metadata",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "scene_intents",
        "column": "character_name",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "scene_intents",
        "column": "obstacle",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "scene_intents",
        "column": "tactic",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "scene_intents",
        "column": "constraints",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "plot_ledgers",
        "column": "hook_id",
        "definition": "VARCHAR(150)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "status",
        "definition": "VARCHAR(20) DEFAULT 'open'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "created_at_chapter",
        "definition": "INTEGER",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "plot_ledgers",
        "column": "metadata",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "tension_level",
        "definition": "INTEGER DEFAULT 5 NOT NULL",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "chapters",
        "column": "pacing_style",
        "definition": "VARCHAR(50) DEFAULT 'balanced' NOT NULL",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "entry_state",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "exit_state",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "red_lines",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "story_beats",
        "column": "beat_type",
        "definition": "VARCHAR(100) DEFAULT 'progression'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "position",
        "definition": "INTEGER DEFAULT 0",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "story_beats",
        "column": "status",
        "definition": "VARCHAR(50) DEFAULT 'planned'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "entry_type",
        "definition": "VARCHAR(50) DEFAULT 'foreshadow'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "content",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "books",
        "column": "core_motifs_taboos",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "books",
        "column": "golden_snippets",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "books",
        "column": "style_blacklist",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "story_beats",
        "column": "pacing_type",
        "definition": "VARCHAR(50)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "weight",
        "definition": "INTEGER DEFAULT 1",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "story_beats",
        "column": "anchor_pov",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "original_actor",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "chapters",
        "column": "chapter_assets_schema",
        "definition": "TEXT DEFAULT ''",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "pov_perception_state",
        "definition": "TEXT DEFAULT '正常'",
        "expected_udt_names": {"text"},
    },
]


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
    from backend.models import (
        Book,
        Chapter,
        ChapterEntity,
        ChapterMapLocation,
        Character,
        CharacterRelationship,
        MapLocation,
        MemoryChunk,
        PlotLedger,
        SceneIntent,
        StoryBeat,
    )

    async with engine.begin() as conn:
        # 关键：pgvector 必须在使用向量类型前创建，且需超级用户权限
        # 副作用：IF NOT EXISTS 确保幂等性，但首次失败会中断启动
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)


async def _get_column_info(conn, table_name: str, column_name: str) -> Optional[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT data_type, udt_name, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    row = result.mappings().first()
    return dict(row) if row else None


def _is_column_compatible(column_info: dict[str, Any], migration: dict[str, Any]) -> bool:
    expected_udt_names: set[str] = migration.get("expected_udt_names", set())
    if not expected_udt_names:
        return True
    actual_udt_name = str(column_info.get("udt_name", "")).lower()
    return actual_udt_name in expected_udt_names


async def run_migrations(conn, migrations: Optional[Sequence[dict[str, Any]]] = None):
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
    migrations = migrations or MIGRATIONS

    for migration in migrations:
        table_name = migration["table"]
        column_name = migration["column"]
        try:
            column_info = await _get_column_info(conn, table_name=table_name, column_name=column_name)
            if column_info:
                if not _is_column_compatible(column_info, migration):
                    logger.warning(
                        f"[MIGRATION] Column conflict on {table_name}.{column_name}: "
                        f"actual_type={column_info.get('udt_name')} expected={sorted(migration.get('expected_udt_names', []))}"
                    )
                continue
            await conn.execute(
                text(
                    f'ALTER TABLE "{table_name}" '
                    f'ADD COLUMN IF NOT EXISTS "{column_name}" {migration["definition"]};'
                )
            )
            logger.info(f"[MIGRATION] Added column {table_name}.{column_name}")
        except Exception as e:
            logger.warning(f"[MIGRATION] Skipped {table_name}.{column_name}: {e}")
