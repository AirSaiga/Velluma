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
一致性守卫（Phase 7）与专名注册表的单测。

纯函数 + mock，不依赖 DB / 真实 LLM。
运行方式（项目根目录）：
    python -m unittest backend.services.workflows.adf.test_consistency_guard -v
"""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

import backend.services.workflows.adf.consistency_guard as cg
from backend.services.prompts.adf_prompts import (
    parse_consistency_audit_response,
    parse_edit_verify_response,
)
from backend.services.workflows.adf.consistency_guard import _surgery_safe
from backend.services.workflows.adf.dedup_guard import (
    char_shingles,
    find_duplicate_blocks,
    remove_duplicate_blocks,
    segment_too_similar,
)
from backend.services.workflows.adf.name_registry import (
    NameRegistry,
    _pseg as jieba_pseg,
    build_name_registry,
    registry_to_prompt_block,
    scan_name_anomalies,
)
from backend.services.workflows.adf.segment_writer import (
    _build_compact_canon_hint,
    _build_knowledge_constraints,
    _build_presence_hint,
)
from backend.services.workflows.adf.setting_resolver import (
    resolve_hidden_constraints,
    resolve_relationships,
)
from backend.services.workflows.adf.types import ChapterClimax, Precondition


CANON_CONTEXT = """## 作者脑中的真相 [private] ★ 绝不许在正文直接写出
- 白霆真实身份：他是卧底
  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出

## 必须遵守的已建立事实 [public]
- 林尘：主角，弦月巅峰修为
- 老赵：工地工头
- 这是一个长度超限的标签名：不应被收录

## 活跃伏笔 [hook]（本章可推进/回收）
- [断剑] 强度=7：林尘遗失的佩剑"""


def _make_entities():
    return [
        SimpleNamespace(character=SimpleNamespace(
            name="林尘", aliases=["尘哥", "林"],  # "林" 单字应被过滤
            static_prompt="", dynamic_state="",
        )),
    ]


def _make_locations():
    return [SimpleNamespace(location=SimpleNamespace(
        name="仓库区", description="", current_state="",
    ))]


def _make_assets():
    return [SimpleNamespace(asset=SimpleNamespace(
        name="流光机甲", aliases=["机甲"], static_description="", current_state="",
    ))]


class NameRegistryBuildTests(unittest.TestCase):
    def test_build_collects_names_aliases_and_canon_public_labels(self):
        registry = build_name_registry(
            entities=_make_entities(),
            locations=_make_locations(),
            assets=_make_assets(),
            canon_context=CANON_CONTEXT,
        )
        # ORM 名称与 Canon public label 都进规范名
        self.assertIn("林尘", registry.canonical_names)
        self.assertIn("老赵", registry.canonical_names)
        self.assertIn("仓库区", registry.canonical_names)
        self.assertIn("流光机甲", registry.canonical_names)
        # 别名映射
        self.assertEqual(registry.alias_to_canonical.get("尘哥"), "林尘")
        self.assertEqual(registry.alias_to_canonical.get("机甲"), "流光机甲")
        self.assertIn("尘哥", registry.all_surface_forms)

    def test_build_filters_invalid_and_private_labels(self):
        registry = build_name_registry(
            entities=_make_entities(), canon_context=CANON_CONTEXT,
        )
        # 单字别名被过滤
        self.assertNotIn("林", registry.all_surface_forms)
        # 超长 Canon label（>8 字）被过滤
        self.assertNotIn("这是一个长度超限的标签名", registry.all_surface_forms)
        # private 标签不进专名表（避免在 prompt 里重复敏感词）
        self.assertNotIn("白霆真实身份", registry.all_surface_forms)
        # hook 区块不是 public，不收录
        self.assertNotIn("断剑", registry.all_surface_forms)
        # 角色名子集只含角色
        self.assertEqual(registry.character_names, {"林尘"})

    def test_prompt_block_lists_names_and_instruction(self):
        registry = build_name_registry(entities=_make_entities())
        block = registry_to_prompt_block(registry)
        self.assertIn("专名表", block)
        self.assertIn("- 林尘（别名：尘哥）", block)
        self.assertIn("禁止给同一人物起新称呼", block)
        # 空注册表返回空串
        empty = NameRegistry()
        self.assertEqual(registry_to_prompt_block(empty), "")


class NameDriftScanTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_name_registry(canon_context=CANON_CONTEXT)

    def test_variant_drift_detected_when_repeated(self):
        text = "老张把安全帽扣上。老张骂了一句。老张挥手让他们开工。"
        suspects = scan_name_anomalies(text, self.registry)
        drift = [s for s in suspects if s["type"] == "name_drift"]
        self.assertTrue(any(s["name"] == "老张" and s["canonical"] == "老赵" for s in drift))

    def test_registered_name_not_flagged(self):
        text = "老赵把安全帽扣上。老赵骂了一句。老赵挥手让他们开工。"
        suspects = scan_name_anomalies(text, self.registry)
        self.assertFalse([s for s in suspects if s["type"] == "name_drift"])

    def test_single_occurrence_drift_not_reported(self):
        # 漂移候选只出现 1 次，不达 ≥2 次阈值，不报（降误报）
        text = "老张把安全帽扣上。老赵骂了一句。老赵挥手让他们开工。"
        suspects = scan_name_anomalies(text, self.registry)
        drift = [s for s in suspects if s["type"] == "name_drift" and s["name"] == "老张"]
        self.assertFalse(drift)


class UnregisteredNameScanTests(unittest.TestCase):
    def setUp(self):
        if jieba_pseg is None:
            self.skipTest("jieba.posseg 不可用")
        self.registry = build_name_registry(canon_context=CANON_CONTEXT)

    def test_unregistered_person_name_detected_when_repeated(self):
        text = "王小明来了。王小明看着天。王小明又走了。"
        suspects = scan_name_anomalies(text, self.registry)
        unregistered = [s for s in suspects if s["type"] == "unregistered_name"]
        self.assertTrue(
            any(s["name"] in text for s in unregistered),
            f"应检出未注册人名，实际 suspects: {suspects}",
        )

    def test_single_occurrence_name_not_reported(self):
        text = "王小明来了。天气很好。他走了。"
        suspects = scan_name_anomalies(text, self.registry)
        unregistered = [s for s in suspects if s["type"] == "unregistered_name"]
        self.assertFalse(unregistered)


class HiddenRelationshipTests(unittest.TestCase):
    def _rels(self):
        return [
            SimpleNamespace(
                is_public=False, relation_type="兄弟", affinity_score=None,
                interaction_prompt=None,
                source_character=SimpleNamespace(name="林尘"),
                target_character=SimpleNamespace(name="白霆"),
            ),
            SimpleNamespace(
                is_public=True, relation_type="同事", affinity_score=3,
                interaction_prompt="日常互怼",
                source_character=SimpleNamespace(name="林尘"),
                target_character=SimpleNamespace(name="白霆"),
            ),
            # is_public 缺失（None）视为公开
            SimpleNamespace(
                relation_type="旧识", affinity_score=None, interaction_prompt=None,
                source_character=SimpleNamespace(name="林尘"),
                target_character=SimpleNamespace(name="白霆"),
            ),
        ]

    def test_hidden_relationship_excluded_from_public_block(self):
        characters = [{"name": "林尘"}, {"name": "白霆"}]
        public = resolve_relationships(self._rels(), characters)
        types = {r["relation_type"] for r in public}
        self.assertNotIn("兄弟", types)
        self.assertIn("同事", types)
        self.assertIn("旧识", types)  # None 视为公开

    def test_hidden_relationship_becomes_negative_constraint(self):
        characters = [{"name": "林尘"}, {"name": "白霆"}]
        hidden = resolve_hidden_constraints(self._rels(), characters)
        self.assertEqual(len(hidden), 1)
        self.assertIn("林尘", hidden[0])
        self.assertIn("白霆", hidden[0])
        self.assertIn("兄弟", hidden[0])
        self.assertIn("不为外人所知", hidden[0])

    def test_hidden_relationship_ignored_when_character_absent(self):
        # 只有一端在场 → 本章写不出这段关系，无需约束
        hidden = resolve_hidden_constraints(self._rels(), [{"name": "林尘"}])
        self.assertEqual(hidden, [])


class KnowledgeConstraintTests(unittest.TestCase):
    def test_private_labels_become_constraints(self):
        constraints = _build_knowledge_constraints(CANON_CONTEXT, ["隐藏约束A"])
        self.assertTrue(
            any("白霆真实身份" in c and "不得说出" in c for c in constraints),
            f"private 节点应转为否定约束，实际: {constraints}",
        )
        self.assertIn("隐藏约束A", constraints)

    def test_empty_canon_yields_only_hidden_constraints(self):
        constraints = _build_knowledge_constraints("", ["隐藏约束A"])
        self.assertEqual(constraints, ["隐藏约束A"])


class CompactCanonHintTests(unittest.TestCase):
    def test_public_facts_appended_after_upgrade(self):
        hint = _build_compact_canon_hint(CANON_CONTEXT)
        # private 标签提醒保留（现状行为）
        self.assertIn("private 提醒", hint)
        self.assertIn("白霆真实身份", hint)
        # public 事实完整行追加（升级行为）
        self.assertIn("public 事实", hint)
        self.assertIn("老赵：工地工头", hint)


class PresenceHintTests(unittest.TestCase):
    def test_first_segment_returns_empty(self):
        registry = build_name_registry(entities=_make_entities())
        self.assertEqual(_build_presence_hint([], registry), "")

    def test_presence_collected_from_recent_segments(self):
        registry = build_name_registry(entities=_make_entities())
        segments = [
            SimpleNamespace(text="林尘走进仓库区。"),
            SimpleNamespace(text="他抬头看了看天。"),
        ]
        hint = _build_presence_hint(segments, registry)
        self.assertIn("林尘", hint)


class SurgerySafetyNetTests(unittest.TestCase):
    def setUp(self):
        self.anchor = ChapterClimax(preconditions=[
            Precondition(id="PC1", must_use_terms=["暗元素"], landed=True),
        ])
        self.registry = NameRegistry(
            canonical_names={"林尘"},
            alias_to_canonical={},
            all_surface_forms={"林尘"},
        )
        self.original = "林尘催动暗元素，一拳砸出。"

    def test_losing_must_use_terms_is_unsafe(self):
        safe, reason = _surgery_safe(
            self.original, "林尘催动全力，一拳砸出。", self.anchor, self.registry,
        )
        self.assertFalse(safe)
        self.assertIn("暗元素", reason)

    def test_overlong_revision_is_unsafe(self):
        safe, reason = _surgery_safe(
            self.original, self.original + "扩写" * 50, self.anchor, self.registry,
        )
        self.assertFalse(safe)
        self.assertIn("超长", reason)

    def test_losing_canonical_name_is_unsafe(self):
        safe, reason = _surgery_safe(
            self.original, "他催动暗元素，一拳砸出。", self.anchor, self.registry,
        )
        self.assertFalse(safe)
        self.assertIn("林尘", reason)

    def test_legitimate_revision_is_safe(self):
        # 等长改写：保留专名与伏笔关键词，且不超过原文 ×1.5
        safe, _ = _surgery_safe(
            self.original, "林尘催动暗元素，一掌拍出。",
            self.anchor, self.registry,
        )
        self.assertTrue(safe)

    def test_unlanded_precondition_not_protected(self):
        anchor = ChapterClimax(preconditions=[
            Precondition(id="PC2", must_use_terms=["暗元素"], landed=False),
        ])
        safe, _ = _surgery_safe(
            self.original, "林尘催动全力，一拳砸出。", anchor, self.registry,
        )
        self.assertTrue(safe)


class AuditResponseParseTests(unittest.TestCase):
    def test_issues_without_evidence_or_quote_are_dropped(self):
        raw = json.dumps({
            "issues": [
                {  # 合法 issue：保留
                    "id": "C001", "type": "name_drift", "severity": "high",
                    "location": {"paragraph": 3, "quote": "老张把安全帽往头上一扣"},
                    "diagnosis": "工头被称为老张", "suggestion": "改为老赵",
                    "canon_evidence": "专名表：- 老赵",
                },
                {  # 无 canon_evidence：丢弃
                    "id": "C002", "type": "setting_conflict", "severity": "high",
                    "location": {"paragraph": 1, "quote": "某句原文"},
                    "canon_evidence": "",
                },
                {  # 非四类 type：丢弃
                    "id": "C003", "type": "plot_hole", "severity": "high",
                    "location": {"paragraph": 1, "quote": "某句原文"},
                    "canon_evidence": "某证据",
                },
                {  # 无 location.quote：丢弃
                    "id": "C004", "type": "knowledge_breach", "severity": "medium",
                    "location": {"paragraph": 2},
                    "canon_evidence": "某证据",
                },
            ],
            "rejected_suspects": [],
        }, ensure_ascii=False)
        issues = parse_consistency_audit_response(raw)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["id"], "C001")
        self.assertEqual(issues[0]["location"]["paragraph"], 3)

    def test_fenced_json_is_parsed(self):
        raw = "```json\n" + json.dumps({"issues": []}, ensure_ascii=False) + "\n```"
        self.assertEqual(parse_consistency_audit_response(raw), [])

    def test_garbage_returns_empty_list(self):
        self.assertEqual(parse_consistency_audit_response("不是 JSON"), [])
        self.assertEqual(parse_consistency_audit_response(""), [])


class DedupGuardTests(unittest.TestCase):
    # 合成 A/A′ 样例：块 A（P0-P2 仓库对峙）→ P3 袭击闪回 → 块 A′（P4-P6 逐段重复 A）
    A0 = "仓库的铁门被风撞得哐当作响，林尘把身影藏进立柱后的阴影里，目光锁住对面三个持棍的打手。"
    A1 = "白霆站在货箱上，慢条斯理地摘下手套，声音不大，却让每个字都砸在众人心口上。"
    A2 = "老赵的额头渗出冷汗，他攥紧手里的扳手，指节因为用力而泛白，喉咙里发不出半点声音。"
    FLASHBACK = "三小时前，袭击来得毫无征兆。黑色的装甲车撞开工地围栏，探照灯把夜空撕成碎片，工人们四散奔逃。"
    TAIL = "对峙仍在继续。林尘深吸一口气，从阴影里迈出第一步，所有人的目光瞬间聚到他身上。"

    def test_find_duplicate_blocks_hits_later_block(self):
        paras = [self.A0, self.A1, self.A2, self.FLASHBACK,
                 self.A0, self.A1, self.A2]
        removed = find_duplicate_blocks(paras)
        # 命中后出现的块 P4-P6（保留先出现的 P0-P2）
        self.assertEqual(removed, [(4, 6)])

    def test_near_verbatim_block_with_minor_edits(self):
        # A′ 有少量措辞差异（近乎逐字而非完全逐字）仍应命中
        a2_variant = "老赵的额头渗出冷汗，他攥紧手里的扳手，指节因用力而泛白，喉咙里发不出一丝声音。"
        paras = [self.A0, self.A1, self.A2, self.FLASHBACK,
                 self.A0, self.A1, a2_variant]
        removed = find_duplicate_blocks(paras)
        self.assertEqual(removed, [(4, 6)])

    def test_short_paragraph_repeat_not_flagged(self):
        # "灰尘还没散。"这类短句在不同场景自然重现，不构成锚定配对 → 不触发
        paras = [
            self.A0, "灰尘还没散。", self.A1,
            self.FLASHBACK, "灰尘还没散。", self.TAIL,
        ]
        self.assertEqual(find_duplicate_blocks(paras), [])

    def test_same_topic_different_wording_not_flagged(self):
        # 非相邻段话题相近（同一仓库场景）但文字完全不同 → 不触发
        same_topic = "库房深处，林尘贴着冰冷的墙根移动，视线扫过几个拿武器的男人，寻找突围的空隙。"
        paras = [self.A0, self.A1, self.FLASHBACK, same_topic]
        self.assertEqual(find_duplicate_blocks(paras), [])

    def test_segment_too_similar_threshold_boundary(self):
        long_a = self.A0 * 8   # >200 字
        long_b = self.FLASHBACK * 8
        # 完全相同的长段 → 命中
        self.assertTrue(segment_too_similar(long_a, long_a))
        # 完全不同的长段 → 不命中
        self.assertFalse(segment_too_similar(long_a, long_b))
        # 短于 min_chars 即使完全相同也不判重
        short = "灰尘还没散。"
        self.assertFalse(segment_too_similar(short, short))

    def test_short_paragraph_at_block_head_is_removed_with_block(self):
        # 重复块开头共同的短句（"灰尘还没散。"）不能锚定，但属于块的一部分，
        # 应随块一起删除（真实章节 07136b7a 的悬挂残句案例）
        short = "灰尘还没散。"
        paras = [self.A2, short, self.A0, self.A1,
                 self.FLASHBACK, short, self.A0, self.A1]
        removed = find_duplicate_blocks(paras)
        self.assertEqual(removed, [(5, 7)])

    def test_remove_duplicate_blocks_preserves_structure(self):
        paras = [self.A0, self.A1, self.A2, self.FLASHBACK,
                 self.A0, self.A1, self.A2, self.TAIL]
        text = "\n\n".join(paras)
        new_text, removed = remove_duplicate_blocks(text)
        self.assertEqual(removed, [(4, 6)])
        # 保留先出现块 + 后续段衔接：仓库对峙 → 袭击闪回 → 对峙继续
        self.assertEqual(
            new_text, "\n\n".join([self.A0, self.A1, self.A2, self.FLASHBACK, self.TAIL]),
        )
        # 文本完整性：删除后不再含第二份 A′，且首尾内容都在
        self.assertEqual(new_text.count(self.A0), 1)
        self.assertTrue(new_text.startswith(self.A0))
        self.assertTrue(new_text.endswith(self.TAIL))

    def test_remove_duplicate_blocks_no_dup_zero_change(self):
        text = "\n\n".join([self.A0, self.FLASHBACK, self.TAIL])
        new_text, removed = remove_duplicate_blocks(text)
        self.assertEqual(new_text, text)
        self.assertEqual(removed, [])

    def test_char_shingles_normalization(self):
        # 空白/换行/半角标点差异不影响 shingle
        a = char_shingles("林尘抬起头， 灰尘还没散。")
        b = char_shingles("林尘抬起头,\n灰尘还没散.")
        self.assertEqual(a, b)


class EditVerifyParseTests(unittest.TestCase):
    """parse_edit_verify_response 三态：ok / not-ok 带 problems / not-ok 无 problems。"""

    def test_ok_verdict(self):
        raw = json.dumps({"verdicts": [
            {"operation_id": "OP001", "ok": True, "problems": ""},
        ]})
        self.assertEqual(parse_edit_verify_response(raw), {"OP001": True})

    def test_not_ok_with_problems_is_rejected(self):
        raw = json.dumps({"verdicts": [
            {"operation_id": "OP001", "ok": False, "problems": "改动后与邻段重复"},
        ]})
        self.assertEqual(parse_edit_verify_response(raw), {"OP001": False})

    def test_not_ok_without_problems_treated_as_ok(self):
        # 防复验幻觉：无问题描述的 not-ok 不误杀好修复
        raw = json.dumps({"verdicts": [
            {"operation_id": "OP001", "ok": False, "problems": ""},
            {"operation_id": "OP002", "ok": False},
        ]})
        self.assertEqual(
            parse_edit_verify_response(raw), {"OP001": True, "OP002": True},
        )

    def test_fenced_json_is_parsed(self):
        raw = "```json\n" + json.dumps({"verdicts": [
            {"operation_id": "OP001", "ok": True},
        ]}) + "\n```"
        self.assertEqual(parse_edit_verify_response(raw), {"OP001": True})

    def test_garbage_returns_empty_dict(self):
        self.assertEqual(parse_edit_verify_response("不是 JSON"), {})
        self.assertEqual(parse_edit_verify_response(""), {})


class EditVerifyRollbackTests(unittest.IsolatedAsyncioTestCase):
    """Agent Loop 2 集成：手术复验回滚（mock LLM/手术，spy apply）。

    走 run_consistency_guard 全链：审计(mock) → plan_operations(真实) →
    execute_surgery(mock) → 安全网(真实) → apply(spy) → 复验(mock) → 回滚重拼。
    """

    P0 = "老张把安全帽往头上一扣，骂骂咧咧地走向升降机。"
    P1 = "林尘站在仓库门口，看着远处的烟尘。"
    P2 = "夜色渐深，工地上的探照灯逐一熄灭。"

    REVISED = {
        "OP001": "老赵把安全帽往头上一扣，骂骂咧咧地走向升降机。",
        "OP002": "夜色渐深，工地上的探照灯先后熄灭。",
    }

    def _text(self):
        return "\n\n".join([self.P0, self.P1, self.P2])

    def _audit_json(self):
        # 两个不同段落的 issue → plan_operations 分两个 operation
        return json.dumps({"issues": [
            {"id": "C001", "type": "name_drift", "severity": "high",
             "location": {"paragraph": 0, "quote": "老张把安全帽"},
             "diagnosis": "工头被称为老张", "suggestion": "改为老赵",
             "canon_evidence": "专名表：- 老赵（工地工头）"},
            {"id": "C002", "type": "setting_conflict", "severity": "high",
             "location": {"paragraph": 2, "quote": "探照灯逐一熄灭"},
             "diagnosis": "与场景设定冲突", "suggestion": "改写",
             "canon_evidence": "场景设定：探照灯彻夜通明"},
        ]}, ensure_ascii=False)

    def _fake_surgery(self, revised_map):
        async def fake(op, paragraphs, **_kwargs):
            idx = op["target_paragraphs"][0]
            return {
                "operation_id": op["id"],
                "applied": True,
                "original_text": paragraphs[idx],
                "revised_text": revised_map[op["id"]],
                "target_indices": list(op["target_paragraphs"]),
                "diff_summary": "fake",
            }
        return fake

    def _make_mocks(self, verify_json, revised_map=None):
        """返回 (llm_calls, apply_calls, patchers 上下文用到的 fake 函数字典)。"""
        llm_calls: list = []
        apply_calls: list = []
        real_apply = cg.apply_surgeries_to_text

        async def fake_llm(**kwargs):
            llm_calls.append(kwargs)
            content = self._audit_json() if len(llm_calls) == 1 else verify_json
            return SimpleNamespace(content=content)

        def spy_apply(paragraphs, surgeries):
            apply_calls.append([s["operation_id"] for s in surgeries])
            return real_apply(paragraphs, surgeries)

        return llm_calls, apply_calls, {
            "call_llm_with_usage": fake_llm,
            "execute_surgery": self._fake_surgery(revised_map or self.REVISED),
            "apply_surgeries_to_text": spy_apply,
        }

    async def _run(self, verify_json, text=None, revised_map=None, **guard_kwargs):
        llm_calls, apply_calls, fakes = self._make_mocks(verify_json, revised_map)
        with (
            mock.patch.object(cg, "call_llm_with_usage", fakes["call_llm_with_usage"]),
            mock.patch.object(cg, "execute_surgery", fakes["execute_surgery"]),
            mock.patch.object(cg, "apply_surgeries_to_text", fakes["apply_surgeries_to_text"]),
        ):
            result = await cg.run_consistency_guard(
                final_text=text or self._text(),
                registry=NameRegistry(),
                canon_context="",
                scene_setting_text="",
                knowledge_constraints=[],
                anchor=None,
                purpose="测试章节",
                **guard_kwargs,
            )
        return result, llm_calls, apply_calls

    async def test_mixed_verdicts_reapply_ok_subset_only(self):
        verify_json = json.dumps({"verdicts": [
            {"operation_id": "OP001", "ok": True, "problems": ""},
            {"operation_id": "OP002", "ok": False, "problems": "改动后与邻段内容重复"},
        ]})
        result, llm_calls, apply_calls = await self._run(verify_json)

        # OP002 被回滚：从原始 paragraphs 重 apply 时只含 OP001
        self.assertEqual(apply_calls[0], ["OP001", "OP002"])  # 第 5 步全量应用
        self.assertEqual(apply_calls[-1], ["OP001"])           # 回滚后重拼
        self.assertEqual(len(result.rolled_back), 1)
        self.assertIn("OP002", result.rolled_back[0])
        self.assertEqual(result.surgeries_applied, 1)
        self.assertEqual(result.issues_fixed, 1)
        # 正文：OP001 生效，OP002 目标段保持原文
        self.assertIn("老赵把安全帽", result.new_text)
        self.assertIn("探照灯逐一熄灭", result.new_text)
        self.assertNotIn("先后熄灭", result.new_text)
        # 复验是 1×reasoning，参数符合约定
        self.assertEqual(len(llm_calls), 2)
        self.assertEqual(llm_calls[1]["model_type"], "reasoning")
        self.assertEqual(llm_calls[1]["max_tokens"], 2048)

    async def test_all_verdicts_not_ok_restores_original_text(self):
        verify_json = json.dumps({"verdicts": [
            {"operation_id": "OP001", "ok": False, "problems": "引入设定矛盾"},
            {"operation_id": "OP002", "ok": False, "problems": "引入逻辑断裂"},
        ]})
        result, _, apply_calls = await self._run(verify_json)

        self.assertEqual(len(result.rolled_back), 2)
        self.assertEqual(result.surgeries_applied, 0)
        self.assertEqual(result.issues_fixed, 0)
        # 全部回滚 → 回到手术前文本，且没有第三次 apply
        self.assertEqual(result.new_text, self._text())
        self.assertEqual(len(apply_calls), 2)  # 第 5 步 + 复验邻段计算

    async def test_code_precheck_rolls_back_duplicate_revision(self):
        # 6a：改动后与原文邻段近重复（两段都 ≥200 归一化字才判重）
        p2_long = "夜色渐深，工地上的探照灯逐一熄灭，四周安静下来。" * 9
        p3_long = "他蹲在角落里，想起白天发生的一切，心里翻江倒海。" * 9
        text = "\n\n".join([self.P0, self.P1, p2_long, p3_long])
        revised_map = dict(self.REVISED)
        revised_map["OP002"] = p3_long  # 手术把邻段内容又写了一遍

        verify_json = json.dumps({"verdicts": [
            {"operation_id": "OP001", "ok": True, "problems": ""},
        ]})
        result, llm_calls, apply_calls = await self._run(
            verify_json, text=text, revised_map=revised_map,
        )

        self.assertEqual(len(result.rolled_back), 1)
        self.assertIn("代码预验", result.rolled_back[0])
        # 6a 之后只剩 OP001 进入 LLM 复验与重拼
        self.assertEqual(apply_calls[1], ["OP001"])
        self.assertEqual(apply_calls[-1], ["OP001"])
        self.assertIn("老赵把安全帽", result.new_text)
        self.assertIn(p2_long[:20], result.new_text)  # OP002 目标段保持原文

    async def test_edit_verify_disabled_skips_recheck(self):
        result, llm_calls, _ = await self._run(
            '{"verdicts": []}', enable_edit_verify=False,
        )
        # 只有审计 1 次 LLM 调用，两个手术全部生效
        self.assertEqual(len(llm_calls), 1)
        self.assertEqual(result.surgeries_applied, 2)
        self.assertEqual(result.rolled_back, [])
        self.assertIn("老赵把安全帽", result.new_text)
        self.assertIn("先后熄灭", result.new_text)


if __name__ == "__main__":
    unittest.main()