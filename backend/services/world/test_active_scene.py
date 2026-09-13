# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""光标派生取景框单测（第三弹 · docs/scene-transit-feasibility.md §3.1）。

运行：python -m pytest backend/services/world/test_active_scene.py -v
"""
from __future__ import annotations

from backend.services.world.active_scene import (
    ActiveScene,
    pre_cursor_window,
    resolve_active_scene,
)


class Loc:
    def __init__(self, id, name, aliases=None, coord_x=None, coord_y=None):
        self.id = id
        self.name = name
        self.aliases = aliases or []
        self.coord_x = coord_x
        self.coord_y = coord_y


REPAIR = Loc("loc-repair", "维修棚", coord_x=100, coord_y=100)
VILLAGE = Loc("loc-village", "村道", coord_x=200, coord_y=150)
MINGJIE = Loc("loc-mingjie", "明姐家厨房", aliases=["明姐家"], coord_x=300, coord_y=200)
# 内部构造（无坐标房间）——名册同样入册
INNER = Loc("loc-inner", "里屋", aliases=[], coord_x=None, coord_y=None)
NAMES = [REPAIR, VILLAGE, MINGJIE, INNER]


# ============================================================
# 核心派生
# ============================================================

def test_transit_hit_derives_new_scene():
    """最近转场命中 → 派生新景（500 字跨三地的主场景，动词紧邻地名）。"""
    text = "老王在维修棚里修发电机。他拎着工具包穿过村道。推门进了明姐家厨房。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is True
    assert r.loc_id == "loc-mingjie"
    assert r.via == "推门·明姐家厨房"


def test_non_adjacent_mention_does_not_switch():
    """动词与地名被其他词隔开（「推门进屋，明姐家的灯…」）→ 不算转场：
    转场语义由动宾紧邻承载（与穿越闸同判据），隔空提及不切换。"""
    text = "老王在维修棚里修发电机。推门进屋，明姐家的灯还亮着。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is False and r.loc_id == "loc-repair"


def test_verb_adherence_required():
    """地点名无转场动词紧邻 → 不算转场（提及≠到场）。"""
    text = "他还惦记着明姐家的热汤。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is False
    assert r.loc_id == "loc-repair"


def test_fallback_to_pin_without_hit():
    text = "发电机嗡了一声，又哑了。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is False and r.loc_id == "loc-repair" and r.loc_name == "维修棚"


def test_fallback_empty_without_pin():
    text = "发电机嗡了一声。"
    r = resolve_active_scene(text, NAMES, base_loc_id=None)
    assert r.loc_id == "" and r.derived is False


def test_unfinished_sentence_does_not_switch():
    """防抖①：作者正在写的半截转场短语（句未完结）不切换——无状态滞回。"""
    text = "老王在维修棚修好了发电机。他推门走进了明姐家厨"  # 名没写完+句没结束
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is False and r.loc_id == "loc-repair"


def test_finished_sentence_switches():
    """同一句写完句号 → 切换成立。"""
    text = "老王在维修棚修好了发电机。他推门走进了明姐家厨房。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is True and r.loc_id == "loc-mingjie"


def test_flashback_exempt_continues_left():
    """闪回豁免：回忆里的转场不算数，继续向左找更早的非闪回转场。"""
    text = (
        "他推门进了明姐家厨房。锅还热着。"
        "他忽然想起当年走进维修棚学艺的那个下午。"
    )
    r = resolve_active_scene(text, NAMES, base_loc_id=None)
    # 最右命中（维修棚）在「当年」句里 → 豁免；次右（明姐家厨房）合法 → 派生
    assert r.derived is True and r.loc_id == "loc-mingjie"


def test_alias_maps_to_primary():
    """别名（明姐家）命中归主地点。"""
    text = "他走进明姐家，灶上炖着肉。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is True and r.loc_id == "loc-mingjie"


def test_nested_names_take_longest():
    """嵌名（明姐家 ⊂ 明姐家厨房）同位置取最长——派生最具体的房间。"""
    text = "他走进明姐家厨房，灶上炖着肉。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.loc_id == "loc-mingjie" and r.loc_name == "明姐家厨房"


def test_metaphor_target_not_in_roster_keeps_scene():
    """比喻目标（「回到过去」）不在名册 → 命中失败保持原景（防漂闸）。"""
    text = "他仿佛回到了过去。那时一切都还好。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is False and r.loc_id == "loc-repair"


def test_filler_between_verb_and_name():
    """动词与地名间 ≤2 字填充合法（「走进了明姐家」「赶回那座要塞」同款）。"""
    text = "他走进了明姐家，灯亮着。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is True


def test_extra_indoor_verbs():
    """扩充室内动词（推门/跨进/拐进）驱动转场。"""
    text = "他跨进里屋，把包放下。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is True and r.loc_id == "loc-inner"


def test_backward_edit_derives_earlier_scene():
    """删改回滚正确性：光标窗截到旧转场后 → 场景回到更早处（派生非状态）。"""
    full = "他在维修棚修好发电机。走进明姐家厨房吃了饭。回到维修棚睡觉。"
    # 作者删掉最后一句后重看：窗内最近转场=进明姐家
    text = "他在维修棚修好发电机。走进明姐家厨房吃了饭。"
    r = resolve_active_scene(text, NAMES, base_loc_id=None)
    assert r.loc_id == "loc-mingjie"
    # 没删时最近转场=回维修棚
    r2 = resolve_active_scene(full, NAMES, base_loc_id=None)
    assert r2.loc_id == "loc-repair"


# ============================================================
# 锚定取窗
# ============================================================

def test_pre_cursor_window_anchor_by_recent_tail():
    plain = "甲" * 200 + "他在维修棚修发电机。" + "乙" * 50 + "他走进明姐家厨房。"
    anchor = "他走进明姐家厨房。"  # 光标段尾
    win = pre_cursor_window(plain, anchor, window_chars=60)
    assert win.endswith("他走进明姐家厨房。")
    assert "甲" not in win  # 窗外更早文本不进扫描


def test_pre_cursor_window_anchor_missing_falls_to_tail():
    win = pre_cursor_window("前文。中段。结尾。", "这段根本不在文里！！", window_chars=3)
    assert win == "结尾。"


def test_pre_cursor_window_empty_inputs():
    assert pre_cursor_window("", "锚") == ""
    assert pre_cursor_window("正文。", "") == "正文。"


def test_end_to_end_window_then_resolve():
    """锚定取窗 → 派生：光标段之后的旧转场不进窗（不会穿越到未来）。"""
    plain = (
        "他走进明姐家厨房吃了顿热饭。"  # 更早场景（窗外）
        + "闲话。" * 400
        + "他回到维修棚，把工具包挂上墙。"
    )
    anchor = "他回到维修棚，把工具包挂上墙。"
    win = pre_cursor_window(plain, anchor, window_chars=300)
    r = resolve_active_scene(win, NAMES, base_loc_id=None)
    assert r.loc_id == "loc-repair" and r.derived is True
    assert "明姐家" not in win or r.loc_id == "loc-repair"
