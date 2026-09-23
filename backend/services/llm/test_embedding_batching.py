# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""embedding 批量透明分批单测（2026-09-24 生产修复，校准报告 §6.1）。

背景：qwen3.7-text-embedding（DashScope 兼容端点）单批 input >20 条直接
400，两个批量入口曾整包直发 → 整体静默降级为全空向量（semantic_scan_text
可达 200 段、semantic_overlap 两 shadow 检随之整体失效）。修复后
_request_embedding 按 EMBEDDING_BATCH_SIZE 分批，存储门控路径
（get_embeddings）与纯 API 路径（get_embeddings_api_only）均经它发送，
天然同时覆盖。

mock 面：只替换模块内 AsyncOpenAI（HTTP 层替身——记录每次 create 的
input，返回确定性 4 维向量，首维=文本序号，可直接断言按序拼接）；
连接配置与两个门控判定一并打桩，不连网、不读真实 model_config.json。

覆盖：45 条 → 3 批（20/20/5）按序拼接（两条入口各验）/ ≤20 条单次
调用零变化（含 str 单文本路径）/ 单批失败中止后续批次并整体降级全空
（既有错误语义）/ 逐条维度校验跨批仍逐条生效 / 未配置零网络调用直返。

运行：.venv/Scripts/python.exe -m pytest backend/services/llm/test_embedding_batching.py -v
"""
import asyncio

import pytest

import backend.services.llm.embedding as emb

_DIM = 4


def _mk_text(i: int) -> str:
    return f"句#{i}"


def _vec_for(text: str) -> list:
    # 首维 = 文本序号：断言「按输入序拼接」直接比对首维即可
    return [float(int(text.split("#")[1])), 1.0, 1.0, 1.0]


class _FakeData:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeResponse:
    def __init__(self, vectors):
        self.data = [_FakeData(v) for v in vectors]


class _FakeEmbeddings:
    """替身 client.embeddings：按调用记录 input 并返回确定性向量。

    fail_on_call=N 时第 N 批抛异常（模拟单批请求失败）；
    bad_dim_texts 中的文本返回 3 维向量（模拟逐条维度不符）。
    """

    def __init__(self, calls, *, fail_on_call=None, bad_dim_texts=()):
        self.calls = calls
        self.fail_on_call = fail_on_call
        self.bad_dim_texts = set(bad_dim_texts)

    async def create(self, **kwargs):
        raw = kwargs["input"]
        inputs = [raw] if isinstance(raw, str) else list(raw)
        self.calls.append(inputs)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("模拟单批请求失败")
        return _FakeResponse([
            [9.0, 9.0, 9.0] if t in self.bad_dim_texts else _vec_for(t)
            for t in inputs
        ])


def _patch(monkeypatch, *, configured=True, api_only=True, **fake_kwargs):
    """打桩 HTTP 层 + 连接配置 + 两个门控；返回累计的 create 调用列表。"""
    calls: list = []

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.embeddings = _FakeEmbeddings(calls, **fake_kwargs)

    monkeypatch.setattr(emb, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(emb, "_get_active_proxy", lambda: None)
    monkeypatch.setattr(
        emb,
        "get_embedding_connection",
        lambda: {
            "api_key": "test-key-not-real",
            "base_url": "https://embedding.test/v1",
            "model": "qwen3.7-text-embedding",
            "dimensions": _DIM,
            "source": "self",
        },
    )
    monkeypatch.setattr(emb, "is_embedding_configured", lambda: configured)
    monkeypatch.setattr(emb, "is_embedding_api_configured", lambda: api_only)
    return calls


def test_45_texts_split_into_ordered_batches_api_only(monkeypatch):
    """纯 API 入口：45 条 → 20/20/5 三批串行，结果按输入序拼接。"""
    calls = _patch(monkeypatch)
    texts = [_mk_text(i) for i in range(45)]

    result = asyncio.run(emb.get_embeddings_api_only(texts))

    assert [len(c) for c in calls] == [20, 20, 5]
    assert [t for batch in calls for t in batch] == texts
    assert len(result) == 45
    assert [v[0] for v in result] == [float(i) for i in range(45)]


def test_45_texts_split_into_ordered_batches_storage_gated(monkeypatch):
    """存储门控入口同样分批（同经 _request_embedding 发送，天然覆盖）。"""
    calls = _patch(monkeypatch)
    texts = [_mk_text(i) for i in range(45)]

    result = asyncio.run(emb.get_embeddings(texts))

    assert [len(c) for c in calls] == [20, 20, 5]
    assert [v[0] for v in result] == [float(i) for i in range(45)]


def test_at_limit_20_single_call(monkeypatch):
    """恰 20 条 = 模型上限内 → 单次调用（零变化红线）。"""
    calls = _patch(monkeypatch)

    result = asyncio.run(emb.get_embeddings_api_only([_mk_text(i) for i in range(20)]))

    assert len(calls) == 1
    assert len(result) == 20


def test_single_text_str_path_unchanged(monkeypatch):
    """单文本（str 输入）不进分批支路：一次调用、返回单向量。"""
    calls = _patch(monkeypatch)

    vec = asyncio.run(emb.get_embedding(_mk_text(7)))

    assert len(calls) == 1
    assert vec[0] == 7.0


def test_single_batch_failure_degrades_to_all_empty(monkeypatch):
    """单批失败 → 中止后续批次、整体降级全空（与分批前错误语义一致）。"""
    calls = _patch(monkeypatch, fail_on_call=2)
    texts = [_mk_text(i) for i in range(45)]

    api_result = asyncio.run(emb.get_embeddings_api_only(texts))
    assert len(calls) == 2                       # 第二批失败即止，不发第三批
    assert api_result == [[] for _ in texts]

    calls.clear()
    storage_result = asyncio.run(emb.get_embeddings(texts))
    assert len(calls) == 2
    assert storage_result == [[] for _ in texts]


def test_dimension_mismatch_still_per_item_across_batches(monkeypatch):
    """跨批逐条维度校验仍逐条生效：坏条只置空自身，其余批/条不受牵连。"""
    calls = _patch(monkeypatch, bad_dim_texts={_mk_text(25)})   # 落在第二批
    texts = [_mk_text(i) for i in range(45)]

    result = asyncio.run(emb.get_embeddings(texts))

    assert len(calls) == 3
    assert result[25] == []
    assert all(result[i] != [] for i in range(45) if i != 25)
    assert result[0][0] == 0.0 and result[44][0] == 44.0


def test_unconfigured_zero_network_calls(monkeypatch):
    """未配置 → 与输入等长全空、零网络调用（既有短路行为不变）。"""
    calls = _patch(monkeypatch, configured=False, api_only=False)
    texts = [_mk_text(i) for i in range(45)]

    assert asyncio.run(emb.get_embeddings(texts)) == [[] for _ in texts]
    assert asyncio.run(emb.get_embeddings_api_only(texts)) == [[] for _ in texts]
    assert calls == []


def test_empty_list_short_circuits(monkeypatch):
    calls = _patch(monkeypatch)

    assert asyncio.run(emb.get_embeddings_api_only([])) == []
    assert asyncio.run(emb.get_embeddings([])) == []
    assert calls == []
