# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 矛盾词对检测单测（2026-08-29「不知所云」重写）
"""旧 _has_contradiction 裸子串查单字对（活/死、有/无、左手/右手、年轻/老）
——「生活」×「死寂」、「没有」×「毫无」、「老周」×「年轻」全都成对命中，
矛盾卡遍地误报且作者看不出矛盾在哪（2026-08-29 实测事故）。

新纪律（_find_contradiction）：
1. 只留死活对（活着×已死/死了/阵亡/牺牲）——语义无歧义、价值最高；
2. ≥2 字 + 分词 token 边界匹配（连续 token 拼接恰为该词），杜绝嵌词误报；
3. 返回 (设定侧词, 正文侧词) 带方向——卡片文案「正文写X，设定是Y」。

运行：python -m pytest backend/services/adaptive/test_contradiction_pairs.py -v
"""

from backend.services.adaptive.components.sediment import (
    _find_contradiction,
    _term_hit,
    _token_list,
)


# ============================================================
# 1. 旧误报全部退役（「不知所云」事故现场级用例）
# ============================================================

def test_old_single_char_false_positives_gone():
    """单字对（活/死、有/无）曾把无关词判成矛盾——全部不再命中。"""
    assert _find_contradiction("生活简朴，靠捡废料为生", "废料场一片死寂") is None
    assert _find_contradiction("他没有家人", "毫无牵挂地干活") is None
    assert _find_contradiction("老周是工头", "林尘还年轻") is None


def test_left_right_hand_pair_retired():
    """左手/右手对退役：语义本就是反的（设定左手残疾+正文用右手=一致）。"""
    assert _find_contradiction("左手残疾", "右手攥紧扳手") is None


def test_embedded_word_no_hit():
    """嵌词不算命中：token 边界判据（「死死地」不含「死了」）。"""
    assert _find_contradiction("已死于矿难", "他死死地盯着传送带") is None


# ============================================================
# 2. 真矛盾命中 + 方向正确
# ============================================================

def test_dead_setting_vs_alive_action():
    """设定已死 × 正文活着行动——最高价值死活矛盾，方向正确。"""
    pair = _find_contradiction("三年前已死于矿难", "他活着走出仓库")
    assert pair == ("已死", "活着")   # (设定侧, 正文侧)


def test_reverse_direction():
    """反向：设定写着活着 × 正文写死了。"""
    pair = _find_contradiction("至今活着，隐居北岸", "有人说他死了")
    assert pair == ("活着", "死了")


def test_martyr_variant():
    pair = _find_contradiction("阵亡于南线战役", "他活着回到了基地")
    assert pair == ("阵亡", "活着")


# ============================================================
# 3. 底层判据：token 边界
# ============================================================

def test_term_hit_token_boundary():
    toks = _token_list("他活着走出仓库")
    assert toks is not None
    assert _term_hit("活着", "他活着走出仓库", toks) is True
    # 「生活」是独立词——「活」不该以边界形态出现
    toks2 = _token_list("生活简朴")
    assert _term_hit("活着", "生活简朴", toks2) is False


def test_term_hit_fallback_substring_without_jieba():
    """jieba 不可用（tokens=None）退回子串——柔性红线（≥2 字误报面已小）。"""
    assert _term_hit("活着", "他还活着", None) is True
    assert _term_hit("活着", "生活所迫", None) is False


def test_detect_conflicts_carries_pair():
    """_detect_conflicts 产出的 conflict 带 pair 字段（canon_watch 文案消费）。"""
    from backend.services.adaptive.components.sediment import _detect_conflicts

    class _Char:
        def __init__(self, name, static):
            self.name = name
            self.static_prompt = static

    class _Ent:
        def __init__(self, name, static):
            self.character = _Char(name, static)

    class _Bundle:
        entities = [_Ent("林尘", "三年前已死于矿难")]
        def hard_constraints(self):
            return {}
        def soft_constraints(self):
            return {}
        def nutrients(self):
            return {}

    facts = {"new_entities": [{"name": "林尘", "description": "他活着走出仓库"}]}
    conflicts = _detect_conflicts(facts, _Bundle())
    assert len(conflicts) == 1
    assert conflicts[0]["pair"] == ["已死", "活着"]
    assert conflicts[0]["type"] == "character_contradiction"


def test_detect_conflicts_clean_desc_no_conflict():
    """正常描述不产矛盾（旧实现这里全是误报）。"""
    from backend.services.adaptive.components.sediment import _detect_conflicts

    class _Char:
        def __init__(self, name, static):
            self.name = name
            self.static_prompt = static

    class _Ent:
        def __init__(self, name, static):
            self.character = _Char(name, static)

    class _Bundle:
        entities = [_Ent("林尘", "统合局基地的机甲废料分拣工，喜欢读书")]
        def hard_constraints(self):
            return {}
        def soft_constraints(self):
            return {}
        def nutrients(self):
            return {}

    facts = {"new_entities": [{"name": "林尘", "description": "在传送带边分拣散热片，把书塞进口袋"}]}
    assert _detect_conflicts(facts, _Bundle()) == []
