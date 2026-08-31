# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""数据层回归锁（2026-09-01 审计轮）。

锁定两只已确认并修复的高置信缺陷：
1. ChapterAssetRepository.delete_by_chapter 旧实现只做 ORM delete 标记、从不
   commit——PUT /chapters/{id}/assets 空列表（清空全部）时无任何提交，请求
   结束即回滚、静默失效。锁 = 删除后**换新会话**查行数必须为 0（旧代码下
   新会话仍能读到行，测试即红）。
2. ChapterCardRepository.get_or_create_for_chapter 旧实现把 ORM 实例传给
   BaseRepository.create(payload: dict)（内部 model(**payload)），首访必
   TypeError（与 6e6670b AuthorSampleRepository 同款）。锁 = 首访建卡成功
   且跨会话幂等。

配方与 test_intent_repository 同款（内存 SQLite 栈；UUID 带字母防全数字坑）。
"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import select

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.asset_repository import ChapterAssetRepository
from backend.repositories.chapter_card_repository import ChapterCardRepository

BOOK = uuid.UUID("d1a00000-0000-4000-8000-00000000000b")
CH1 = uuid.UUID("d1a00000-0000-4000-8000-0000000000c1")
AST1 = uuid.UUID("d1a00000-0000-4000-8000-0000000000a1")


def _stack(tmp_path: Path, name: str):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _seed(session):
    session.add(m.Book(id=BOOK, title="数据层回归书"))
    session.add(m.Chapter(id=CH1, book_id=BOOK, chapter_number=1, title="第一章"))


def _seed_with_asset(session):
    _seed(session)
    session.add(m.Asset(id=AST1, book_id=BOOK, name="旧提灯"))
    session.add(m.ChapterAsset(chapter_id=CH1, asset_id=AST1))


class TestDeleteByChapterCommits(unittest.TestCase):
    def test_clear_all_persists_across_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _stack(Path(td), "assets.db")
            try:
                async def run():
                    async with maker() as s:
                        _seed_with_asset(s)
                        await s.commit()
                    # 清空全部（路由空列表路径的核心副作用）
                    async with maker() as s:
                        await ChapterAssetRepository(s).delete_by_chapter(CH1)
                    # 新会话核账：必须真的删掉了（旧实现无 commit，此处读到 1 行）
                    async with maker() as s:
                        rows = (await s.execute(select(m.ChapterAsset))).scalars().all()
                        self.assertEqual(len(rows), 0)

                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())

    def test_delete_returns_rowcount(self):
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _stack(Path(td), "assets2.db")
            try:
                async def run():
                    async with maker() as s:
                        _seed_with_asset(s)
                        await s.commit()
                    async with maker() as s:
                        n = await ChapterAssetRepository(s).delete_by_chapter(CH1)
                        self.assertEqual(n, 1)
                        n2 = await ChapterAssetRepository(s).delete_by_chapter(CH1)
                        self.assertEqual(n2, 0)  # 幂等清空

                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())


class TestChapterCardGetOrCreate(unittest.TestCase):
    def test_first_visit_creates_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _stack(Path(td), "cards.db")
            try:
                async def run():
                    async with maker() as s:
                        _seed(s)
                        await s.commit()
                    # 首访建卡（旧实现传 ORM 实例，此处直接 TypeError）
                    async with maker() as s:
                        repo = ChapterCardRepository(s)
                        card = await repo.get_or_create_for_chapter(BOOK, CH1, chapter_number=1)
                        self.assertEqual(str(card.chapter_id), str(CH1))
                        self.assertEqual(card.status, "draft")
                        self.assertEqual(card.chapter_number, 1)
                    # 幂等：二次访问返回既有卡，不重复建
                    async with maker() as s:
                        again = await ChapterCardRepository(s).get_or_create_for_chapter(
                            BOOK, CH1, chapter_number=1)
                        self.assertEqual(str(again.id), str(card.id))

                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())


if __name__ == "__main__":
    unittest.main()
