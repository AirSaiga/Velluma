# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""event_scout 候选去重单测（A5a，mock LLM——不连真实 LLM/DB）。

覆盖（docs/foundation-hardening.md §2.4）：
- 零变化契约：无 recent_events（旧调用形态）/ None / [] 三种入参下
  user prompt 与改版前逐字节一致，system prompt 恒不变
- 排除块注入：「第N日 类型：note截断」行格式、空 note 跳过、40 字截断
- 账本预筛（纯算法）：归一化（去空白/标点）子串重合判重、双向 containment、
  短文本放行（宁漏勿误）
- run() 全链路：同义重复候选不再入池 / LLM 调用参数不动 /
  pending 池同章 (event_type, summary) 幂等（原有行为不回退）
"""
# Velluma - event_scout dedup tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.models import Chapter
from backend.services.context.world_bridge import NarrativeTime
from backend.services.llm.client import REASONING_DISABLED
from backend.services.prompts.world_event_prompts import build_event_candidates_prompt
from backend.services.world.event_scout import (
    _is_ledger_duplicate,
    _normalize_for_dedup,
    run,
)

_LLM = "backend.services.world.event_scout.call_llm_with_usage"
_RNT = "backend.services.world.event_scout.resolve_narrative_time"
_REPO = "backend.services.world.event_scout.WorldRepository"


def _run(coro):
    """独立 event loop 跑异步（对齐 test_sentence_integrity 的 _run——
    避免 asyncio.run 污染同进程后续测试的事件循环策略）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================
# 零变化契约（最重要的回归护栏）
# ============================================================

ENTS = [SimpleNamespace(name="林尘", entity_type="character", aliases=[])]
LOCS = [SimpleNamespace(name="北岸要塞")]
BODY = "林尘推开要塞侧门，风雪灌了进来，火把齐齐一暗。"
T = 12

# 改版前（无 recent_events 参数）的 user prompt 逐字节快照
EXPECTED_USER = """当前世界时刻（连续日计数）：t = 12

角色与地点名单：
- 林尘 [character]
- 北岸要塞 [地点]

正文：
---
林尘推开要塞侧门，风雪灌了进来，火把齐齐一暗。
---

请抽取候选事件（最多 6 条，按叙事顺序）。"""


class TestZeroChangeContract:
    def test_old_call_shape_byte_identical(self):
        """旧调用形态（完全不传 recent_events）→ 与改版前逐字节一致。"""
        sys_p, user_p = build_event_candidates_prompt(BODY, T, ENTS, LOCS, max_candidates=6)
        assert user_p == EXPECTED_USER
        assert "已入账" not in user_p and "勿重复提取" not in user_p

    def test_none_and_empty_list_identical(self):
        """recent_events=None / [] / 不传 → 三者互为逐字节一致，system 恒不变。"""
        sys_none, user_none = build_event_candidates_prompt(BODY, T, ENTS, LOCS, recent_events=None)
        sys_empty, user_empty = build_event_candidates_prompt(BODY, T, ENTS, LOCS, recent_events=[])
        assert user_none == EXPECTED_USER
        assert user_empty == EXPECTED_USER
        assert sys_none == sys_empty

    def test_all_empty_note_events_zero_change(self):
        """全空 note 的事件列表无文本比对价值 → prompt 仍逐字节一致。"""
        evts = [SimpleNamespace(time_start=9, event_type="battle", note="", sequence_num=1)]
        _, user_p = build_event_candidates_prompt(BODY, T, ENTS, LOCS, recent_events=evts)
        assert user_p == EXPECTED_USER


# ============================================================
# 排除块注入
# ============================================================

class TestExclusionBlock:
    def test_block_format_and_order(self):
        """行格式「- 第N日 类型：note」按传入序注入，空 note 行跳过。"""
        evts = [
            SimpleNamespace(time_start=12, event_type="move", note="林尘抵达北岸要塞，与守军汇合", sequence_num=2),
            SimpleNamespace(time_start=9, event_type="battle", note="  ", sequence_num=1),
            SimpleNamespace(time_start=7, event_type="custom", note="长" * 45, sequence_num=0),
        ]
        sys_old, _ = build_event_candidates_prompt(BODY, T, ENTS, LOCS)
        sys_new, user_p = build_event_candidates_prompt(BODY, T, ENTS, LOCS, recent_events=evts)
        assert sys_new == sys_old  # system prompt 不动
        assert "勿重复提取" in user_p and "同义换措辞也算重复" in user_p
        assert "- 第12日 move：林尘抵达北岸要塞，与守军汇合" in user_p
        assert "- 第7日 custom：" + "长" * 40 in user_p   # note 截 40 字
        assert "长" * 41 not in user_p
        assert "第9日" not in user_p                      # 空 note 事件不出现


# ============================================================
# 账本预筛（纯算法）
# ============================================================

NOTE = "林尘抵达北岸要塞，与守军汇合"


class TestLedgerPreFilter:
    def test_normalize_strips_ws_and_punct(self):
        assert _normalize_for_dedup(" 林尘，抵达。北岸要塞！\n") == "林尘抵达北岸要塞"

    def test_punct_variant_substring_caught(self):
        """同措辞 + 标点/空白差异 + 账本侧多缀语 → 判重（summary ⊂ note）。"""
        assert _is_ledger_duplicate("林尘抵达北岸要塞。", [NOTE]) is True

    def test_note_contained_in_summary_caught(self):
        """反向 containment（note ⊂ summary，候选把账本原话扩写重提）→ 判重。"""
        assert _is_ledger_duplicate("是夜林尘抵达北岸要塞与守军汇合之后开宴", [NOTE]) is True

    def test_genuinely_new_event_passes(self):
        assert _is_ledger_duplicate("夜袭焚毁北岸粮仓", [NOTE]) is False

    def test_short_summary_passes(self):
        """归一化后 <4 字不参与比对（宁漏勿误：防「死了」「搬家」类短词误杀）。"""
        assert _is_ledger_duplicate("死了", ["林尘死了，葬于北岸"]) is False

    def test_empty_inputs_pass(self):
        assert _is_ledger_duplicate("", [NOTE]) is False
        assert _is_ledger_duplicate("林尘抵达北岸要塞", []) is False
        assert _is_ledger_duplicate("林尘抵达北岸要塞", [""]) is False


# ============================================================
# run() 全链路（mock LLM + fake repo/db）
# ============================================================

def _event(day, etype, note, seq=1):
    return SimpleNamespace(time_start=day, event_type=etype, note=note, sequence_num=seq)


def _fake_repo(entities, locations, pending):
    created = []

    async def _create(book_id, chapter_id, draft, source="settle"):
        created.append({"draft": draft, "source": source})
        return SimpleNamespace(draft=draft)

    repo = SimpleNamespace(
        entities=SimpleNamespace(list_by_book=AsyncMock(return_value=entities)),
        locations=SimpleNamespace(list_by_book=AsyncMock(return_value=locations)),
        candidates=SimpleNamespace(
            list_by_book=AsyncMock(return_value=pending),
            create=AsyncMock(side_effect=_create),
        ),
    )
    return repo, created


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class _FakeDb:
    """run() 里唯一的 db.execute 就是最近事件查询；db.get 取章节。"""

    def __init__(self, chapter, recent):
        self._chapter = chapter
        self._recent = recent

    async def get(self, model, pk):
        return self._chapter if model is Chapter else None

    async def execute(self, stmt):
        return _FakeResult(self._recent)


def _llm_resp(cands):
    # 测试 mock 形态 (text, usage) 二元组（对齐 memory_ingestion/event_parser 约定）
    return (json.dumps({"candidates": cands}, ensure_ascii=False), {})


_CHAPTER = SimpleNamespace(book_id="b1", content_text="")

_CAND_DUP = {
    "event_type": "move", "summary": "林尘抵达北岸要塞。", "participants": ["林尘"],
    "location": None, "day_offset": 0, "duration_days": 0, "note": "正文提及",
}
_CAND_NEW = {
    "event_type": "battle", "summary": "夜袭焚毁北岸粮仓", "participants": [],
    "location": None, "day_offset": 1, "duration_days": 0, "note": "正文提及",
}


class TestRunEndToEnd:
    def test_ledger_duplicate_not_pooled(self):
        """已入账事件的同义候选（标点/缀语差异）不再入池，新事件照常入池。"""
        recent = [_event(12, "move", NOTE)]
        repo, created = _fake_repo(ENTS, LOCS, pending=[])
        db = _FakeDb(_CHAPTER, recent)
        llm = AsyncMock(return_value=_llm_resp([_CAND_DUP, _CAND_NEW]))

        with patch(_LLM, new=llm), patch(_RNT, new=AsyncMock(return_value=NarrativeTime(T, "chapter_anchor"))), \
                patch(_REPO, new=lambda _: repo):
            result = _run(run("c1", db, {}, 0, source="settle", text=BODY))

        assert result == {"created": 1}
        assert len(created) == 1
        assert created[0]["draft"]["summary"] == "夜袭焚毁北岸粮仓"
        assert created[0]["source"] == "settle"
        # 排除块随 prompt 送给 LLM（语义侧闸门）
        user_p = llm.call_args.kwargs["user_prompt"]
        assert "- 第12日 move：林尘抵达北岸要塞，与守军汇合" in user_p
        assert "勿重复提取" in user_p

    def test_no_events_book_prompt_byte_identical_and_params_unchanged(self):
        """无事件书：LLM 收到的 user prompt 与旧版逐字节一致；调用参数不动。"""
        repo, created = _fake_repo(ENTS, LOCS, pending=[])
        db = _FakeDb(_CHAPTER, recent=[])
        llm = AsyncMock(return_value=_llm_resp([_CAND_NEW]))

        with patch(_LLM, new=llm), patch(_RNT, new=AsyncMock(return_value=NarrativeTime(T, "chapter_anchor"))), \
                patch(_REPO, new=lambda _: repo):
            result = _run(run("c1", db, {}, 0, source="finish", text=BODY))

        assert result == {"created": 1}
        kwargs = llm.call_args.kwargs
        # prompt 与旧版（不传 recent_events）逐字节一致
        _, expected_user = build_event_candidates_prompt(BODY, T, ENTS, LOCS, max_candidates=6)
        assert kwargs["user_prompt"] == expected_user
        assert kwargs["model_type"] == "creative"
        assert kwargs["temperature"] == 0.1
        assert kwargs["max_tokens"] == 1500
        assert kwargs["reasoning_config"] == REASONING_DISABLED

    def test_pending_pool_dedup_still_works(self):
        """原有幂等不回退：pending 池同章同 (event_type, summary) 仍跳过。"""
        pending = [SimpleNamespace(draft={"event_type": "battle", "summary": "夜袭焚毁北岸粮仓"})]
        repo, created = _fake_repo(ENTS, LOCS, pending=pending)
        db = _FakeDb(_CHAPTER, recent=[])

        with patch(_LLM, new=AsyncMock(return_value=_llm_resp([_CAND_NEW]))), \
                patch(_RNT, new=AsyncMock(return_value=NarrativeTime(T, "chapter_anchor"))), \
                patch(_REPO, new=lambda _: repo):
            result = _run(run("c1", db, {}, 0, source="settle", text=BODY))

        assert result == {"created": 0}
        assert created == []

    def test_cross_chapter_pending_dedup_by_containment(self):
        """2026-08-26 全书通读实测：同一事件跨章被重复抽取（前文回顾/场景延续），
        pending 判重从「同章精确对」升级为「全书归一化子串」——换措辞也拦住。"""
        pending = [SimpleNamespace(draft={"event_type": "move", "summary": "陈朗救走李岩父女二人"})]
        repo, created = _fake_repo(ENTS, LOCS, pending=pending)
        db = _FakeDb(_CHAPTER, recent=[])
        # 同一事件换措辞 + 不同章（pending 来自他章）——子串判重应拦
        dup_reworded = {**_CAND_NEW, "event_type": "move", "summary": "陈朗救走李岩父女"}

        with patch(_LLM, new=AsyncMock(return_value=_llm_resp([dup_reworded]))), \
                patch(_RNT, new=AsyncMock(return_value=NarrativeTime(T, "chapter_anchor"))), \
                patch(_REPO, new=lambda _: repo):
            result = _run(run("c1", db, {}, 0, source="auto_read", text=BODY))

        assert result == {"created": 0}
        assert created == []
