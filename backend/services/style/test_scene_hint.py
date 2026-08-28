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
场景判定 + 检索场景加成单测（P5 C2，docs/foundation-hardening.md §5.2）。

覆盖三块（纯算法/LLM-mock——不连 LLM/DB，同项目单测惯例）：
1. 判定口径：detect_scene_type 阈值边界（0.35 上/下/恰等）、空文本兜底
   ——对话占比统计与 fingerprint「同一把尺子」同源；
2. 兜底流加成：order_samples_for_fallback 同型同档内提前、档位键
   （收藏/新近）优先级不被加成破坏、异型不消失；
3. retrieve_author_samples 全链（monkeypatch 假 repo + 假 embedding）：
   向量流 +0.1 加成与超额取候选、兜底流透传、
   **零变化锁**——hint 为 None/"general" 时输出与旧逻辑逐一致。

运行：python -m pytest backend/services/style/test_scene_hint.py -v
"""

import asyncio
from types import SimpleNamespace

from backend.services.style import retrieval as retrieval_mod
from backend.services.style.fingerprint import (
    compute_text_fingerprint,
    count_dialogue_chars,
    count_words,
)
from backend.services.style.retrieval import (
    SCENE_HINT_BONUS,
    order_samples_for_fallback,
    retrieve_author_samples,
)
from backend.services.style.scene_hint import (
    DIALOGUE_RATIO_THRESHOLD,
    SCENE_DIALOGUE,
    SCENE_GENERAL,
    SCENE_HINT_TAIL_CHARS,
    detect_scene_type,
)


# ============================================================
# 1. 判定口径（阈值边界 + 空文本兜底）
# ============================================================

class TestDetectSceneType:
    def test_dialogue_heavy_text(self):
        # 全引号文本（无空白）→ 对话占比 1.0
        assert detect_scene_type("“走？”“走。”" * 40) == SCENE_DIALOGUE

    def test_narrative_text(self):
        text = "他沿着江岸走了很远，看着潮水一层一层地漫上来，又一层一层地退下去。" * 8
        assert detect_scene_type(text) == SCENE_GENERAL

    def test_boundary_exactly_at_threshold_is_general(self):
        # 7 对话字符（含引号）/ 20 全文字 = 0.35 恰等阈值——严格大于才判 dialogue
        text = "“abcde”" + "f" * 13
        assert count_dialogue_chars(text) / count_words(text) == DIALOGUE_RATIO_THRESHOLD
        assert detect_scene_type(text) == SCENE_GENERAL

    def test_boundary_just_above_threshold_is_dialogue(self):
        # 7 / 19 ≈ 0.368 > 0.35
        text = "“abcde”" + "f" * 12
        assert detect_scene_type(text) == SCENE_DIALOGUE

    def test_ratio_same_ruler_as_fingerprint(self):
        # 同一把尺子：detect 用的就是 compute_text_fingerprint 的 dialogue_ratio
        text = "“你走吧。”他说。\n她在灯下没有抬头。"
        assert (
            compute_text_fingerprint(text, light=True)["dialogue_ratio"]
            == round(count_dialogue_chars(text) / max(1, count_words(text)), 3)
        )

    def test_empty_and_blank_fallback_general(self):
        assert detect_scene_type(None) == SCENE_GENERAL
        assert detect_scene_type("") == SCENE_GENERAL
        assert detect_scene_type("   \n\t ") == SCENE_GENERAL

    def test_tail_window_constant(self):
        # 接线契约：stitch 装配处按尾 300 字切片（设计稿 §5.2 拍板值）
        assert SCENE_HINT_TAIL_CHARS == 300


# ============================================================
# 2. 兜底流加成（order_samples_for_fallback）
# ============================================================

class _Sample:
    def __init__(self, name, scene_type="general", favorite=False, era="recent", source="manual"):
        self.name = name
        self.id = name  # P5 meta 契约：id 用 name 占位
        self.content = name
        self.scene_type = scene_type
        self.favorite = favorite
        self.era = era
        self.source = source


def _names(samples):
    return [s.name for s in samples]


class TestFallbackSceneBoost:
    def test_same_tier_dialogue_moves_ahead(self):
        # 池序模拟 list_by_book 新→旧；同档（非收藏近期）内 dialogue 提前，
        # 档内既有次序不破坏（g1 仍在 g2 前）
        pool = [_Sample("g1"), _Sample("d1", scene_type="dialogue"), _Sample("g2"),
                _Sample("e1", scene_type="dialogue", era="early")]
        assert _names(order_samples_for_fallback(pool, scene_hint="dialogue")) == [
            "d1", "g1", "g2", "e1",
        ]

    def test_tier_keys_beat_scene_boost(self):
        # 档位键优先级不变：收藏 > 新近/早期 > 场景加成
        pool = [_Sample("recent_dialogue", scene_type="dialogue"),
                _Sample("fav_general", favorite=True),
                _Sample("early_dialogue", scene_type="dialogue", era="early"),
                _Sample("recent_general")]
        assert _names(order_samples_for_fallback(pool, scene_hint="dialogue")) == [
            "fav_general", "recent_dialogue", "recent_general", "early_dialogue",
        ]

    def test_mismatched_samples_not_dropped(self):
        # 软加成不是过滤：异型样本仍在结果里，只是让位
        pool = [_Sample("d1", scene_type="dialogue"), _Sample("g1"), _Sample("g2")]
        ordered = order_samples_for_fallback(pool, scene_hint="dialogue")
        assert set(_names(ordered)) == {"d1", "g1", "g2"}

    def test_zero_change_without_hint_and_with_general(self):
        """零变化锁：None / "general" 与旧逻辑（(favorite, era) 键）排序逐一致。"""
        pool = [_Sample("g1"), _Sample("d1", scene_type="dialogue"),
                _Sample("fav", favorite=True), _Sample("e1", era="early"),
                _Sample("fav_early_d", favorite=True, era="early", scene_type="dialogue")]
        # 旧口径显式重算（同 sorted 稳定语义）
        old_order = sorted(
            pool,
            key=lambda s: (0 if s.favorite else 1, 0 if s.era != "early" else 1),
        )
        assert _names(order_samples_for_fallback(pool)) == _names(old_order)
        assert _names(order_samples_for_fallback(pool, scene_hint=None)) == _names(old_order)
        assert _names(order_samples_for_fallback(pool, scene_hint=SCENE_GENERAL)) == _names(old_order)

    def test_missing_scene_type_attr_no_crash(self):
        # 旧数据/假件无 scene_type 属性 → 视为不命中（不炸）
        s = type("S", (), {"name": "旧样本", "content": "旧样本", "favorite": False, "era": "recent"})()
        assert _names(order_samples_for_fallback([s], scene_hint="dialogue")) == ["旧样本"]


# ============================================================
# 3. retrieve_author_samples 全链（假 repo + 假 embedding）
# ============================================================

class _FakeFallbackRepo:
    """兜底流假 repo：list_by_book 按注入序原样返回（模拟新→旧）。"""

    def __init__(self, samples):
        self._samples = samples

    async def list_by_book(self, book_id, scene_type=None):
        return list(self._samples)


class _FakeVectorRepo:
    """向量流假 repo：返回按 distance 升序的预制命中，记录 limit 供断言。"""

    def __init__(self, hits):
        self._hits = hits
        self.limits = []

    async def search_by_style(self, embedding, book_id, scene_type=None, limit=3):
        self.limits.append(limit)
        return list(self._hits[:limit])


def _disable_embedding(monkeypatch):
    monkeypatch.setattr(retrieval_mod, "is_embedding_configured", lambda: False)


def _neutral_prior(monkeypatch):
    """P5 采纳先验中性化：检索排序对拍需要确定性——真实 collab 事件会引入
    非 1.0 因子（先验行为见 test_sample_prior.py 专属单测）。"""
    monkeypatch.setattr(retrieval_mod, "sample_prior_factor", lambda book_id, sid: 1.0)


def _use_repo(monkeypatch, repo):
    """把假 repo 注入 retrieve_author_samples 的构造点（db 传 None 即可）。
    同时中性化 P5 采纳先验（排序对拍的确定性）。"""
    monkeypatch.setattr(retrieval_mod, "AuthorSampleRepository", lambda db: repo)
    _neutral_prior(monkeypatch)


def _enable_embedding(monkeypatch, repo):
    monkeypatch.setattr(retrieval_mod, "is_embedding_configured", lambda: True)

    async def _fake_embed(text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(retrieval_mod, "get_embedding", _fake_embed)
    _use_repo(monkeypatch, repo)


class TestRetrieveFallbackFlow:
    def test_dialogue_hint_promotes_same_type_within_tier(self, monkeypatch):
        # 新→旧池 [g1, d1, g2]：hint 下 d1 提前进前 k；无 hint 时 d1 在 k 外
        repo = _FakeFallbackRepo([_Sample("g1"), _Sample("d1", scene_type="dialogue"), _Sample("g2")])
        _disable_embedding(monkeypatch)
        _use_repo(monkeypatch, repo)
        with_hint = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        # 内容即 name，直接对拍
        assert with_hint == ["d1", "g1"]

    def test_no_hint_zero_change(self, monkeypatch):
        repo = _FakeFallbackRepo([_Sample("g1"), _Sample("d1", scene_type="dialogue"), _Sample("g2")])
        _disable_embedding(monkeypatch)
        _use_repo(monkeypatch, repo)
        no_hint = asyncio.run(retrieve_author_samples(None, "bk-1", "query", k=2))
        general = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint=SCENE_GENERAL,
        ))
        assert no_hint == ["g1", "d1"]      # 旧口径：池序（均为近期非收藏）取前 k
        assert general == no_hint           # general 档 = 无 hint（零变化）


class TestRetrieveVectorFlow:
    def _hits(self):
        # SQL 语义：按 cosine_distance 升序返回
        return [
            (SimpleNamespace(content="genA", scene_type="general"), 0.18),
            (SimpleNamespace(content="genC", scene_type="general"), 0.22),
            (SimpleNamespace(content="diaB", scene_type="dialogue"), 0.28),
            (SimpleNamespace(content="diaD", scene_type="dialogue"), 0.50),
            (SimpleNamespace(content="diaE", scene_type="dialogue"), 0.90),
        ]

    def test_no_hint_keeps_sql_topk(self, monkeypatch):
        repo = _FakeVectorRepo(self._hits())
        _enable_embedding(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(None, "bk-1", "query", k=2))
        assert out == ["genA", "genC"]       # 旧口径：limit=k 原序
        assert repo.limits == [2]            # 不超额取候选

    def test_dialogue_hint_boosts_into_topk(self, monkeypatch):
        repo = _FakeVectorRepo(self._hits())
        _enable_embedding(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        # diaB 0.28-0.1=0.18 与 genA 0.18 平手——稳定排序保 SQL 原序 genA 在前；
        # diaB 顶掉 genC 进前 k；异型 genA 不消失（软加成非过滤）
        assert out == ["genA", "diaB"]
        assert repo.limits == [10]           # 超额取候选 max(k*5, k)

    def test_general_hint_identical_to_none(self, monkeypatch):
        hits = self._hits()
        repo_none = _FakeVectorRepo(hits)
        _enable_embedding(monkeypatch, repo_none)
        none_out = asyncio.run(retrieve_author_samples(None, "bk-1", "query", k=2))
        repo_general = _FakeVectorRepo(hits)
        _enable_embedding(monkeypatch, repo_general)
        general_out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint=SCENE_GENERAL,
        ))
        assert none_out == general_out == ["genA", "genC"]
        assert repo_none.limits == repo_general.limits == [2]

    def test_bonus_magnitude_semantics(self, monkeypatch):
        # 加成恰为 0.1：distance 差 < 0.1 时同型反超；差 > 0.1 时不反超
        close = _FakeVectorRepo([
            (SimpleNamespace(content="genA", scene_type="general"), 0.20),
            (SimpleNamespace(content="diaB", scene_type="dialogue"), 0.20 + SCENE_HINT_BONUS - 0.05),
        ])
        far = _FakeVectorRepo([
            (SimpleNamespace(content="genA", scene_type="general"), 0.20),
            (SimpleNamespace(content="diaB", scene_type="dialogue"), 0.20 + SCENE_HINT_BONUS + 0.10),
        ])
        _enable_embedding(monkeypatch, close)
        close_out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        _enable_embedding(monkeypatch, far)
        far_out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        assert close_out == ["diaB", "genA"]
        assert far_out == ["genA", "diaB"]
