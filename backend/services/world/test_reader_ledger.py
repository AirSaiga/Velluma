# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 读者清单与开章卡单测（01 下一阶段 M1/M2）
"""两面「镜子」的行为契约（docs/next-phase/01-opening-card-and-reader-ledger.md）：

- 读者清单分类：本章新知道（==）/ 已经知道（<）/ 还不知道（> 按计划章分桶升序）/
  未排期（reveal 意图无章窗）；三段全空返回 None（finish 不设键）
- read_merge_reveals 扩展：行携带表/里/揭示计划原文（展开内容，规则二）
- 开章卡：L1 该揭含 overdue_by（逾期深度升序）；L2 别说破退全书口径+scope 徽标
  （空章无在场）；L3 线头真实总数+最久；L4 无世界书的 zero 时刻整行消失（规则三）；
  空书整卡 {}（空集零像素）

配方：临时 SQLite 真实栈（同 test_accept_dedup.py）。运行：
python -m pytest backend/services/world/test_reader_ledger.py -v
"""

import asyncio
import uuid

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.intent_repository import IntentRepository
from backend.routes.chapter_generation.adaptive.opening_card import get_opening_card
from backend.services.world.reader_ledger import build_opening_card, load_reader_ledger

BOOK_ID = uuid.UUID("dd550000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("dd550000-0000-4000-8000-0000000000c5")  # 第 5 章


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed(s):
    s.add(m.Book(id=BOOK_ID, title="镜子测试书"))
    s.add(m.Chapter(id=CH_ID, book_id=BOOK_ID, chapter_number=5, title="第五章"))


async def _add_canon(s, label, expected, canon="里文本", public="表文本", plan="翻牌时说"):
    node = m.CanonNode(
        book_id=BOOK_ID, type="event", label=label,
        canon_text=canon, public_text=public, reveal_plan=plan,
        visibility="private", source="manual", confidence="settled",
        expected_reveal_chapter=expected,
    )
    s.add(node)
    await s.flush()
    return node


class TestReaderLedger:
    def test_classification_and_buckets(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "rl_classify.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await _add_canon(s, "身世真相", 3)    # 已经知道（逾期章）
                await _add_canon(s, "密信内容", 5)    # 本章新知道
                await _add_canon(s, "凶手身份", 7)    # 还不知道 → 第 7 章桶
                await _add_canon(s, "宝藏地点", 9)    # 还不知道 → 第 9 章桶
                # 未排期：reveal 意图无章窗（target_ch=None）
                s.add(m.WorldIntent(
                    book_id=BOOK_ID, kind="reveal", target_type="free_text",
                    target_text="没排期的计划", lifecycle="declared",
                ))
                await s.commit()

                out = await load_reader_ledger(s, str(BOOK_ID), 5)
                assert [r["label"] for r in out["new_known"]] == ["密信内容"]
                assert [r["label"] for r in out["known"]] == ["身世真相"]
                assert [(g["chapter"], [r["label"] for r in g["items"]]) for g in out["upcoming"]] == [
                    (7, ["凶手身份"]), (9, ["宝藏地点"]),
                ]
                assert [r["label"] for r in out["unscheduled"]] == ["没排期的计划"]

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_empty_returns_none(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "rl_empty.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await s.commit()
                assert await load_reader_ledger(s, str(BOOK_ID), 5) is None

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_reveal_rows_carry_text(self, tmp_path):
        """read_merge_reveals 扩展（01 M1）：行带表/里/计划原文——展开内容的数据底座。"""
        engine, maker = _make_stack(tmp_path, "rl_text.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await _add_canon(s, "身世真相", 7)
                await s.commit()
                rows = await IntentRepository(s).read_merge_reveals(str(BOOK_ID), chapter_number=None)
                row = next(r for r in rows if r["label"] == "身世真相")
                assert row["public_text"] == "表文本"
                assert row["canon_text"] == "里文本"
                assert row["reveal_plan"] == "翻牌时说"

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())


class TestOpeningCard:
    def test_card_rows_and_book_scope(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "oc_card.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await _add_canon(s, "身世真相", 3)   # 逾期 2 章
                await _add_canon(s, "密信内容", 5)   # 本章该揭
                await _add_canon(s, "凶手身份", 7)
                s.add(m.PlotLedger(
                    book_id=BOOK_ID, content="北岸的旧钟没有敲响", ledger_key="hk-1",
                    status="open", created_at_chapter=1,
                ))
                s.add(m.PlotLedger(
                    book_id=BOOK_ID, content="密道尽头的那扇门", ledger_key="hk-2",
                    status="open", created_at_chapter=4,
                ))
                await s.commit()

                ch = await s.get(m.Chapter, CH_ID)
                card = await build_opening_card(s, str(BOOK_ID), ch)

                # L1：逾期深度升序（3 在前），overdue_by 正确
                due = card["due_reveals"]
                assert [r["label"] for r in due] == ["身世真相", "密信内容"]
                assert due[0]["overdue_by"] == 2 and due[1]["overdue_by"] == 0
                # L2：空章无世界实体 → 退全书口径 + 徽标（规则一）
                assert card["untold"]["scope"] == "book"
                assert [r["label"] for r in card["untold"]["items"]] == ["凶手身份"]
                # L3：真实总数 + 最久吊的章数（第 1 章埋的吊了 4 章）
                assert card["threads"]["count"] == 2
                assert card["threads"]["oldest"] == 4
                assert card["threads"]["items"][0]["content"].startswith("北岸的旧钟")
                # L4：无世界数据的 zero 兜底时刻整行消失（规则三——不是信息是噪音）
                assert "scene" not in card

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_empty_book_card_is_blank(self, tmp_path):
        """空集零像素：什么都没录的书 → 整卡 {}（前端整块不渲染）。"""
        engine, maker = _make_stack(tmp_path, "oc_blank.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await s.commit()
                ch = await s.get(m.Chapter, CH_ID)
                assert await build_opening_card(s, str(BOOK_ID), ch) == {}

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_route_missing_chapter_returns_empty(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "oc_route.db")

        async def run():
            async with maker() as s:
                assert await get_opening_card("not-a-chapter", s) == {}

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
