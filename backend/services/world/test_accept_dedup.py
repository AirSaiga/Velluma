# Velluma - 候选转正重复闸单测（2026-08-26 全书通读实测修复）
# AGPL-3.0
"""accept_candidate 重复转正闸的行为契约：

同一事件换措辞的候选可并存于 pending 池（跨章抽取/历史存量），全部采纳
会把账本写重（实测：「陈朗救走李岩父女」×2 双双入账）。转正前对全书账本
近期事件做归一化子串判重（与 event_scout 同一把尺子）：
- 命中 → 不建事件，候选标 rejected + draft.auto_reject="duplicate" 留痕，
  响应 duplicated=True（前端不计失败、不进撤销名单）
- 未命中 → 正常转正（零变化）
- quiet_learning 不把 auto_reject 的假拒绝计入静音学习

配方：临时文件 SQLite + 真实 repo/路由栈（同 test_quiet_learning.py）；
UUID 带字母。

运行：python -m pytest backend/services/world/test_accept_dedup.py -v
"""

import asyncio
import uuid

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.world_repository import WorldRepository
from backend.routes.world import accept_candidate

BOOK_ID = uuid.UUID("aa770000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("aa770000-0000-4000-8000-0000000000c1")


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed(session):
    session.add(m.Book(id=BOOK_ID, title="转正闸测试书"))
    session.add(m.Chapter(id=CH_ID, book_id=BOOK_ID, chapter_number=1, title="第一章"))
    await session.flush()


async def _add_candidate(session, summary, etype="move"):
    repo = WorldRepository(session)
    cand = await repo.candidates.create(
        str(BOOK_ID), str(CH_ID),
        {"event_type": etype, "summary": summary, "time_start": 0, "time_end": 0,
         "participant_ids": [], "location_id": None, "note": "正文提及"},
        source="auto_read",
    )
    await session.commit()
    return cand


async def _ledger_count(session):
    repo = WorldRepository(session)
    return len(await repo.events.list_all_by_book(str(BOOK_ID)))


class TestAcceptDedupGate:
    def test_duplicate_accept_skips_event_creation(self, tmp_path):
        """账本已有同义事件 → 转正闸：不建事件、候选 rejected + auto_reject 留痕。"""
        engine, maker = _make_stack(tmp_path, "accept_dup.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                repo = WorldRepository(s)
                await repo.events.create(
                    str(BOOK_ID), event_type="move", time_start=0, time_end=0,
                    location_id=None, participant_ids=[], payload={},
                    note="陈朗救走李岩父女，连夜出城",
                )
                cand = await _add_candidate(s, "陈朗救走李岩父女")
                before = await _ledger_count(s)

                resp = await accept_candidate(BOOK_ID, cand.id, s)
                assert resp["duplicated"] is True
                assert resp["event"] is None
                assert await _ledger_count(s) == before  # 账本没写重

                fresh = await repo.candidates.get(str(cand.id))
                assert fresh.status == "rejected"
                assert (fresh.draft or {}).get("auto_reject") == "duplicate"

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_genuinely_new_event_accepted_normally(self, tmp_path):
        """非同义候选：正常转正建事件（零变化契约）。"""
        engine, maker = _make_stack(tmp_path, "accept_new.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                repo = WorldRepository(s)
                await repo.events.create(
                    str(BOOK_ID), event_type="move", time_start=0, time_end=0,
                    location_id=None, participant_ids=[], payload={},
                    note="陈朗救走李岩父女，连夜出城",
                )
                cand = await _add_candidate(s, "夜袭焚毁北岸粮仓", etype="battle")
                resp = await accept_candidate(BOOK_ID, cand.id, s)
                assert resp.event is not None
                assert resp.duplicated is False

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
