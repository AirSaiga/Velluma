# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 全局笔迹库 scope 字段路由契约（2026-09 重设计批）。
"""对拍口径（FakeRepo 桩不连库，与 test_samples_favorite.py 同边界，
完整数据面由 test_cross_book_fallback.py DB 层覆盖）：

1. POST scope 透传落库 + 默认 book；from-golden 导入默认 global；
2. adopted_ghost × global → 422（创建与 PATCH 双闸——AI 学 AI 不跨库扩散）；
3. GET 列表 = 本书段 + global 段合并（global 段排除本书行）；
4. recall 外来样本收回 = 复制挂入（book 副本），幂等 409 / 本书样本 422。

运行：python -m pytest backend/routes/style/test_samples_scope.py -v
"""
import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

import backend.routes.style.samples as samples_mod
from backend.schemas import AuthorSampleCreate, AuthorSamplePatchRequest


def _sample(book_id, *, source="manual", scope="book"):
    """与 AuthorSampleResponse 同形的最小样本对象（from_attributes 消费）。"""
    return SimpleNamespace(
        id=uuid.uuid4(),
        book_id=book_id,
        chapter_id=None,
        scene_type="general",
        content="灯塔在雾里眨了一次眼。",
        source=source,
        era="recent",
        favorite=False,
        scope=scope,
        word_count=10,
        embedding=None,
        created_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
    )


class _FakeBookRepo:
    def __init__(self, book):
        self._book = book

    async def get_by_id(self, book_id):
        return self._book


class _FakeSampleRepo:
    """记录 create_with_embedding 实参 + 预置列表段。"""

    def __init__(self, book_samples=(), global_samples=()):
        self._book = list(book_samples)
        self._global = list(global_samples)
        self.captured = None

    async def create_with_embedding(self, **kwargs):
        self.captured = kwargs
        s = _sample(kwargs["book_id"], source=kwargs.get("source", "manual"),
                    scope=kwargs.get("scope", "book"))
        self._book.append(s)
        return s

    async def list_by_book(self, book_id, scene_type=None):
        return list(self._book)

    async def list_global(self, exclude_book_id=None, limit=None):
        return [s for s in self._global
                if exclude_book_id is None or s.book_id != exclude_book_id]

    async def get_by_id(self, sample_id):
        for s in self._book + self._global:
            if s.id == sample_id:
                return s
        return None


class _FakeDb:
    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


async def _no_embedding(text):
    return []


class ScopeRouteTest(unittest.TestCase):
    def _create(self, payload):
        book_id = uuid.uuid4()
        repo = _FakeSampleRepo()
        book = SimpleNamespace(id=book_id, title="灯塔与雾", golden_snippets=[])
        original = samples_mod.get_embedding
        samples_mod.get_embedding = _no_embedding
        try:
            asyncio.run(samples_mod.create_author_sample(
                book_id=book_id, payload=payload,
                db=_FakeDb(), repo=repo, book_repo=_FakeBookRepo(book),
            ))
        finally:
            samples_mod.get_embedding = original
        return book_id, repo

    def test_post_scope_round_trip_and_default(self):
        """POST scope=global 透传落库；缺省默认 book。"""
        _, repo = self._create(AuthorSampleCreate(
            content="海风把盐粒吹进灯罩。", scope="global",
        ))
        self.assertEqual(repo.captured["scope"], "global")
        _, repo2 = self._create(AuthorSampleCreate(content="雨停在窗棂上。"))
        self.assertEqual(repo2.captured["scope"], "book")

    def test_post_adopted_ghost_global_422(self):
        """创建闸：source=adopted_ghost + scope=global → 422。"""
        with self.assertRaises(HTTPException) as ctx:
            self._create(AuthorSampleCreate(
                content="机甲转动关节。", source="adopted_ghost", scope="global",
            ))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_post_adopted_ghost_book_allowed(self):
        """本书内不受限：adopted_ghost + scope=book 正常创建。"""
        _, repo = self._create(AuthorSampleCreate(
            content="机甲转动关节。", source="adopted_ghost",
        ))
        self.assertEqual(repo.captured["scope"], "book")

    def test_patch_adopted_ghost_to_global_422(self):
        """修改闸：adopted_ghost 样本 PATCH scope=global → 422。"""
        book_id = uuid.uuid4()
        ghost = _sample(book_id, source="adopted_ghost")
        repo = _FakeSampleRepo(book_samples=[ghost])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(samples_mod.patch_author_sample(
                book_id=book_id, sample_id=ghost.id,
                payload=AuthorSamplePatchRequest(scope="global"),
                db=_FakeDb(), repo=repo,
            ))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ghost.scope, "book")       # 原值不动

    def test_patch_scope_change_allowed_on_manual(self):
        """manual 样本 book → global 改档成功（我的笔迹库入口）。"""
        book_id = uuid.uuid4()
        s = _sample(book_id)
        repo = _FakeSampleRepo(book_samples=[s])
        updated = asyncio.run(samples_mod.patch_author_sample(
            book_id=book_id, sample_id=s.id,
            payload=AuthorSamplePatchRequest(scope="global"),
            db=_FakeDb(), repo=repo,
        ))
        self.assertEqual(updated.scope, "global")

    def test_get_list_merges_book_and_global(self):
        """GET 列表 = 本书段在前 + global 段在后（排除本书行，不重复）。"""
        book_id = uuid.uuid4()
        own = _sample(book_id)
        own_global = _sample(book_id, scope="global")   # 本书行挂 global（list_by_book 已含）
        foreign = _sample(uuid.uuid4(), scope="global")
        repo = _FakeSampleRepo(book_samples=[own, own_global], global_samples=[own_global, foreign])
        listed = asyncio.run(samples_mod.list_author_samples(
            book_id=book_id, scene_type=None, repo=repo,
            book_repo=_FakeBookRepo(SimpleNamespace(id=book_id)),
        ))
        self.assertEqual([id(x) for x in listed],
                         [id(own), id(own_global), id(foreign)])

    def test_from_golden_defaults_global(self):
        """黄金片段导入：新样本默认 scope='global'（进我的笔迹库）。"""
        book_id = uuid.uuid4()
        book = SimpleNamespace(
            id=book_id, title="灯塔与雾",
            golden_snippets=["海风把盐粒吹进灯罩。"],
        )
        repo = _FakeSampleRepo()
        original = samples_mod.get_embedding
        samples_mod.get_embedding = _no_embedding
        try:
            created = asyncio.run(samples_mod.create_samples_from_golden(
                book_id=book_id, db=_FakeDb(), repo=repo, book_repo=_FakeBookRepo(book),
            ))
        finally:
            samples_mod.get_embedding = original
        self.assertEqual(len(created), 1)
        self.assertEqual(repo.captured["scope"], "global")

    # ---- 外来样本收回（recall 端点：复制挂入，非改档）----

    def _recall(self, book_id, sample_id, repo, book):
        return asyncio.run(samples_mod.recall_foreign_sample(
            book_id=book_id, sample_id=sample_id,
            db=_FakeDb(), repo=repo, book_repo=_FakeBookRepo(book),
        ))

    def test_recall_foreign_creates_book_copy(self):
        """外来样本收回：当前书创建 scope=book 副本（内容/场景/向量保留，manual 挂入），原行不动。"""
        book_id = uuid.uuid4()
        foreign = _sample(uuid.uuid4(), scope="global")
        foreign.scene_type = "dialogue"
        foreign.embedding = [0.1, 0.2]
        repo = _FakeSampleRepo(global_samples=[foreign])
        created = self._recall(book_id, foreign.id, repo, SimpleNamespace(id=book_id))
        self.assertEqual(repo.captured["book_id"], book_id)
        self.assertEqual(repo.captured["scope"], "book")
        self.assertEqual(repo.captured["source"], "manual")
        self.assertEqual(repo.captured["content"], foreign.content)
        self.assertEqual(repo.captured["scene_type"], "dialogue")
        self.assertEqual(repo.captured["embedding"], [0.1, 0.2])  # 内容同源直接复用
        self.assertEqual(created.scope, "book")
        # 原书 global 行不动（所有权归原书）
        self.assertEqual(foreign.scope, "global")
        self.assertNotEqual(foreign.book_id, book_id)

    def test_recall_own_book_422(self):
        """本书样本不走收回（转移归属走 PATCH scope 通路）。"""
        book_id = uuid.uuid4()
        own = _sample(book_id, scope="global")
        repo = _FakeSampleRepo(book_samples=[own])
        with self.assertRaises(HTTPException) as ctx:
            self._recall(book_id, own.id, repo, SimpleNamespace(id=book_id))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIsNone(repo.captured)

    def test_recall_missing_book_or_sample_404(self):
        """书不存在 / 样本不存在 → 404。"""
        book_id = uuid.uuid4()
        repo = _FakeSampleRepo()
        with self.assertRaises(HTTPException) as ctx:
            self._recall(book_id, uuid.uuid4(), repo, SimpleNamespace(id=book_id))
        self.assertEqual(ctx.exception.status_code, 404)          # 样本不存在
        foreign = _sample(uuid.uuid4(), scope="global")
        repo2 = _FakeSampleRepo(global_samples=[foreign])
        with self.assertRaises(HTTPException) as ctx2:
            self._recall(book_id, foreign.id, repo2, None)        # _FakeBookRepo(None)
        self.assertEqual(ctx2.exception.status_code, 404)         # 书籍不存在

    def test_recall_duplicate_content_409(self):
        """幂等闸：本书已有同文样本（任意 scope）→ 409，不建副本。"""
        book_id = uuid.uuid4()
        own = _sample(book_id)
        foreign = _sample(uuid.uuid4(), scope="global")           # 同 _sample 默认内容
        repo = _FakeSampleRepo(book_samples=[own], global_samples=[foreign])
        with self.assertRaises(HTTPException) as ctx:
            self._recall(book_id, foreign.id, repo, SimpleNamespace(id=book_id))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIsNone(repo.captured)


if __name__ == "__main__":
    unittest.main()
