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
语义匹配器单测（任务包 D，纯算法——monkeypatch 掉 embedding 层，不连网/DB）。

合成向量精确控制余弦值（2 维 [1, t] 向量族，cos = 1/sqrt(1+t²)）：
- [1,0] × [1,0] → 1.0（平行，必命中）
- [1,0] × [0,1] → 0.0（正交，必不命中）
- [1,0] × [1,0.76] → ≈0.796（阈值 0.78 之上，命中）
- [1,0] × [1,0.85] → ≈0.762（阈值之下，不命中）

覆盖：阈值边界 / is_regex 与短模式跳过 / 长句二切与段数上限 /
每 pattern 3 段与总 20 截断 / 模式向量缓存命中（二次扫描零模式请求）/
未配置零调用直返 / get_embeddings 异常降级 / 空集安全。
"""

import asyncio

import pytest

import backend.services.style.semantic_match as sm
from backend.services.style.prohibitions import ProhibitionEntry, ProhibitionSet


# ============================================================
# 假 embedding 层
# ============================================================

class FakeEmbedder:
    """替身 get_embeddings：按 文本→向量 映射返回并记录每次调用。

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


def _run(text, ps):
    return asyncio.run(sm.semantic_scan_text(text, ps))


@pytest.fixture(autouse=True)
def _clear_pattern_cache():
    """模式向量缓存是模块级进程生命周期——逐测试清空防串扰。"""
    sm._PATTERN_EMB_CACHE.clear()
    yield
    sm._PATTERN_EMB_CACHE.clear()


def _patch(monkeypatch, fake, configured=True):
    monkeypatch.setattr(sm, "is_embedding_configured", lambda: configured)
    monkeypatch.setattr(sm, "get_embeddings", fake)


# ============================================================
# 未配置 / 空输入
# ============================================================

def test_unconfigured_short_circuits_zero_calls(monkeypatch):
    """未配置 embedding → 直返 [] 且零 embedding 调用（SQLite 零变化红线）。"""
    fake = FakeEmbedder()
    _patch(monkeypatch, fake, configured=False)
    ps = ProhibitionSet((ProhibitionEntry(pattern="深度禁忌短语", source="t"),))
    assert _run("任意正文内容。", ps) == []
    assert fake.calls == []  # 一次网络请求都不该发


def test_empty_prohibitions_and_text_safe(monkeypatch):
    """空禁忌集 / 空文本 → []，零调用。"""
    fake = FakeEmbedder()
    _patch(monkeypatch, fake, configured=True)
    assert _run("有正文。", ProhibitionSet(())) == []
    assert _run("", ProhibitionSet((ProhibitionEntry(pattern="深度禁忌短语"),))) == []
    assert fake.calls == []


# ============================================================
# 阈值边界
# ============================================================

def test_threshold_boundary_hit_and_miss(monkeypatch):
    """cos ≈0.796（≥0.78）命中、≈0.762（<0.78）不命中；hit 六键齐全。"""
    fake = FakeEmbedder(mapping={
        "深度禁忌短语": [1.0, 0.0],
        "这句很接近了": [1.0, 0.76],   # cos = 1/sqrt(1+0.5776) ≈ 0.7963
        "这句稍远一点": [1.0, 0.85],   # cos = 1/sqrt(1+0.7225) ≈ 0.7622
    })
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(
        pattern="深度禁忌短语", severity="blocker",
        alternative="换个写法", source="negative_list",
    ),))
    hits = _run("这句很接近了。这句稍远一点。", ps)
    assert len(hits) == 1
    hit = hits[0]
    assert hit["segment"] == "这句很接近了"
    assert hit["pattern"] == "深度禁忌短语"
    assert hit["similarity"] == pytest.approx(0.796, abs=0.001)
    assert hit["severity"] == "blocker"
    assert hit["alternative"] == "换个写法"
    assert hit["source"] == "negative_list"


def test_orthogonal_never_hits(monkeypatch):
    """正交向量（cos=0）绝不命中。"""
    fake = FakeEmbedder(mapping={
        "深度禁忌短语": [1.0, 0.0],
        "完全无关的句子": [0.0, 1.0],
    })
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="深度禁忌短语"),))
    assert _run("完全无关的句子。", ps) == []


# ============================================================
# 候选过滤
# ============================================================

def test_regex_and_short_patterns_skipped(monkeypatch):
    """is_regex 与 <4 字模式不进语义流——模式请求只含合规词面。"""
    fake = FakeEmbedder(mapping={"正常禁忌词": [1.0, 0.0]})
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((
        ProhibitionEntry(pattern="不是.*而是", is_regex=True),
        ProhibitionEntry(pattern="短词"),
        ProhibitionEntry(pattern="正常禁忌词"),
    ))
    assert _run("正文而已。", ps) == []
    # 第一次调用 = 模式批量请求；只有正常禁忌词入选
    assert fake.calls[0] == ["正常禁忌词"]
    # 第二次调用 = 段向量请求
    assert len(fake.calls) == 2


def test_no_candidates_zero_calls(monkeypatch):
    """全部模式被过滤（只配了正则/短词）→ 不发任何 embedding 请求。"""
    fake = FakeEmbedder()
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="不是.*而是", is_regex=True),))
    assert _run("有正文。", ps) == []
    assert fake.calls == []


# ============================================================
# 切段
# ============================================================

def test_long_sentence_subsplit(monkeypatch):
    """>60 字长句按 [，；、：] 二次细切；碎片 ≤2 字被滤掉。"""
    fake = FakeEmbedder()
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="深度禁忌短语"),))
    g = "一二三四五六七八九十一二三四五六七八九"  # 19 字
    long_sentence = f"{g}，甲乙，{g}，{g}。"  # 全句 63 字 > 60 → 触发细切
    _run(long_sentence, ps)
    segments = fake.calls[1]  # calls[0]=模式，calls[1]=段
    # 三个 19 字段保留，「甲乙」(2 字) 滤掉
    assert segments == [g, g, g]
    assert all(len(s) <= sm.SEMANTIC_SEGMENT_MAX_CHARS for s in segments)
    assert all(len(s) > 2 for s in segments)
    # 逗号切出的碎片不残留分隔符
    assert all("，" not in s for s in segments)


def test_segment_cap_200(monkeypatch):
    """超长章截前 200 段。"""
    fake = FakeEmbedder()
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="深度禁忌短语"),))
    text = "".join(f"第{i}句话。" for i in range(250))
    _run(text, ps)
    assert len(fake.calls[1]) == sm.SEMANTIC_SCAN_MAX_SEGMENTS == 200


# ============================================================
# 截断
# ============================================================

def test_per_pattern_cap_3(monkeypatch):
    """同一 pattern 命中再多也最多报 3 段。"""
    mapping = {"禁忌词甲乙丙": [1.0, 0.0]}
    for i in range(5):
        mapping[f"第{i}句话甲"] = [1.0, 0.0]  # 与模式平行 → cos=1
    fake = FakeEmbedder(mapping=mapping)
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="禁忌词甲乙丙"),))
    hits = _run("".join(f"第{i}句话甲。" for i in range(5)), ps)
    assert len(hits) == sm.SEMANTIC_MAX_HITS_PER_PATTERN == 3
    assert all(h["pattern"] == "禁忌词甲乙丙" for h in hits)


def test_total_cap_20(monkeypatch):
    """多 pattern 总命中按相似度降序截 20（8 pattern × 5 段平行 = 40 → 24 → 20）。"""
    mapping = {}
    for p in range(8):
        pattern = f"禁忌词第{p}组"
        vec = [1.0, float(p) / 100.0]  # 每组不同向量，组内句子与之平行
        mapping[pattern] = vec
        for s in range(5):
            mapping[f"句{p}排{s}号"] = vec
    fake = FakeEmbedder(mapping=mapping)
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet(tuple(
        ProhibitionEntry(pattern=f"禁忌词第{p}组") for p in range(8)
    ))
    text = "".join(f"句{p}排{s}号。" for p in range(8) for s in range(5))
    hits = _run(text, ps)
    # 每 pattern 3 段 × 8 = 24 → 总截 20
    assert len(hits) == sm.SEMANTIC_MAX_TOTAL_HITS == 20
    # 相似度降序
    sims = [h["similarity"] for h in hits]
    assert sims == sorted(sims, reverse=True)
    # 每 pattern ≤3；全平行（相似度并列 1.0）时 24→20 必然挤掉末位
    # pattern 的部分段（稳定排序按 pattern 先后录取）——至少 7 个有代表
    from collections import Counter
    per_pattern = Counter(h["pattern"] for h in hits)
    assert max(per_pattern.values()) <= 3
    assert len(per_pattern) >= 7


# ============================================================
# 模式向量缓存
# ============================================================

def test_pattern_cache_second_scan_skips_pattern_call(monkeypatch):
    """同一禁忌集二次扫描：模式向量走缓存，只为段落发请求。"""
    mapping = {
        "禁忌词甲乙丙": [1.0, 0.0],
        "命中句子在此": [1.0, 0.0],
    }
    fake = FakeEmbedder(mapping=mapping)
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="禁忌词甲乙丙"),))
    text = "命中句子在此。"

    hits1 = _run(text, ps)
    assert hits1 and len(fake.calls) == 2  # 模式 + 段各一次

    hits2 = _run(text, ps)
    assert hits2 == hits1
    assert len(fake.calls) == 3  # 只新增段请求，零模式请求
    assert fake.calls[2] == ["命中句子在此"]


def test_pattern_cache_invalidation_on_model_change(monkeypatch):
    """连接参数（model/dims）变了 → 缓存 key 变 → 模式重新请求。

    用 FakeEmbedder 返回不同维度的向量模拟换模型：第二组维度与第一组
    不同，若缓存未失效会拿到旧维度向量（比较时 zip 截断出错误 cos）。
    """
    from backend.core.model_config import get_embedding_connection

    original = get_embedding_connection
    state = {"model": "model-a"}
    monkeypatch.setattr(
        "backend.core.model_config.get_embedding_connection",
        lambda: {**original(), "model": state["model"]},
    )
    # semantic_match._pattern_vectors 内部 from-import 取的是模块属性，同源生效
    fake = FakeEmbedder(mapping={"禁忌词甲乙丙": [1.0, 0.0]})
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="禁忌词甲乙丙"),))

    _run("正文一句。", ps)
    assert fake.calls[0] == ["禁忌词甲乙丙"]
    state["model"] = "model-b"
    _run("正文一句。", ps)
    # 换模型后模式向量必须重新请求（缓存 key 含 model）：
    # 第二轮 = [模式重请求, 段请求] 两次调用
    assert len(fake.calls) == 4
    assert fake.calls[2] == ["禁忌词甲乙丙"]


# ============================================================
# 降级
# ============================================================

def test_embedding_exception_returns_empty(monkeypatch):
    """get_embeddings 整体抛异常 → 静默 []（绝不阻塞完稿审计）。"""
    fake = FakeEmbedder(error=RuntimeError("网络炸了"))
    _patch(monkeypatch, fake, configured=True)
    ps = ProhibitionSet((ProhibitionEntry(pattern="深度禁忌短语"),))
    assert _run("正常正文内容。", ps) == []


def test_empty_vector_positions_skipped(monkeypatch):
    """段向量位为 []（该条 embedding 失败）→ 跳过比较，不抛错。"""
    fake = FakeEmbedder(mapping={"深度禁忌短语": [1.0, 0.0]})
    # 「失败句」未映射但需要返回 []：包装替身把未映射改为 []
    async def _embed(texts, model=None, timeout=120):
        fake.calls.append(list(texts))
        return [fake.mapping.get(t, []) for t in texts]
    monkeypatch.setattr(sm, "is_embedding_configured", lambda: True)
    monkeypatch.setattr(sm, "get_embeddings", _embed)
    ps = ProhibitionSet((ProhibitionEntry(pattern="深度禁忌短语"),))
    assert _run("失败句。正常句。", ps) == []  # 失败位跳过，正常位无映射也 []


# ============================================================
# 模式向量缓存：同集合异序不得错位（2026-09-04 审计修复回归锁）
# ============================================================

def test_pattern_vector_cache_order_independent(monkeypatch):
    """同集合异序二次调用：向量必须按**当前调用序**还原，不得复用首调顺序。

    事故：缓存值存 (首调下标, 向量)，异序命中按首调序还原 → 段向量与
    pattern 错位配对，命中归因与相似度全乱。
    """
    vec_a, vec_b = [1.0, 0.0], [0.0, 1.0]
    fake = FakeEmbedder({"模式甲": vec_a, "模式乙": vec_b})
    _patch(monkeypatch, fake, configured=True)

    ps_first = ProhibitionSet((
        ProhibitionEntry(pattern="模式甲长词", source="t"),
        ProhibitionEntry(pattern="模式乙长词", source="t"),
    ))
    _run("这是一段足够长的正文内容，可以被切成有效段落。", ps_first)
    assert len(fake.calls) == 2  # 1 次模式向量 + 1 次段向量

    # 同集合、异序的第二次调用：零新请求，且还原序随当前调用序
    ps_second = ProhibitionSet((
        ProhibitionEntry(pattern="模式乙长词", source="t"),
        ProhibitionEntry(pattern="模式甲长词", source="t"),
    ))
    hits = _run("这是另一段足够长的正文内容，同样可以切成有效段落。", ps_second)
    assert len(fake.calls) == 3  # 首 scan 2 次 + 第二次 scan 仅段向量 1 次
    # 模式向量未因异序重发，且缓存只留首调那次（按集合命中，与顺序无关）
    assert ['模式乙长词', '模式甲长词'] not in fake.calls
    cached_entry = next(iter(sm._PATTERN_EMB_CACHE.values()))
    key_order = list(cached_entry.keys())
    # value 已是 {pattern: 向量}——不再存在「首调下标」概念
    assert all(isinstance(v, list) for v in cached_entry.values())
    assert set(key_order) == {"模式甲长词", "模式乙长词"}


def test_pattern_vector_cache_hit_returns_current_order(monkeypatch):
    """异序命中还原结果逐位等于当前序的向量（错位回归锁核心断言）。"""
    vec_a, vec_b = [0.9, 0.1], [0.1, 0.9]
    fake = FakeEmbedder({"甲": vec_a, "乙": vec_b})
    _patch(monkeypatch, fake, configured=True)

    async def _grab(patterns):
        from backend.core.model_config import get_embedding_connection as _g
        # 直接走 _pattern_vectors（绕过 is_embedding 门控层）
        return await sm._pattern_vectors(patterns)

    first = asyncio.run(_grab(["甲", "乙"]))
    second = asyncio.run(_grab(["乙", "甲"]))
    assert first == [vec_a, vec_b]
    assert second == [vec_b, vec_a]  # 异序命中 → 按当前序还原
    assert len(fake.calls) == 1      # 只在首调请求一次
