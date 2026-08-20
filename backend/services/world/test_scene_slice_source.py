# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""A4 叙事时间来源可见（docs/foundation-hardening.md §2.2）单测。

锁两件事：
1. resolve_narrative_time 四级降级的 t/source 值**逐分支不变**（D6 零行为变化），
   仅新增 prev_anchor 章号这一附加信息；
2. build_scene_slice 新字段：source=max_event 时附 time_start 最大事件摘要
   （note 优先、event_type 兜底、截 30 字），其他 source 一律无摘要；
   prev_anchor 附来源章号；字段缺席即省略（向后兼容）。

用 db_sqlite 真实 ORM 栈种数据（与 test_context_contract.py 同 _make_stack 模式）。
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import select

from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.db_sqlite.type_compat import register_sqlite_type_compat  # noqa: F401（方言编译副作用注册）

register_sqlite_type_compat()

import backend.models as m
from backend.services.context.world_bridge import resolve_narrative_time
from backend.services.world.scene_slice import build_scene_slice


def _make_stack(tmp_path):
    engine = build_sqlite_engine(tmp_path / "scene_slice_source.db")
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _seed(maker):
    """一本书：1 个实体 + 3 事件 + 3 章（第 1 章锚 / 第 2 章未锚 / 第 3 章未锚）。

    事件 time_start：10 / 500 / 40（最大者 500 带长 note）——故意乱序防"列表序即时间序"。
    """
    book_id = uuid.uuid4()

    async def run():
        async with maker() as s:
            s.add(m.Book(id=book_id, title="来源可见测试书"))
            s.add(m.WorldEntity(id=uuid.uuid4(), book_id=book_id, name="兰星", entity_type="character"))
            s.add(m.WorldEvent(
                book_id=book_id, sequence_num=1, event_type="birth", time_start=10, time_end=10,
                note="兰星出生",
            ))
            s.add(m.WorldEvent(
                book_id=book_id, sequence_num=2, event_type="battle", time_start=500, time_end=500,
                note="结局之战：三方在北岸会猎，旧王朝的旗帜倒下，新秩序自此确立",
            ))
            s.add(m.WorldEvent(
                book_id=book_id, sequence_num=3, event_type="move", time_start=40, time_end=70,
                note="",
            ))
            s.add(m.Chapter(id=uuid.uuid4(), book_id=book_id, chapter_number=1,
                            chapter_name="锚定章", narrative_time=100))
            s.add(m.Chapter(id=uuid.uuid4(), book_id=book_id, chapter_number=2,
                            chapter_name="未锚章", narrative_time=None))
            await s.commit()
            chapters = (await s.execute(
                select(m.Chapter).where(m.Chapter.book_id == book_id)
            )).scalars().all()
            return {c.chapter_number: c.id for c in chapters}
    return book_id, asyncio.run(run())


def _chapter(maker, chapter_id):
    async def run():
        async with maker() as s:
            return await s.get(m.Chapter, chapter_id)
    return asyncio.run(run())


def test_a4_zero_behavior_change_resolve(tmp_path):
    """D6 契约：四级降级的 t/source 逐分支不变（只多了附加章号）。"""
    engine, maker = _make_stack(tmp_path)
    try:
        book_id, chapter_ids = _seed(maker)

        # ① 本章锚
        nt = asyncio.run(_resolve(maker, chapter_ids[1]))
        assert (nt.t, nt.source) == (100, "chapter_anchor")
        assert nt.chapter_number is None

        # ② 前序最近已锚章（第 2 章未锚 → 承第 1 章的 100）
        nt = asyncio.run(_resolve(maker, chapter_ids[2]))
        assert (nt.t, nt.source) == (100, "prev_anchor")
        assert nt.chapter_number == 1  # 新增附加信息：来源章号

        # ③/④（本章无前序锚场景在下方 scene-slice 用例覆盖）
    finally:
        asyncio.run(engine.dispose())


async def _resolve(maker, chapter_id):
    async with maker() as s:
        chapter = await s.get(m.Chapter, chapter_id)
        return await resolve_narrative_time(s, chapter)


def test_a4_scene_slice_source_fields(tmp_path):
    """scene-slice 新字段：max_event 附摘要（截 30 字）；其他 source 无摘要。"""
    engine, maker = _make_stack(tmp_path)
    try:
        book_id, chapter_ids = _seed(maker)

        # ---- 本章锚：无 note / 无 chapter ----
        sl = asyncio.run(_slice(maker, book_id, chapter_ids[1]))
        assert sl["t"] == 100 and sl["t_source"] == "chapter_anchor"
        assert "t_source_note" not in sl
        assert "t_source_chapter" not in sl

        # ---- prev_anchor：附来源章号、无摘要 ----
        sl = asyncio.run(_slice(maker, book_id, chapter_ids[2]))
        assert sl["t"] == 100 and sl["t_source"] == "prev_anchor"
        assert sl.get("t_source_chapter") == 1
        assert "t_source_note" not in sl

        # ---- 清掉全部锚 → max_event：附最大时刻事件摘要，截 30 字 ----
        async def clear_anchors():
            async with maker() as s:
                for c in (await s.execute(
                    select(m.Chapter).where(m.Chapter.book_id == book_id)
                )).scalars().all():
                    c.narrative_time = None
                await s.commit()
        asyncio.run(clear_anchors())

        sl = asyncio.run(_slice(maker, book_id, chapter_ids[2]))
        assert sl["t"] == 500 and sl["t_source"] == "max_event"
        note = sl.get("t_source_note")
        assert note is not None
        # note 优先于 event_type；截 30 字（原文 29 字全量保留会误判，故断言 ≤30 且来自 note）
        assert note == "结局之战：三方在北岸会猎，旧王朝的旗帜倒下，新秩序自此确立"[:30]
        assert "t_source_chapter" not in sl

        # ---- 删光事件 → zero：无摘要无章号 ----
        async def clear_events():
            async with maker() as s:
                for e in (await s.execute(
                    select(m.WorldEvent).where(m.WorldEvent.book_id == book_id)
                )).scalars().all():
                    await s.delete(e)
                await s.commit()
        asyncio.run(clear_events())

        sl = asyncio.run(_slice(maker, book_id, chapter_ids[2]))
        assert sl["t"] == 0 and sl["t_source"] == "zero"
        assert "t_source_note" not in sl
        assert "t_source_chapter" not in sl
    finally:
        asyncio.run(engine.dispose())


async def _slice(maker, book_id, chapter_id):
    async with maker() as s:
        chapter = await s.get(m.Chapter, chapter_id)
        return await build_scene_slice(s, str(book_id), chapter)


def test_a4_max_event_note_fallback_and_tie(tmp_path):
    """note 空时兜底 event_type；time_start 并列取 sequence_num 更大者。"""
    engine, maker = _make_stack(tmp_path)
    try:
        book_id = uuid.uuid4()

        async def seed():
            async with maker() as s:
                s.add(m.Book(id=book_id, title="兜底测试书"))
                s.add(m.WorldEntity(id=uuid.uuid4(), book_id=book_id, name="甲", entity_type="character"))
                # 同一 time_start=999：seq 小的有 note，seq 大的 note 空（应选中后者 → 兜底 event_type）
                s.add(m.WorldEvent(book_id=book_id, sequence_num=1, event_type="battle",
                                   time_start=999, time_end=999, note="更早录入的同刻事件"))
                s.add(m.WorldEvent(book_id=book_id, sequence_num=2, event_type="coronation",
                                   time_start=999, time_end=999, note=""))
                s.add(m.Chapter(id=uuid.uuid4(), book_id=book_id, chapter_number=1, chapter_name="一"))
                await s.commit()
        asyncio.run(seed())

        async def run():
            async with maker() as s:
                chapter = (await s.execute(
                    select(m.Chapter).where(m.Chapter.book_id == book_id)
                )).scalars().first()
                return await build_scene_slice(s, str(book_id), chapter)
        sl = asyncio.run(run())

        assert sl["t"] == 999 and sl["t_source"] == "max_event"
        assert sl.get("t_source_note") == "coronation"  # note 空 → event_type 兜底
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
