# -*- coding: utf-8 -*-
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

"""
PG → SQLite 一次性数据搬迁脚本（迁移准备期工具，切换日/演练时手动运行）。

用法：
    python scripts/migrate_pg_to_sqlite.py --sqlite-path data/velluma_migrated.db
    python scripts/migrate_pg_to_sqlite.py --pg-url postgresql+asyncpg://... --truncate

行为契约：
- PG 侧全程只读（SELECT），绝不写源库。
- SQLite 目标库若已初始化且有数据，必须显式 --truncate 才会清空重搬
  （拓扑逆序 DELETE，防半途搬迁的脏数据）。
- embedding 列（memory_chunks / 另一处 Vector(1536)）默认丢弃置 NULL：
  SQLite 模式不支持向量记忆（本就是未配置 embedding 时自动降级的可选功能），
  保留只会得到一份无法检索的死数据。--keep-embedding 可保留为 TEXT 占位。
- 校验：逐表行数对照 + PRAGMA foreign_key_check（孤儿行检测），
  任何一项不过 → 退出码 1。

⚠ 演练建议：先 --sqlite-path 指向临时文件跑一遍并人工抽查，
确认无误后再面向真实目标库执行（切换日动作之一）。
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows 控制台 GBK 防御
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import class_mapper

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite

# 默认与 backend/database.py 保持一致（不 import 它，避免绑定其模块级 PG 引擎）
DEFAULT_PG_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver",
)
EMBEDDING_SKIP_TABLES = {"memory_chunks", "author_samples"}


async def count_rows(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def table_has_data(conn, table_name: str) -> bool:
    """表存在且有数据才返回 True（全新库尚未建表 → False，走正常初始化路径）。"""
    exists = await conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n").bindparams(n=table_name)
    )
    if exists.fetchone() is None:
        return False
    rows = await conn.execute(text(f'SELECT 1 FROM "{table_name}" LIMIT 1'))
    return rows.fetchone() is not None


async def truncate_sqlite(engine) -> None:
    """拓扑逆序清空（子表先删，外键 ON 下安全）。"""
    tables = list(reversed(list(m.Base.metadata.sorted_tables)))
    async with engine.begin() as conn:
        for table in tables:
            await conn.execute(table.delete())
    print(f"[TRUNCATE] 已清空 {len(tables)} 张表")


async def copy_table(pg_session, lite_session, model, batch_size: int, keep_embedding: bool):
    """逐字段拷贝一张表（只走 column_attrs，不碰 relationship 防级联重插）。"""
    mapper = class_mapper(model)
    col_keys = [c.key for c in mapper.column_attrs]
    skip_embedding = not keep_embedding and "embedding" in col_keys
    if skip_embedding:
        col_keys = [k for k in col_keys if k != "embedding"]

    total = 0
    batch = []
    result = await pg_session.execute(select(model))
    for obj in result.scalars():
        row = {k: getattr(obj, k) for k in col_keys}
        batch.append(model(**row))
        total += 1
        if len(batch) >= batch_size:
            lite_session.add_all(batch)
            await lite_session.commit()
            batch = []
    if batch:
        lite_session.add_all(batch)
        await lite_session.commit()
    return total, skip_embedding


def _table_to_model() -> dict:
    """表名 → ORM 类映射（Base 实体集合，一次构建）。"""
    return {
        cls.__tablename__: cls
        for cls in _model_map_values()
    }


def _model_map_values():
    return [
        cls
        for cls in vars(m).values()
        if isinstance(cls, type) and issubclass(cls, m.Base) and cls is not m.Base and hasattr(cls, "__tablename__")
    ]


async def run(pg_url: str, sqlite_path: str, batch_size: int, truncate: bool, keep_embedding: bool) -> int:
    print(f"[PG]     连接 {pg_url}")
    pg_engine = create_async_engine(pg_url, future=True)
    pg_maker = async_sessionmaker(pg_engine, expire_on_commit=False)

    lite_engine = build_sqlite_engine(sqlite_path)
    lite_maker = build_sqlite_sessionmaker(lite_engine)

    try:
        try:
            async with pg_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as e:
            print(f"[ERROR] PG 连接失败: {e}")
            return 1

        # ---- 源库结构补齐（2026-08-19 增补）：应用 ORM 新增列（spine/map_scale/
        # ref_type 等）若源 PG 未跑过启动迁移，SELECT 反射会 UndefinedColumn。
        # 只做加列（同应用启动迁移的 MIGRATIONS 清单），不改任何行——数据只读契约不变。
        try:
            from backend.database import MIGRATIONS, run_migrations
            async with pg_engine.begin() as conn:
                await run_migrations(conn)
            print(f"[SCHEMA] 源 PG 结构已补齐（{len(MIGRATIONS)} 项列迁移检查，仅加缺失列）")
        except Exception as e:
            print(f"[ERROR] 源 PG 结构补齐失败: {e}")
            return 1

        # 目标库有数据必须显式 --truncate
        async with lite_engine.begin() as conn:
            populated = False
            for t in m.Base.metadata.sorted_tables:
                if await table_has_data(conn, t.name):
                    populated = True
                    break
        if populated and not truncate:
            print("[ERROR] SQLite 目标库已有数据。确认重搬请加 --truncate（将清空目标库全部表）。")
            return 1
        if populated and truncate:
            await truncate_sqlite(lite_engine)

        print("[SCHEMA] 初始化 SQLite schema（建表 + 列迁移 + 数据迁移）")
        # sessionmaker 不传 → 跳过 SystemCliche 种子化：数据以源库为准
        # （种子数据在 PG 里已存在，再种一遍会翻倍——首次演练实测踩过）
        await init_db_sqlite(lite_engine)

        print("[COPY]   开始搬迁（拓扑序，父表先入）")
        t2m = _table_to_model()
        report = {}
        async with pg_maker() as pg_session, lite_maker() as lite_session:
            for table in m.Base.metadata.sorted_tables:
                model = t2m.get(table.name)
                if model is None:
                    print(f"[WARN]   跳过无 ORM 模型表: {table.name}")
                    continue
                total, skipped_vec = await copy_table(
                    pg_session, lite_session, model, batch_size, keep_embedding
                )
                report[table.name] = total
                note = "（embedding 置空）" if skipped_vec else ""
                print(f"  {table.name:<28} {total:>7} 行 {note}")

        print("[CHECK]  校验")
        ok = True
        async with pg_maker() as pg_session, lite_maker() as lite_session:
            for table in m.Base.metadata.sorted_tables:
                model = t2m.get(table.name)
                if model is None:
                    continue
                pg_n = await count_rows(pg_session, model)
                lite_n = await count_rows(lite_session, model)
                if pg_n != lite_n:
                    print(f"  [FAIL] {table.name}: PG={pg_n} SQLite={lite_n}")
                    ok = False
        async with lite_engine.connect() as conn:
            orphans = (await conn.execute(text("PRAGMA foreign_key_check"))).fetchall()
            if orphans:
                print(f"  [FAIL] foreign_key_check 发现 {len(orphans)} 行孤儿引用: {orphans[:5]}")
                ok = False
        if ok:
            total_rows = sum(report.values())
            print(f"[DONE]   全部通过：{len(report)} 表 {total_rows} 行 → {sqlite_path}")
            return 0
        return 1
    finally:
        await pg_engine.dispose()
        await lite_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Velluma PG → SQLite 数据搬迁（PG 只读）")
    parser.add_argument("--pg-url", default=DEFAULT_PG_URL, help="源 PG 连接串（默认读 DATABASE_URL）")
    parser.add_argument("--sqlite-path", default="data/velluma_migrated.db", help="目标 SQLite 文件")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--truncate", action="store_true", help="目标库有数据时清空重搬")
    parser.add_argument("--keep-embedding", action="store_true", help="保留 embedding 为 TEXT（默认丢弃）")
    args = parser.parse_args()

    code = asyncio.run(
        run(args.pg_url, args.sqlite_path, args.batch_size, args.truncate, args.keep_embedding)
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
