# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 词法在场兜底 + 事件参与者三级匹配单测（约束治理一期 · 数据缺口 B6）
"""
边界锁（导师审查验收闸）：死者排除 / 同名歧义不填 / 无 location_id 事件
不采 / 幂等 / 不碰有状态实体；三级匹配的精确-包含-token 边界与歧义。

运行：python -m pytest backend/services/world/test_lexical_presence.py -v
"""
from types import SimpleNamespace

from backend.services.world.lexical_presence import enrich_state_with_lexical_presence
from backend.services.world.event_parser import _resolve_names


def _ent(eid, name, aliases=None, etype="character"):
    return SimpleNamespace(id=eid, name=name, aliases=aliases or [], entity_type=etype)


def _ev(seq, note, t=100, loc="loc-1", etype="custom", payload=None, eid="ev-1"):
    return SimpleNamespace(
        sequence_num=seq, note=note, time_start=t, time_end=t,
        location_id=loc, event_type=etype, payload=payload or {}, id=eid,
    )


def _loc(loc_id):
    return SimpleNamespace(id=loc_id, name="统合局基地", coord_x=1.0, coord_y=2.0)


def test_fills_missing_entity_from_note():
    state = {"character_states": []}
    enrich_state_with_lexical_presence(
        state, [_ev(1, "林尘来到统合局基地作为一名底层搬运工工作")],
        [_ent("e1", "林尘")], {"loc-1": _loc("loc-1")}, 100,
    )
    assert len(state["character_states"]) == 1
    cs = state["character_states"][0]
    assert cs["entity_id"] == "e1" and cs["location_id"] == "loc-1"
    assert cs["presence_source"] == "lexical" and cs["alive"] is True


def test_dead_entity_never_lexically_present():
    state = {"character_states": []}
    events = [
        _ev(1, "老王在统合局基地巡逻", eid="ev-a"),
        _ev(2, "", etype="death", loc=None, payload={"character_id": "e1"}, eid="ev-b"),
    ]
    enrich_state_with_lexical_presence(state, events, [_ent("e1", "老王")], {"loc-1": _loc("loc-1")}, 100)
    assert state["character_states"] == []  # 宁可缺席不可复活


def test_ambiguous_name_skipped():
    state = {"character_states": []}
    enrich_state_with_lexical_presence(
        state, [_ev(1, "流光带领武装机甲突袭基地")],
        [_ent("e1", "流光"), _ent("e2", "流光")], {"loc-1": _loc("loc-1")}, 100,
    )
    assert state["character_states"] == []  # 双实体同名=歧义不猜（实例书的真实坑）


def test_event_without_location_ignored_and_idempotent():
    state = {"character_states": []}
    events = [_ev(1, "林尘在仓库卸货", loc=None), _ev(2, "林尘在统合局基地搬货")]
    enrich_state_with_lexical_presence(state, events, [_ent("e1", "林尘")], {"loc-1": _loc("loc-1")}, 100)
    n = len(state["character_states"])
    assert n == 1
    # 幂等：重复调用 no-op（有状态者不覆盖）
    enrich_state_with_lexical_presence(state, events, [_ent("e1", "林尘")], {"loc-1": _loc("loc-1")}, 100)
    assert len(state["character_states"]) == n


def test_existing_state_not_overridden():
    state = {"character_states": [
        {"entity_id": "e1", "location_id": "loc-2", "alive": True, "label": "驻留"},
    ]}
    enrich_state_with_lexical_presence(
        state, [_ev(1, "林尘来到统合局基地")], [_ent("e1", "林尘")], {"loc-1": _loc("loc-1")}, 100,
    )
    assert state["character_states"][0]["location_id"] == "loc-2"  # 折叠优先
    assert "presence_source" not in state["character_states"][0]


def test_non_character_entities_excluded():
    """P2-8：势力/资产的词法命中不进 character_states（在场语义=谁在这）。"""
    state = {"character_states": []}
    ents = [_ent("e1", "林尘"), _ent("e2", "统合局", etype="faction"), _ent("e3", "血噬", etype="asset")]
    enrich_state_with_lexical_presence(
        state, [_ev(1, "林尘和血噬在统合局基地交货")], ents, {"loc-1": _loc("loc-1")}, 100,
    )
    ids = {cs["entity_id"] for cs in state["character_states"]}
    assert ids == {"e1"}


def test_gap_event_fires_per_fill():
    """P1-3：每个词法补填落一条 event-participant-gap 事件（数据缺口可度量）。"""
    events_log = []
    state = {"character_states": []}
    enrich_state_with_lexical_presence(
        state, [_ev(1, "林尘来到统合局基地", eid="ev-9")], [_ent("e1", "林尘")],
        {"loc-1": _loc("loc-1")}, 100,
        on_event=lambda cid, outcome, reason, detail: events_log.append((cid, outcome, reason, detail)),
    )
    assert len(events_log) == 1
    cid, outcome, reason, detail = events_log[0]
    assert cid == "event-participant-gap" and outcome == "hit" and reason == "lexical_presence_fill"
    assert detail == {"entity_id": "e1", "name": "林尘", "event_id": "ev-9"}


def test_embedded_compound_not_filled():
    """token 边界加固（2026-09-17）：名嵌在更长成词里不算在场——「流光溢彩」
    是单 token，不再因子串命中凭空造在场（裸子串时代此条会误填）。"""
    state = {"character_states": []}
    enrich_state_with_lexical_presence(
        state, [_ev(1, "流光溢彩之间他沉默了")],
        [_ent("e1", "流光")], {"loc-1": _loc("loc-1")}, 100,
    )
    assert state["character_states"] == []


def test_substring_fallback_when_jieba_missing(monkeypatch):
    """jieba 缺失退子串柔性红线（判据可降级，兜底不失明）。"""
    import backend.services.world.lexical_presence as lp

    monkeypatch.setattr(lp, "_token_accs", lambda _text: None)
    state = {"character_states": []}
    enrich_state_with_lexical_presence(
        state, [_ev(1, "林尘在统合局基地搬货")],
        [_ent("e1", "林尘")], {"loc-1": _loc("loc-1")}, 100,
    )
    assert len(state["character_states"]) == 1


def test_lexicon_registered_before_matching():
    """词典注入挂点（2026-09-17）：enrich 顺手把名表注册进 jieba——
    生僻专名恒为单 token，token 边界命中不依赖默认词典恰好认识它。"""
    import jieba

    state = {"character_states": []}
    enrich_state_with_lexical_presence(
        state, [_ev(1, "云漪端着药走进统合局基地")],
        [_ent("e1", "云漪")], {"loc-1": _loc("loc-1")}, 100,
    )
    assert len(state["character_states"]) == 1
    assert "云漪" in list(jieba.cut("云漪端着药"))


# ============================================================
# _resolve_names 三级匹配
# ============================================================

def test_resolve_exact_and_alias():
    ents = [_ent("e1", "林尘", ["小林子"]), _ent("e2", "白霆")]
    out = _resolve_names(["林尘", "小林子", "路人甲"], ents)
    assert set(out.keys()) == {"林尘", "小林子"}


def test_resolve_level2_containment_with_modifier():
    """「阿晚姑娘」⊃「阿晚」：修饰性称呼二级包含命中。"""
    ents = [_ent("e1", "阿晚")]
    out = _resolve_names(["阿晚姑娘"], ents)
    assert set(out.keys()) == {"阿晚姑娘"}


def test_resolve_ambiguous_leaves_unresolved():
    """双实体同名（实例书真坑：机甲「流光」+ 持有者「流光」）→ 全级歧义不猜。"""
    ents = [_ent("e1", "流光"), _ent("e2", "流光")]
    assert _resolve_names(["流光"], ents) == {}


def test_resolve_exact_wins_over_containment_ambiguity():
    """精确名优先于包含歧义：报告名与实体名完全一致时直接命中（level1 短路）。"""
    ents = [_ent("e1", "阿晚"), _ent("e2", "阿晚姐")]
    out = _resolve_names(["阿晚姐"], ents)
    assert set(out.keys()) == {"阿晚姐"}


def test_resolve_rejects_single_char_containment():
    """包含级要求 ≥2 字：单字实体名不吃包含匹配（误报率不可接受）。"""
    ents = [_ent("e1", "云")]
    assert _resolve_names(["云中君"], ents) == {}
