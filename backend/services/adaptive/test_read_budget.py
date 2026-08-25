# Velluma - 自动阅读预算闸（read_budget）单测
# AGPL-3.0
"""预算闸行为契约（2026-08-25 战略定稿「系统自己去读」的成本护栏）：

1. 判定序语义：short_text → unchanged → too_soon → daily_cap（「没变」是最常见
   静默出口，先于预算曝光；间隔闸只对真要读的生效）。
2. 幂等锚：同指纹不重读；entities_hash 与 hash 是两个独立键（阶段 A/B 互不封锁）。
3. 24h 滚动窗口计数：只算自动观察口径 stage、只算窗口内、只算本书。
4. 指纹折叠空白（排版抖动不重新武装）。

运行：python -m pytest backend/services/adaptive/test_read_budget.py -v
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.adaptive import read_budget as rb

BOOK_ID = uuid.UUID("ff660000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("ff660000-0000-4000-8000-0000000000b1")
NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


class TestDecideAutoRead:
    def test_short_text_skips_first(self):
        ok, code = rb.decide_auto_read(text_len=10, state=None, fingerprint="x", now=NOW)
        assert (ok, code) == (False, "short_text")

    def test_unchanged_skips_before_budget(self):
        """哈希没变 → unchanged，即使预算已满（静默出口优先，不暴露预算信息）。"""
        state = {"hash": "fp1", "last_run_at": NOW.isoformat()}
        ok, code = rb.decide_auto_read(
            text_len=500, state=state, fingerprint="fp1", now=NOW,
            daily_used=rb.AUTO_READ_DAILY_CAP,
        )
        assert (ok, code) == (False, "unchanged")

    def test_too_soon_after_recent_run(self):
        state = {"hash": "old", "last_run_at": NOW.isoformat()}
        ok, code = rb.decide_auto_read(
            text_len=500, state=state, fingerprint="new", now=NOW,
        )
        assert (ok, code) == (False, "too_soon")

    def test_interval_passed_allows(self):
        state = {"hash": "old", "last_run_at": (NOW - timedelta(seconds=301)).isoformat()}
        ok, code = rb.decide_auto_read(
            text_len=500, state=state, fingerprint="new", now=NOW,
        )
        assert (ok, code) == (True, None)

    def test_daily_cap_blocks_real_run(self):
        ok, code = rb.decide_auto_read(
            text_len=500, state=None, fingerprint="x", now=NOW,
            daily_used=rb.AUTO_READ_DAILY_CAP,
        )
        assert (ok, code) == (False, "daily_cap")

    def test_entities_hash_is_independent_key(self):
        """阶段 A（实体）读过不影响阶段 B（事件）的哈希判定，反之亦然。"""
        state = {"entities_hash": "fp1", "last_run_at": (NOW - timedelta(days=1)).isoformat()}
        ok, _ = rb.decide_auto_read(
            text_len=500, state=state, fingerprint="fp1", hash_key="hash", now=NOW,
        )
        assert ok  # 事件键从未读过 → 放行（entities_hash 不挡 hash）

    def test_naive_state_timestamp_tolerated(self):
        """SQLite DateTime naive 兼容（naive 一律按 UTC）。"""
        state = {"hash": "old", "last_run_at": "2026-08-25T11:59:58"}
        ok, code = rb.decide_auto_read(
            text_len=500, state=state, fingerprint="new", now=NOW,
        )
        assert (ok, code) == (False, "too_soon")


class TestFingerprint:
    def test_whitespace_insensitive(self):
        assert rb.content_fingerprint("一 段\n话。") == rb.content_fingerprint("一段话。")

    def test_content_change_rearms(self):
        assert rb.content_fingerprint("第一段。") != rb.content_fingerprint("第二段。")


class TestCountAutoReads24h:
    def test_counts_only_auto_scope_within_window(self, tmp_path):
        engine = build_sqlite_engine(tmp_path / "budget.db")
        maker = build_sqlite_sessionmaker(engine)
        asyncio.run(init_db_sqlite(engine, maker))

        async def run():
            async with maker() as s:
                s.add(m.Book(id=BOOK_ID, title="预算闸测试书"))
                s.add(m.Chapter(id=CH_ID, book_id=BOOK_ID, chapter_number=1, title="一"))
                await s.flush()
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                def run_row(stage, hours_ago):
                    return m.GenerationRun(
                        id=uuid.uuid4(), chapter_id=CH_ID,
                        run_id=f"adaptive_{CH_ID}", stage=stage,
                        created_at=now - timedelta(hours=hours_ago),
                    )
                s.add(run_row("adaptive.event_scout.auto_read", 1))   # 计
                s.add(run_row("loop3.emergent_facts", 2))           # 计（实体通读同池）
                s.add(run_row("adaptive.event_scout.settle", 1))    # 不计（手动沉淀）
                s.add(run_row("adaptive.event_scout.auto_read", 30))  # 不计（出窗）
                s.add(run_row("adaptive.stitch.continue", 1))       # 不计（非观察类）
                await s.commit()
                return await rb.count_auto_reads_24h(s, str(BOOK_ID))

        try:
            assert asyncio.run(run()) == 2
        finally:
            asyncio.run(engine.dispose())
