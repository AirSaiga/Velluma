# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - B3 检索分流去敏对拍（2026-09-13 深水区批）
"""V/B 流去敏 + A 流原文红线（docs 红队报告 Q3 裁定）：

- mask_entity_names：token 边界抹名（嵌词保护）、缺席零操作、短名过滤；
- bundle_mask_names：书级专名 + 别名（顶层 / character 链两形态）收集；
- recall_memories 分流：A 流（结构化事件）吃原文（实体名命中=召回机制，
  抹名全灭）；V 流 embedding query 与 B 流关键词源均吃去敏 query。

运行：python -m pytest backend/services/rag/test_recall_masking.py -v
"""
import asyncio
from types import SimpleNamespace

import backend.services.rag.recall as recall_mod
from backend.services.rag.recall import bundle_mask_names, mask_entity_names


class TestMaskEntityNames:

    def test_masks_standalone_name_keeps_context(self):
        out = mask_entity_names("林尘蹲在机房里，把扳手拧紧了最后一颗螺栓。", ["林尘"])
        assert "林尘" not in out
        assert "扳手" in out and "机房" in out          # 语境词保留

    def test_no_match_is_zero_op(self):
        text = "老周咳嗽着问发电机的事。"
        assert mask_entity_names(text, ["林尘"]) == text

    def test_short_and_blank_names_filtered(self):
        text = "王拿着灯走过去。"
        # 单字名（"王"）不进名单——嵌词误伤面太大，≥2 字口径对齐 _mentioned
        assert mask_entity_names(text, ["王", "  ", ""]) == text

    def test_punctuation_adjacent_name_masked(self):
        """粘连名也彻底抹除（token 边界方案实测漏掉「明兰叹了口气」形态）。"""
        out = mask_entity_names("「明兰」把账本合上，明兰叹了口气。", ["明兰"])
        assert "明兰" not in out and "账本" in out

    def test_longest_first_prevents_double_cut(self):
        """长名先抹：工头老王 整体消一次，而不是 老王 先被抠走留下 工头。"""
        out = mask_entity_names("工头老王把闸合上。", ["老王", "工头老王"])
        assert "工头老王" not in out and "老王" not in out
        assert "闸" in out


class TestBundleMaskNames:

    def test_collects_proper_nouns_and_aliases_both_shapes(self):
        class _Bundle:
            def proper_nouns(self):
                return ["林尘", "发电机"]

            entities = [
                SimpleNamespace(name="明兰", aliases=["明姐"]),        # 顶层别名
                SimpleNamespace(  # world 桥适配器：别名挂 character 链
                    character=SimpleNamespace(name="流光", aliases=["白露"]),
                ),
            ]
            assets = [SimpleNamespace(name="扳手", aliases=["撬棍"])]

        names = bundle_mask_names(_Bundle())
        assert "林尘" in names and "发电机" in names     # 书级专名
        assert "明姐" in names and "白露" in names       # 两种别名形态
        assert "撬棍" in names                            # 资产别名

    def test_broken_proper_nouns_degrades_to_aliases_only(self):
        class _Bundle:
            def proper_nouns(self):
                raise RuntimeError("空 bundle 形态")

            entities = [SimpleNamespace(name="甲", aliases=[])]
            assets = []
        assert bundle_mask_names(_Bundle()) == []


class TestRecallStreamSplit:

    def test_a_gets_raw_v_and_b_get_masked(self, monkeypatch):
        """分流红线：A 流 query 原文（抹名=召回机制全灭）；V/B 吃去敏 query。"""
        got = {"world": None, "vector": None, "b_src": None}

        async def fake_world(db, *, book_id, chapter_id, query_text, limit):
            got["world"] = query_text
            return ["【前情事件·fix】林尘：林尘在机房修好了发电机（第 100 日）"]

        async def fake_vector(db, *, query, book_id, chapter_id, chapter_number, k):
            got["vector"] = query
            return []

        def fake_extract(text, top_k=8):
            got["b_src"] = text
            return []

        class _Repo:
            def __init__(self, db):
                pass

            async def search_lexical(self, *a, **kw):
                return []

        monkeypatch.setattr(recall_mod, "_world_echoes", fake_world)
        monkeypatch.setattr(recall_mod, "_vector_echoes", fake_vector)
        monkeypatch.setattr(recall_mod, "is_embedding_configured", lambda: True)
        monkeypatch.setattr(recall_mod, "extract_keywords", fake_extract)
        monkeypatch.setattr(recall_mod, "MemoryRepository", _Repo)

        query = "林尘蹲在机房里，把扳手拧紧了最后一颗螺栓。"
        out = asyncio.run(recall_mod.recall_memories(
            None, book_id="bk-1", chapter_id="ch-1", chapter_number=5,
            query_text=query, mask_names=["林尘"],
        ))
        assert "林尘" in got["world"]          # A 流原文（红线）
        assert "林尘" not in got["vector"]     # V 流去敏
        assert "林尘" not in got["b_src"]      # B 流关键词源去敏
        assert out                              # A 流命中且过相关性门（机房/发电机）

    def test_no_mask_names_keeps_raw_everywhere(self, monkeypatch):
        """不传名单（旧调用面零变化契约）：三流都吃原文。"""
        got = {"world": None, "vector": None, "b_src": None}

        async def fake_world(db, *, book_id, chapter_id, query_text, limit):
            got["world"] = query_text
            return []

        async def fake_vector(db, *, query, book_id, chapter_id, chapter_number, k):
            got["vector"] = query
            return []

        def fake_extract(text, top_k=8):
            got["b_src"] = text
            return []

        class _Repo:
            def __init__(self, db):
                pass

            async def search_lexical(self, *a, **kw):
                return []

        monkeypatch.setattr(recall_mod, "_world_echoes", fake_world)
        monkeypatch.setattr(recall_mod, "_vector_echoes", fake_vector)
        monkeypatch.setattr(recall_mod, "is_embedding_configured", lambda: True)
        monkeypatch.setattr(recall_mod, "extract_keywords", fake_extract)
        monkeypatch.setattr(recall_mod, "MemoryRepository", _Repo)

        query = "林尘蹲在机房里，把扳手拧紧了最后一颗螺栓。"
        asyncio.run(recall_mod.recall_memories(
            None, book_id="bk-1", chapter_id="ch-1", chapter_number=5,
            query_text=query,
        ))
        assert got["world"] == query == got["vector"] == got["b_src"]
