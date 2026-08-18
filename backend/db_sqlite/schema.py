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
SQLite 侧数据库初始化（对应 backend/database.py init_db() 的等价物）。

与 PG 版 init_db 的差异（均为刻意为之）：
- 无 CREATE EXTENSION / 无向量维度迁移：pgvector 是 PG 专有；SQLite 模式下
  embedding 列渲染为 TEXT 占位且永远不用（向量记忆降级路径见 type_compat）。
- 列迁移复用 backend.database.MIGRATIONS 同一份定义（单一事实源：两侧补列
  规则永远同步演进），但类型校验（expected_udt_names）跳过——那是 PG 系统
  目录的 udt 名，SQLite 动态类型无对应概念。definition 原样执行：SQLite
  宽松解析接受 JSONB/UUID 等类型名（实际按亲和规则存储，读写经 ORM 类型
  处理器无损）。⚠ MIGRATIONS 若未来新增带 server-side 特性的 definition
  （如触发器），此处需要单独评审。
- props.legacy_profile 数据迁移用 Python 实现（PG 版是 jsonb_set/to_jsonb
  纯 SQL），语义逐字对齐：background 非空则 "background\\n\\nlegacy" 合并，
  否则直接搬入；空串 legacy 只摘键不并入。
- SystemCliche 种子化逻辑与 PG 版一致，但 sessionmaker 参数化注入
  （不能复用 database.py 里绑定 PG 引擎的 AsyncSessionLocal）。
"""

import logging
from typing import Any, Optional, Sequence

from sqlalchemy import select, text, update

from backend.db_sqlite.type_compat import register_sqlite_type_compat

logger = logging.getLogger(__name__)


async def init_db_sqlite(engine, sessionmaker: Optional[Any] = None) -> None:
    """初始化 SQLite 库：建表 → 列迁移 → 数据迁移 → 种子化。

    Args:
        engine: build_sqlite_engine 产物（自带 pragma/类型适配）。
        sessionmaker: 可选，提供则执行 SystemCliche 种子化
            （需要 AsyncSession；engine.begin 的 conn 上跑不了仓储）。
    """
    from backend.models import Base  # 延迟 import：避免模型循环依赖并复用同一份 metadata
    from backend.database import MIGRATIONS

    register_sqlite_type_compat()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations_sqlite(conn, MIGRATIONS)
        await _migrate_legacy_profile_keys_sqlite(conn)

    if sessionmaker is not None:
        await _seed_system_cliches_sqlite(sessionmaker)


async def _sqlite_table_columns(conn, table_name: str) -> Optional[set[str]]:
    """PRAGMA table_info 取现有列名集合；表不存在返回 None。

    （对应 PG 版的 information_schema.columns 查询。）
    """
    result = await conn.execute(text(f'PRAGMA table_info("{table_name}")'))
    rows = result.fetchall()
    if not rows:
        # PRAGMA 对不存在的表返回空集而非报错；create_all 后不应出现，
        # 防御 MIGRATIONS 里表名与 ORM 不同步的笔误。
        return None
    return {str(row[1]) for row in rows}


async def run_migrations_sqlite(conn, migrations: Sequence[dict[str, Any]]) -> None:
    """补缺失列（对应 PG 版 run_migrations，差异见模块文档字符串）。"""
    for migration in migrations:
        table_name = migration["table"]
        column_name = migration["column"]
        try:
            columns = await _sqlite_table_columns(conn, table_name)
            if columns is None:
                logger.warning(f"[MIGRATION-SQLITE] 表不存在，跳过: {table_name}.{column_name}")
                continue
            if column_name in columns:
                continue
            await conn.execute(
                text(
                    f'ALTER TABLE "{table_name}" '
                    f'ADD COLUMN "{column_name}" {migration["definition"]};'
                )
            )
            logger.info(f"[MIGRATION-SQLITE] Added column {table_name}.{column_name}")
        except Exception as e:
            logger.warning(f"[MIGRATION-SQLITE] Skipped {table_name}.{column_name}: {e}")


async def _migrate_legacy_profile_keys_sqlite(conn) -> None:
    """world_entities.props.legacy_profile → props.background（Python 版，幂等）。

    WHERE 用 LIKE 粗筛（SQLAlchemy json_serializer 默认 ensure_ascii=True，
    legacy_profile 为 ASCII 键名，序列化文本必然含该子串），Python 侧精确判键。
    跑过一次后不再命中，后续启动零开销。
    """
    from backend.models import WorldEntity

    rows = (
        await conn.execute(
            select(WorldEntity.id, WorldEntity.props).where(
                text("props LIKE '%legacy_profile%'")
            )
        )
    ).all()
    if not rows:
        return

    merged = 0
    for entity_id, props in rows:
        props = dict(props) if isinstance(props, dict) else {}
        if "legacy_profile" not in props:
            continue
        legacy = str(props.get("legacy_profile") or "").strip()
        background = str(props.get("background") or "").strip()
        if legacy:
            props["background"] = f"{background}\n\n{legacy}" if background else legacy
        props.pop("legacy_profile", None)
        await conn.execute(
            update(WorldEntity).where(WorldEntity.id == entity_id).values(props=props)
        )
        merged += 1
    if merged:
        logger.info(f"[MIGRATION-SQLITE] props.legacy_profile → background: {merged} entities")


async def _seed_system_cliches_sqlite(sessionmaker) -> None:
    """SystemCliche 空表种子化（语义同 database._seed_system_cliches_if_empty）。"""
    try:
        from backend.repositories import SystemClicheRepository
        from backend.services.style.default_cliches import get_all_seed_cliches

        async with sessionmaker() as session:
            repo = SystemClicheRepository(session)
            seeds = get_all_seed_cliches()
            inserted = await repo.seed_if_empty(seeds)
            if inserted > 0:
                logger.info(f"[INIT-SQLITE] SystemCliche 表已种子化 {inserted} 条默认禁词")
    except Exception as e:
        logger.warning(f"[INIT-SQLITE] SystemCliche 种子化失败（不阻断启动）: {e}")
