# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 线 D（2026-09-03）：思绪泄漏（mind_leak）+ 信念泄漏（belief_leak）对拍
"""
两检均 shadow 出生（只落台账不进帧；登记册 status 驱动 local_only）：

- mind_leak（POV 相机确定性半）：非白名单实体名 × 内心动词框架——旁白替
  不在场者报告内心=相机拍不到的画面。只抓具名主语（代词指代认栽）。
- belief_leak：在场者无人知晓的私有真相命题，里文本短语被逐字写出。
  「无人知晓」的命题级预裁在路由侧（belief.fold_belief/proposition_status），
  快检层只做纯文本比对——此处对拍纯函数契约与 ghost_guard 接线。

运行：python -m pytest backend/services/validation/test_mind_belief_leak.py -v
"""
from types import SimpleNamespace

from backend.services.context.scene_visibility import find_mind_leak_hits
from backend.services.validation.ghost_guard import check_ghost_text


VISIBLE = ["林尘", "老周"]
ALL_NAMES = ["林尘", "老周", "流光", "沈工"]


# ============================================================
# find_mind_leak_hits 纯函数判据
# ============================================================

class TestMindLeakHits:
    def test_hidden_name_mind_verb_hits(self):
        hits = find_mind_leak_hits("林尘低头拧螺栓。流光心想，这批货今晚必须出完。", VISIBLE, ALL_NAMES)
        assert len(hits) == 1
        assert hits[0]["name"] == "流光"
        assert hits[0]["verb"] == "心想"
        assert hits[0]["exempt"] is False

    def test_visible_name_never_hits(self):
        """在场者的内心是合法 POV 叙述面——白名单内名字不报。"""
        hits = find_mind_leak_hits("林尘心想，这活没法干了。老周意识到不对劲。", VISIBLE, ALL_NAMES)
        assert hits == []

    def test_hidden_name_without_mind_verb_no_hit(self):
        """裸名字/外显行为帧不命中（外显行为第三人称可合法叙述）。"""
        assert find_mind_leak_hits("林尘想起流光昨天笑了。", VISIBLE, ALL_NAMES) == []
        assert find_mind_leak_hits("流光走进来坐下。", VISIBLE, ALL_NAMES) == []

    def test_hand_verb_frame_is_not_mind_leak(self):
        """上手动词帧归第五检管，不进本检（两检动词族互斥）。"""
        assert find_mind_leak_hits("他把流光拧紧了。", VISIBLE, ALL_NAMES) == []

    def test_flashback_exempt(self):
        """转述/回忆里报告他人内心合法——豁免标记，由调用方记 exempt 事件。"""
        hits = find_mind_leak_hits("听说流光当年心想，这地方待不下去。", VISIBLE, ALL_NAMES)
        assert len(hits) == 1
        assert hits[0]["exempt"] is True

    def test_nested_word_no_hit(self):
        """嵌词边界复核：「流光溢彩」里的「流光」不算命中。"""
        assert find_mind_leak_hits("灯带流光溢彩，他心想真好看。", ["他"], ["他", "流光"]) == []

    def test_empty_inputs(self):
        assert find_mind_leak_hits("", VISIBLE, ALL_NAMES) == []
        assert find_mind_leak_hits("正文", [], []) == []


# ============================================================
# ghost_guard 接线（第九检）
# ============================================================

class TestMindLeakGuardIntegration:
    def test_hit_carries_shadow_local_only(self):
        warnings = check_ghost_text(
            "林尘低头拧螺栓。流光心想，这批货今晚必须出完。",
            visible_names=VISIBLE, all_names=ALL_NAMES,
        )
        hits = [w for w in warnings if w["kind"] == "mind_leak"]
        assert len(hits) == 1
        assert hits[0]["span_text"] == "流光"
        assert "内心" in hits[0]["message"]
        # shadow 出生：命中带 local_only（路由过滤出 SSE 帧只落台账）
        assert hits[0].get("local_only") is True

    def test_none_visible_names_closes_check(self):
        """零变化契约：调用方不传白名单（legacy 路径）整检关闭。"""
        warnings = check_ghost_text("流光心想，今晚必须出完。")
        assert [w for w in warnings if w["kind"] == "mind_leak"] == []

    def test_bundle_shape_candidates(self):
        """bundle 形态候选宇宙自动取用（与第五检同路径）。"""
        bundle = SimpleNamespace(
            canon_context="", character_secrets=[], world_state=None,
            entities=[
                SimpleNamespace(
                    world_entity=SimpleNamespace(entity_type="character"),
                    character=SimpleNamespace(name="流光"),
                ),
            ],
            assets=[],
        )
        warnings = check_ghost_text(
            "林尘拧螺栓。流光心想这批货必须出完。",
            bundle, visible_names=["林尘"],
        )
        assert any(w["kind"] == "mind_leak" and w["span_text"] == "流光" for w in warnings)


# ============================================================
# belief_leak（第十检）：纯文本比对层
# ============================================================

class TestBeliefLeakGuard:
    _PHRASES = [
        {"node_id": "n1", "label": "扳手的来历", "phrase": "扳手是林尘父亲留下的"},
        {"node_id": "n2", "label": "假信", "phrase": "那封信是伪造的"},
    ]

    def test_unknown_proposition_phrase_hits(self):
        warnings = check_ghost_text(
            "他摩挲着扳手。扳手是林尘父亲留下的，这一点没人敢提。",
            unknown_canon_phrases=self._PHRASES,
        )
        hits = [w for w in warnings if w["kind"] == "belief_leak"]
        assert len(hits) == 1
        assert hits[0]["span_text"] == "扳手是林尘父亲留下的"
        assert hits[0]["detail"]["node_id"] == "n1"
        assert "扳手的来历" in hits[0]["message"]
        assert hits[0].get("local_only") is True

    def test_reworded_paraphrase_passes(self):
        """改写复述不命中（切段而非滑窗——宁漏勿误，与 secret_leak 同纪律）。"""
        warnings = check_ghost_text(
            "他听说这扳手跟他父亲有些渊源。",
            unknown_canon_phrases=self._PHRASES,
        )
        assert [w for w in warnings if w["kind"] == "belief_leak"] == []

    def test_none_material_closes_check(self):
        """零变化契约：素材 None（非 world 书/无私有命题/装配失败）整检关闭。"""
        warnings = check_ghost_text("扳手是林尘父亲留下的。")
        assert [w for w in warnings if w["kind"] == "belief_leak"] == []

    def test_short_phrase_skipped(self):
        warnings = check_ghost_text(
            "假货。他冷笑。",
            unknown_canon_phrases=[{"node_id": "n3", "label": "x", "phrase": "假货"}],
        )
        assert [w for w in warnings if w["kind"] == "belief_leak"] == []


# ============================================================
# 顺带修复回归锁（2026-09-03 线 D 测试捞出）：_get_nested(ent, "world_entity",
# None) 把 None 当属性名——对象形态实体（world 适配器=生产形态）必抛
# TypeError 被零报错契约吞掉，_bundle_all_names 候选宇宙静默全灭
# （out_of_scene/mind_leak 双双失候选）；dict 形态则 entity_type 过滤失效
# （势力名混入「可上手」候选）。修复=调用点去掉第三个 None 参。
# ============================================================

class TestBundleAllNamesRegression:
    def test_object_entities_yield_names_and_filter_factions(self):
        from backend.services.validation.ghost_guard import _bundle_all_names
        bundle = SimpleNamespace(
            entities=[
                SimpleNamespace(
                    world_entity=SimpleNamespace(entity_type="character"),
                    character=SimpleNamespace(name="流光"),
                ),
                SimpleNamespace(
                    world_entity=SimpleNamespace(entity_type="faction"),
                    character=SimpleNamespace(name="统合局"),
                ),
            ],
            assets=[SimpleNamespace(name="扳手")],
        )
        names = _bundle_all_names(bundle)
        assert "流光" in names          # 对象形态不再整表炸掉
        assert "扳手" in names
        assert "统合局" not in names    # 势力过滤真生效（dict 形态此前失效）

    def test_dict_entities_still_work(self):
        from backend.services.validation.ghost_guard import _bundle_all_names
        bundle = SimpleNamespace(
            entities=[{"world_entity": {"entity_type": "faction"},
                        "character": {"name": "统合局"}},
                       {"world_entity": {"entity_type": "character"},
                        "character": {"name": "林尘"}}],
            assets=[],
        )
        names = _bundle_all_names(bundle)
        assert names == ["林尘"]
