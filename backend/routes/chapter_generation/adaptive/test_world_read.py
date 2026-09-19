# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - auto-read/read-entities 端点锚纪律单测（02 候选回流修缮 P6）
"""read-entities 失败不写幂等锚——保留重试资格（与 auto_read 事件阶段同纪律）。

行为契约：
- extract 返回 failed=True（LLM 异常/输出不可解析）→ ran=False +
  skipped.code="llm_failed"，chapters.auto_read_state 不落 entities_hash
- 成功（含无涌现——failed=False 空列表是合法结果）→ 照写锚（零变化）

配方：临时 SQLite 真实栈 + monkeypatch emergent_facts.extract_emergent_facts
（路由内函数级 import，patch 模块属性即生效）。运行：
python -m pytest backend/routes/chapter_generation/adaptive/test_world_read.py -v
"""

import asyncio
import uuid

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.routes.chapter_generation.adaptive.world_read import read_chapter_entities
from backend.services.adaptive.emergent_facts import EmergentFacts

BOOK_ID = uuid.UUID("cc440000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("cc440000-0000-4000-8000-0000000000c1")
CONTENT = "林尘推开要塞侧门，风雪灌了进来，火把齐齐一暗。" * 6  # >100 字过短文闸


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed(s):
    s.add(m.Book(id=BOOK_ID, title="认人锚纪律测试书"))
    s.add(m.Chapter(id=CH_ID, book_id=BOOK_ID, chapter_number=1, title="第一章",
                    content_text=CONTENT))
    await s.flush()


def test_read_entities_failure_keeps_retry(tmp_path, monkeypatch):
    """认人失败：不写 entities_hash——下次进通读或正文变化时可重跑。"""

    async def _failed(*a, **k):
        return EmergentFacts(failed=True)

    monkeypatch.setattr(
        "backend.services.adaptive.emergent_facts.extract_emergent_facts", _failed)
    engine, maker = _make_stack(tmp_path, "re_fail.db")

    async def run():
        async with maker() as s:
            await _seed(s)
            resp = await read_chapter_entities(str(CH_ID), None, s)
            assert resp.ran is False
            assert resp.skipped["code"] == "llm_failed"
            assert resp.skipped["reason"]  # 人话一句非空
            ch = await s.get(m.Chapter, CH_ID)
            assert not (ch.auto_read_state or {}).get("entities_hash")

    try:
        asyncio.run(run())
    finally:
        asyncio.run(engine.dispose())


def test_read_entities_success_writes_anchor(tmp_path, monkeypatch):
    """认人成功（有产出或无涌现都算成功）：照写幂等锚——行为不变。"""

    async def _ok(*a, **k):
        return EmergentFacts(new_entities=[{"name": "明姐", "kind": "character"}])

    monkeypatch.setattr(
        "backend.services.adaptive.emergent_facts.extract_emergent_facts", _ok)
    engine, maker = _make_stack(tmp_path, "re_ok.db")

    async def run():
        async with maker() as s:
            await _seed(s)
            resp = await read_chapter_entities(str(CH_ID), None, s)
            assert resp.ran is True
            assert len(resp.entities) == 1
            ch = await s.get(m.Chapter, CH_ID)
            assert (ch.auto_read_state or {}).get("entities_hash")

    try:
        asyncio.run(run())
    finally:
        asyncio.run(engine.dispose())


def test_read_entities_no_emergence_still_writes_anchor(tmp_path, monkeypatch):
    """无涌现（failed=False 空手而归）= 合法结果照写锚——与失败严格区分。"""

    async def _empty(*a, **k):
        return EmergentFacts()

    monkeypatch.setattr(
        "backend.services.adaptive.emergent_facts.extract_emergent_facts", _empty)
    engine, maker = _make_stack(tmp_path, "re_empty.db")

    async def run():
        async with maker() as s:
            await _seed(s)
            resp = await read_chapter_entities(str(CH_ID), None, s)
            assert resp.ran is True
            assert resp.entities == []
            ch = await s.get(m.Chapter, CH_ID)
            assert (ch.auto_read_state or {}).get("entities_hash")

    try:
        asyncio.run(run())
    finally:
        asyncio.run(engine.dispose())
