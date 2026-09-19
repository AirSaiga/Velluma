# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 候选转正重复闸单测（2026-08-26 全书通读实测修复）
"""accept_candidate 重复转正闸 + undo_accept_candidate 单事务撤销（02 候选回流修缮 P2b）的行为契约：

同一事件换措辞的候选可并存于 pending 池（跨章抽取/历史存量），全部采纳
会把账本写重（实测：「陈朗救走李岩父女」×2 双双入账）。转正前对全书账本
近期事件做归一化子串判重（与 event_scout 同一把尺子）：
- 命中 → 不建事件，候选标 rejected + draft.auto_reject="duplicate" 留痕，
  响应 duplicated=True（前端不计失败、不进撤销名单）
- 未命中 → 正常转正（零变化）
- quiet_learning 不把 auto_reject 的假拒绝计入静音学习

undo_accept_candidate 单事务撤销（02 修缮 P2b）：
- accept 时转正产物 id 记入 draft（accepted_event_id / accepted_canon_node_id）
- 撤销 = 删产物 + 回 pending 一个 commit 内完成——旧前端「删事件 / reopen」
  两条独立请求链断出的「事件已删、候选仍 accepted」孤儿态不可能再发生
- 存量候选（draft 无产物 id）靠请求体显式 id；产物已被单独删除时幂等 reopen

配方：临时文件 SQLite + 真实 repo/路由栈（同 test_quiet_learning.py）；
UUID 带字母。

运行：python -m pytest backend/services/world/test_accept_dedup.py -v
"""

import asyncio
import uuid

import pytest
from fastapi import HTTPException

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.world_repository import WorldRepository
from backend.routes.world import (
    UndoAcceptRequest,
    accept_candidate,
    create_entity,
    create_location,
    undo_accept_candidate,
)
from backend.schemas.world import WorldEntityCreate, WorldLocationCreate

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


class TestCreateIdempotencyGate:
    """服务端幂等闸（2026-08-26 实测事故：确认无防连点，14 连击建出 14 份同名实体）。"""

    def test_same_name_same_type_returns_existing(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "idem.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                p = WorldEntityCreate(book_id=BOOK_ID, entity_type="character", name="陈朗")
                first = await create_entity(BOOK_ID, p, s)
                second = await create_entity(BOOK_ID, p, s)
                assert str(first.id) == str(second.id)
                repo = WorldRepository(s)
                assert len(await repo.entities.list_by_book(str(BOOK_ID), "character")) == 1

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_same_name_different_type_both_created(self, tmp_path):
        """同名不同类是两个东西（组织「鹰翼」与机甲「鹰翼」）——不误合并。"""
        engine, maker = _make_stack(tmp_path, "idem_type.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                a = await create_entity(BOOK_ID, WorldEntityCreate(
                    book_id=BOOK_ID, entity_type="faction", name="鹰翼"), s)
                b = await create_entity(BOOK_ID, WorldEntityCreate(
                    book_id=BOOK_ID, entity_type="asset", name="鹰翼"), s)
                assert str(a.id) != str(b.id)

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_explicit_id_bypasses_gate(self, tmp_path):
        """undo/redo 幂等重建路径豁免：显式 id 直入不查重。"""
        engine, maker = _make_stack(tmp_path, "idem_undo.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                fixed = uuid.uuid4()
                p1 = WorldEntityCreate(book_id=BOOK_ID, entity_type="character", name="陈朗", id=fixed)
                first = await create_entity(BOOK_ID, p1, s)
                assert str(first.id) == str(fixed)

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_location_same_name_returns_existing(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "idem_loc.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                p = WorldLocationCreate(book_id=BOOK_ID, name="北岸要塞")
                first = await create_location(BOOK_ID, p, s)
                second = await create_location(BOOK_ID, p, s)
                assert str(first.id) == str(second.id)

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

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


class TestUndoAcceptTransaction:
    """单事务撤销（02 候选回流修缮 P2b）：删产物 + 回 pending 原子完成。"""

    def test_accept_records_product_id_in_draft(self, tmp_path):
        """accept 把转正产物 id 写进 draft——撤销端点据此定位产物。"""
        engine, maker = _make_stack(tmp_path, "undo_rec.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                cand = await _add_candidate(s, "夜袭焚毁北岸粮仓", etype="battle")
                resp = await accept_candidate(BOOK_ID, cand.id, s)
                repo = WorldRepository(s)
                fresh = await repo.candidates.get(str(cand.id))
                assert fresh.status == "accepted"
                assert (fresh.draft or {}).get("accepted_event_id") == str(resp.event.id)

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_undo_deletes_event_and_reopens(self, tmp_path):
        """主路径：事件删除 + 候选回 pending 同一 commit；deleted=event。"""
        engine, maker = _make_stack(tmp_path, "undo_ev.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                repo = WorldRepository(s)
                cand = await _add_candidate(s, "夜袭焚毁北岸粮仓", etype="battle")
                resp = await accept_candidate(BOOK_ID, cand.id, s)
                event_id = resp.event.id

                out = await undo_accept_candidate(BOOK_ID, cand.id, None, s)
                assert out == {"status": "pending", "deleted": "event"}
                assert await repo.events.get(str(event_id)) is None
                fresh = await repo.candidates.get(str(cand.id))
                assert fresh.status == "pending"

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_undo_canon_node_path(self, tmp_path):
        """canon_extract 候选：撤销删真相节点 + 回 pending。"""
        engine, maker = _make_stack(tmp_path, "undo_canon.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                repo = WorldRepository(s)
                cand = await repo.candidates.create(
                    str(BOOK_ID), str(CH_ID),
                    {"type": "event", "label": "林尘身世", "canon_text": "里", "public_text": "表"},
                    source="canon_extract",
                )
                await s.commit()
                resp = await accept_candidate(BOOK_ID, cand.id, s)
                node_id = resp["canon_node_id"]

                out = await undo_accept_candidate(BOOK_ID, cand.id, None, s)
                assert out == {"status": "pending", "deleted": "canon_node"}
                assert await s.get(m.CanonNode, node_id) is None
                fresh = await repo.candidates.get(str(cand.id))
                assert fresh.status == "pending"

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_undo_legacy_candidate_with_explicit_event_id(self, tmp_path):
        """存量候选（draft 无产物 id——端点上线前采纳）：请求体显式 id 兜底。"""
        engine, maker = _make_stack(tmp_path, "undo_legacy.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                repo = WorldRepository(s)
                cand = await _add_candidate(s, "夜袭焚毁北岸粮仓", etype="battle")
                resp = await accept_candidate(BOOK_ID, cand.id, s)
                # 抹掉 draft 记录的产物 id，模拟端点上线前的存量候选
                fresh = await repo.candidates.get(str(cand.id))
                fresh.draft = {k: v for k, v in (fresh.draft or {}).items()
                               if k != "accepted_event_id"}
                await s.commit()

                out = await undo_accept_candidate(
                    BOOK_ID, cand.id, UndoAcceptRequest(event_id=resp.event.id), s)
                assert out == {"status": "pending", "deleted": "event"}
                assert await repo.events.get(str(resp.event.id)) is None

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_undo_missing_product_still_reopens(self, tmp_path):
        """产物已被单独删除：幂等撤销照样 reopen（不报错不阻塞）。"""
        engine, maker = _make_stack(tmp_path, "undo_gone.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                repo = WorldRepository(s)
                cand = await _add_candidate(s, "夜袭焚毁北岸粮仓", etype="battle")
                resp = await accept_candidate(BOOK_ID, cand.id, s)
                await repo.events.delete(str(resp.event.id))
                await s.commit()

                out = await undo_accept_candidate(BOOK_ID, cand.id, None, s)
                assert out == {"status": "pending", "deleted": None}
                fresh = await repo.candidates.get(str(cand.id))
                assert fresh.status == "pending"

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_undo_non_accepted_rejected_with_409(self, tmp_path):
        """未采纳态（pending/rejected）不可撤销——与 accept 的 409 口径一致。"""
        engine, maker = _make_stack(tmp_path, "undo_409.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                cand = await _add_candidate(s, "夜袭焚毁北岸粮仓", etype="battle")
                with pytest.raises(HTTPException) as ei:
                    await undo_accept_candidate(BOOK_ID, cand.id, None, s)
                assert ei.value.status_code == 409

        try:
            asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
