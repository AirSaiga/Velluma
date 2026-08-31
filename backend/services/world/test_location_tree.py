# Velluma - 地点树（内部构造）单测
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""location_tree.py / 速记匹配 / prompt 名单的纯函数对拍（docs/location-interior.md）。

渲染契约不变量：上图权 = parent_id IS NULL——collect_subtree_ids 的删除顺序
（父前子后）与 location_path 的全路径消歧是这条契约的两侧支撑。
"""

from types import SimpleNamespace

from backend.services.world.event_parser import _location_lookup, normalize_draft
from backend.services.world.location_tree import (
    ancestor_chain,
    children_index,
    collect_subtree_ids,
    location_path,
    locations_by_id,
    scene_scope_ids,
)
from backend.services.prompts.world_event_prompts import _roster_text


def _loc(id: str, name: str, parent_id: str | None = None):
    return SimpleNamespace(id=id, name=name, parent_id=parent_id)


# 统一书架：基地 → B2层 → 拘留室；另一基地也有同名「拘留室」
def _shelf():
    base = _loc("base", "统合局基地")
    b2 = _loc("b2", "B2 拘留层", "base")
    cell = _loc("cell", "拘留室", "b2")
    rebel = _loc("rebel", "反抗军营地")
    cell2 = _loc("cell2", "拘留室", "rebel")
    return [base, b2, cell, rebel, cell2]


# ===== collect_subtree_ids =====

def test_subtree_single():
    assert collect_subtree_ids(_shelf(), "rebel") == ["rebel", "cell2"]


def test_subtree_deep_bfs_parent_first():
    """三层子树父前子后——删除按序执行不产生顶层孤儿。"""
    assert collect_subtree_ids(_shelf(), "base") == ["base", "b2", "cell"]


def test_subtree_root_missing():
    assert collect_subtree_ids(_shelf(), "nope") == []
    assert collect_subtree_ids([], "base") == []


def test_subtree_no_cross_contamination():
    """删「反抗军营地」不误收统合局的拘留室。"""
    ids = collect_subtree_ids(_shelf(), "rebel")
    assert "cell" not in ids and "b2" not in ids and "base" not in ids


def test_children_index_and_by_id():
    kids = children_index(_shelf())
    assert [c.id for c in kids["base"]] == ["b2"]
    assert [c.id for c in kids["b2"]] == ["cell"]
    assert kids["rebel"][0].id == "cell2"
    assert set(locations_by_id(_shelf())) == {"base", "b2", "cell", "rebel", "cell2"}


# ===== location_path =====

def test_path_top_level_is_bare_name():
    by_id = locations_by_id(_shelf())
    assert location_path(_shelf()[0], by_id) == "统合局基地"


def test_path_child_and_grandchild():
    by_id = locations_by_id(_shelf())
    locs = {l.id: l for l in _shelf()}
    assert location_path(locs["b2"], by_id) == "统合局基地·B2 拘留层"
    assert location_path(locs["cell"], by_id) == "统合局基地·B2 拘留层·拘留室"


def test_path_cycle_guard():
    """脏数据环（a↔b）不无限循环——爬到已见节点截断，返回确定值。"""
    a = _loc("a", "甲")
    b = _loc("b", "乙", "a")
    a.parent_id = "b"
    by_id = {"a": a, "b": b}
    assert location_path(a, by_id) == "乙·甲"


# ===== _location_lookup（速记匹配）=====

def test_lookup_bare_name_hits_child():
    """速记口语只说「拘留室」→ 命中先建的那个（歧义留表单改）。"""
    hit = _location_lookup(_shelf(), "拘留室")
    assert hit is not None and hit.id == "cell"


def test_lookup_full_path_disambiguates():
    hit = _location_lookup(_shelf(), "反抗军营地·拘留室")
    assert hit is not None and hit.id == "cell2"


def test_lookup_top_level_and_empty():
    assert _location_lookup(_shelf(), "统合局基地").id == "base"
    assert _location_lookup(_shelf(), "  ") is None
    assert _location_lookup(_shelf(), "不存在") is None


def test_normalize_draft_pins_room_level_event():
    """Alt+N 记「在拘留室审讯」→ 草稿地点钉到房间级（身份红利的入口验证）。"""
    draft = normalize_draft(
        {"event_type": "custom", "summary": "审讯俘虏", "participants": [],
         "location": "统合局基地·B2 拘留层·拘留室", "day_offset": 0},
        t=100, entities=[], locations=_shelf(),
    )
    assert draft["location_id"] == "cell"
    assert draft["location_name"] == "拘留室"


def test_normalize_draft_bare_name_still_works():
    draft = normalize_draft(
        {"event_type": "custom", "summary": "越狱", "participants": [], "location": "反抗军营地"},
        t=0, entities=[], locations=_shelf(),
    )
    assert draft["location_id"] == "rebel"


# ===== _roster_text（prompt 名单）=====

def test_roster_flat_book_unchanged():
    """无子地点的书名单逐字节同旧版（零变化契约）。"""
    text = _roster_text([], [_loc("a", "北岸要塞"), _loc("b", "旧王都")])
    assert text == "- 北岸要塞 [地点]\n- 旧王都 [地点]"


def test_roster_children_show_full_path():
    text = _roster_text([], _shelf())
    assert "- 统合局基地 [地点]" in text
    assert "- 统合局基地·B2 拘留层 [地点]" in text
    assert "- 统合局基地·B2 拘留层·拘留室 [地点]" in text
    assert "- 反抗军营地·拘留室 [地点]" in text


# ===== ancestor_chain / scene_scope_ids（二期：场景作用域）=====

def test_ancestor_chain_inner_to_top():
    by_id = locations_by_id(_shelf())
    chain = ancestor_chain(by_id, "cell")
    assert [l.id for l in chain] == ["cell", "b2", "base"]  # 自内向外
    assert [l.id for l in ancestor_chain(by_id, "base")] == ["base"]
    assert ancestor_chain(by_id, "nope") == []


def test_ancestor_chain_cycle_guard():
    a = _loc("a", "甲", "b")
    b = _loc("b", "乙", "a")
    chain = ancestor_chain({"a": a, "b": b}, "a")
    assert [l.id for l in chain] == ["a", "b"]  # 环截断不死循环


def test_scene_scope_ids_room_pin_covers_ancestors():
    """场景钉「拘留室」→ 作用域含整条进路（写基地戏时基地上的人也在场）；
    子级不在作用域（钉基地不等于钉某个房间）。"""
    assert scene_scope_ids(_shelf(), "cell") == {"cell", "b2", "base"}
    assert scene_scope_ids(_shelf(), "cell2") == {"cell2", "rebel"}


def test_scene_scope_ids_zero_change_contract():
    """无场景钉 → 空集；顶层钉 → 恒等集（= 旧精确匹配行为逐字节不变）。"""
    assert scene_scope_ids(_shelf(), "") == set()
    assert scene_scope_ids(_shelf(), "base") == {"base"}
    assert scene_scope_ids([], "x") == set()
