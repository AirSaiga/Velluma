# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""作者样本 favorite 透传契约（2026-09-24 favorite 丢失修复配套）。

对拍口径：锁「POST /books/{id}/samples 创建时 favorite 字段完整落库并可
读回」——手动创建通路 favorite=True 必须原样返回（曾因 create_with_embedding
签名缺 favorite 而静默丢失）；不传时默认 False。纯路由逻辑冒烟（FakeRepo 桩
不连库，与 test_book_backup_routes.py 同边界），完整数据面由 DB 层覆盖。
"""
import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import backend.routes.style.samples as samples_mod
from backend.schemas import AuthorSampleCreate


def _sample(book_id, favorite):
    """与 AuthorSampleResponse 同形的最小样本对象（from_attributes 消费）。"""
    return SimpleNamespace(
        id=uuid.uuid4(),
        book_id=book_id,
        chapter_id=None,
        scene_type="general",
        content="灯塔在雾里眨了一次眼。",
        source="manual",
        era="recent",
        favorite=favorite,
        word_count=10,
        created_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )


class _FakeBookRepo:
    def __init__(self, book):
        self._book = book

    async def get_by_id(self, book_id):
        return self._book


class _FakeSampleRepo:
    """记录 create_with_embedding 收到的实参——断言透传的唯一事实源。"""

    def __init__(self, stored):
        self._stored = stored
        self.captured = None

    async def create_with_embedding(self, **kwargs):
        self.captured = kwargs
        s = _sample(kwargs["book_id"], kwargs.get("favorite", False))
        self._stored.append(s)
        return s

    async def list_by_book(self, book_id, scene_type=None):
        return list(self._stored)


class _FakeDb:
    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


async def _no_embedding(text):
    # embedding 未配置路径：get_embedding 返回空（[]），失败不阻断创建
    return []


class FavoriteRoundTripTest(unittest.TestCase):
    def _run_create(self, payload):
        book_id = uuid.uuid4()
        stored = []
        repo = _FakeSampleRepo(stored)
        book = SimpleNamespace(id=book_id, title="灯塔与雾")
        original = samples_mod.get_embedding
        samples_mod.get_embedding = _no_embedding
        try:
            created = asyncio.run(
                samples_mod.create_author_sample(
                    book_id=book_id,
                    payload=payload,
                    db=_FakeDb(),
                    repo=repo,
                    book_repo=_FakeBookRepo(book),
                )
            )
        finally:
            samples_mod.get_embedding = original
        return book_id, repo, stored, created

    def test_post_favorite_true_read_back(self):
        """POST 带 favorite=true：落库实参与创建响应都为 true，GET 列表读回 true。"""
        book_id, repo, stored, created = self._run_create(
            AuthorSampleCreate(content="风把门吹开了一条缝。", favorite=True)
        )
        self.assertTrue(repo.captured["favorite"], "create_with_embedding 必须收到 favorite=True（丢失即回归）")
        self.assertEqual(created.favorite, True)
        # GET 列表读回
        listed = asyncio.run(
            samples_mod.list_author_samples(
                book_id=book_id,
                scene_type=None,
                repo=_FakeSampleRepo(stored),
                book_repo=_FakeBookRepo(SimpleNamespace(id=book_id)),
            )
        )
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0].favorite, "GET /samples 列表必须读回 favorite=true")

    def test_post_favorite_defaults_false(self):
        """不传 favorite：默认 False，与 schema 默认一致（行为一致性锁定）。"""
        book_id, repo, stored, created = self._run_create(
            AuthorSampleCreate(content="雨停在窗棂上。")
        )
        self.assertFalse(repo.captured["favorite"])
        self.assertFalse(created.favorite)


if __name__ == "__main__":
    unittest.main()
