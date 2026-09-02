# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 约束治理一期单测（registry/events/prompt_sections/persona_drift/ghost_guard 集成）
"""
覆盖（2026-09-02 一期，docs/constraint-governance.md）：
1. registry：多层执法关联（dock-no-psych 是第一例）、未知 id 状态兜底、lint；
2. events：schema 完整性（constraint_id/status_at_event/outcome——信用分
   机制的不可补采前提）+ VELLUMA_DATA_DIR 覆盖 + 轮转对称读；
3. prompt_sections：谓词激活与谓词异常降级；
4. persona_drift：对白剥离与密度；
5. ghost_guard 第五检 out_of_scene 集成：local_only 标记 / 闪回豁免不产
   warning 只产 exempt 事件 / visible_names=None 该检不跑（零变化契约）。

运行：python -m pytest backend/services/constraints/test_governance.py -v
"""
import uuid
from types import SimpleNamespace

from backend.services.constraints import events as constraint_events_mod
from backend.services.constraints.prompt_sections import PromptSection, render_sections
from backend.services.constraints.registry import (
    get_constraint,
    scan_prompt_wording,
    status_of,
)
from backend.services.constraints.persona_drift import narrative_first_person_density
from backend.services.validation.ghost_guard import check_ghost_text


# ============================================================
# 1. registry
# ============================================================

def test_multilayer_constraint_associated_by_id():
    """dock-no-psych：prompt 禁令与代码嗅探是同一约束的两层（多层关联首例）。"""
    c = get_constraint("dock-no-psych")
    assert c is not None
    assert "prompt" in c.layers and "gate" in c.layers


def test_unknown_constraint_status_falls_back_live():
    assert status_of("no-such-constraint") == "live"
    assert status_of("ghost-guard-out-of-scene") == "shadow"


def test_wording_lint_counts():
    report = scan_prompt_wording("铁律第一条：必须绝不妥协。")
    assert report["铁律"] == 1 and report["必须"] == 1 and report["绝不"] == 1
    assert report["total"] == 3


# ============================================================
# 2. events（schema 完整性是硬性验收项）
# ============================================================

def test_event_schema_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VELLUMA_DATA_DIR", str(tmp_path))
    constraint_events_mod.log_constraint_event(
        "bk-1", "ch-1", "ghost-guard-out-of-scene", "hit",
        reason="handling_verb_frame", detail={"name": "流光"},
    )
    data = constraint_events_mod.read_constraint_events(chapter_id="ch-1")
    assert data["total"] == 1
    ev = data["recent"][0]
    # 信用分不可补采字段：constraint_id + status_at_event + outcome + reason
    assert ev["constraint_id"] == "ghost-guard-out-of-scene"
    assert ev["status_at_event"] == "shadow"
    assert ev["outcome"] == "hit" and ev["reason"] == "handling_verb_frame"
    assert ev["detail"]["name"] == "流光"
    assert ev["ts"]
    # 章过滤：别的章读不到
    assert constraint_events_mod.read_constraint_events(chapter_id="ch-2")["total"] == 0


def test_event_rotation_and_silent_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("VELLUMA_DATA_DIR", str(tmp_path))
    # 写满轮转：超过上限（测试里直接构造大文件触发 rename 分支）
    from backend.services.constraints import events as m

    p = m._events_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x" * (m._MAX_BYTES + 1), encoding="utf-8")
    constraint_events_mod.log_constraint_event("b", "c", "persona-drift", "hit")
    assert m._rotated_path().exists()
    assert constraint_events_mod.read_constraint_events(chapter_id="c")["total"] == 1


# ============================================================
# 3. prompt_sections
# ============================================================

def test_sections_render_by_predicate_and_exception_degrades_absent():
    sections = [
        PromptSection(key="a", text="[A]"),
        PromptSection(key="b", text="[B]", when=lambda ctx: bool(ctx.get("on"))),
        PromptSection(key="c", text="[C]", when=lambda ctx: ctx["missing_key"]),  # 异常→缺席
    ]
    assert render_sections(sections, {"on": True}) == "[A][B]"
    assert render_sections(sections, {"on": False}) == "[A]"
    assert render_sections(sections, {}) == "[A]"


# ============================================================
# 4. persona_drift（B5 report-only）
# ============================================================

def test_persona_density_strips_dialogue():
    # 对白里的「我」合法：剥引号后叙述段无第一人称
    text = "“我明天就来。”他说完转身走了，脚步声消失在走廊尽头，只留下满地灰烬。"
    r = narrative_first_person_density(text)
    assert r["sufficient"] == 1 and r["density"] == 0
    # 叙述段第一人称：密度超阈值
    text2 = "我停下来。我看着那台机器。我不知道它在想什么，但我知道它醒着。"
    r2 = narrative_first_person_density(text2)
    assert r2["sufficient"] == 1 and r2["density"] > 2.0


def test_persona_short_narrative_insufficient():
    assert narrative_first_person_density("我走了。")["sufficient"] == 0


# ============================================================
# 5. ghost_guard 第五检 out_of_scene（集成）
# ============================================================

def _bundle():
    """《最终武装》第 1 章形态：林尘在场，流光/白霆/血噬不在名单。"""
    ents = [
        SimpleNamespace(
            world_entity=SimpleNamespace(id="e1", entity_type="character"),
            character=SimpleNamespace(name="林尘", aliases=[]),
        ),
        SimpleNamespace(
            world_entity=SimpleNamespace(id="e2", entity_type="character"),
            character=SimpleNamespace(name="白霆", aliases=[]),
        ),
        SimpleNamespace(
            world_entity=SimpleNamespace(id="e3", entity_type="asset"),
            character=SimpleNamespace(name="血噬", aliases=[]),
        ),
    ]
    assets = []
    return SimpleNamespace(
        entities=ents, assets=assets,
        hard_constraints=lambda: {"canon_private_labels": []},
        character_secrets=[], world_state={}, prohibitions=None,
    )


def test_out_of_scene_hit_marked_local_only():
    events_log = []
    warnings = check_ghost_text(
        "工头炸在耳边：发什么愣！把流光左腿关节的螺栓给我拧紧了！",
        _bundle(),
        visible_names=["林尘"],
        all_names=["林尘", "白霆", "血噬", "流光"],
        on_event=lambda cid, outcome, reason, detail: events_log.append((cid, outcome, reason)),
    )
    hit = next(w for w in warnings if w["kind"] == "out_of_scene")
    assert hit["span_text"] == "流光" and hit["local_only"] is True
    assert events_log and events_log[0][1] == "hit"


def test_out_of_scene_flashback_exempt_never_warns():
    events_log = []
    warnings = check_ghost_text(
        "他想起当年自己跟师父修过流光的传动轴，那会儿零件还用的是民用标准。",
        _bundle(),
        visible_names=["林尘"],
        all_names=["林尘", "白霆", "血噬", "流光"],
        on_event=lambda cid, outcome, reason, detail: events_log.append((cid, outcome, reason)),
    )
    assert not [w for w in warnings if w["kind"] == "out_of_scene"]  # 连 shadow warning 都不产
    assert events_log and events_log[0][1] == "exempt" and events_log[0][2] == "flashback"


def test_out_of_scene_skipped_without_visible_names():
    """visible_names=None（旧调用方）→ 第五检不跑——零变化契约。"""
    warnings = check_ghost_text(
        "把流光左腿关节的螺栓给我拧紧了！", _bundle(),
    )
    assert not [w for w in warnings if w["kind"] == "out_of_scene"]


def test_out_of_scene_death_guard_unaffected():
    """dead_speak 与第五检并行不悖：死者名仍走 dead_speak 通道。"""
    bundle = _bundle()
    bundle.world_state = {"character_states": [
        {"entity_id": "e2", "alive": False, "location_id": "", "label": "已死亡"},
    ]}
    warnings = check_ghost_text(
        "白霆走了进来，手里握着茶杯。", bundle,
        visible_names=["林尘"], all_names=["林尘", "白霆", "血噬"],
    )
    kinds = {w["kind"] for w in warnings}
    assert "dead_speak" in kinds
