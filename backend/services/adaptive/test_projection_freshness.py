# Velluma - NLE-ADF 3.0 走向卡活性 + severity 分级校对单测（P0 治理）
# AGPL-3.0
"""2026-08-25 治理计划（docs/adaptive-assist-hardening.md）P0 两项的对拍：

A1 走向卡整章缺席/冻结——layer3_projections 混装 __dock__/__canon_watch__
缓存标记项，`not projections` 永假；且意图置信度恒 ≥0.5，刷新通道全死。
本文件锁定修复后行为：
1. set_projections 覆写推测时保留缓存标记项（缓存命中调度不再取不到件）；
2. _decide 的 need_proj 只看真实推测（缓存项不占位）；
3. 意图版本变化使旧推测过期（缺键的旧推测刷新一次）；
4. 无意图时不再空激活 future_projection（它本就 skip）。

A2 提醒级负面清单词穿透生成侧硬拦——_violates 只消费 blocker 档，
banned_words_blocker 键缺失（手工构造 hard dict）回退全量保持旧行为。

配方同 test_world_model_liveness.py：独立 asyncio.run、UUID 带字母。
运行：python -m pytest backend/services/adaptive/test_projection_freshness.py -v
"""

import asyncio
import json
import uuid

from backend.services.adaptive.change_detector import AuthorState
from backend.services.adaptive.orchestrator import AdaptiveOrchestrator

BOOK_ID = uuid.UUID("bb220000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("bb220000-0000-4000-8000-0000000000c1")

QUIET_TEXT = (
    "这是林尘昨晚睡前翻书时撇到的话，在这个世道，"
    "这句话值得被贴在工棚的每一面墙上。工地的轰鸣把它震得七零八落，"
    "只剩下最后半句还挂在林尘嘴边，混着机油味一起被咽了回去。"
)

INTENT = {"source": "author", "confidence": 0.85, "must_hits": [], "foreshadows": []}


def _state() -> AuthorState:
    """停顿心跳现场：段尾、完整句、已有正文——rule 2 必进入。"""
    return AuthorState(
        chapter_id=str(CH_ID),
        word_count=400,
        paused_ms=5000,
        cursor_at_paragraph_end=True,
        recent_text=QUIET_TEXT,
    )


def _decide(snapshot):
    orch = AdaptiveOrchestrator(db_factory=None, chapter_id=str(CH_ID))
    return [a.component for a in orch._decide(_state(), snapshot, [])]


# ============================================================
# A1：_decide 的 need_proj 判定
# ============================================================

def test_cache_markers_do_not_count_as_projections():
    """layer3 只有缓存标记项（无意图时停顿过）→ 意图到位后必须激活推测。"""
    snap = {
        "intent": dict(INTENT),
        "intent_version": 3,
        "fact_count": 2,
        "total_words": 300,
        "projections": [
            {"__canon_watch__": True, "hints": [], "ts": 1},
            {"__dock__": True, "parts": [{"text": "旧挂件"}], "ts": 1},
        ],
    }
    assert "future_projection" in _decide(snap)


def test_fresh_projections_not_regenerated():
    """真实推测存在且意图版本一致 → 不刷新（懒加载语义保持）。"""
    snap = {
        "intent": dict(INTENT),
        "intent_version": 3,
        "fact_count": 2,
        "total_words": 300,
        "projections": [
            {"possible_beats": [{"event": "工头打断发愣"}], "intent_version": 3},
            {"__dock__": True, "parts": [{"text": "旧挂件"}], "ts": 1},
        ],
    }
    assert "future_projection" not in _decide(snap)


def test_intent_version_bump_stales_projections():
    """意图重算（version 3→4）后旧推测过期 → 重新激活。"""
    snap = {
        "intent": dict(INTENT),
        "intent_version": 4,
        "fact_count": 2,
        "total_words": 300,
        "projections": [
            {"possible_beats": [{"event": "工头打断发愣"}], "intent_version": 3},
        ],
    }
    assert "future_projection" in _decide(snap)


def test_legacy_projections_without_version_refresh_once():
    """修复前的旧推测（无 intent_version 键）视为过期，刷新一次。"""
    snap = {
        "intent": dict(INTENT),
        "intent_version": 1,
        "fact_count": 2,
        "total_words": 300,
        "projections": [{"possible_beats": [{"event": "工头打断发愣"}]}],
    }
    assert "future_projection" in _decide(snap)


def test_no_intent_never_activates_projection():
    """无意图：即使正文够长也不空激活推测（它本就 skip）；挂件照常。"""
    snap = {
        "intent": {"source": "none"},
        "intent_version": 0,
        "fact_count": 2,
        "total_words": 300,
        "projections": [],
    }
    got = _decide(snap)
    assert "future_projection" not in got
    assert "dock_generator" in got


# ============================================================
# A1：set_projections 保留缓存标记项（真实 repo 栈）
# ============================================================

def test_set_projections_preserves_cache_markers(tmp_path):
    from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
    from backend.db_sqlite.schema import init_db_sqlite
    import backend.models as m
    from backend.services.adaptive.world_model import (
        SegmentProjection,
        WorldModelRepository,
    )

    engine = build_sqlite_engine(tmp_path / "proj.db")
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))

    async def scenario():
        async with maker() as s:
            s.add(m.Book(id=BOOK_ID, title="走向卡测试书"))
            s.add(m.Chapter(
                id=CH_ID, book_id=BOOK_ID, chapter_number=1,
                title="第一章", content_text=f"<p>{QUIET_TEXT}</p>",
            ))
            await s.flush()
            repo = WorldModelRepository(s)
            model = await repo.get_or_create(CH_ID)
            model.layer3_projections = [
                {"possible_beats": [{"event": "旧推测"}], "intent_version": 1},
                {"__dock__": True, "parts": [{"text": "旧挂件"}], "ts": 1},
                {"__canon_watch__": True, "hints": [{"kind": "appearance"}], "ts": 1},
            ]
            await s.commit()

            await repo.set_projections(CH_ID, [SegmentProjection(
                possible_beats=[{"event": "新推测", "intent_version": 2}],
                confidence=0.5,
                signature="x",
            )])
            await s.commit()

            snap = await repo.snapshot(CH_ID)
            projs = snap["projections"]
            events = [
                b.get("event")
                for p in projs
                for b in (p.get("possible_beats") or [])
            ]
            assert events == ["新推测"]                      # 旧推测被覆写
            assert projs[0].get("possible_beats")           # 真推测在前
            assert any(p.get("__dock__") for p in projs)    # 挂件缓存存活
            assert any(p.get("__canon_watch__") for p in projs)  # 感知带缓存存活

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


# ============================================================
# A1：future_projection 产出打意图版本
# ============================================================

class _Bundle:
    book_id = "b1"
    chapter_number = 1
    content_text = f"<p>{QUIET_TEXT}</p>"
    outline_text = ""
    chapter_card = None

    def nutrients(self):
        return {}

    def hard_constraints(self):
        return {}

    def soft_constraints(self):
        return {}


class _Result:
    def __init__(self, content):
        self.content = content


class _Rec:
    def record_result(self, *a, **k):
        pass


def test_future_projection_tags_intent_version(monkeypatch):
    from backend.services.adaptive.components import future_projection as fp

    captured = {}

    async def fake_bundle(chapter_id, db):
        return _Bundle()

    async def fake_llm(system_prompt, user_prompt, **kw):
        return _Result(json.dumps({"projections": [
            {"event": "工头打断发愣", "anchors": ["林尘"], "emotion": "无奈"},
        ]}, ensure_ascii=False))

    class _Repo:
        def __init__(self, db):
            pass

        async def set_projections(self, chapter_id, projections):
            captured["projs"] = projections

    monkeypatch.setattr(fp, "load_chapter_settings_bundle", fake_bundle)
    monkeypatch.setattr(fp, "call_llm_with_usage", fake_llm)
    monkeypatch.setattr(fp, "get_adaptive_recorder", lambda cid: _Rec())
    monkeypatch.setattr(fp, "WorldModelRepository", _Repo)

    snap = {
        "intent": {"source": "inferred", "confidence": 0.6, "arc": "觉醒"},
        "intent_version": 7,
        "projections": [],
    }
    result = asyncio.run(fp.run(str(CH_ID), None, snap, 1500))
    assert result == {"count": 1}
    beat = captured["projs"][0].possible_beats[0]
    assert beat["intent_version"] == 7


# ============================================================
# A2：severity 分级校对
# ============================================================

def test_dock_violates_ignores_warning_words():
    """提醒级词（含静态反 AI 词）不再拦挂件——blocker 键在但为空。"""
    from backend.services.adaptive.components.dock_generator import _violates

    hard = {
        "banned_words": ["林尘", "眼底闪过"],   # 提醒级（事故词+静态词）
        "banned_words_blocker": [],
    }
    assert _violates("林尘眼底闪过一丝暖意", hard) is False


def test_dock_violates_blocks_blocker_words():
    from backend.services.adaptive.components.dock_generator import _violates

    hard = {
        "banned_words": ["林尘", "眼底闪过"],
        "banned_words_blocker": ["眼底闪过"],
    }
    assert _violates("林尘决定去北岸", hard) is False        # 提醒级不拦
    assert _violates("她眼底闪过一丝杀意", hard) is True      # blocker 拦


def test_dock_violates_legacy_dict_falls_back_to_full_list():
    """手工构造的 hard dict（无 blocker 键）回退全量拦截——旧行为不变。"""
    from backend.services.adaptive.components.dock_generator import _violates

    assert _violates("她眼底闪过一丝杀意", {"banned_words": ["眼底闪过"]}) is True


def test_projection_violates_ignores_warning_words():
    from backend.services.adaptive.components.future_projection import (
        _violates_constraints,
    )

    hard = {"banned_words": ["林尘"], "banned_words_blocker": []}
    assert _violates_constraints("林尘决定去北岸", hard) is False
    hard2 = {"banned_words": ["林尘"], "banned_words_blocker": ["北岸"]}
    assert _violates_constraints("林尘决定去北岸", hard2) is True


def test_canon_private_labels_still_block():
    """canon private 泄密拦截不受 severity 分级影响（真相层纪律）。"""
    from backend.services.adaptive.components.dock_generator import _violates

    hard = {"canon_private_labels": ["双重身份"], "banned_words_blocker": []}
    assert _violates("他的双重身份暴露了", hard) is True
