# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""光标派生取景框单测（第三弹 · docs/scene-transit-feasibility.md §3.1）。

运行：python -m pytest backend/services/world/test_active_scene.py -v
"""
from __future__ import annotations

from backend.services.world.active_scene import (
    ActiveScene,
    dedupe_guest_names,
    extract_active_actors,
    known_name_terms,
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
    """动词与地名被其他词隔开（「推门进屋，明姐家的灯…」）→ 宏观不切换：
    转场语义由动宾紧邻承载（与穿越闸同判据），隔空提及不换据点——但
    「推门进屋」本身是合法的微观空间动势（2026-09-16 姿态层）：室内姿态
    成立、derived=True，宏观留在钉上。"""
    text = "老王在维修棚里修发电机。推门进屋，明姐家的灯还亮着。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.loc_id == "loc-repair"          # 宏观据点不动
    assert r.derived is True                 # 正文确实推导出了东西（微观姿态）
    assert r.posture == {"kind": "indoor_living", "label": "室内生活", "cue": "进屋"}


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


# ============================================================
# 微观空间姿态（Spatial Posture · 2026-09-16 第四批）
# ============================================================

def test_posture_only_fires_without_roster_room():
    """主场景（第四批任务书）：名册只有宏观据点，正文「推开门」——地名匹配
    失败但姿态成立：宏观回退钉 + 微观室内生活，derived=True。"""
    VILLAGE_ONLY = [Loc("loc-village", "林尘序章生活的村子")]
    text = "林尘回到林尘序章生活的村子。他推开门，屋里飘着饭菜香。"
    r = resolve_active_scene(text, VILLAGE_ONLY, base_loc_id="loc-village")
    assert r.loc_id == "loc-village" and r.loc_name == "林尘序章生活的村子"
    assert r.derived is True
    # 「回到×村名」是合法地名转场（via 记地名证据）；更靠后的「屋里」叠加为姿态后缀
    assert r.via == "回到·林尘序章生活的村子"
    assert r.posture == {"kind": "indoor_living", "label": "室内生活", "cue": "屋里"}


def test_posture_rightmost_wins_across_kinds():
    """Q3 优先级覆盖：开头「修车棚」（工位）后文「进屋」（室内）——逆扫取
    最右命中，后期室内绝对覆盖早期工位，与类别无关。"""
    text = "他一早蹲在修车棚里拆机箱。忙到晌午。推门进屋，明姐已经把饭摆上了桌。"
    r = resolve_active_scene(text, NAMES, base_loc_id=None)
    assert r.derived is True
    assert r.posture is not None and r.posture["kind"] == "indoor_living"
    assert r.posture["cue"] == "进屋"


def test_posture_without_pin_still_derives():
    """无钉无名册命中但有姿态 → derived=True、loc_id 空（宏观无锚）。"""
    text = "他掀帘进了屋，灶台上还温着一锅粥。"
    r = resolve_active_scene(text, NAMES, base_loc_id=None)
    assert r.derived is True and r.loc_id == ""
    assert r.posture["kind"] == "indoor_living" and r.posture["cue"] == "灶台"


def test_posture_unfinished_sentence_does_not_fire():
    """半截防抖同闸：作者正在写「他推门」（句未完结）→ 姿态不成立。"""
    text = "他放下碗。他推门"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is False and r.loc_id == "loc-repair" and r.posture is None


def test_posture_flashback_exempt():
    """闪回里的空间不算当前镜头：想起当年炕上 → 姿态豁免回退钉。"""
    text = "他站在院里。他忽然想起当年炕上听师父说书的冬夜。"
    r = resolve_active_scene(text, NAMES, base_loc_id="loc-repair")
    assert r.derived is False and r.posture is None


def test_posture_appends_after_later_than_loc_hit():
    """地名命中后作者继续往里走（cue 更靠后）→ 姿态作补充后缀；
    cue 早于地名命中 → 不叠（进「明姐家厨房」之前的「推门」不重复计）。"""
    text = "他推门走进明姐家厨房。在桌边坐下。"
    r = resolve_active_scene(text, NAMES, base_loc_id=None)
    assert r.loc_id == "loc-mingjie" and r.derived is True
    assert r.posture is not None and r.posture["cue"] == "桌边"

    early = "他推开门。走进明姐家厨房，灶上炖着肉。"
    r2 = resolve_active_scene(early, NAMES, base_loc_id=None)
    assert r2.loc_id == "loc-mingjie" and r2.posture is None


# ============================================================
# 正文活跃者（Active Actors · 2026-09-16 双轨在场）
# ============================================================

class Ent:
    def __init__(self, id, name, entity_type="character", aliases=None, visibility="public"):
        self.id = id
        self.name = name
        self.entity_type = entity_type
        self.aliases = aliases or []
        self.visibility = visibility


def test_actor_speaker_and_action_qualify():
    """明姐说了四段话+端肉（无任何 move 事件）→ 无条件入镜（对白/动作）。"""
    ents = [Ent("e-lin", "林尘"), Ent("e-ming", "明姐")]
    text = (
        "林尘推门进屋。明姐端来一碗肉。"
        "“快吃。”明姐说。林尘低头扒饭。明姐又添了半勺汤。"
    )
    actors = extract_active_actors(text, ents)
    names = {a["name"] for a in actors}
    assert names == {"林尘", "明姐"}
    by_name = {a["name"]: a for a in actors}
    assert by_name["明姐"]["via"] in ("对白", "动作", "交互", "在场")


def test_actor_recall_mention_excluded():
    """想起远方的老张（纯回忆提及）→ 不入镜；同窗内老张无任何正向姿态。"""
    ents = [Ent("e-lin", "林尘"), Ent("e-zhang", "老张")]
    text = "林尘坐在桌边。他忽然想起了远方的老张，不知道他现在怎么样。"
    actors = extract_active_actors(text, ents)
    assert {a["name"] for a in actors} == {"林尘"}  # 老张被闪回句豁免


def test_actor_bare_mention_not_enough():
    """纯位置陈述（老张在上海）无对白/交互/动作且仅出现一次 → 不入镜。"""
    ents = [Ent("e-lin", "林尘"), Ent("e-zhang", "老张")]
    text = "林尘端起碗。据说老张在千里之外的上海。"
    actors = extract_active_actors(text, ents)
    assert {a["name"] for a in actors} == {"林尘"}


def test_actor_high_frequency_with_dialogue_counts():
    """对白语境高频出现（≥2 次）→ 以「在场」入镜（泛对话参与者）。"""
    ents = [Ent("e-lin", "林尘"), Ent("e-ming", "明姐")]
    text = "“明姐，尝尝这个。”林尘把碗递过去。明姐笑了笑没接。明姐看着窗外。"
    actors = extract_active_actors(text, ents)
    names = {a["name"] for a in actors}
    assert names == {"林尘", "明姐"}


def test_actor_alias_maps_to_display_name_and_filters():
    """别名（老周师傅）命中归正名（周砚）；非角色类型与私有实体不参评。"""
    ents = [
        Ent("e-zhou", "周砚", aliases=["老周师傅"]),
        Ent("e-sword", "青锋", entity_type="asset"),
        Ent("e-boss", "幕后主使", visibility="private"),
    ]
    text = "老周师傅递过茶。青锋躺在匣子里。幕后主使在京城。"
    actors = extract_active_actors(text, ents)
    assert {a["name"] for a in actors} == {"周砚"}


def test_actor_window_truncated_to_tail():
    """扫描窗=尾部 500 字：窗外更早的说话不计（与 dock 段级窗口同口径）。"""
    ents = [Ent("e-old", "王屠户"), Ent("e-lin", "林尘")]
    text = "王屠户说今天收摊早。" + "铺垫。" * 300 + "林尘端起碗。"
    actors = extract_active_actors(text, ents)
    assert {a["name"] for a in actors} == {"林尘"}


# ============================================================
# 双轨身份同构（2026-09-17 解耦批）
# ============================================================

def test_known_name_terms_flattens_roles_only():
    """名册词表=正名+别名展平；非角色/私有实体不入词表（两层共用此单一来源）。"""
    ents = [
        Ent("e-zhou", "周砚", aliases=["老周师傅"]),
        Ent("e-sword", "青锋", entity_type="asset", aliases=["小青"]),
        Ent("e-boss", "幕后主使", visibility="private"),
    ]
    assert known_name_terms(ents) == ["周砚", "老周师傅"]


def test_extract_active_actors_full_chapter_mode():
    """window_chars=None 全章模式：章首的戏份不因尾部铺垫被截掉（宏观名册用）。"""
    ents = [Ent("e-wang", "王大爷"), Ent("e-lin", "林尘")]
    text = "王大爷递过旱烟。" + "铺垫。" * 400 + "林尘端起碗。"
    tail_only = extract_active_actors(text, ents)  # 默认 500 字窗只见林尘
    assert {a["name"] for a in tail_only} == {"林尘"}
    full = extract_active_actors(text, ents, window_chars=None, max_actors=12)
    assert {a["name"] for a in full} == {"王大爷", "林尘"}


def test_dedupe_guest_names_drops_jieba_artifacts():
    """分词伪影包含去重：「明姐端」（明姐+端来的 nr 伪影）被真名包含 → 出局；
    完全不同的名字互不误伤。"""
    assert dedupe_guest_names(["明姐", "明姐端"]) == ["明姐"]
    assert dedupe_guest_names(["明姐端", "明姐"]) == ["明姐"]
    assert dedupe_guest_names(["明姐", "王叔"]) == ["明姐", "王叔"]
    assert dedupe_guest_names([]) == []
