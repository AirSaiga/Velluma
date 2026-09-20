# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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

"""A4 叙事时间来源可见（docs/reports/foundation-hardening.md §2.2）单测。

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


def test_presence_location_id_passthrough(tmp_path):
    """2026-09-16 双层分立：presence 行携带结构化 location_id（同室/章范围过滤的数据前提）。

    厨房（村子内部构造）与千里外基地各有一人——两条 presence 行各自带正确
    location_id，前端才能做「取景点子树闭包」过滤（场外角色收敛世界页）。
    """
    engine, maker = _make_stack(tmp_path)
    try:
        book_id = uuid.uuid4()
        kitchen, base = uuid.uuid4(), uuid.uuid4()
        lin, liu = uuid.uuid4(), uuid.uuid4()

        async def seed():
            async with maker() as s:
                s.add(m.Book(id=book_id, title="取景器测试书"))
                village = uuid.uuid4()
                s.add(m.WorldLocation(id=village, book_id=book_id, name="村子"))
                s.add(m.WorldLocation(id=kitchen, book_id=book_id, name="明姐家厨房", parent_id=village))
                s.add(m.WorldLocation(id=base, book_id=book_id, name="统全局基地"))
                s.add(m.WorldEntity(id=lin, book_id=book_id, name="林尘", entity_type="character", importance=2))
                s.add(m.WorldEntity(id=liu, book_id=book_id, name="流光", entity_type="character", importance=9))
                s.add(m.WorldEvent(
                    book_id=book_id, sequence_num=1, event_type="move", time_start=10, time_end=10,
                    participant_ids=[str(lin)],
                    payload={"character_ids": [str(lin)], "to_location_id": str(kitchen)},
                ))
                s.add(m.WorldEvent(
                    book_id=book_id, sequence_num=2, event_type="move", time_start=10, time_end=10,
                    participant_ids=[str(liu)],
                    payload={"character_ids": [str(liu)], "to_location_id": str(base)},
                ))
                s.add(m.Chapter(id=uuid.uuid4(), book_id=book_id, chapter_number=1,
                                chapter_name="厨房章", narrative_time=100))
                await s.commit()
        asyncio.run(seed())

        chapter_id = asyncio.run(_chapter_id(maker, book_id))
        sl = asyncio.run(_slice(maker, book_id, chapter_id))
        by_name = {p["name"]: p for p in sl["presence"]}
        assert by_name["林尘"]["location_id"] == str(kitchen)
        assert by_name["林尘"]["location_name"] == "明姐家厨房"
        # 场外高重要度角色不再被上限挤出（榜完整性=章范围名册不漏人的前提）
        assert by_name["流光"]["location_id"] == str(base)
    finally:
        asyncio.run(engine.dispose())


async def _chapter_id(maker, book_id):
    async with maker() as s:
        chapter = (await s.execute(
            select(m.Chapter).where(m.Chapter.book_id == book_id)
        )).scalars().first()
        return chapter.id


def test_chapter_actors_full_text_scan(tmp_path):
    """方向 B（2026-09-17）：全章正文活跃名册——零事件≠零戏份。

    明姐（未建档，正文说话+端肉）与王叔（已建档但零事件，正文递茶）都必须
    出现在 chapter_actors；md5 缓存同内容二跑结果逐字节相等。
    """
    engine, maker = _make_stack(tmp_path)
    try:
        book_id = uuid.uuid4()
        wang = uuid.uuid4()

        async def seed():
            async with maker() as s:
                s.add(m.Book(id=book_id, title="全章名册测试书"))
                s.add(m.WorldEntity(id=wang, book_id=book_id, name="王叔",
                                    entity_type="character", importance=3))
                s.add(m.Chapter(
                    id=uuid.uuid4(), book_id=book_id, chapter_number=1,
                    chapter_name="厨房章", narrative_time=100,
                    content_text=(
                        "<p>林尘推门进屋。</p>"
                        "<p>明姐端来一碗肉。“快吃。”明姐说。</p>"
                        "<p>王叔递过茶，没说话。</p>"
                    ),
                ))
                await s.commit()
        asyncio.run(seed())

        chapter_id = asyncio.run(_chapter_id(maker, book_id))
        sl = asyncio.run(_slice(maker, book_id, chapter_id))
        actors = {a["name"]: a for a in sl["chapter_actors"]}
        # 王叔：已建档零事件——正文轨（registered）补位
        assert actors["王叔"]["source"] == "registered"
        assert actors["王叔"]["entity_id"] == str(wang)
        assert actors["王叔"]["via"] in ("交互", "动作", "对白", "在场")
        # 明姐：未建档高频人名——guest 轨（jieba 双核验）
        assert actors["明姐"]["source"] == "guest"
        assert actors["明姐"]["entity_id"] == ""
        # 林尘不在实体名册也未达 guest 门槛（出现 1 次）→ 不在名册
        assert "林尘" not in actors
        # md5 缓存：同内容二跑逐字节相等
        sl2 = asyncio.run(_slice(maker, book_id, chapter_id))
        assert sl2["chapter_actors"] == sl["chapter_actors"]
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
