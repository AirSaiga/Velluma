# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""书级备份/还原路由冒烟（FakeDb 桩，不连库）。

对拍口径：锁「路由函数体可执行到业务分支」——404/400/409 的分流与
Content-Disposition 头。完整数据面由 services/book_archive 往返测试
覆盖（test_world_kernel_routes.py 同款边界：纯路由逻辑，不重复服务层
断言）。
"""
import asyncio
import io
import json
import unittest
import uuid
from types import SimpleNamespace as _Sns
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

import backend.routes.books as b


class _FakeRepo:
    def __init__(self, book=None):
        self._book = book

    async def get_by_id(self, book_id):
        return self._book


class _FakeDb:
    async def execute(self, stmt):
        raise AssertionError("不应触达 DB")

    async def delete(self, obj):
        pass


def _upload(content: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename="x.vellumabook")


class TestBackupRoutesSmoke(unittest.TestCase):
    def test_backup_404_when_book_missing(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(b.backup_book(uuid.uuid4(), repo=_FakeRepo(None), db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_backup_returns_payload_with_disposition(self):
        book_id = uuid.uuid4()
        book = _Sns(id=book_id, title="灯塔《与》雾")
        payload = {"format": "velluma.book-backup", "version": 1, "rows": {"books": []}}

        async def fake_export(db, bid):
            return payload

        with patch.object(b, "export_book_payload", fake_export):
            resp = asyncio.run(b.backup_book(book_id, repo=_FakeRepo(book), db=_FakeDb()))
        self.assertEqual(json.loads(resp.body)["format"], "velluma.book-backup")
        disposition = resp.headers["content-disposition"]
        self.assertIn("filename*=UTF-8''", disposition)
        self.assertIn(".vellumabook", disposition)

    def test_restore_rejects_invalid_json(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(b.restore_book(_upload(b"\xff\xfe not json"), db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_restore_rejects_wrong_format_marker(self):
        body = json.dumps({"format": "other-thing", "version": 1}).encode("utf-8")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(b.restore_book(_upload(body), db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_restore_conflict_maps_409(self):
        from backend.services.book_archive import BookAlreadyExistsError

        async def fake_import(db, payload):
            raise BookAlreadyExistsError(uuid.uuid4(), "灯塔与雾")

        body = json.dumps({
            "format": "velluma.book-backup", "version": 1,
            "rows": {"books": [{"id": str(uuid.uuid4()), "title": "灯塔与雾"}]},
        }).encode("utf-8")
        with patch.object(b, "import_book_payload", fake_import):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(b.restore_book(_upload(body), db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("不能重复还原", ctx.exception.detail)

    def test_backup_filename_sanitizes_windows_reserved(self):
        name = b._backup_filename('灯塔:"雾"/')
        self.assertNotIn(":", name)
        self.assertNotIn('"', name)
        self.assertNotIn("/", name)
        self.assertTrue(name.endswith(".vellumabook"))


if __name__ == "__main__":
    unittest.main()
