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
books.style_blacklist → 书级 StyleCard.negative_list 启动迁移测试（任务包 B）。

运行：`.venv/Scripts/python.exe -m pytest backend/db_sqlite/test_style_blacklist_migration.py -v`

覆盖面（与迁移契约一一对应）：
- 首跑合并 + 清空（清空 = 已迁移标记）
- 二跑零变更（幂等）
- 无书级卡的书自动建卡（章级卡不受影响、不被复用）
- str / dict（word|phrase + alternative）混合形态归一
- word 去重 + 已有条目无 alternative 而新条有则补全
- 空库零操作（init_db_sqlite 挂点在空库上启动即验证）

注意：
- 沿用 test_db_sqlite.py 的模式：每测试独立事件循环（asyncio.run）+ 独立临时库文件。
- 测试用 UUID 固定带字母（全数字 UUID 在 SQLite 方言下有坑——项目已知教训）。
"""

import asyncio
import uuid

from sqlalchemy import select

import backend.models as m
from backend.database import _migrate_style_blacklist_into_negative_cards
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite

# 固定 UUID（带字母，规避 SQLite 方言对全数字 UUID 的已知坑）
BOOK_A = uuid.UUID("aaaa1e11-1111-4111-8111-111111111111")
BOOK_B = uuid.UUID("bbbb2e22-2222-4222-8222-222222222222")
BOOK_C = uuid.UUID("cccc3e33-3333-4333-8333-333333333333")
CARD_A = uuid.UUID("dddd4e44-4444-4444-8444-444444444444")
CARD_B_CHAPTER = uuid.UUID("eeee5e55-5555-4555-8555-555555555555")
CHAPTER_B = uuid.UUID("ffff6e66-6666-4666-8666-666666666666")


def _make_stack(tmp_path, name="mig.db"):
    """建引擎+会话工厂+初始化 schema（init 挂点在空库上已跑过一次迁移）。"""
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _run_migration(maker):
    async def run():
        async with maker() as s:
            await _migrate_style_blacklist_into_negative_cards(s)

    asyncio.run(run())


def _seed_book(maker, book_id, title, blacklist=None, negative=None, with_chapter_card=False):
    """种一本书：可选预置书级卡 negative_list / 章级卡（迁移只许碰书级卡）。"""

    async def run():
        async with maker() as s:
            s.add(m.Book(id=book_id, title=title, style_blacklist=blacklist))
            if negative is not None:
                s.add(m.StyleCard(id=CARD_A, book_id=book_id, chapter_id=None, negative_list=negative))
            if with_chapter_card:
                s.add(m.Chapter(id=CHAPTER_B, book_id=book_id, chapter_number=1, title="一章"))
                await s.flush()  # 先落章行，防同批 flush 里章级卡 FK 先插报错
                s.add(m.StyleCard(
                    id=CARD_B_CHAPTER, book_id=book_id, chapter_id=CHAPTER_B,
                    negative_list=[{"word": "章级私有词", "alternative": None}],
                ))
            await s.commit()

    asyncio.run(run())


def _book_state(maker, book_id):
    """取 (book.style_blacklist, 书级卡 negative_list, 书级卡 id)。无卡 → (…, None, None)。"""

    async def run():
        async with maker() as s:
            book = await s.get(m.Book, book_id)
            card = (
                await s.execute(
                    select(m.StyleCard).where(
                        m.StyleCard.book_id == book_id,
                        m.StyleCard.chapter_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
            return (
                list(book.style_blacklist or []),
                list(card.negative_list) if card else None,
                card.id if card else None,
            )

    return asyncio.run(run())


def _count_book_cards(maker, book_id):
    async def run():
        async with maker() as s:
            rows = await s.execute(
                select(m.StyleCard).where(
                    m.StyleCard.book_id == book_id,
                    m.StyleCard.chapter_id.is_(None),
                )
            )
            return len(rows.scalars().all())

    return asyncio.run(run())


def test_first_run_merges_and_clears(tmp_path):
    """首跑：混合形态归并进书级卡、book.style_blacklist 清空。"""
    engine, maker = _make_stack(tmp_path)
    try:
        _seed_book(
            maker, BOOK_A, "首跑合并",
            blacklist=["  词一  ", {"word": "词二", "alternative": "替换乙"}],
            negative=[{"word": "已有词", "alternative": "旧替"}],
        )
        _run_migration(maker)

        blacklist, negative, _ = _book_state(maker, BOOK_A)
        assert blacklist == [], "清空即已迁移标记"
        assert negative == [
            {"word": "已有词", "alternative": "旧替"},
            {"word": "词一", "alternative": None},      # str 条目 strip 归一
            {"word": "词二", "alternative": "替换乙"},  # dict 条目带替代
        ]
    finally:
        asyncio.run(engine.dispose())


def test_second_run_is_noop(tmp_path):
    """幂等：二跑零变更（黑名单已空不命中、卡条目逐字节不变、不新建卡）。"""
    engine, maker = _make_stack(tmp_path)
    try:
        _seed_book(
            maker, BOOK_A, "幂等",
            blacklist=["词一", {"word": "词二", "alternative": "替换乙"}],
        )
        _run_migration(maker)
        _, negative_1, card_id_1 = _book_state(maker, BOOK_A)

        _run_migration(maker)
        blacklist_2, negative_2, card_id_2 = _book_state(maker, BOOK_A)

        assert blacklist_2 == []
        assert negative_2 == negative_1
        assert card_id_2 == card_id_1
        assert _count_book_cards(maker, BOOK_A) == 1
    finally:
        asyncio.run(engine.dispose())


def test_creates_book_card_when_missing(tmp_path):
    """无书级卡的书自动建卡归并；同书的章级卡不被复用、不被触碰。"""
    engine, maker = _make_stack(tmp_path)
    try:
        _seed_book(
            maker, BOOK_B, "无卡建卡",
            blacklist=["黑词甲", {"phrase": "黑词乙", "alternative": "替乙"}],
            with_chapter_card=True,
        )
        assert _count_book_cards(maker, BOOK_B) == 0

        _run_migration(maker)

        blacklist, negative, _ = _book_state(maker, BOOK_B)
        assert blacklist == []
        assert negative == [
            {"word": "黑词甲", "alternative": None},
            {"word": "黑词乙", "alternative": "替乙"},  # phrase 键兼容
        ]
        assert _count_book_cards(maker, BOOK_B) == 1, "只建一张书级卡"

        # 章级卡原样（迁移只碰书级卡）
        async def chapter_card_state():
            async with maker() as s:
                card = await s.get(m.StyleCard, CARD_B_CHAPTER)
                return list(card.negative_list)

        assert asyncio.run(chapter_card_state()) == [{"word": "章级私有词", "alternative": None}]
    finally:
        asyncio.run(engine.dispose())


def test_dedup_and_alternative_backfill(tmp_path):
    """word 去重（卡内已有 / 黑名单内部重复）；已有条目无 alternative 而新条有则补全。"""
    engine, maker = _make_stack(tmp_path)
    try:
        _seed_book(
            maker, BOOK_C, "去重补全",
            blacklist=[
                {"word": "重复词", "alternative": "补替"},
                "重复词",                                        # 黑名单内部重复
                {"word": "新词"},                                # 无 alternative
                {"word": "  ", "alternative": "空词被跳过"},     # 归一后空词跳过
                42,                                              # 非法形态跳过
            ],
            negative=[
                {"word": "重复词", "alternative": ""},           # 无 alternative
                {"word": "独词", "alternative": None},
            ],
        )
        _run_migration(maker)

        blacklist, negative, _ = _book_state(maker, BOOK_C)
        assert blacklist == []
        assert negative == [
            {"word": "重复词", "alternative": "补替"},  # 补全，不重复追加
            {"word": "独词", "alternative": None},
            {"word": "新词", "alternative": None},
        ]
    finally:
        asyncio.run(engine.dispose())


def test_empty_blacklist_books_untouched(tmp_path):
    """黑名单本就为空的书：不建卡、不写库。"""
    engine, maker = _make_stack(tmp_path)
    try:
        _seed_book(maker, BOOK_A, "空黑名单", blacklist=[], negative=None)
        _run_migration(maker)

        blacklist, negative, card_id = _book_state(maker, BOOK_A)
        assert blacklist == []
        assert negative is None and card_id is None, "空书不得凭空建卡"
    finally:
        asyncio.run(engine.dispose())


def test_empty_db_noop(tmp_path):
    """空库：init 挂点（_make_stack 内已跑）+ 显式再跑一次，零操作不报错。"""
    engine, maker = _make_stack(tmp_path, name="empty.db")
    try:
        _run_migration(maker)  # 不抛异常即通过
    finally:
        asyncio.run(engine.dispose())
