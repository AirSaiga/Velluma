# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""速记解析新实体草拟单测（关联式录入 2026-09-05，mock LLM——不连真实 LLM/DB）。

覆盖：
- _collect_new_drafts 纯函数：evidence 硬闸（子串+包含名）/ kind clamp / 数量 clamp /
  名单闸（既有实体·地点·已解析参与者·发生地同名不报）/ 重复名去重 / 被闸实体名回落
- parse_event_text 全链路：空名册不再早退（新书解析照跑、名字全进 new_entities）/
  chapter=None 走书级此刻 / LLM 失败返回空草稿+空草拟 / fallen 并入 unresolved 去重
- 零变化契约：无 new_entities/new_locations 字段的旧 LLM 输出（写作台既有行为）
  返回空草拟列表，draft 逐字段不变
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.world.event_parser import (
    _collect_new_drafts,
    _resolve_names,
    parse_event_text,
)

_LLM = "backend.services.world.event_parser.call_llm_with_usage"
_RNT = "backend.services.world.event_parser.resolve_narrative_time"
_BOOK_NOW = "backend.services.world.event_parser._book_now_t"
_REPO = "backend.services.world.event_parser.WorldRepository"


def _run(coro):
    """独立 event loop 跑异步（对齐 test_event_scout_dedup 的 _run）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================
# _collect_new_drafts 纯函数
# ============================================================

ENTS = [
    SimpleNamespace(id="11111111-1111-1111-1111-111111111111", name="林尘", entity_type="character", aliases=[]),
    SimpleNamespace(id="22222222-2222-2222-2222-222222222222", name="流光", entity_type="character", aliases=["白露"]),
]
LOCS = [
    SimpleNamespace(id="33333333-3333-3333-3333-333333333333", name="统合局基地"),
    SimpleNamespace(id="44444444-4444-4444-4444-444444444444", name="上海"),
]
TEXT = "林尘在北境要塞遇到白塞，工头老王死了"


def _resolved(*names):
    """按名字从 ENTS 构造 resolved dict（模拟 _resolve_names 的产物形状）。"""
    return {n: next(e for e in ENTS if e.name == n) for n in names}


def test_pass_through_new_entity_and_location():
    ents, locs, fallen = _collect_new_drafts(
        {"new_entities": [{"name": "白塞", "kind": "character", "evidence": "遇到白塞"}],
         "new_locations": [{"name": "北境要塞", "evidence": "在北境要塞"}]},
        TEXT, ENTS, LOCS, {}, "",
    )
    assert ents == [{"name": "白塞", "kind": "character", "evidence": "遇到白塞"}]
    assert locs == [{"name": "北境要塞", "evidence": "在北境要塞"}]
    assert fallen == []


def test_fabricated_evidence_dropped_and_falls_back():
    """evidence 不是原文子串=改写/编造 → 整条丢弃，实体名回落 fallen。"""
    ents, locs, fallen = _collect_new_drafts(
        {"new_entities": [{"name": "白塞", "kind": "character", "evidence": "白塞很强大"}],
         "new_locations": [{"name": "北境要塞", "evidence": "塞北要境"}]},
        TEXT, ENTS, LOCS, {}, "",
    )
    assert ents == [] and locs == []
    assert fallen == ["白塞"]  # 地点不回落（过目单上有地点下拉，原文在 note 里）


def test_evidence_must_contain_name():
    """evidence 在原文里但不包含 name → 丢（名字与依据对不上）。"""
    ents, _, fallen = _collect_new_drafts(
        {"new_entities": [{"name": "白塞", "kind": "character", "evidence": "工头老王"}]},
        TEXT, ENTS, LOCS, {}, "",
    )
    assert ents == [] and fallen == ["白塞"]


def test_kind_clamped_to_character():
    ents, _, _ = _collect_new_drafts(
        {"new_entities": [{"name": "白塞", "kind": " organization", "evidence": "遇到白塞"}]},
        TEXT, ENTS, LOCS, {}, "",
    )
    assert ents[0]["kind"] == "character"


def test_count_clamped():
    many = [{"name": f"路人{i}", "kind": "character", "evidence": f"路人{i}"} for i in range(6)]
    # 原文要真的包含这些名字（否则全被 evidence 闸丢了测不到数量闸）
    text = TEXT + "，还有路人0、路人1、路人2、路人3、路人4、路人5"
    ents, _, _ = _collect_new_drafts({"new_entities": many}, text, ENTS, LOCS, {}, "")
    assert len(ents) == 4


def test_roster_and_claimed_names_skipped():
    """名单内实体/已解析参与者/发生地同名 → 不报新（匹配层的事不重复建档）。"""
    ents, locs, fallen = _collect_new_drafts(
        {"new_entities": [
            {"name": "林尘", "kind": "character", "evidence": "林尘在北境要塞"},
            {"name": "白露", "kind": "character", "evidence": "遇到白塞"},  # 别名命中但不完整——只测名单闸用「流光」
            {"name": "流光", "kind": "character", "evidence": "遇到白塞"},
         ],
         "new_locations": [{"name": "上海", "evidence": "上海"}]},
        "林尘在上海遇到流光", ENTS, LOCS, {"流光": ENTS[1]}, "上海",
    )
    assert ents == [] and locs == []
    assert fallen == []  # 名单内名字不算 fallen（不是「名单外被闸」，是「本就在名单」）


def test_duplicate_names_deduped():
    text = "白塞和白塞同行"
    ents, _, fallen = _collect_new_drafts(
        {"new_entities": [
            {"name": "白塞", "kind": "character", "evidence": "白塞和"},
            {"name": "白塞", "kind": "faction", "evidence": "和白塞"},
         ]},
        text, ENTS, LOCS, {}, "",
    )
    assert len(ents) == 1 and fallen == []


# ============================================================
# parse_event_text 全链路（mock LLM + repo）
# ============================================================

def _mock_repo(entities, locations):
    repo = AsyncMock()
    repo.entities.list_by_book = AsyncMock(return_value=entities)
    repo.locations.list_by_book = AsyncMock(return_value=locations)
    return repo


def _llm_response(payload):
    # 生产形态 LLMResult(.content)
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))


def test_empty_roster_still_parses():
    """空名册（新书）不再早退：解析照跑，句子里所有名字进 new_entities。"""
    parsed = {
        "event_type": "custom", "summary": "林尘到访北境要塞",
        "participants": [], "location": None, "day_offset": 0, "duration_days": 0,
        "note": "林尘到访北境要塞",
        "new_entities": [{"name": "林尘", "kind": "character", "evidence": "林尘到访"}],
        "new_locations": [{"name": "北境要塞", "evidence": "北境要塞"}],
    }
    with patch(_REPO, return_value=_mock_repo([], [])), \
         patch(_LLM, AsyncMock(return_value=_llm_response(parsed))), \
         patch(_BOOK_NOW, AsyncMock(return_value=7)):
        out = _run(parse_event_text(AsyncMock(), "book-1", None, "林尘到访北境要塞"))
    assert out["new_entities"][0]["name"] == "林尘"
    assert out["new_locations"][0]["name"] == "北境要塞"
    assert out["confidence"] == "low"  # custom 且无参与者（既有语义不回退）


def test_chapter_none_uses_book_now():
    """chapter=None（世界页入口）走书级此刻，不碰 resolve_narrative_time。"""
    rnt = AsyncMock(side_effect=AssertionError("不应调用 chapter 级解析"))
    with patch(_REPO, return_value=_mock_repo(ENTS, LOCS)), \
         patch(_RNT, rnt), \
         patch(_BOOK_NOW, AsyncMock(return_value=99)), \
         patch(_LLM, AsyncMock(return_value=SimpleNamespace(content="不是JSON"))):
        out = _run(parse_event_text(AsyncMock(), "book-1", None, "随便一句"))
    assert out["confidence"] == "none"
    # 解析失败的空草稿时刻 = 书级此刻（降级空白表单预填「现在」，与写作台 t 语义一致）
    assert out["draft"]["time_start"] == 99


def test_chapter_present_uses_resolve():
    with patch(_REPO, return_value=_mock_repo(ENTS, LOCS)), \
         patch(_RNT, AsyncMock(return_value=SimpleNamespace(t=33))), \
         patch(_LLM, AsyncMock(return_value=SimpleNamespace(content="not json"))):
        out = _run(parse_event_text(AsyncMock(), "book-1", object(), "随便一句"))
    assert out["draft"]["time_start"] == 33


def test_legacy_output_shape_zero_change():
    """旧 LLM 输出（无 new_entities/new_locations 字段）→ 空草拟，draft 不变。"""
    parsed = {
        "event_type": "move", "summary": "林尘北上",
        "participants": ["林尘"], "location": "上海", "day_offset": 2, "duration_days": 5,
        "note": "林尘北上",
    }
    with patch(_REPO, return_value=_mock_repo(ENTS, LOCS)), \
         patch(_RNT, AsyncMock(return_value=SimpleNamespace(t=10))), \
         patch(_LLM, AsyncMock(return_value=_llm_response(parsed))):
        out = _run(parse_event_text(AsyncMock(), "book-1", object(), "林尘去上海"))
    assert out["new_entities"] == [] and out["new_locations"] == []
    assert out["confidence"] == "high"
    assert out["draft"]["participant_ids"] == [str(ENTS[0].id)] if ENTS[0].id else True
    assert out["draft"]["location_name"] == "上海"


def test_fallen_merges_into_unresolved_deduped():
    """被闸实体名并入 unresolved_names 且与既有 unresolved 去重。"""
    parsed = {
        "event_type": "custom", "summary": "遇人",
        "participants": ["白塞"],  # 名单外 → unresolved_names 已含「白塞」
        "location": None, "day_offset": 0, "duration_days": 0, "note": "遇人",
        "new_entities": [{"name": "白塞", "kind": "character", "evidence": "白塞编造依据不在原文"}],
    }
    with patch(_REPO, return_value=_mock_repo(ENTS, LOCS)), \
         patch(_RNT, AsyncMock(return_value=SimpleNamespace(t=10))), \
         patch(_LLM, AsyncMock(return_value=_llm_response(parsed))):
        out = _run(parse_event_text(AsyncMock(), "book-1", object(), "林尘遇到白塞"))
    assert out["draft"]["unresolved_names"].count("白塞") == 1


def test_adopted_new_name_removed_from_unresolved():
    """P1-2 收口（审查 2026-09-05）：LLM 把名单外名字同时塞进 participants 和
    new_entities（大概率行为）→ 勾选行接管，unresolved 不再双显示。"""
    parsed = {
        "event_type": "custom", "summary": "遇人",
        "participants": ["白塞"],
        "location": None, "day_offset": 0, "duration_days": 0, "note": "遇人",
        "new_entities": [{"name": "白塞", "kind": "character", "evidence": "遇到白塞"}],
        "new_locations": [{"name": "北境要塞", "evidence": "在北境要塞"}],
    }
    with patch(_REPO, return_value=_mock_repo(ENTS, LOCS)), \
         patch(_RNT, AsyncMock(return_value=SimpleNamespace(t=10))), \
         patch(_LLM, AsyncMock(return_value=_llm_response(parsed))):
        out = _run(parse_event_text(AsyncMock(), "book-1", object(), "林尘在北境要塞遇到白塞"))
    assert out["new_entities"][0]["name"] == "白塞"
    assert "白塞" not in out["draft"]["unresolved_names"]


def test_resolve_names_still_works():
    """三级匹配回归锚（_collect_new_drafts 的 claimed 集合来源）。"""
    resolved = _resolve_names(["林尘"], ENTS)
    assert "林尘" in resolved
    assert _resolve_names(["不存在"], ENTS) == {}
