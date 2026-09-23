# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 语义重合检测单测（约束治理二期 · 抢拍语义闸底座）
"""
semantic_overlap_hits 合成向量单测（纯算法——monkeypatch 掉 embedding 层，
不连网/DB；范式照 test_semantic_match.py）。

合成向量精确控制余弦（2 维 [1, t] 向量族，cos([1,0],[1,t]) = 1/sqrt(1+t²)）：
- [1,0] × [1,0]    → 1.0（平行，必命中）
- [1,0] × [0,1]    → 0.0（正交，必不命中）
- [1,0] × [1,0.75] → 0.8（阈值 0.78 之上，命中）
- [1,0] × [1,0.85] → ≈0.762（阈值 0.78 之下，不命中）

覆盖：未配置零调用直返 / 空输入与短目标过滤 / 阈值边界 / 正交不中 /
best-target 选最近者 / 目标向量缓存（二次比对目标零重嵌、段向量每次新鲜）
/ embedding 异常静默降级 / 命中按相似度降序。

运行：python -m pytest backend/services/validation/test_semantic_overlap.py -v
"""
import asyncio

import pytest

import backend.services.validation.semantic_overlap as so


class FakeEmbedder:
    """替身 get_embeddings_api_only：按 文本→向量 映射返回并记录每次调用。

    未映射文本回 [0.0, 0.0]（零模向量——cosine 恒 0，天然不命中）。
    error 不为 None 时抛异常（模拟整体失败）。
    """

    def __init__(self, mapping=None, error=None):
        self.mapping = mapping or {}
        self.error = error
        self.calls = []

    async def __call__(self, texts, model=None, timeout=120):
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return [self.mapping.get(t, [0.0, 0.0]) for t in texts]


def _run(text, targets, threshold=so.BEAT_RUSH_SHADOW_THRESHOLD):
    return asyncio.run(so.semantic_overlap_hits(text, targets, threshold=threshold))


@pytest.fixture(autouse=True)
def _clear_target_cache():
    """目标向量缓存是模块级进程生命周期——逐测试清空防串扰。"""
    so._TARGET_EMB_CACHE.clear()
    yield
    so._TARGET_EMB_CACHE.clear()


def _patch(monkeypatch, fake, configured=True):
    monkeypatch.setattr(so, "is_embedding_api_configured", lambda: configured)
    monkeypatch.setattr(so, "get_embeddings_api_only", fake)


SEG = "他转身走进了北岸要塞"   # _split_segments 剥句末标点——映射键须为剥后形态
TARGET = "主角进入北岸要塞与守军对峙"


def test_unconfigured_short_circuits_zero_calls(monkeypatch):
    """未配置 embedding API → 直返 [] 且零调用（零变化红线）。"""
    fake = FakeEmbedder()
    _patch(monkeypatch, fake, configured=False)
    assert _run(SEG, [TARGET]) == []
    assert fake.calls == []


def test_empty_inputs_safe(monkeypatch):
    fake = FakeEmbedder()
    _patch(monkeypatch, fake)
    assert _run("", [TARGET]) == []
    assert _run(SEG, []) == []
    assert _run(SEG, ["短", "二字"]) == []   # <4 字目标整体过滤 → 零调用
    assert fake.calls == []


def test_threshold_boundary_hit_and_miss(monkeypatch):
    """cos=0.8（≥0.78）命中、≈0.762 不命中；命中带 segment/target/similarity。"""
    fake = FakeEmbedder(mapping={
        SEG: [1.0, 0.0],
        "高过阈值的节拍": [1.0, 0.75],
    })
    _patch(monkeypatch, fake)
    hits = _run(SEG, ["高过阈值的节拍"])
    assert len(hits) == 1
    assert hits[0]["segment"] == SEG
    assert hits[0]["target"] == "高过阈值的节拍"
    assert hits[0]["similarity"] == 0.8

    fake2 = FakeEmbedder(mapping={
        SEG: [1.0, 0.0],
        "略低于阈值的节拍": [1.0, 0.85],
    })
    _patch(monkeypatch, fake2)
    assert _run(SEG, ["略低于阈值的节拍"]) == []


def test_orthogonal_never_hits(monkeypatch):
    fake = FakeEmbedder(mapping={SEG: [1.0, 0.0], TARGET: [0.0, 1.0]})
    _patch(monkeypatch, fake)
    assert _run(SEG, [TARGET]) == []


def test_best_target_is_closest(monkeypatch):
    """段向量同时可比多目标时，命中记录取相似度最高的那个目标。"""
    fake = FakeEmbedder(mapping={
        SEG: [1.0, 0.0],
        "远一点的节拍目标": [1.0, 0.75],   # cos 0.80
        "更近的节拍目标呀": [1.0, 0.10],   # cos ≈0.995
    })
    _patch(monkeypatch, fake)
    hits = _run(SEG, ["远一点的节拍目标", "更近的节拍目标呀"])
    assert len(hits) == 1
    assert hits[0]["target"] == "更近的节拍目标呀"


def test_target_vectors_cached_across_calls(monkeypatch):
    """同一目标集二次比对：段向量每次新鲜请求，目标向量零重嵌（缓存）。"""
    fake = FakeEmbedder(mapping={SEG: [1.0, 0.0], TARGET: [1.0, 0.0]})
    _patch(monkeypatch, fake)
    assert _run(SEG, [TARGET])           # 第一次：段+目标各一次批量
    assert _run(SEG, [TARGET])           # 第二次：段新鲜，目标走缓存
    target_embed_calls = [c for c in fake.calls if TARGET in c]
    assert len(target_embed_calls) == 1  # 目标只嵌过一次
    seg_embed_calls = [c for c in fake.calls if SEG in c]
    assert len(seg_embed_calls) == 2     # 段每次新鲜


def test_embedding_failure_degrades_silent(monkeypatch):
    fake = FakeEmbedder(error=RuntimeError("网络挂了"))
    _patch(monkeypatch, fake)
    assert _run(SEG, [TARGET]) == []


def test_hits_sorted_desc(monkeypatch):
    """多段文本：命中按相似度降序。"""
    seg_a = "他走进了北岸要塞"
    seg_b = "守军立刻围了上来"
    text = seg_a + "。" + seg_b + "。"
    fake = FakeEmbedder(mapping={
        seg_a: [1.0, 0.75],   # ×目标[1,0] → 0.8
        seg_b: [1.0, 0.10],   # ×目标[1,0] → ≈0.995
        TARGET: [1.0, 0.0],
    })
    _patch(monkeypatch, fake)
    hits = _run(text, [TARGET])
    assert len(hits) == 2
    assert hits[0]["segment"] == seg_b and hits[1]["segment"] == seg_a
    assert hits[0]["similarity"] > hits[1]["similarity"]
