# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - A 流回响相关性门测试（2026-09-11 排毒批「前情强买强卖」）
"""召回硬门槛：结构化前情按实体名命中≠语境相关——共享词（≥2 字）≥2 个
或占比 ≥0.3 才放行；实体名单命中天然贡献 1 个共享词，门槛实际要求事件
词面上还有第二个当下语境的词。无及格事件允许 A 流为空（prompt 侧同口径
放开 echo 槽位——允许零呼应件）。

运行：python -m pytest backend/services/rag/test_recall_gate.py -v
"""
import asyncio

from backend.services.rag.recall import echo_is_relevant, recall_memories

# 事故现场语料（发电机/明姐章）：温馨做饭段落 vs 全书唯一的玄幻黑历史
_BLACK_HISTORY = (
    "【前情事件·move】林尘：林尘被血噬融合后坠落，日出时被村民发现并带回村子（第 794371 日）"
)
_COOKING_SCENE = (
    "明姐端过来准备好的脸盆，满满的清水。林尘接过脸盆，捧起一把清水扑在脸上，"
    "把毛巾搭在肩上，明姐转身去灶台边添柴。"
)
_RELEVANT_EVENT = (
    "【前情事件·fix】林尘：修好了王叔家的旧发电机，换了碳刷，重新缠了线（第 794375 日）"
)
_FIXING_SCENE = (
    "发电机又滋滋响了，林尘把工具包放在门边，拧开面板检查上回换的碳刷。"
)


class TestEchoRelevanceGate:

    def test_black_history_dropped_in_cooking_scene(self):
        """强买强卖事故原样：血噬坠落 vs 洗脸做饭——共享词只剩「林尘」。"""
        assert not echo_is_relevant(_BLACK_HISTORY, _COOKING_SCENE)

    def test_relevant_event_kept(self):
        """修发电机事件 vs 正在修发电机——共享发电机/碳刷/林尘 ≥2。"""
        assert echo_is_relevant(_RELEVANT_EVENT, _FIXING_SCENE)

    def test_empty_inputs_rejected(self):
        assert not echo_is_relevant("", _COOKING_SCENE)
        assert not echo_is_relevant(_BLACK_HISTORY, "")

    def test_recall_filters_a_stream(self, monkeypatch):
        """端到端：A 流混排相关/不相关事件 → 只放行相关的。"""
        import backend.services.rag.recall as recall_mod

        async def fake_world(db, **kw):
            return [_BLACK_HISTORY, _RELEVANT_EVENT]

        monkeypatch.setattr(recall_mod, "_world_echoes", fake_world)
        monkeypatch.setattr(recall_mod, "is_embedding_configured", lambda: False)
        out = asyncio.run(recall_memories(
            None,
            book_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            chapter_id=None,
            chapter_number=None,
            query_text=_FIXING_SCENE,
        ))
        assert any("碳刷" in e for e in out)
        assert not any("血噬" in e for e in out)

    def test_all_irrelevant_yields_empty_a_stream(self, monkeypatch):
        """无及格事件：A 流整体为空（记忆是增强不是义务）。"""
        import backend.services.rag.recall as recall_mod

        async def fake_world(db, **kw):
            return [_BLACK_HISTORY]

        monkeypatch.setattr(recall_mod, "_world_echoes", fake_world)
        monkeypatch.setattr(recall_mod, "is_embedding_configured", lambda: False)
        out = asyncio.run(recall_memories(
            None,
            book_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            chapter_id=None,
            chapter_number=None,
            query_text=_COOKING_SCENE,
        ))
        assert not any("血噬" in e for e in out)
