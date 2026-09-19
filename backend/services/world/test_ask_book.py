# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 问书单测（04 下一阶段 M1-M3）
"""图书管理员的行为契约（docs/next-phase/04-ask-the-book.md）：

- classify_question 纯函数：六类模式识别（线头/该揭/距离/谁知道/哪章写过/
  上次出场）+ 听不懂返回 None
- 六类纯代码直答：逐条带 sources 出处；零数据/查不到 → not_found（诚实是功能）
- M2 意图笼：LLM 只翻译；解析产物过硬闸（名单外的角色名拒答）；
  解析失败 → no_match 提示六类问法
- M3 材料内合成：引用材料袋外的出处 id = 编造 → 整稿拒收（宁拒勿假）

配方：临时 SQLite 真实栈 + monkeypatch llm client（模块内函数级 import，
patch backend.services.llm.client 命名空间即生效）。运行：
python -m pytest backend/services/world/test_ask_book.py -v
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.routes.chapter_generation.adaptive.ask_book import ask_book as ask_route
from backend.services.world.ask_book import (
    answer_question,
    classify_question,
    log_ask_metric,
)

BOOK_ID = uuid.UUID("ee660000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("ee660000-0000-4000-8000-0000000000c7")  # 第 7 章
ENT_ID = uuid.UUID("ee660000-0000-4000-8000-0000000000e1")  # 明姐
ENT2_ID = uuid.UUID("ee660000-0000-4000-8000-0000000000e2")  # 林尘
LOC_A = uuid.UUID("ee660000-0000-4000-8000-0000000000a1")  # 北岸要塞
LOC_B = uuid.UUID("ee660000-0000-4000-8000-0000000000b2")  # 渡口

_LLM = "backend.services.llm.client.call_llm_with_usage"


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed(s):
    s.add(m.Book(id=BOOK_ID, title="问书测试书", map_scale={
        "refs": [{"ax": 0, "ay": 0, "bx": 100, "by": 0, "days_foot": 2}],  # 50px/天
    }))
    s.add(m.Chapter(id=CH_ID, book_id=BOOK_ID, chapter_number=7, title="第七章",
                    narrative_time=700))
    s.add(m.Chapter(book_id=BOOK_ID, chapter_number=3, title="第三章",
                    narrative_time=300, content_text="<p>明姐把轮渡时刻表钉在了码头的木柱上。</p>"))
    s.add(m.WorldEntity(id=ENT_ID, book_id=BOOK_ID, name="明姐", entity_type="character"))
    s.add(m.WorldEntity(id=ENT2_ID, book_id=BOOK_ID, name="林尘", entity_type="character"))
    s.add(m.WorldLocation(id=LOC_A, book_id=BOOK_ID, name="北岸要塞", coord_x=0, coord_y=0))
    s.add(m.WorldLocation(id=LOC_B, book_id=BOOK_ID, name="渡口", coord_x=100, coord_y=0))
    s.add(m.PlotLedger(book_id=BOOK_ID, content="北岸的旧钟没有敲响", ledger_key="hk-1",
                       status="open", created_at_chapter=1))
    node = m.CanonNode(book_id=BOOK_ID, type="event", label="明姐的身世",
                       canon_text="明姐是要塞旧主之女", public_text="普通厨娘",
                       visibility="private", source="manual", confidence="settled",
                       expected_reveal_chapter=6)
    s.add(node)
    await s.flush()
    s.add(m.WorldEvent(
        book_id=BOOK_ID, event_type="move", time_start=650, time_end=650,
        participant_ids=[str(ENT_ID)], location_id=str(LOC_A),
        payload={}, note="明姐押粮北上，进驻北岸要塞", sequence_num=1,
    ))
    s.add(m.WorldEvent(
        book_id=BOOK_ID, event_type="told", time_start=600, time_end=600,
        participant_ids=[str(ENT2_ID)], location_id=None,
        payload={"subject": str(ENT2_ID), "proposition_ref": str(node.id)},
        note="老王把明姐的身世告诉了林尘", sequence_num=2,
    ))
    await s.flush()


# ============================================================
# 模式识别（纯函数）
# ============================================================

class TestClassify:
    def test_six_types(self):
        assert classify_question("还有几条没收的伏笔？") == {"type": "threads"}
        assert classify_question("这章该揭什么真相？")["type"] == "reveals_due"
        d = classify_question("北岸要塞到渡口走几天？")
        assert d["type"] == "distance" and d["a"] == "北岸要塞" and d["b"] == "渡口"
        k = classify_question("林尘知道明姐的身世吗")
        assert k["type"] == "knows" and k["x"] == "林尘"
        w = classify_question("轮渡时刻表是在哪章写的？")
        assert w["type"] == "which_chapter"
        assert classify_question("明姐上次出场是什么时候？")["type"] == "last_appearance"

    def test_unrecognized_returns_none(self):
        assert classify_question("今天天气怎么样") is None
        assert classify_question("") is None


# ============================================================
# 六类纯代码直答（零 LLM——ask 路径上没有 LLM 调用点）
# ============================================================

class TestPureAnswers:
    def _run(self, tmp_path, name, q, patch_llm=True):
        engine, maker = _make_stack(tmp_path, name)

        async def run():
            async with maker() as s:
                await _seed(s)
                await s.commit()
                ch = await s.get(m.Chapter, CH_ID)
                if patch_llm:
                    # 六类直答不应碰 LLM——挂个哨兵，被调用即炸
                    guard = AsyncMock(side_effect=AssertionError("六类直答不许调 LLM"))
                    with patch(_LLM, new=guard):
                        out = await answer_question(s, str(BOOK_ID), ch, q)
                else:
                    out = await answer_question(s, str(BOOK_ID), ch, q)
                return out

        try:
            return asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_threads(self, tmp_path):
        out = self._run(tmp_path, "ab_t.db", "还有几条没收的伏笔？")
        assert out["kind"] == "threads"
        assert "1 条没收的线头" in out["text"] and "吊了 6 章" in out["text"]
        assert out["sources"][0]["type"] == "foreshadow"

    def test_reveals_due(self, tmp_path):
        out = self._run(tmp_path, "ab_r.db", "这章该揭什么真相？")
        assert out["kind"] == "reveals_due"
        assert "明姐的身世" in out["text"] and "已逾期 1 章" in out["text"]
        assert out["sources"][0]["type"] == "canon"

    def test_distance(self, tmp_path):
        out = self._run(tmp_path, "ab_d.db", "北岸要塞到渡口走几天？")
        assert out["kind"] == "distance"
        assert "从北岸要塞到渡口" in out["text"] and "约 2" in out["text"]
        assert {s["type"] for s in out["sources"]} == {"location"}

    def test_last_appearance(self, tmp_path):
        out = self._run(tmp_path, "ab_l.db", "明姐上次出场是什么时候？")
        assert out["kind"] == "last_appearance"
        assert "明姐押粮北上" in out["text"] and "约第 3 章" in out["text"]
        assert out["sources"][0]["type"] == "world_event"

    def test_knows_proposition_four_value(self, tmp_path):
        """Y 是真相 → belief 四值判定（told 事件 → knows）。
        断言收紧（GUI 交叉验证缺陷 #2）：降级分支文案也含「知道」二字，旧断言
        两个分支都过=假绿——必须断言命题分支专属措辞「知道「Y」」。"""
        out = self._run(tmp_path, "ab_k.db", "林尘知道明姐的身世吗")
        assert out["kind"] == "knows"
        assert "知道「明姐的身世」" in out["text"], out["text"]

    def test_knows_particle_tail_regression(self, tmp_path):
        """回归（缺陷 #2）：「X 知道 Y 吗」的 Y 懒惰截短曾致 canon 标签匹配
        失败降级同场分支——Y 必须完整剥掉句尾「吗」后命中命题分支。"""
        out = self._run(tmp_path, "ab_k2.db", "林尘晓得明姐的身世吗?")
        assert out["kind"] == "knows"
        assert "知道「明姐的身世」" in out["text"], out["text"]

    def test_which_chapter(self, tmp_path):
        out = self._run(tmp_path, "ab_w.db", "轮渡时刻表是在哪章写的？")
        assert out["kind"] == "which_chapter"
        assert "第 3 章" in out["text"] and "轮渡时刻表" in out["text"]
        assert out["sources"][0]["type"] == "chapter"

    def test_unknown_thing_not_found(self, tmp_path):
        out = self._run(tmp_path, "ab_n.db", "北岸要塞到不存在的地名走几天？")
        assert out["kind"] == "not_found" and "没查到" in out["text"]


# ============================================================
# M2 意图笼 / M3 材料内合成（mock LLM）
# ============================================================

def _llm_resp(obj) -> AsyncMock:
    return AsyncMock(return_value=(json.dumps(obj, ensure_ascii=False), {}))


class TestIntentCage:
    def test_llm_intent_routes_to_retriever(self, tmp_path):
        """听不懂的问题经 LLM 解析后走同一扇检索门（示例：上次出场的口语变体）。"""
        engine, maker = _make_stack(tmp_path, "ab_m2a.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await s.commit()
                ch = await s.get(m.Chapter, CH_ID)
                llm = _llm_resp({"type": "last_appearance", "name": "明姐"})
                with patch(_LLM, new=llm):
                    out = await answer_question(s, str(BOOK_ID), ch, "那个厨娘最近一次露面是啥时候来着")
                return out

        try:
            out = asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
        assert out["kind"] == "last_appearance" and "明姐押粮北上" in out["text"]

    def test_fabricated_name_rejected_by_hard_gate(self, tmp_path):
        """硬闸：LLM 编了名单外的角色名 → 拒答 no_match（不猜）。"""
        engine, maker = _make_stack(tmp_path, "ab_m2b.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await s.commit()
                ch = await s.get(m.Chapter, CH_ID)
                llm = _llm_resp({"type": "last_appearance", "name": "根本不存在的人"})
                with patch(_LLM, new=llm):
                    out = await answer_question(s, str(BOOK_ID), ch, "随便问点啥")
                return out

        try:
            out = asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
        assert out["kind"] == "no_match" and "没查到" in out["text"]

    def test_parse_garbage_falls_back_to_no_match(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "ab_m2c.db")

        async def run():
            async with maker() as s:
                await _seed(s)
                await s.commit()
                ch = await s.get(m.Chapter, CH_ID)
                llm = AsyncMock(return_value=("这不是JSON", {}))
                with patch(_LLM, new=llm):
                    out = await answer_question(s, str(BOOK_ID), ch, "随便问点啥")
                return out

        try:
            out = asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
        assert out["kind"] == "no_match"


class TestSynthesisCage:
    def _synth(self, tmp_path, name, llm_obj, question="明姐和轮渡时刻表是怎么回事"):
        engine, maker = _make_stack(tmp_path, name)

        async def run():
            async with maker() as s:
                await _seed(s)
                await s.commit()
                ch = await s.get(m.Chapter, CH_ID)
                llm = _llm_resp({"type": "synthesis", "question": question})
                synth = _llm_resp(llm_obj)
                calls = [llm, synth]
                async def _router(*a, **k):
                    return calls.pop(0).return_value
                with patch(_LLM, new=AsyncMock(side_effect=_router)):
                    out = await answer_question(s, str(BOOK_ID), ch, question)
                return out

        try:
            return asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())

    def test_valid_synthesis_with_sources(self, tmp_path):
        out = self._synth(tmp_path, "ab_m3a.db", {
            "text": "轮渡时刻表是明姐钉在码头木柱上的。",
            "source_ids": ["c0"],  # 章材料按 chapter_number 升序编号：第三章=c0
        })
        assert out["kind"] == "synthesis"
        assert "轮渡时刻表" in out["text"]
        assert out["sources"] and out["sources"][0]["type"] == "material"

    def test_fabricated_source_id_rejects_whole_answer(self, tmp_path):
        """出处铁律：引用材料袋外的 id（e99）= 编造出处 → 整稿拒收。"""
        out = self._synth(tmp_path, "ab_m3b.db", {
            "text": "看起来很可靠的答案。",
            "source_ids": ["c0", "e99"],
        })
        assert out["kind"] == "not_found"

    def test_empty_text_rejected(self, tmp_path):
        out = self._synth(tmp_path, "ab_m3c.db", {"text": "", "source_ids": ["c0"]})
        assert out["kind"] == "not_found"


# ============================================================
# 路由与度量
# ============================================================

class TestRouteAndMetric:
    def test_route_bad_chapter_not_found(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "ab_route.db")

        async def run():
            async with maker() as s:
                from backend.routes.chapter_generation.adaptive.ask_book import AskBookRequest
                out = await ask_route("bad-chapter", AskBookRequest(question="还有几条伏笔"), s)
                return out

        try:
            out = asyncio.run(run())
        finally:
            asyncio.run(engine.dispose())
        assert out["kind"] == "not_found"

    def test_metric_written(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VELLUMA_DATA_DIR", str(tmp_path))
        log_ask_metric("b", "c", "还有几条伏笔？", "threads")
        path = tmp_path / "ask_book_metrics.jsonl"
        assert path.exists()
        line = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        assert line["question"] == "还有几条伏笔？" and line["kind"] == "threads"
