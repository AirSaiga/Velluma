# Velluma - 学着闭嘴（被拒学习）单测
# AGPL-3.0
"""quiet_learning 静音派生单测（2026-08-25 战略定稿）。

锁定四条行为契约：
1. 阈值纪律（宁错放勿错杀）：裁决样本 <3 永不静音；✗ ≥3 且 ✓ == 0 才静音，
   任一采纳立即解除（一次肯定胜过三次否定）。
2. 安全类永不静音：leak/contradiction 及一切未识别类别不在白名单内，
   收起再多次也不静音（白名单闸，非黑名单闸——防未来新增安全类被误伤）。
3. 宽恕复位语义：books.assist_mutes 只存 forgiven_at 锚点；宽恕时刻之前的
   拒绝一笔勾销，静音集合实时重算（派生不落库）。
4. prompt 零变化契约：muted_types=None/空 → 候选抽取 prompt 逐字节不变。

配方：临时文件 SQLite + 真实模型栈（同 test_chapter_style_override.py）；
UUID 带字母；VELLUMIA_DATA_DIR 用 monkeypatch 指到 tmp_path 隔离埋点文件。

运行：python -m pytest backend/services/adaptive/test_quiet_learning.py -v
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.adaptive import quiet_learning as ql
from backend.services.prompts.world_event_prompts import build_event_candidates_prompt

BOOK_ID = uuid.UUID("ee550000-0000-4000-8000-000000000001")


# ============================================================
# 1. 纯决策：阈值与安全白名单
# ============================================================

class TestDecideEventTypeMutes:
    def test_below_min_decided_never_mutes(self):
        assert ql.decide_event_type_mutes({"move": {"rejected": 2, "accepted": 0}}) == set()

    def test_three_rejects_zero_accept_mutes(self):
        assert ql.decide_event_type_mutes({"move": {"rejected": 3, "accepted": 0}}) == {"move"}

    def test_any_accept_unmutes(self):
        """一次肯定胜过三次否定。"""
        counts = {"move": {"rejected": 5, "accepted": 1}}
        assert ql.decide_event_type_mutes(counts) == set()

    def test_selective_per_type(self):
        counts = {
            "move": {"rejected": 3, "accepted": 0},
            "battle": {"rejected": 1, "accepted": 2},
        }
        assert ql.decide_event_type_mutes(counts) == {"move"}

    def test_empty_type_key_skipped(self):
        assert ql.decide_event_type_mutes({"": {"rejected": 9, "accepted": 0}}) == set()


class TestDecideHintMutes:
    def test_three_dismissals_mute(self):
        assert ql.decide_hint_mutes({"appearance": 3}) == {"appearance"}

    def test_two_dismissals_do_not(self):
        assert ql.decide_hint_mutes({"appearance": 2}) == set()

    def test_safety_kinds_never_mute(self):
        """泄露/矛盾收起再多次也不静音——安全护栏不接受「别烦我」。"""
        counts = {"leak": 9, "contradiction": 9}
        assert ql.decide_hint_mutes(counts) == set()

    def test_unknown_kind_never_mutes(self):
        """未识别类别走保守方向（白名单制）。"""
        assert ql.decide_hint_mutes({"some_future_kind": 9}) == set()


class TestKeyHelpers:
    def test_key_round_trip(self):
        keys = {ql.event_mute_key("move"), ql.hint_mute_key("appearance")}
        assert ql.muted_event_types(keys) == {"move"}

    def test_describe_labels(self):
        desc = {d["key"]: d for d in ql.describe_mute_keys(["wevt:move", "hint:style_drift"])}
        assert desc["wevt:move"]["label"] == "世界候选·移动"
        assert desc["wevt:move"]["channel"] == "inbox"
        assert desc["hint:style_drift"]["label"] == "文风偏离提醒"
        assert desc["hint:style_drift"]["channel"] == "hint"


# ============================================================
# 2. prompt 零变化契约
# ============================================================

class TestPromptZeroChange:
    def test_none_and_empty_byte_identical(self):
        base = build_event_candidates_prompt("正文若干", 100, [], [])
        assert base == build_event_candidates_prompt("正文若干", 100, [], [], muted_types=None)
        assert base == build_event_candidates_prompt("正文若干", 100, [], [], muted_types=[])

    def test_muted_types_render_exclusion(self):
        _sys, user = build_event_candidates_prompt("正文若干", 100, [], [], muted_types=["move"])
        assert "不要再提" in user
        assert "move" in user


# ============================================================
# 3. 真实栈：候选裁决史 → 静音 → 宽恕复位
# ============================================================

def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _candidate(etype, status):
    return m.WorldEventCandidate(
        id=uuid.uuid4(),
        book_id=BOOK_ID,
        chapter_id=None,
        draft={"event_type": etype, "summary": f"{etype} 测试事件"},
        source="settle",
        status=status,
    )


class TestLoadMutedKeysWithDb:
    def test_rejection_history_mutes_and_forgive_restores(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VELLUMA_DATA_DIR", str(tmp_path))  # 埋点文件隔离
        engine, maker = _make_stack(tmp_path, "quiet.db")

        async def run():
            async with maker() as s:
                s.add(m.Book(id=BOOK_ID, title="学着闭嘴测试书"))
                # move ×3 ✗（达阈值）、battle ×2 ✗ + 1 ✓（有采纳不静音）、death ×2 ✗（样本不足）
                for _ in range(3):
                    s.add(_candidate("move", "rejected"))
                s.add(_candidate("battle", "rejected"))
                s.add(_candidate("battle", "rejected"))
                s.add(_candidate("battle", "accepted"))
                for _ in range(2):
                    s.add(_candidate("death", "rejected"))
                await s.commit()

                keys = await ql.load_muted_keys(s, str(BOOK_ID), use_cache=False)
                assert "wevt:move" in keys
                assert "wevt:battle" not in keys
                assert "wevt:death" not in keys

                # 宽恕复位：move 的历史拒绝一笔勾销
                keys = await ql.forgive_mute(s, str(BOOK_ID), "wevt:move")
                assert "wevt:move" not in keys

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
            ql.invalidate_mutes_cache(str(BOOK_ID))

    def test_auto_reject_marked_rows_not_counted(self, tmp_path, monkeypatch):
        """重复转正闸的系统跳过（auto_reject 留痕）不是作者态度——不计入静音学习
        （否则三条重复候选会把该类型误静音）。"""
        monkeypatch.setenv("VELLUMA_DATA_DIR", str(tmp_path))
        engine, maker = _make_stack(tmp_path, "quiet_autoreject.db")

        async def run():
            async with maker() as s:
                s.add(m.Book(id=BOOK_ID, title="假拒绝豁免测试书"))
                for _ in range(3):
                    c = _candidate("move", "rejected")
                    c.draft = {**(c.draft or {}), "auto_reject": "duplicate"}
                    s.add(c)
                await s.commit()
                keys = await ql.load_muted_keys(s, str(BOOK_ID), use_cache=False)
                assert "wevt:move" not in keys

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
            ql.invalidate_mutes_cache(str(BOOK_ID))

    def test_hint_dismiss_events_mute_only_whitelisted(self, tmp_path, monkeypatch):
        """感知带拒收史：appearance 收 3 次静音；leak 收 5 次永不静音；30 天外过期原谅。"""
        monkeypatch.setenv("VELLUMA_DATA_DIR", str(tmp_path))
        engine, maker = _make_stack(tmp_path, "quiet_hint.db")
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=40)
        lines = []
        for _ in range(3):
            lines.append({"ts": (now - timedelta(days=1)).isoformat(), "book_id": str(BOOK_ID),
                          "chapter_id": "", "kind": "hint_dismiss", "detail": {"kind": "appearance"}})
        for _ in range(5):
            lines.append({"ts": now.isoformat(), "book_id": str(BOOK_ID),
                          "chapter_id": "", "kind": "hint_dismiss", "detail": {"kind": "leak"}})
        # 窗口外的旧记录不计（过期原谅）
        for _ in range(3):
            lines.append({"ts": old.isoformat(), "book_id": str(BOOK_ID),
                          "chapter_id": "", "kind": "hint_dismiss", "detail": {"kind": "callback"}})
        (tmp_path / "collab_events.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in lines), encoding="utf-8",
        )

        async def run():
            async with maker() as s:
                s.add(m.Book(id=BOOK_ID, title="静音提示测试书"))
                await s.commit()
                keys = await ql.load_muted_keys(s, str(BOOK_ID), use_cache=False)
                assert "hint:appearance" in keys
                assert "hint:leak" not in keys      # 安全类永不静音
                assert "hint:callback" not in keys  # 40 天前的收起已过期原谅

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
            ql.invalidate_mutes_cache(str(BOOK_ID))
