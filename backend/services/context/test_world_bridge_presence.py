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
A2 在场提权单测（docs/foundation-hardening.md §2.3）。

覆盖：
- 有场景钉：低重要度在场角色击败高重要度远端角色进 16 名单；任一端点在场的
  活跃关系边提前（仍截 8）；
- 无场景钉：同一份世界数据下角色名单/关系边序与旧逻辑逐一致（零变化契约）；
- 空世界 / 无位置数据不报错；chapter 为鸭子类型对象（getattr 防御 + str 形态
  场景钉）可正常工作。

配方：临时文件 SQLite + 真实 repo 栈（db_sqlite 引擎 + init_db_sqlite 建 schema，
同 backend/db_sqlite/test_db_sqlite.py）。⚠ 引擎为 NullPool + WAL，
:memory: 库不适用（见 db_sqlite/engine.py 模块注释），故走临时文件库；
每个测试独立 asyncio.run 事件循环，规避已知跨文件事件循环污染（AGENTS.md 测试节）；
测试 UUID 一律带字母——全数字 UUID 在 SQLite NUMERIC 亲和性下有已知坑
（db_sqlite/type_compat.py _patch_uuid_int_tolerance）。

运行：python -m pytest backend/services/context/test_world_bridge_presence.py -v
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.world_repository import WorldRepository
from backend.services.context.world_bridge import load_world_overlay

BOOK_ID = uuid.UUID("aa110000-0000-4000-8000-000000000001")
LOC_SCENE = uuid.UUID("aa110000-0000-4000-8000-0000000000a1")  # 场景钉：大厅
LOC_REMOTE = uuid.UUID("aa110000-0000-4000-8000-0000000000a2")  # 远端：北岸要塞
CH_PINNED = uuid.UUID("aa110000-0000-4000-8000-0000000000b1")  # 钉了大厅
CH_UNPINNED = uuid.UUID("aa110000-0000-4000-8000-0000000000b2")  # 未钉

_T0 = datetime(2026, 1, 1, 12, 0, 0)


def _make_stack(tmp_path, name: str):
    """建引擎+会话工厂+初始化 schema，返回 (engine, sessionmaker)。"""
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed_world(session) -> None:
    """17 角色（1 低重要度在场 + 16 高重要度远端，均有事态）+ 9 条 static 活跃边。

    旧排序（有事态 → 重要度降序）下「扫地僧」（重要度 1）在 17 人中垫底被截；
    旧边序（created_at 序截 8）下最后建的扫地僧边被截——两者构成提权对照基线。
    """
    session.add(m.Book(id=BOOK_ID, title="在场提权测试书"))
    session.add_all(
        [
            m.Chapter(
                id=CH_PINNED,
                book_id=BOOK_ID,
                chapter_number=1,
                title="钉了场景",
                narrative_time=20,
                scene_location_id=LOC_SCENE,
            ),
            m.Chapter(
                id=CH_UNPINNED,
                book_id=BOOK_ID,
                chapter_number=2,
                title="未钉场景",
                narrative_time=20,
            ),
        ]
    )
    session.add_all(
        [
            m.WorldLocation(id=LOC_SCENE, book_id=BOOK_ID, name="大厅", kind="point"),
            m.WorldLocation(id=LOC_REMOTE, book_id=BOOK_ID, name="北岸要塞", kind="point"),
        ]
    )
    await session.flush()

    repo = WorldRepository(session)
    # 在场小角色：重要度 1，出生（t=5）即在大厅 → t=20 切片在场
    sweeper = await repo.entities.create(
        book_id=BOOK_ID,
        entity_type="character",
        name="扫地僧",
        importance=1,
    )
    await repo.events.create(
        book_id=BOOK_ID,
        event_type="birth",
        time_start=5,
        time_end=5,
        payload={"character_id": str(sweeper.id), "location_id": str(LOC_SCENE)},
        note="扫地僧生在大厅",
    )
    # 16 个远端角色：重要度 2..17（名字后缀 = 重要度-2），出生（t=5）即在北岸要塞
    remote_ids = []
    for i in range(16):
        ent = await repo.entities.create(
            book_id=BOOK_ID,
            entity_type="character",
            name=f"远端{i:02d}",
            importance=2 + i,
        )
        remote_ids.append(ent.id)
        await repo.events.create(
            book_id=BOOK_ID,
            event_type="birth",
            time_start=5,
            time_end=5,
            payload={"character_id": str(ent.id), "location_id": str(LOC_REMOTE)},
            note=f"远端{i:02d}生在北岸要塞",
        )
    # 关系边：8 条远端-远端（先建，created_at 递增保证确定序）+ 1 条扫地僧边（最后建）
    for i in range(8):
        await repo.relations.create(
            book_id=BOOK_ID,
            source_entity_id=remote_ids[i],
            target_entity_id=remote_ids[i + 8],
            relation_type="ally",
            label=f"远端同盟{i}",
            static=True,
            created_at=_T0 + timedelta(minutes=i),
        )
    await repo.relations.create(
        book_id=BOOK_ID,
        source_entity_id=sweeper.id,
        target_entity_id=remote_ids[0],
        relation_type="kin",
        label="扫地僧与远端00",
        static=True,
        created_at=_T0 + timedelta(minutes=99),
    )
    await session.flush()


def _char_names(overlay):
    return [c.character.name for c in overlay["entities"]]


def _rel_pairs(overlay):
    return [(r.source_character.name, r.target_character.name) for r in overlay["relationships"]]


async def _load_for_chapter(session, chapter) -> dict:
    return await load_world_overlay(str(BOOK_ID), session, chapter)


def test_pinned_scene_boosts_present_character_and_edges(tmp_path):
    """有场景钉：低重要度在场角色进 16 名单且居首；在场关系边提前进 8 边名单。"""
    engine, maker = _make_stack(tmp_path, "pinned.db")
    try:

        async def run():
            async with maker() as s:
                await _seed_world(s)
                chapter = await s.get(m.Chapter, CH_PINNED)
                return await _load_for_chapter(s, chapter)

        overlay = asyncio.run(run())
        assert overlay is not None
        assert overlay["world_time"] == 20
        assert overlay["world_time_source"] == "chapter_anchor"

        names = _char_names(overlay)
        # 知识检索平面 v3.1（2026-08-27）：名单数量上限退役——选择在消费侧
        # knowledge_plane 完成（宁多勿漏），桥接层只排序不裁剪；在场者仍排首位
        assert len(names) == 17
        assert names[0] == "扫地僧"
        assert "远端00" in names  # 不再被挤出名单（未选时由知识平面标注原因）
        # 其余席位按重要度降序：远端15（17）…远端00（2）——全员保留
        assert names[1] == "远端15"
        assert names[-1] == "远端00"

        pairs = _rel_pairs(overlay)
        # 数量上限退役：全部活跃边保留；在场边（扫地僧—远端00）提前到首位，
        # 其余远端边保持 created_at 序（07↔15 不再被截）
        assert len(pairs) >= 8  # 不再截 8（v3.1 桥接层去 cap）
        assert pairs[0] == ("扫地僧", "远端00")
        assert ("远端00", "远端08") in pairs
        assert ("远端07", "远端15") in pairs
    finally:
        asyncio.run(engine.dispose())


def test_unpinned_matches_legacy_ordering(tmp_path):
    """无场景钉（零变化契约）：同一份世界数据，名单/边序与旧逻辑逐一致。"""
    engine, maker = _make_stack(tmp_path, "unpinned.db")
    try:

        async def run():
            async with maker() as s:
                await _seed_world(s)
                chapter = await s.get(m.Chapter, CH_UNPINNED)
                return await _load_for_chapter(s, chapter)

        overlay = asyncio.run(run())
        assert overlay is not None

        # v3.1（2026-08-27）：桥接层数量 cap 退役——全员保留、纯重要度降序
        # 排序不变（无钉时在场第一键恒 0，排序与旧逻辑同序只是不再截尾）
        names = _char_names(overlay)
        assert len(names) == 17
        assert "扫地僧" in names
        assert names[0] == "远端15"
        assert names[-1] == "扫地僧"

        # 活跃边全部保留（原 created_at 序不变）
        pairs = _rel_pairs(overlay)
        assert len(pairs) >= 8
        assert ("扫地僧", "远端00") in pairs
        assert pairs[0] == ("远端00", "远端08")
    finally:
        asyncio.run(engine.dispose())


def test_duck_typed_chapter_with_str_scene_pin(tmp_path):
    """chapter 为鸭子类型对象 + str 形态场景钉：getattr 防御路径下提权照常生效。"""
    engine, maker = _make_stack(tmp_path, "duck.db")
    try:

        async def run():
            async with maker() as s:
                await _seed_world(s)
                duck = SimpleNamespace(
                    book_id=str(BOOK_ID),
                    chapter_number=3,
                    narrative_time=20,
                    scene_location_id=str(LOC_SCENE),  # str 而非 UUID 对象
                )
                return await _load_for_chapter(s, duck)

        overlay = asyncio.run(run())
        assert overlay is not None
        assert _char_names(overlay)[0] == "扫地僧"
        assert _rel_pairs(overlay)[0] == ("扫地僧", "远端00")
    finally:
        asyncio.run(engine.dispose())


def test_entities_without_position_data_no_error(tmp_path):
    """无位置/事件数据（char_states 空 → 在场集恒空）：钉与不钉都不报错、名单不丢。"""
    engine, maker = _make_stack(tmp_path, "nopos.db")
    try:

        async def run():
            async with maker() as s:
                s.add(m.Book(id=BOOK_ID, title="无位置数据书"))
                s.add(m.WorldLocation(id=LOC_SCENE, book_id=BOOK_ID, name="大厅", kind="point"))
                s.add(
                    m.Chapter(
                        id=CH_PINNED,
                        book_id=BOOK_ID,
                        chapter_number=1,
                        title="钉了但没人有位置",
                        narrative_time=20,
                        scene_location_id=LOC_SCENE,
                    )
                )
                repo = WorldRepository(s)
                for name, imp in (("甲", 3), ("乙", 8)):
                    await repo.entities.create(
                        book_id=BOOK_ID,
                        entity_type="character",
                        name=name,
                        importance=imp,
                    )
                await s.flush()
                chapter = await s.get(m.Chapter, CH_PINNED)
                return await _load_for_chapter(s, chapter)

        overlay = asyncio.run(run())
        assert overlay is not None
        # 无事态 → 纯重要度降序；在场集空不炸、不改变相对序
        assert _char_names(overlay) == ["乙", "甲"]
        assert overlay["relationships"] == []
    finally:
        asyncio.run(engine.dispose())


def test_empty_world_returns_none(tmp_path):
    """空世界（无实体）：返回 None 走旧表兜底，不报错。"""
    engine, maker = _make_stack(tmp_path, "empty.db")
    try:

        async def run():
            async with maker() as s:
                s.add(m.Book(id=BOOK_ID, title="空世界书"))
                await s.flush()
                chapter = SimpleNamespace(
                    book_id=str(BOOK_ID), chapter_number=1, narrative_time=0
                )
                return await _load_for_chapter(s, chapter)

        assert asyncio.run(run()) is None
    finally:
        asyncio.run(engine.dispose())


def test_dead_character_at_scene_not_boosted(tmp_path):
    """死者不提权：death 不清 location_id，尸体原位不得占在场名额（扫地僧 t=10 死于大厅）。"""
    engine, maker = _make_stack(tmp_path, "dead.db")
    try:

        async def run():
            async with maker() as s:
                await _seed_world(s)
                repo = WorldRepository(s)
                sweeper = next(
                    e
                    for e in await repo.entities.list_by_book(str(BOOK_ID))
                    if e.name == "扫地僧"
                )
                await repo.events.create(
                    book_id=BOOK_ID,
                    event_type="death",
                    time_start=10,
                    time_end=10,
                    payload={"character_id": str(sweeper.id)},
                    note="扫地僧死于大厅",
                )
                await s.flush()
                chapter = await s.get(m.Chapter, CH_PINNED)
                return await _load_for_chapter(s, chapter)

        overlay = asyncio.run(run())
        assert overlay is not None
        names = _char_names(overlay)
        # 扫地僧虽位置仍在大厅，但已死亡 → 不进在场集、不提权（v3.1 去 cap
        # 后死者仍在名单尾部——死亡拦截发生在知识平面的在场标记/recency 重钉，
        # 而非名单裁剪）；纯重要度序与无钉基线一致
        assert names[0] == "远端15"
        assert names[-1] == "扫地僧"
        pairs = _rel_pairs(overlay)
        assert pairs[0] == ("远端00", "远端08")  # 死者边不获在场提权（不在首位）
        assert ("扫地僧", "远端00") in pairs     # v3.1 去 cap 后保留（死亡标记在知识平面）
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    import unittest

    unittest.main()
