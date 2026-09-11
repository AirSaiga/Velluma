# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""2026-09-03 节拍供给分级对拍：卷首致辞过滤 + 抢拍代码闸 + 意图块目的地措辞。

事故链（trace 实证）：大纲卷首致辞/就近节拍原文 verbatim 进 stitch 意图块
→ 模型把「几步之后的节拍」当现在该写的场面 → 3/3 幽灵落地即消费节拍
（「被工头打断」）。修复三件套：
① outline_nearby 过滤元信息行（引语/《》/指示短行）——供给面；
② 意图块重框为「几步之后的目的地」（现在不写它本身）——措辞面；
③ ghost_guard 第七检 beat_rush（双 4 字窗+正文尾排除）进返修环——闸门面。

运行：.venv/Scripts/python.exe -m pytest backend/services/validation/test_beat_rush_gate.py -v
"""

from types import SimpleNamespace

from backend.services.adaptive.outline_nearby import (
    outline_line_is_meta,
    outline_nearby,
)
from backend.services.constraints import registry as reg
from backend.services.prompts.adaptive_prompts import build_continue_prompt
from backend.services.validation.ghost_guard import (
    check_ghost_text,
    find_beat_rush_hits,
    repair_eligible,
)


# ============================================================
# ① 元信息行过滤（供给面）
# ============================================================

class TestOutlineLineIsMeta:
    def test_quote_wrapped_line_is_meta(self):
        assert outline_line_is_meta("“一个人的力量是微薄的，世界不会因你而逆转。”") is True
        assert outline_line_is_meta("「名言原文」") is True

    def test_work_reference_line_is_meta(self):
        assert outline_line_is_meta("以罗曼·罗兰的巨著《约翰·克利斯朵夫》") is True

    def test_short_directive_line_is_meta(self):
        assert outline_line_is_meta("名言开篇") is True
        assert outline_line_is_meta("") is True
        assert outline_line_is_meta("   ") is True

    def test_plot_line_is_not_meta(self):
        assert outline_line_is_meta("林尘喜欢读书，干着活的期间想到昨天晚上读到的内容") is False
        # 行内含引号但非整行包裹——是剧情行
        assert outline_line_is_meta("工头冲进来喊「手别停」，林尘吓了一跳") is False

    def test_nearby_skips_meta_lines(self):
        outline = (
            "以罗曼·罗兰的巨著《约翰·克利斯朵夫》\n"
            "“一个人的力量是微薄的，世界的洪流不会因你而逆转。”\n"
            "名言开篇\n"
            "林尘读书发愣被工头打断\n"
            "无奈自嘲自己的处境"
        )
        got = outline_nearby(outline, "")
        assert got and "工头打断" in got[0]
        assert all("罗曼" not in b and "一个人的力量" not in b for b in got)


# ============================================================
# ② 抢拍判据（纯函数）
# ============================================================

BEAT = "不多时，基地遭到反抗组织的袭击"


class TestFindBeatRushHits:
    def test_verbatim_beat_consumption_is_hit(self):
        ghost = "他刚直起身，外面就乱了。不多时，基地遭到反抗组织的袭击，警报声撕裂了夜空。"
        hits = find_beat_rush_hits(ghost, [BEAT])
        assert len(hits) == 1
        assert hits[0]["beat"].startswith("不多时")

    def test_legit_first_step_no_hit(self):
        # 通往节拍路上的画面：与节拍零字面重合
        ghost = "他把扳手插回腰带，听见走廊尽头有人跑动，脚步声乱成一团。"
        assert find_beat_rush_hits(ghost, [BEAT]) == []

    def test_single_gram_coincidence_no_hit(self):
        # 只共用一个 4 字窗（基地遭到）不到双窗门槛
        ghost = "他忽然担心基地遭到池鱼之殃，手里的活却没敢停。"
        assert find_beat_rush_hits(ghost, [BEAT]) == []

    def test_author_already_writing_beat_is_excluded(self):
        # 作者正在亲笔写这一拍（正文尾部已含节拍措辞）→ 幽灵顺写是合法承接
        ghost = "反抗组织的袭击越来越密，他抱着头蹲了下去。"
        tail = "不多时，基地遭到反抗组织的袭击，第一发炮弹落在东墙。"
        assert find_beat_rush_hits(ghost, [BEAT], written_tail=tail) == []

    def test_empty_inputs_no_hit(self):
        assert find_beat_rush_hits("任何文本", []) == []
        assert find_beat_rush_hits("任何文本", None) == []
        assert find_beat_rush_hits("", [BEAT]) == []
        assert find_beat_rush_hits("太短了", [BEAT]) == []

    def test_span_locates_in_raw_text(self):
        # span_text 必须是原稿逐字子串（返修环切除/前端高亮的定位契约）
        ghost = "他刚直起身。不多时，基地遭到反抗组织的袭击。"
        hits = find_beat_rush_hits(ghost, [BEAT])
        assert hits and hits[0]["span"] in ghost


# ============================================================
# ③ check_ghost_text 集成 + 登记册接线
# ============================================================


class TestBeatRushGuardIntegration:
    def test_zero_change_when_beats_none(self):
        # outline_beats=None = 整检关闭（open/outline/burst 与无大纲书零变化）
        ghost = "不多时，基地遭到反抗组织的袭击，警报声撕裂了夜空。"
        assert check_ghost_text(ghost, outline_beats=None) == []

    def test_hit_produces_warning_and_event(self):
        events = []
        ghost = "他刚直起身，外面就乱了。不多时，基地遭到反抗组织的袭击，火光冲天。"
        warnings = check_ghost_text(
            ghost,
            outline_beats=[BEAT],
            on_event=lambda cid, outcome, reason, detail: events.append((cid, outcome)),
        )
        br = [w for w in warnings if w.get("kind") == "beat_rush"]
        assert len(br) == 1
        assert "抢拍" in br[0]["message"]
        assert br[0]["span_text"] in ghost
        assert ("ghost-guard-beat-rush", "hit") in events

    def test_registry_wiring_live_and_repairable(self):
        # 登记册三重门：live + repair=rewrite → repair_eligible 放行返修环
        assert reg.status_of("ghost-guard-beat-rush") == reg.STATUS_LIVE
        assert reg.repair_policy("ghost-guard-beat-rush") == reg.REPAIR_REWRITE
        assert repair_eligible({"kind": "beat_rush"}) is True

    def test_repair_prompt_line_exists(self):
        from backend.services.adaptive.stitch_gates import _VIOLATION_REPAIR_LINES

        assert "beat_rush" in _VIOLATION_REPAIR_LINES
        assert "{span}" in _VIOLATION_REPAIR_LINES["beat_rush"]


# ============================================================
# ⑤ 名单演出 shadow 检（在场名单重构，2026-09-03 第三层）
# ============================================================


class TestCastRollCall:
    def test_two_present_names_is_roll_call(self):
        events = []
        ghost = "流光站在观察台边没动，老烟在角落里咳嗽了一声，他忽然觉得屋里很挤。"
        warnings = check_ghost_text(
            ghost,
            present_names=["流光", "老烟"],
            on_event=lambda cid, outcome, reason, detail: events.append((cid, outcome)),
        )
        rc = [w for w in warnings if w.get("kind") == "cast_roll_call"]
        assert len(rc) == 1
        assert "流光" in rc[0]["message"] and "老烟" in rc[0]["message"]
        # shadow 出生：local_only 只落台账不进帧
        assert rc[0].get("local_only") is True
        assert ("ghost-guard-cast-roll-call", "hit") in events

    def test_single_present_name_no_hit(self):
        ghost = "流光站在观察台边没动，他忽然觉得屋里很挤。"
        assert check_ghost_text(ghost, present_names=["流光", "老烟"]) == []

    def test_names_in_written_tail_excluded(self):
        # 作者正文尾部已点过名 → 幽灵顺着写是连续性，不是名单演出
        ghost = "流光点了点头，老烟把烟掐了，两人都没再说话。"
        tail = "他看见流光和老烟一前一后走进来。"
        assert check_ghost_text(
            ghost, present_names=["流光", "老烟"], written_tail=tail,
        ) == []

    def test_none_present_names_check_off(self):
        ghost = "流光站在观察台边没动，老烟在角落里咳嗽了一声。"
        assert check_ghost_text(ghost, present_names=None) == []

    def test_registry_shadow_no_repair(self):
        # shadow：命中只落台账；无返修资格（计数粗代理，不动稿子）
        assert reg.status_of("ghost-guard-cast-roll-call") == reg.STATUS_SHADOW
        assert reg.repair_policy("ghost-guard-cast-roll-call") == reg.REPAIR_NONE
        assert repair_eligible({"kind": "cast_roll_call"}) is False


# ============================================================
# ④ 意图块目的地措辞 + 装配同源
# ============================================================


class TestDestinationFraming:
    def test_intent_block_reframed_as_destination(self):
        _sys, user = build_continue_prompt(
            "他放下扳手", "前文……", mode="stitch",
            chapter_intent="不多时，基地遭到反抗组织的袭击",
        )
        assert "几步之后的目的地" in user
        assert "现在不写它本身" in user
        assert "章节意图（方向参考，非强制）" not in user

    def test_intent_block_absent_when_empty(self):
        _sys, user = build_continue_prompt("他放下扳手", "前文……", mode="continue")
        assert "几步之后的目的地" not in user

    def test_context_carries_beats_for_guard(self):
        # stitch_context：请求自带意图 → outline_beats 空（闸关闭）；
        # 兜底路径 → outline_beats 与意图文本同源
        from backend.services.context.stitch_context import (
            _nearby_beats_from_outline,
            _nearby_intent_from_outline,
        )

        bundle = SimpleNamespace(
            outline_text="林尘读书发愣被工头打断\n无奈自嘲自己的处境",
            content_text="",
        )
        beats = _nearby_beats_from_outline(bundle)
        assert beats and "工头打断" in beats[0]
        assert _nearby_intent_from_outline(bundle) == "\n".join(beats)
        empty = SimpleNamespace(outline_text="  ", content_text="")
        assert _nearby_beats_from_outline(empty) == []
        assert _nearby_intent_from_outline(empty) == ""


# ============================================================
# ④ 切除兜底口径：beat_rush 不授权 excise（2026-09-09 文档=代码对齐）
# ============================================================

class TestBeatRushNotExcisable:
    """AGENTS/ghost_guard 声明 beat_rush「excise 不授权」（抢拍是方向性错误，
    删句对整稿伤害大于改写）——切除兜底必须同口径：beat_rush 违规改写失败后
    走拒稿（熔断/逃生舱），绝不删句。事故形态：返修环 excise 回调曾把全部
    repair-eligible 违规无差别喂给切除，beat_rush 句被静默删掉。"""

    def _viol(self, kind: str, span: str) -> dict:
        return {"kind": kind, "span_text": span}

    def test_beat_rush_only_not_excised(self):
        from backend.services.adaptive.stitch_gates import (
            _excise_violating_sentences,
        )

        text = (
            "他握紧手里的扳手，指节因用力而发白。"
            "工头打断了所有人的争论，车间瞬间安静下来。"
            "他慢慢退后半步，把扳手塞回工具袋里，转身走向门口的更衣柜。"
        )
        # 唯一违规是 beat_rush → 不可切除，返回 None（返修环据此走拒稿）
        assert _excise_violating_sentences(
            text, [self._viol("beat_rush", "工头打断")],
            mode="stitch", target_chars=120,
        ) is None

    def test_mixed_cuts_only_non_beat_rush(self):
        from backend.services.adaptive.stitch_gates import (
            _excise_violating_sentences,
        )

        text = (
            "他握紧手里的扳手，指节因用力而发白，掌心的旧茧压出一道浅浅的白痕。"
            "工头打断了所有人的争论，车间瞬间安静下来，只剩下传送带低沉的嗡鸣。"
            "流光的螺栓在灯下闪着微光，像一截烧红的铁。"
            "他慢慢退后半步，把扳手塞回工具袋里，转身走向门口的更衣柜，脚步放得很轻。"
        )
        out = _excise_violating_sentences(
            text,
            [self._viol("beat_rush", "工头打断"),
             self._viol("secret_leak", "流光的螺栓")],
            mode="stitch", target_chars=120,
        )
        # secret_leak 句照切；beat_rush 句保住（不是它的切除授权）
        assert out is not None
        assert "工头打断" in out
        assert "流光的螺栓" not in out
