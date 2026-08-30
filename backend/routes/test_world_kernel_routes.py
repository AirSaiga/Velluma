# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# AGPL-3.0
"""世界内核路由冒烟（2026-08-28 审计回归锁）。

背景：backfill_depictions / list_digest 曾裸用 `select(...)` 而模块无导入，
调用即 NameError→500——752 个服务层单测全绿也没抓到（无路由级测试，
py_compile 不查 NameError）。本测试直接调用路由函数（FakeDb 桩，不连库），
锁「函数体可执行到业务分支」。
"""
import asyncio
import unittest
from types import SimpleNamespace as _Sns
from uuid import uuid4

import backend.routes.world as w


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDb:
    """最小 db 桩：Chapter 命中返回同书 stub（带正文），其余查询返回空集。"""

    def __init__(self, book_id, chapter_id):
        self._book_id = book_id
        self._chapter_id = chapter_id

    async def get(self, model, pk):
        if model.__name__ == "Chapter" and str(pk) == str(self._chapter_id):
            return _Sns(book_id=self._book_id,
                        content_text="<p>灯塔的旧日志里藏着一把钥匙。</p>")
        return None

    async def execute(self, stmt):
        return _FakeResult()

    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def commit(self):
        pass


class TestKernelRoutesSmoke(unittest.TestCase):
    def test_backfill_and_list_digest_reach_business_logic(self):
        async def run():
            bid, cid = uuid4(), uuid4()
            db = _FakeDb(bid, cid)
            r1 = await w.backfill_depictions(
                bid, w.DepictionBackfillRequest(chapter_id=cid), db=db)
            self.assertEqual(r1["created"], 0)
            self.assertEqual(r1["candidates"], [])
            r2 = await w.list_digest(bid, db=db)
            self.assertEqual(r2["sections"], [])
            self.assertFalse(r2["enabled"])  # DIGEST_ENABLED=False（B8 双门未签发）

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
