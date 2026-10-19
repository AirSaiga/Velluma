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
场景判定 + 检索场景加成单测（P5 C2，docs/reports/foundation-hardening.md §5.2）。

覆盖三块（纯算法/LLM-mock——不连 LLM/DB，同项目单测惯例）：
1. 判定口径：detect_scene_type 阈值边界（0.35 上/下/恰等）、空文本兜底
   ——对话占比统计与 fingerprint「同一把尺子」同源；
2. 兜底流加成：order_samples_for_fallback 同型同档内提前、档位键
   （收藏/新近）优先级不被加成破坏、异型不消失；
3. retrieve_author_samples 全链（monkeypatch 假 repo + 假 embedding）：
   向量流 +0.1 加成与超额取候选、兜底流透传、
   **零变化锁**——hint 为 None/"general" 时输出与旧逻辑逐一致。

运行：python -m pytest backend/services/style/test_scene_hint.py -v
"""

import asyncio
from types import SimpleNamespace

from backend.services.style import retrieval as retrieval_mod
from backend.services.style.fingerprint import (
    compute_text_fingerprint,
    count_dialogue_chars,
    count_words,
)
from backend.services.style.retrieval import (
    SCENE_HINT_BONUS,
    order_samples_for_fallback,
    retrieve_author_samples,
)
from backend.services.style.scene_hint import (
    _ACTION_VERB_RE,
    ACTION_STRONG_DENSITY_PER_1K,
    DIALOGUE_RATIO_THRESHOLD,
    SCENE_ACTION,
    SCENE_DIALOGUE,
    SCENE_GENERAL,
    SCENE_LYRICAL,
    SCENE_HINT_TAIL_CHARS,
    detect_scene_hint,
    detect_scene_type,
    resolve_scene_type,
)


# ============================================================
# 1. 判定口径（阈值边界 + 空文本兜底）
# ============================================================

class TestDetectSceneType:
    def test_dialogue_heavy_text(self):
        # 全引号文本（无空白）→ 对话占比 1.0
        assert detect_scene_type("“走？”“走。”" * 40) == SCENE_DIALOGUE

    def test_narrative_text(self):
        text = "他沿着江岸走了很远，看着潮水一层一层地漫上来，又一层一层地退下去。" * 8
        assert detect_scene_type(text) == SCENE_GENERAL

    def test_boundary_exactly_at_threshold_is_general(self):
        # 7 对话字符（含引号）/ 20 全文字 = 0.35 恰等阈值——严格大于才判 dialogue
        text = "“abcde”" + "f" * 13
        assert count_dialogue_chars(text) / count_words(text) == DIALOGUE_RATIO_THRESHOLD
        assert detect_scene_type(text) == SCENE_GENERAL

    def test_boundary_just_above_threshold_is_dialogue(self):
        # 7 / 19 ≈ 0.368 > 0.35
        text = "“abcde”" + "f" * 12
        assert detect_scene_type(text) == SCENE_DIALOGUE

    def test_ratio_same_ruler_as_fingerprint(self):
        # 同一把尺子：detect 用的就是 compute_text_fingerprint 的 dialogue_ratio
        text = "“你走吧。”他说。\n她在灯下没有抬头。"
        assert (
            compute_text_fingerprint(text, light=True)["dialogue_ratio"]
            == round(count_dialogue_chars(text) / max(1, count_words(text)), 3)
        )

    def test_empty_and_blank_fallback_general(self):
        assert detect_scene_type(None) == SCENE_GENERAL
        assert detect_scene_type("") == SCENE_GENERAL
        assert detect_scene_type("   \n\t ") == SCENE_GENERAL

    def test_tail_window_constant(self):
        # 接线契约：stitch 装配处按尾 300 字切片（设计稿 §5.2 拍板值）
        assert SCENE_HINT_TAIL_CHARS == 300


# ============================================================
# 1b. v2 扩档：action / lyrical 正反例 + 边界回落
# ============================================================

# 动作戏正例（结构仿《弦上灰》第 9 章夺机戏/第 4 章仓库破门——动词风暴
# + 短促破折节奏）
_ACTION_TEXT = (
    "他猛扑过去！铁门被撞开，碎片四溅。\n"
    "陈朗拽住李岩的手腕往侧面一甩，两人一起摔进管道。吼声从身后追来。\n"
    "他咬牙爬起，抓住锈蚀的梯子向上攀。追兵逼近。他跳下，翻滚，闪避砸落的铁架，逃。"
)
# 混合了对白但仍是动作戏（dr ≤ 0.35，动作+节奏双信号仍在）
_ACTION_TEXT_WITH_TALK = (
    "“快！冲出去！”陈朗吼道，一把拽住被震飞的李岩。\n"
    "管道猛地拱起又狠狠下坠！他护住小雅滚进死角，头顶水珠如暴雨砸落。\n"
    "他踹开锈死的舱门，拽着人钻出去，逃进黑暗。追兵的脚步声近了。"
)
# 动词密集但节奏平缓的长句叙述 → 不判 action（佐证信号缺失）
_ACTION_NEGATIVE = (
    "他缓慢地穿过那条堆满废弃管道的长长的走廊，回忆着曾经在这里发生过的许多往事，"
    "那些漫长的岁月疲惫而悠远，像一场没有尽头的迁徙，最终都消失在时间的深处。"
) * 2
# 抒情正例（农场晨光式：高质感描写 + 零对白 + 零动作）
_LYRICAL_TEXT = (
    "晨光准时洒下，柔和的淡金色光线漫过生活区走廊的木地板。\n"
    "远处的麦田在风里起伏，像一片缓慢呼吸的海。她站在门口，恍惚间想起樱花落满肩头的那个下午，"
    "温柔而苍凉的记忆泛起，心底有什么东西悄悄沉淀下去，如同雾气凝成的露水。"
) * 2
# 高质感但动词密集（追逐段）→ 不判 lyrical
_LYRICAL_NEGATIVE_CHASE = (
    "然而他们刚跑出百米，身后就传来了急促而沉重的脚步声！手电光柱划破黑暗，"
    "冰冷地扫过前方潮湿斑驳的墙壁！他拽紧她的手腕扑进巷口，追兵的吼叫撕裂夜色！"
) * 2


class TestDetectSceneTypeV2:
    def test_action_positive(self):
        assert detect_scene_type(_ACTION_TEXT) == SCENE_ACTION

    def test_action_positive_with_some_dialogue(self):
        # 对白占比未过 dialogue 阈值的动作戏仍判 action
        assert detect_scene_type(_ACTION_TEXT_WITH_TALK) == SCENE_ACTION

    def test_action_negative_flat_rhythm(self):
        # 保守优先：动词有但节奏平缓（短句率/CV 均不达标、密度未过强线）→ general
        assert detect_scene_type(_ACTION_NEGATIVE) == SCENE_GENERAL

    def test_action_not_dialogue_regression(self):
        # dialogue 分支仍最先判走：对白占比超阈值时哪怕动词密集也是 dialogue
        assert detect_scene_type("“快冲！拽住他！”“吼什么，追不上了！”" * 10) == SCENE_DIALOGUE

    def test_lyrical_positive(self):
        assert detect_scene_type(_LYRICAL_TEXT) == SCENE_LYRICAL

    def test_lyrical_negative_chase(self):
        # 质感高但动词密集（追逐）→ 不判 lyrical（动作门拦截；该文本本身
        # 双信号确凿，判 action 是正确去向——错判 lyrical 才是红线）
        assert detect_scene_type(_LYRICAL_NEGATIVE_CHASE) == SCENE_ACTION

    def test_plain_narrative_stays_general(self):
        # 普通叙述：各信号都不强 → general（保守兜底）
        text = "他把工具收进背包，看了一眼时间，起身往食堂走。今天的菜和昨天一样。" * 4
        assert detect_scene_type(text) == SCENE_GENERAL

    def test_short_text_fallback_general(self):
        # 极短文本：句数不足统计无意义 → general（不炸不误判）
        assert detect_scene_type("他跑了。") == SCENE_GENERAL


class TestResolveSceneType:
    def test_explicit_valid_passes_through(self):
        for v in ("dialogue", "action", "lyrical", "suspense", "general"):
            assert resolve_scene_type(v, _ACTION_TEXT) == v

    def test_explicit_overrides_autodetect(self):
        # 显式 action 优先于自动判定为 lyrical/general 的文本
        assert resolve_scene_type("action", _LYRICAL_TEXT) == "action"

    def test_invalid_falls_back_to_auto(self):
        assert resolve_scene_type("battle", _ACTION_TEXT) == SCENE_ACTION
        assert resolve_scene_type("DIALOGUE", _ACTION_TEXT) == SCENE_ACTION  # 大小写敏感=非法

    def test_empty_and_none_fall_back_to_auto(self):
        assert resolve_scene_type(None, _ACTION_TEXT) == SCENE_ACTION
        assert resolve_scene_type("", _ACTION_TEXT) == SCENE_ACTION
        assert resolve_scene_type(None, None) == SCENE_GENERAL


# ============================================================
# 1c. v3 两段式（fragment 优先）：断点回归 + 零变化锁
#     材料出处：logs/style_ab/material_v2.json（《弦上灰》真实断点，
#     复现脚本 logs/style_ab/repro_scene_hint.py）——原文内联防 logs
#     目录不入库后测试悬空
# ============================================================

# action 断点：描写性机库尾巴 + 动作 fragment（动词密度 71.4/千字，远过
# 强信号豁免线 25）——旧通路拼接后被尾巴稀释到 15.4 误判 general
_ACTION_BP_TAIL = (
    "在李岩心口。\n"
    "转过最后一道弯，陈朗突然刹住脚步。他抹了把脸上的汗液，食指快速在密码锁上跳动，"
    "金属门“咔嗒”弹开条缝时，李岩听见自己剧烈的心跳声——门后是条狭窄的逃生通道，"
    "尽头那道足有两人高的合金门泛着冷光，门缝里漏出刺目的白光。“那里就是C机库！”"
    "陈朗喘着气，“这儿用的是特殊合金，比外头结实点”\n"
    "合金门缓缓开启的瞬间，强光如刀割开黑暗。李岩下意识地眯起眼，几架外形如蜂鸟般灵动、"
    "流畅的飞行器正静静停在泊位上，银灰色的机身映着应急灯的红光，引擎已经预热启动，"
    "低沉的轰鸣震得空气发颤，尾焰在地面投下跳动的蓝影。\n"
    "“这边！”陈朗的声音几乎被引擎声淹没，他一边径直冲向最里侧的3号“蜂鸟”，一边向李岩招手。"
)
_ACTION_BP_FRAG = "李岩抱着小雅冲进舱门，耳膜被引擎陡然拔高的尖啸刺得生疼。"

# dialogue 断点：对白尾巴 + 无引号短 fragment（13 字，单独判 general）——
# fragment 不抢权，回落拼接判回 dialogue
_DIALOGUE_BP_TAIL = (
    "门。”陈朗的声音没有起伏，“焚风蛾，你在上面见识过了。它翼展千米，从平流层俯冲，"
    "洒下的幽蓝磷火，触之即燃，能将最坚固的合金瞬间烧蚀成虚无——那是物质层面的湮灭。"
    "它留下的‘湮灭区’，像大地上的丑陋伤疤，残留着极不稳定的能量，随时可能引发二次爆发。”\n"
    "昏黄的光晕下，李岩的脸色愈发苍白。\n"
    "“地上的世界早就完了。”陈朗的语气带着疲惫，“除了悬浮城庇护所覆盖的区域，其他地方…"
    "是炼狱。巨兽游荡后留下的污染…会毁灭一切，第五区，这个满是灰尘和铁锈味的地方，"
    "已经是联合机构施舍的‘安全区’了。至于我们脚下这些更深处、更老旧的地下迷宫…”"
    "他顿了顿，声音里带着嘲讽，“不知道什么时候就会彻底消失，被那些巨兽们...”"
)
_DIALOGUE_BP_FRAG = "李岩的心沉入了冰冷的深渊。"

# lyrical 断点（本轮接受 general）：封闭质感词表口径下短句判 lyrical 的
# 误判风险高——两段式不应对它产出 lyrical 强信号，也不应误判成其他档
_LYRICAL_BP_TAIL = (
    "个有好多好多花和小鸟的地方。”\n"
    "小雅的眼睛一下子亮了起来，像落入了星星：“真的吗？还有小鸟？”\n"
    "“当然是真的，”李岩用力点头，拇指轻轻摩挲着女儿的手背“爸爸答应你。所以小雅要好好吃饭，"
    "好好听话哦，我们拉钩？”他伸出小指。\n"
    "小雅立刻伸出自己小小的、还有点肉乎乎的小指，勾住父亲粗粝的手指，用力晃了晃："
    "“拉钩！我要和爸爸一起去看小花和小鸟！”\n"
    "看着女儿脸上充满希望的笑容，李岩也笑了。尽管内心深处那份沉甸甸的忧虑丝毫未减，"
    "但此刻，女儿的笑容就是他最好的安慰。他愿意用尽全力，去守护这份纯净的光亮，"
    "哪怕前路荆棘密布。\n"
    "下午，李岩习惯地来到下层的生态农场，在这里，那份忧虑与纷乱的思绪，"
    "才能稍稍得到一片宁静。"
)
_LYRICAL_BP_FRAG = "这里还是一如既往地静谧，只有自动喷灌系统洒下的细密水雾发出沙沙轻响。"


class TestDetectSceneHintTwoStage:
    def test_action_breakpoint_fragment_wins(self):
        # 回归（material_v2 action 断点）：描写性尾巴 + 动作 fragment →
        # action。旧通路（拼接判定）此例判 general（密度稀释到 15.4）
        assert detect_scene_type(_ACTION_BP_TAIL + _ACTION_BP_FRAG) == SCENE_GENERAL  # 旧行为佐证
        assert detect_scene_hint(_ACTION_BP_TAIL, _ACTION_BP_FRAG) == SCENE_ACTION

    def test_dialogue_breakpoint_fragment_defers_to_concat(self):
        # 回归（material_v2 dialogue 断点）：对白尾巴 + 无引号短 fragment →
        # dialogue。fragment 单独判 general（无强信号不抢权），回落拼接判定
        assert detect_scene_type(_DIALOGUE_BP_FRAG) == SCENE_GENERAL  # fragment 单独不判
        assert detect_scene_hint(_DIALOGUE_BP_TAIL, _DIALOGUE_BP_FRAG) == SCENE_DIALOGUE

    def test_lyrical_breakpoint_accepted_general(self):
        # 本轮拍板：lyrical 断点三种输入都判 general（封闭质感词表口径），
        # 两段式不得误判出其他档
        assert detect_scene_hint(_LYRICAL_BP_TAIL, _LYRICAL_BP_FRAG) == SCENE_GENERAL

    def test_empty_fragment_byte_identical_to_v2(self):
        # 零变化锁：fragment 为空时与旧通路（纯尾窗判定）逐一一致
        for text in (_ACTION_TEXT, _LYRICAL_TEXT, _ACTION_BP_TAIL, None, "", "   "):
            assert detect_scene_hint(text, "") == detect_scene_type(text)
            assert detect_scene_hint(text, None) == detect_scene_type(text)
            assert detect_scene_hint(text, "   ") == detect_scene_type(text)  # 空白=空

    def test_fragment_dialogue_strong_signal(self):
        # fragment 强信号-对白：引号内文字占比过线即采信（不受窗长稀释）
        frag = "“快走！别管我！”"
        assert detect_scene_hint("他望着远处的山，想着一些无关紧要的事情。", frag) == SCENE_DIALOGUE

    def test_fragment_action_requires_strong_line_not_plain(self):
        # fragment 强信号-动作用豁免线 25 而非普线 18：密度 18~25 之间的
        # fragment 不单独定档（短窗噪声大，回落拼接判定）
        frag = "他快步冲上楼梯，扶着栏杆喘了口气，然后继续向着天台的方向走去，脚步声在空荡的楼道里回响。"  # 密度 22.7，落在普线与强线之间
        fp = compute_text_fingerprint(frag, light=True)
        density = len(_ACTION_VERB_RE.findall(frag)) * 1000.0 / max(1, fp.get("word_count") or 0)
        assert ACTION_STRONG_DENSITY_PER_1K > density >= 18.0  # 前置：确在两线之间
        # 尾窗也是普通叙述 → 无任何强信号，兜底 general
        assert detect_scene_hint("他沿着江岸走了很远，看着潮水一层层地漫上来。", frag) == SCENE_GENERAL

    def test_fragment_lyrical_not_open_this_round(self):
        # fragment 强信号-lyrical 本轮不开放：高质感短 fragment 回落拼接
        # 判定（拼接后密度被稀释 → general），不得由 fragment 单独判 lyrical
        assert detect_scene_hint("他平静地坐着，什么也没说。", "晨光柔和，露水清凉如雾。") == SCENE_GENERAL


class TestResolveSceneTypeFragment:
    def test_explicit_beats_fragment_strong_signal(self):
        # 优先级链：显式 scene_type > fragment 强信号
        assert resolve_scene_type("lyrical", _ACTION_BP_TAIL, _ACTION_BP_FRAG) == SCENE_LYRICAL
        assert resolve_scene_type("general", _ACTION_BP_TAIL, _ACTION_BP_FRAG) == SCENE_GENERAL

    def test_auto_uses_two_stage(self):
        assert resolve_scene_type(None, _ACTION_BP_TAIL, _ACTION_BP_FRAG) == SCENE_ACTION
        assert resolve_scene_type(None, _DIALOGUE_BP_TAIL, _DIALOGUE_BP_FRAG) == SCENE_DIALOGUE

    def test_no_fragment_identical_to_v2(self):
        # 旧签名兼容：不传 fragment 时与 v2 行为逐一一致（既有调用方/测试零破坏）
        assert resolve_scene_type(None, _ACTION_TEXT) == SCENE_ACTION
        assert resolve_scene_type(None, _LYRICAL_TEXT) == SCENE_LYRICAL
        assert resolve_scene_type("", _ACTION_TEXT) == SCENE_ACTION


# ============================================================
# 2. 兜底流加成（order_samples_for_fallback）
# ============================================================

class _Sample:
    def __init__(self, name, scene_type="general", favorite=False, era="recent", source="manual"):
        self.name = name
        self.id = name  # P5 meta 契约：id 用 name 占位
        self.content = name
        self.scene_type = scene_type
        self.favorite = favorite
        self.era = era
        self.source = source


def _names(samples):
    return [s.name for s in samples]


class TestFallbackSceneBoost:
    def test_same_tier_dialogue_moves_ahead(self):
        # 池序模拟 list_by_book 新→旧；同档（非收藏近期）内 dialogue 提前，
        # 档内既有次序不破坏（g1 仍在 g2 前）
        pool = [_Sample("g1"), _Sample("d1", scene_type="dialogue"), _Sample("g2"),
                _Sample("e1", scene_type="dialogue", era="early")]
        assert _names(order_samples_for_fallback(pool, scene_hint="dialogue")) == [
            "d1", "g1", "g2", "e1",
        ]

    def test_tier_keys_beat_scene_boost(self):
        # 档位键优先级不变：收藏 > 新近/早期 > 场景加成
        pool = [_Sample("recent_dialogue", scene_type="dialogue"),
                _Sample("fav_general", favorite=True),
                _Sample("early_dialogue", scene_type="dialogue", era="early"),
                _Sample("recent_general")]
        assert _names(order_samples_for_fallback(pool, scene_hint="dialogue")) == [
            "fav_general", "recent_dialogue", "recent_general", "early_dialogue",
        ]

    def test_mismatched_samples_not_dropped(self):
        # 软加成不是过滤：异型样本仍在结果里，只是让位
        pool = [_Sample("d1", scene_type="dialogue"), _Sample("g1"), _Sample("g2")]
        ordered = order_samples_for_fallback(pool, scene_hint="dialogue")
        assert set(_names(ordered)) == {"d1", "g1", "g2"}

    def test_zero_change_without_hint_and_with_general(self):
        """零变化锁：None / "general" 与旧逻辑（(favorite, era) 键）排序逐一致。"""
        pool = [_Sample("g1"), _Sample("d1", scene_type="dialogue"),
                _Sample("fav", favorite=True), _Sample("e1", era="early"),
                _Sample("fav_early_d", favorite=True, era="early", scene_type="dialogue")]
        # 旧口径显式重算（同 sorted 稳定语义）
        old_order = sorted(
            pool,
            key=lambda s: (0 if s.favorite else 1, 0 if s.era != "early" else 1),
        )
        assert _names(order_samples_for_fallback(pool)) == _names(old_order)
        assert _names(order_samples_for_fallback(pool, scene_hint=None)) == _names(old_order)
        assert _names(order_samples_for_fallback(pool, scene_hint=SCENE_GENERAL)) == _names(old_order)

    def test_missing_scene_type_attr_no_crash(self):
        # 旧数据/假件无 scene_type 属性 → 视为不命中（不炸）
        s = type("S", (), {"name": "旧样本", "content": "旧样本", "favorite": False, "era": "recent"})()
        assert _names(order_samples_for_fallback([s], scene_hint="dialogue")) == ["旧样本"]


# ============================================================
# 3. retrieve_author_samples 全链（假 repo + 假 embedding）
# ============================================================

class _FakeFallbackRepo:
    """兜底流假 repo：list_by_book 按注入序原样返回（模拟新→旧）。"""

    def __init__(self, samples):
        self._samples = samples

    async def list_by_book(self, book_id, scene_type=None):
        return list(self._samples)


class _FakeVectorRepo:
    """向量流假 repo：返回按 distance 升序的预制命中，记录 limit 供断言。"""

    def __init__(self, hits):
        self._hits = hits
        self.limits = []

    async def search_by_style(self, embedding, book_id, scene_type=None, limit=3):
        self.limits.append(limit)
        return list(self._hits[:limit])


def _disable_embedding(monkeypatch):
    monkeypatch.setattr(retrieval_mod, "is_embedding_configured", lambda: False)


def _neutral_prior(monkeypatch):
    """P5 采纳先验中性化：检索排序对拍需要确定性——真实 collab 事件会引入
    非 1.0 因子（先验行为见 test_sample_prior.py 专属单测）。"""
    monkeypatch.setattr(retrieval_mod, "sample_prior_factor", lambda book_id, sid: 1.0)


def _use_repo(monkeypatch, repo):
    """把假 repo 注入 retrieve_author_samples 的构造点（db 传 None 即可）。
    同时中性化 P5 采纳先验（排序对拍的确定性）。"""
    monkeypatch.setattr(retrieval_mod, "AuthorSampleRepository", lambda db: repo)
    _neutral_prior(monkeypatch)


def _enable_embedding(monkeypatch, repo):
    monkeypatch.setattr(retrieval_mod, "is_embedding_configured", lambda: True)

    async def _fake_embed(text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(retrieval_mod, "get_embedding", _fake_embed)
    _use_repo(monkeypatch, repo)


class TestRetrieveFallbackFlow:
    def test_dialogue_hint_promotes_same_type_within_tier(self, monkeypatch):
        # 新→旧池 [g1, d1, g2]：hint 下 d1 提前进前 k；无 hint 时 d1 在 k 外
        repo = _FakeFallbackRepo([_Sample("g1"), _Sample("d1", scene_type="dialogue"), _Sample("g2")])
        _disable_embedding(monkeypatch)
        _use_repo(monkeypatch, repo)
        with_hint = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        # 内容即 name，直接对拍
        assert with_hint == ["d1", "g1"]

    def test_no_hint_zero_change(self, monkeypatch):
        repo = _FakeFallbackRepo([_Sample("g1"), _Sample("d1", scene_type="dialogue"), _Sample("g2")])
        _disable_embedding(monkeypatch)
        _use_repo(monkeypatch, repo)
        no_hint = asyncio.run(retrieve_author_samples(None, "bk-1", "query", k=2))
        general = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint=SCENE_GENERAL,
        ))
        assert no_hint == ["g1", "d1"]      # 旧口径：池序（均为近期非收藏）取前 k
        assert general == no_hint           # general 档 = 无 hint（零变化）


class TestRetrieveVectorFlow:
    def _hits(self):
        # SQL 语义：按 cosine_distance 升序返回
        return [
            (SimpleNamespace(content="genA", scene_type="general"), 0.18),
            (SimpleNamespace(content="genC", scene_type="general"), 0.22),
            (SimpleNamespace(content="diaB", scene_type="dialogue"), 0.28),
            (SimpleNamespace(content="diaD", scene_type="dialogue"), 0.50),
            (SimpleNamespace(content="diaE", scene_type="dialogue"), 0.90),
        ]

    def test_no_hint_keeps_sql_topk(self, monkeypatch):
        repo = _FakeVectorRepo(self._hits())
        _enable_embedding(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(None, "bk-1", "query", k=2))
        assert out == ["genA", "genC"]       # 旧口径：limit=k 原序
        assert repo.limits == [2]            # 不超额取候选

    def test_dialogue_hint_boosts_into_topk(self, monkeypatch):
        repo = _FakeVectorRepo(self._hits())
        _enable_embedding(monkeypatch, repo)
        out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        # diaB 0.28-0.1=0.18 与 genA 0.18 平手——稳定排序保 SQL 原序 genA 在前；
        # diaB 顶掉 genC 进前 k；异型 genA 不消失（软加成非过滤）
        assert out == ["genA", "diaB"]
        assert repo.limits == [10]           # 超额取候选 max(k*5, k)

    def test_general_hint_identical_to_none(self, monkeypatch):
        hits = self._hits()
        repo_none = _FakeVectorRepo(hits)
        _enable_embedding(monkeypatch, repo_none)
        none_out = asyncio.run(retrieve_author_samples(None, "bk-1", "query", k=2))
        repo_general = _FakeVectorRepo(hits)
        _enable_embedding(monkeypatch, repo_general)
        general_out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint=SCENE_GENERAL,
        ))
        assert none_out == general_out == ["genA", "genC"]
        assert repo_none.limits == repo_general.limits == [2]

    def test_bonus_magnitude_semantics(self, monkeypatch):
        # 加成恰为 0.1：distance 差 < 0.1 时同型反超；差 > 0.1 时不反超
        close = _FakeVectorRepo([
            (SimpleNamespace(content="genA", scene_type="general"), 0.20),
            (SimpleNamespace(content="diaB", scene_type="dialogue"), 0.20 + SCENE_HINT_BONUS - 0.05),
        ])
        far = _FakeVectorRepo([
            (SimpleNamespace(content="genA", scene_type="general"), 0.20),
            (SimpleNamespace(content="diaB", scene_type="dialogue"), 0.20 + SCENE_HINT_BONUS + 0.10),
        ])
        _enable_embedding(monkeypatch, close)
        close_out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        _enable_embedding(monkeypatch, far)
        far_out = asyncio.run(retrieve_author_samples(
            None, "bk-1", "query", k=2, scene_hint="dialogue",
        ))
        assert close_out == ["diaB", "genA"]
        assert far_out == ["genA", "diaB"]
