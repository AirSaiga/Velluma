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
db_sqlite 包自测（SQLite 后端迁移准备期的回归闸门）。

运行：`.venv/Scripts/python.exe -m pytest backend/db_sqlite/test_db_sqlite.py -v`

覆盖面（与切换风险一一对应）：
- 建表：31 张 ORM 表全部落库（方言类型适配有效性）
- CRUD 往返：UUID 主键 / JSONB dict+list / Float / DateTime 读写无损
- 外键级联：fresh 连接上 CASCADE 生效（连接级 pragma 钩子逐连接生效，
  防"池复用巧合"假阳性）
- 列迁移器：模拟老库缺列，run_migrations_sqlite 补列
- 数据迁移：props.legacy_profile → background 三分支语义
- 兼容查询：canon 三种 JSONB 查询的 SQLite 等价性（含 NULL 边界）

注意：每个测试用独立事件循环（asyncio.run）与独立临时库文件，
规避项目已知的跨文件事件循环污染问题（见 AGENTS.md 测试节）。
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, text

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite import compat_queries as cq
from backend.db_sqlite.schema import (
    _migrate_legacy_profile_keys_sqlite,
    init_db_sqlite,
    run_migrations_sqlite,
)


def _make_stack(tmp_path, name="test.db"):
    """建引擎+会话工厂+初始化 schema，返回 (engine, sessionmaker)。"""
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _table_names(engine):
    async def run():
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            return {r[0] for r in rows.fetchall()}

    return asyncio.run(run())


def test_create_all_builds_every_table(tmp_path):
    engine, _ = _make_stack(tmp_path)
    try:
        expected = set(m.Base.metadata.tables.keys())
        actual = _table_names(engine)
        missing = expected - actual
        assert not missing, f"缺表: {missing}"
        assert len(expected) == 33, f"ORM 表数变化: {len(expected)}（新增表请同步更新本断言；B1 world_event_edges、B2 world_intents）"
    finally:
        asyncio.run(engine.dispose())


def test_crud_roundtrip_uuid_jsonb_float_datetime(tmp_path):
    engine, maker = _make_stack(tmp_path)
    book_id = uuid.uuid4()
    chapter_id = uuid.uuid4()
    try:

        async def seed():
            async with maker() as s:
                s.add(
                    m.Book(
                        id=book_id,
                        title="往返测试",
                        worldview_settings={"era": "架空", "layers": [1, "二"]},
                        golden_snippets=["金句甲", "金句乙"],
                        reader_mirror={"curves": [{"ch": 1, "t": 8}]},
                    )
                )
                s.add(
                    m.WorldEntity(
                        id=uuid.uuid4(),
                        book_id=book_id,
                        entity_type="character",
                        name="兰星",
                        aliases=["星", "小兰"],
                        importance=3,
                        canvas_x=12.5,
                        canvas_y=-3.25,
                        props={"appearance": "黑发", "nested": {"a": [1, 2]}},
                    )
                )
                s.add(
                    m.Chapter(
                        id=chapter_id,
                        book_id=book_id,
                        chapter_number=1,
                        title="第一章",
                        draft_text="正文" * 300,
                        world_snapshot={"pos": {"x": 1.5}},
                    )
                )
                await s.commit()

        asyncio.run(seed())

        async def verify():
            async with maker() as s:
                book = await s.get(m.Book, book_id)
                assert isinstance(book.id, uuid.UUID) and book.id == book_id
                assert book.worldview_settings == {"era": "架空", "layers": [1, "二"]}
                assert book.golden_snippets == ["金句甲", "金句乙"]
                assert book.reader_mirror == {"curves": [{"ch": 1, "t": 8}]}
                assert book.created_at is not None

                ent = (
                    await s.execute(select(m.WorldEntity).where(m.WorldEntity.name == "兰星"))
                ).scalar_one()
                assert ent.aliases == ["星", "小兰"]
                assert ent.canvas_x == 12.5 and ent.canvas_y == -3.25
                assert ent.props["nested"] == {"a": [1, 2]}

                chapter = await s.get(m.Chapter, chapter_id)
                assert chapter.draft_text == "正文" * 300
                assert chapter.world_snapshot == {"pos": {"x": 1.5}}

        asyncio.run(verify())
    finally:
        asyncio.run(engine.dispose())


def test_fk_cascade_on_fresh_connection(tmp_path):
    """删 Book → Chapter/CanonNode 级联消失。用全新连接删（NullPool 下每个
    session 连接都是新开的），证明 connect 钩子对每个连接都设了 pragma，
    而非池复用巧合。"""
    engine, maker = _make_stack(tmp_path)
    book_id = uuid.uuid4()
    try:

        async def seed():
            async with maker() as s:
                s.add(m.Book(id=book_id, title="级联测试"))
                s.add(m.Chapter(id=uuid.uuid4(), book_id=book_id, chapter_number=1, title="c1"))
                s.add(
                    m.CanonNode(
                        id=uuid.uuid4(), book_id=book_id, type="hook", label="伏笔X"
                    )
                )
                await s.commit()

        asyncio.run(seed())

        async def drop_book():
            async with maker() as s:
                await s.execute(delete(m.Book).where(m.Book.id == book_id))
                await s.commit()

        asyncio.run(drop_book())

        async def verify():
            async with maker() as s:
                chapters = (
                    await s.execute(select(m.Chapter).where(m.Chapter.book_id == book_id))
                ).scalars().all()
                nodes = (
                    await s.execute(select(m.CanonNode).where(m.CanonNode.book_id == book_id))
                ).scalars().all()
                assert chapters == [] and nodes == [], "外键级联未生效（pragma 钩子失效）"

        asyncio.run(verify())
    finally:
        asyncio.run(engine.dispose())


def test_run_migrations_adds_missing_column(tmp_path):
    """模拟老库：DROP 掉 MIGRATIONS 管辖的列，再跑迁移器应补回。"""
    engine, maker = _make_stack(tmp_path)
    try:
        from backend.database import MIGRATIONS

        async def drop_column():
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE chapters DROP COLUMN narrative_time"))

        asyncio.run(drop_column())
        cols_before = _columns(engine, "chapters")
        assert "narrative_time" not in cols_before

        async def remigrate():
            async with engine.begin() as conn:
                await run_migrations_sqlite(conn, MIGRATIONS)

        asyncio.run(remigrate())
        assert "narrative_time" in _columns(engine, "chapters")

        # 幂等：再跑一遍不报错不重复
        asyncio.run(remigrate())
    finally:
        asyncio.run(engine.dispose())


def _columns(engine, table):
    async def run():
        async with engine.connect() as conn:
            rows = await conn.execute(text(f'PRAGMA table_info("{table}")'))
            return [r[1] for r in rows.fetchall()]

    return asyncio.run(run())


def test_legacy_profile_migration_branches(tmp_path):
    engine, maker = _make_stack(tmp_path)
    book_id = uuid.uuid4()
    try:

        async def seed():
            async with maker() as s:
                s.add(m.Book(id=book_id, title="档案迁移"))
                s.add(
                    m.WorldEntity(
                        id=uuid.uuid4(), book_id=book_id, entity_type="character", name="空底",
                        props={"legacy_profile": "旧档案", "background": ""},
                    )
                )
                s.add(
                    m.WorldEntity(
                        id=uuid.uuid4(), book_id=book_id, entity_type="character", name="有底",
                        props={"legacy_profile": "旧档案", "background": "新档案"},
                    )
                )
                s.add(
                    m.WorldEntity(
                        id=uuid.uuid4(), book_id=book_id, entity_type="character", name="空legacy",
                        props={"legacy_profile": "   ", "background": "保持"},
                    )
                )
                s.add(
                    m.WorldEntity(
                        id=uuid.uuid4(), book_id=book_id, entity_type="character", name="无关",
                        props={"background": "原样"},
                    )
                )
                await s.commit()

        asyncio.run(seed())

        async def migrate():
            async with engine.begin() as conn:
                await _migrate_legacy_profile_keys_sqlite(conn)

        asyncio.run(migrate())

        async def verify():
            async with maker() as s:
                by_name = {
                    e.name: e.props
                    for e in (
                        await s.execute(select(m.WorldEntity).where(m.WorldEntity.book_id == book_id))
                    ).scalars()
                }
                assert by_name["空底"] == {"background": "旧档案"}
                assert by_name["有底"] == {"background": "新档案\n\n旧档案"}
                assert by_name["空legacy"] == {"background": "保持"}
                assert by_name["无关"] == {"background": "原样"}

        asyncio.run(verify())
    finally:
        asyncio.run(engine.dispose())


def test_canon_compat_queries(tmp_path):
    engine, maker = _make_stack(tmp_path)
    book_id = uuid.uuid4()
    try:

        async def seed():
            async with maker() as s:
                s.add(m.Book(id=book_id, title="canon查询"))
                s.add(
                    m.CanonNode(
                        id=uuid.uuid4(), book_id=book_id, type="hook", label="n1",
                        tags=["主线", "暗线"],
                        metadata_={"status": "open"},
                        appeared_in=[1, 3, 5],
                    )
                )
                s.add(
                    m.CanonNode(
                        id=uuid.uuid4(), book_id=book_id, type="hook", label="n2",
                        tags=[],
                        metadata_={},
                        appeared_in=[],
                    )
                )
                s.add(
                    m.CanonNode(
                        id=uuid.uuid4(), book_id=book_id, type="hook", label="n3",
                        tags=["支线"],
                        metadata_={"status": "echoed"},
                        appeared_in=[2],
                    )
                )
                await s.commit()

        asyncio.run(seed())

        async def q(where):
            async with maker() as s:
                stmt = select(m.CanonNode).where(
                    m.CanonNode.book_id == book_id
                ).where(where)
                rows = (await s.execute(stmt)).scalars().all()
                return sorted(r.label for r in rows)

        assert asyncio.run(q(cq.tags_has_tag("主线"))) == ["n1"]
        assert asyncio.run(q(cq.tags_has_tag("不存在"))) == []
        assert asyncio.run(q(cq.metadata_status_equals("open"))) == ["n1"]
        assert asyncio.run(q(cq.metadata_status_equals("echoed"))) == ["n3"]
        assert asyncio.run(q(cq.metadata_status_equals("missing"))) == []
        assert asyncio.run(q(cq.appeared_in_contains_chapter(3))) == ["n1"]
        assert asyncio.run(q(cq.appeared_in_contains_chapter(4))) == []
        # n2 全空字段：不炸、不误命中
        assert asyncio.run(q(cq.tags_has_tag("主线"))) != ["n1", "n2"]
    finally:
        asyncio.run(engine.dispose())


def test_seed_system_cliches(tmp_path):
    engine, maker = _make_stack(tmp_path)

    async def count():
        async with maker() as s:
            rows = await s.execute(select(m.SystemCliche.id))
            return len(rows.fetchall())

    try:
        n = asyncio.run(count())
        assert n > 0, "SystemCliche 种子化未生效"
        # 幂等：再初始化一次不重复
        asyncio.run(init_db_sqlite(engine, maker))
        assert asyncio.run(count()) == n
    finally:
        asyncio.run(engine.dispose())
