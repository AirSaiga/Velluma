# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
C1 上屏前快检单测（P5 批次 4，docs/foundation-hardening.md §5.1 + §9 红线）。

覆盖（纯算法，不连 LLM/DB）：
1. dead_speak：死者名命中 + 别名命中（别名与主名同表）；
2. 存活在场角色不误报（alive=True 的名字出现 → 零 warnings）；
3. canon_leak：canon [private] 标签命中（显式参数 + bundle 两种入口）；
4. secret_leak：私有档案 ≥4 字连续片段命中；
5. <4 字片段/1 字名不误报（宁漏勿误口径）；
6. 干净文本空 warnings；空 bundle 全零（零报错契约）。

运行：python -m pytest backend/services/validation/test_ghost_guard.py -v
"""

from backend.services.context.settings_bundle import SettingsBundle
from backend.services.validation.ghost_guard import check_ghost_text

DEAD_ID = "e1"
ALIVE_ID = "e2"


class _Ns:
    """简单命名空间（伪造 world 适配器鸭子形状）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_entity(eid: str, name: str, aliases=None):
    """伪造 WorldEntityAdapter 形状：world_entity.id/name/aliases + character.name/aliases。"""
    return _Ns(
        world_entity=_Ns(id=eid, name=name, aliases=list(aliases or [])),
        character=_Ns(name=name, aliases=list(aliases or [])),
    )


def _world_state():
    """老烟（死）+ 甲（活）的 t 时刻推演快照（character_states 形状对齐
    compute_world_state_from_events）。"""
    return {
        "at_time": 100,
        "character_states": [
            {"entity_id": DEAD_ID, "location_id": "l1", "alive": False, "label": "已死亡"},
            {"entity_id": ALIVE_ID, "location_id": "l1", "alive": True, "label": "驻留"},
        ],
        "territory_states": [],
        "location_states": [],
        "relation_states": [],
    }


def _names_by_id():
    return {
        DEAD_ID: ["老烟", "烟叔"],
        ALIVE_ID: ["甲"],
    }


# ============================================================
# 1. dead_speak
# ============================================================

def test_dead_speak_hit_by_name():
    """死者主名出现在续写里 → dead_speak 警告（含人话提示可忽略回忆/闪回）。"""
    warnings = check_ghost_text(
        "老烟把烟杆在鞋底磕了磕，说：走。",
        world_state=_world_state(), entity_names_by_id=_names_by_id(),
    )
    hits = [w for w in warnings if w["kind"] == "dead_speak"]
    assert len(hits) == 1
    assert hits[0]["span_text"] == "老烟"
    assert "已死亡" in hits[0]["message"]


def test_dead_speak_hit_by_alias():
    """死者别名命中：正文只写「烟叔」不写本名，同样报 dead_speak。"""
    warnings = check_ghost_text(
        "烟叔的旧棉袄还挂在门口，甲没敢碰。",
        world_state=_world_state(), entity_names_by_id=_names_by_id(),
    )
    hits = [w for w in warnings if w["kind"] == "dead_speak"]
    assert len(hits) == 1
    assert hits[0]["span_text"] == "烟叔"
    # 存活的「甲」在场不报
    assert all(w["span_text"] != "甲" for w in warnings)


def test_alive_present_no_false_positive():
    """存活在场角色名出现 → 零 warnings（宁漏勿误：不把活人当死者）。"""
    warnings = check_ghost_text(
        "甲沿着河堤走了半里，回头看北岸要塞的灯火。",
        world_state=_world_state(), entity_names_by_id=_names_by_id(),
    )
    assert warnings == []


def test_one_char_dead_name_not_matched():
    """1 字死者名不参与匹配（中文正文单字子串误报不可接受）。"""
    state = {"character_states": [{"entity_id": "e9", "alive": False}]}
    names = {"e9": ["乙"]}
    assert check_ghost_text("乙伸手。", world_state=state, entity_names_by_id=names) == []


# ============================================================
# 2. canon_leak
# ============================================================

def test_canon_private_label_hit_explicit():
    """显式参数入口：canon 私有标签出现在正文 → canon_leak。"""
    warnings = check_ghost_text(
        "他终于明白，叶姑娘的平静底下藏着什么。",
        canon_private_labels=["叶姑娘"],
    )
    hits = [w for w in warnings if w["kind"] == "canon_leak"]
    assert len(hits) == 1
    assert hits[0]["span_text"] == "叶姑娘"
    assert "私有" in hits[0]["message"]


def test_canon_private_label_hit_via_bundle():
    """bundle 入口：hard_constraints()['canon_private_labels'] 抽取同源命中。"""
    canon_context = (
        "## 作者脑中的真相 [private] ★ 绝不许在正文直接写出\n"
        "- 叶姑娘：其实是敌国公主\n"
        "  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出\n"
        "\n## 必须遵守的已建立事实 [public]\n"
        "- 甲：北岸老兵\n"
    )
    bundle = SettingsBundle(canon_context=canon_context)
    assert bundle.hard_constraints()["canon_private_labels"] == ["叶姑娘"]
    warnings = check_ghost_text("叶姑娘笑了。", bundle)
    hits = [w for w in warnings if w["kind"] == "canon_leak"]
    assert len(hits) == 1 and hits[0]["span_text"] == "叶姑娘"
    # public 段的标签（甲）不参与 canon_leak
    assert check_ghost_text("甲笑了。", bundle) == []


# ============================================================
# 3. secret_leak
# ============================================================

def test_secret_phrase_hit():
    """私有档案 ≥4 字连续片段整段复现 → secret_leak。"""
    secrets = [{"name": "叶姑娘", "text": "背景：其实是敌国公主\n目标：复仇"}]
    warnings = check_ghost_text(
        "他从袖中抽出那封信，上面写着：其实是敌国公主。",
        character_secrets=secrets,
    )
    hits = [w for w in warnings if w["kind"] == "secret_leak"]
    assert len(hits) == 1
    assert hits[0]["span_text"] == "其实是敌国公主"
    assert "叶姑娘" in hits[0]["message"]


def test_short_secret_fragment_no_false_positive():
    """<4 字片段（含切段后残留的标签词）不参与匹配——宁漏勿误。"""
    secrets = [{"name": "暗桩", "text": "代号：燕；信物：血滴子"}]
    # 「燕」1 字、「代号」2 字均低于门槛；「血滴子」恰 3 字也低于 4 字门槛
    warnings = check_ghost_text(
        "他袖口的血滴子在灯下一闪，燕也认得这信物，代号早已无人记得。",
        character_secrets=secrets,
    )
    assert [w for w in warnings if w["kind"] == "secret_leak"] == []


def test_secret_paraphrase_not_matched():
    """改写复述（非逐字复现）不报——快检是柔性信号，防泄底强制力在真相层审计。"""
    secrets = [{"name": "叶姑娘", "text": "背景：其实是敌国公主"}]
    # 语义泄漏但字面只复现一半（其实是…公主，中间换了字）
    assert check_ghost_text(
        "她其实是前朝的公主。", character_secrets=secrets,
    ) == []


# ============================================================
# 4. 干净文本 / 空 bundle（零报错契约）
# ============================================================

def test_clean_text_empty_warnings():
    """三类数据全配齐，正文干净 → 空 warnings。"""
    warnings = check_ghost_text(
        "甲蹲下来拨了拨火堆，火星子窜起来又灭了。",
        canon_private_labels=["叶姑娘"],
        character_secrets=[{"name": "叶姑娘", "text": "背景：其实是敌国公主"}],
        world_state=_world_state(),
        entity_names_by_id=_names_by_id(),
    )
    assert warnings == []


def test_empty_bundle_all_zero():
    """空 bundle（无世界/无私有/无 canon）→ 恒空、零报错。"""
    assert check_ghost_text("任何文本都不会触发。", SettingsBundle()) == []
    assert check_ghost_text("", SettingsBundle()) == []
    assert check_ghost_text("正文", None) == []
    # 缺半边输入：有 world_state 无名表 / 有名表无 world_state 均不炸
    assert check_ghost_text("老烟。", world_state=_world_state()) == []
    assert check_ghost_text("老烟。", entity_names_by_id=_names_by_id()) == []


def test_mixed_kinds_capped_and_deduped():
    """三类齐发：kind/span 去重（同触发词只报一次）；输出结构三键齐备。"""
    bundle = SettingsBundle(
        canon_context="## 真相 [private] ★\n- 叶姑娘：皇室遗孤\n",
        character_secrets=[{"name": "叶姑娘", "text": "背景：皇室遗孤，满门被灭"}],
        world_state=_world_state(),
        entities=[_fake_entity(DEAD_ID, "老烟", ["烟叔"]), _fake_entity(ALIVE_ID, "甲")],
    )
    warnings = check_ghost_text(
        "老烟说：叶姑娘其实是皇室遗孤，烟叔早知道。", bundle,
    )
    # 老烟/烟叔两个名字都在正文里 → dead_speak 两条（不同 span 各报一次）；
    # canon_leak（叶姑娘）+ secret_leak（皇室遗孤）各一条
    kinds = sorted(w["kind"] for w in warnings)
    assert kinds == ["canon_leak", "dead_speak", "dead_speak", "secret_leak"]
    assert sorted(w["span_text"] for w in warnings if w["kind"] == "dead_speak") == ["烟叔", "老烟"]
    for w in warnings:
        assert set(w.keys()) == {"kind", "span_text", "message"}
        assert w["span_text"] and w["message"]


if __name__ == "__main__":
    import unittest

    import inspect

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            suite.addTest(unittest.FunctionTestCase(fn))
    unittest.TextTestRunner(verbosity=2).run(suite)
