# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 全局笔迹库向量流对拍（假 repo + 假 embedding——SQLite 跑不了
# cosine 编译，与 test_scene_hint.py 同边界，不连 LLM/DB）
"""锁三件事（2026-09 全局笔迹库重设计批）：

1. 向量流纳入 global 候选（search_by_style 候选池扩容后，重排层吃满
   tier 语义）——本书样本绝对优先，global 只补位；
2. global 样本跳过 era 维度（向量流本无 era 键，此处锁 fallback 流的
   era 忽略 + 向量流档位不越界）；
3. 零变化锁：global 池为空时向量流输出与旧口径逐一致（limit=k 原序）。

运行：python -m pytest backend/services/style/test_global_scope_vector.py -v
"""
import asyncio
from types import SimpleNamespace

from backend.services.style import retrieval as retrieval_mod
from backend.services.style.retrieval import retrieve_author_samples


def _hit(content, book_id, scene_type="general", distance=0.2, **extra):
    attrs = dict(
        content=content, book_id=book_id, scene_type=scene_type,
        id=content, favorite=False, era="recent", source="manual", scope="book",
    )
    attrs.update(extra)
    return (SimpleNamespace(**attrs), distance)


class _FakeVectorRepo:
    """向量流假 repo：预制命中按序原样返回（模拟 SQL (tier, distance) 预排）。"""

    def __init__(self, hits):
        self._hits = hits

    async def search_by_style(self, embedding, book_id, scene_type=None, limit=3):
        return list(self._hits[:limit])

    async def list_by_book(self, book_id, scene_type=None):
        return []

    async def list_global(self, exclude_book_id=None, limit=None):
        return []


class _FakeFallbackRepo:
    """兜底流假 repo：list_by_book / list_global 分档返回。"""

    def __init__(self, book_samples, global_samples):
        self._book = book_samples
        self._global = global_samples

    async def list_by_book(self, book_id, scene_type=None):
        return list(self._book)

    async def list_global(self, exclude_book_id=None, limit=None):
        return list(self._global[: (limit or len(self._global))])


def _enable(monkeypatch, repo):
    monkeypatch.setattr(retrieval_mod, "is_embedding_configured", lambda: True)

    async def _fake_embed(text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(retrieval_mod, "get_embedding", _fake_embed)
    monkeypatch.setattr(retrieval_mod, "AuthorSampleRepository", lambda db: repo)
    # P5 采纳先验中性化（排序对拍的确定性）
    monkeypatch.setattr(retrieval_mod, "sample_prior_factor", lambda book_id, sid: 1.0)


def _disable_embedding(monkeypatch, repo):
    monkeypatch.setattr(retrieval_mod, "is_embedding_configured", lambda: False)
    monkeypatch.setattr(retrieval_mod, "AuthorSampleRepository", lambda db: repo)
    monkeypatch.setattr(retrieval_mod, "sample_prior_factor", lambda book_id, sid: 1.0)


BOOK = "dd450000-0000-4000-8000-00000000000b"
OTHER = "dd450000-0000-4000-8000-00000000000a"


class TestVectorFlowTier:
    def test_global_fills_only_when_book_short(self, monkeypatch):
        """本书 1 条（相似度差）+ global 更相似 → 本书在前 global 补位；
        相似度不得越档抢位。"""
        hits = [
            _hit("本书样本", BOOK, distance=0.80),
            _hit("全局样本", OTHER, distance=0.10, scope="global"),
        ]
        repo = _FakeVectorRepo(hits)
        _enable(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(None, BOOK, "query", k=2))
        assert out == ["本书样本", "全局样本"]   # 全局更相似也只补位

    def test_scene_boost_never_crosses_tier(self, monkeypatch):
        """scene 加成不越档：global 同型样本吃加成后仍不得压过本书样本。"""
        hits = [
            _hit("本书异型", BOOK, scene_type="general", distance=0.50),
            _hit("全局同型", OTHER, scene_type="action", distance=0.49, scope="global"),
        ]
        repo = _FakeVectorRepo(hits)
        _enable(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(
            None, BOOK, "query", k=2, scene_hint="action",
        ))
        assert out == ["本书异型", "全局同型"]

    def test_global_empty_zero_change(self, monkeypatch):
        """零变化锁：无 global 命中 → 输出与旧口径（纯距离序）逐一致。"""
        hits = [
            _hit("A", BOOK, distance=0.18),
            _hit("C", BOOK, distance=0.22),
            _hit("D", BOOK, scene_type="dialogue", distance=0.28),
        ]
        repo = _FakeVectorRepo(hits)
        _enable(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(None, BOOK, "query", k=2))
        assert out == ["A", "C"]


class TestFallbackTier:
    def _sample(self, name, book, **kw):
        attrs = dict(
            id=name, content=name, book_id=book, scene_type="general",
            favorite=False, era="recent", source="manual", scope="book",
        )
        attrs.update(kw)
        return SimpleNamespace(**attrs)

    def test_global_era_ignored(self, monkeypatch):
        """global 样本跳过 era 维度：early-era 的 global 同型仍按 scene 排在
        近期 global 异型之前（era 是书级坐标，对外来样本无意义）。"""
        book = [self._sample("本书动作", BOOK, scene_type="action")]
        glo = [
            self._sample("全局抒情", OTHER, scope="global", era="recent"),
            self._sample("全局动作", OTHER, scope="global", scene_type="action", era="early"),
        ]
        repo = _FakeFallbackRepo(book, glo)
        _disable_embedding(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(
            None, BOOK, "query", k=2, scene_hint="action",
        ))
        assert out == ["本书动作", "全局动作"]

    def test_book_cap_demotion_may_fill_global(self, monkeypatch):
        """本书早期/异型样本不足 k 时 global 补位；本书足够时 global 不上桌。"""
        book = [self._sample("本书唯一", BOOK)]
        glo = [self._sample("全局补位", OTHER, scope="global", favorite=True)]
        repo = _FakeFallbackRepo(book, glo)
        _disable_embedding(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(None, BOOK, "query", k=2))
        assert out == ["本书唯一", "全局补位"]

        repo2 = _FakeFallbackRepo(
            [self._sample("本书一", BOOK), self._sample("本书二", BOOK)], glo,
        )
        _disable_embedding(monkeypatch, repo2)
        out2 = asyncio.run(retrieve_author_samples(None, BOOK, "query", k=2))
        assert out2 == ["本书一", "本书二"]

    def test_global_empty_fallback_zero_change(self, monkeypatch):
        """零变化锁：global 池空 → 与旧口径（favorite/era/scene/prior 序）一致。"""
        pool = [
            self._sample("g1", BOOK),
            self._sample("d1", BOOK, scene_type="dialogue"),
            self._sample("fav", BOOK, favorite=True),
        ]
        repo = _FakeFallbackRepo(pool, [])
        _disable_embedding(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(None, BOOK, "query", k=2))
        assert out == ["fav", "g1"]             # 旧口径：收藏优先 → 池序
