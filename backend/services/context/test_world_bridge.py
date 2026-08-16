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

import unittest
from types import SimpleNamespace

from backend.services.context.world_bridge import (
    WorldAssetAdapter,
    WorldEntityAdapter,
    WorldRelationAdapter,
    dynamic_state_text,
    static_prompt_from_world_entity,
)


def _world_entity(**kw):
    """构造 WorldEntity 形状的假对象（不走 DB）。"""
    base = dict(
        id="e-1",
        entity_type="character",
        name="林尘",
        aliases=["小尘"],
        importance=8,
        intro="",
        props={},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _loc(name):
    return SimpleNamespace(id=f"loc-{name}", name=name)


class StaticPromptTests(unittest.TestCase):
    def test_structured_fields_compose_with_chinese_labels(self):
        ent = _world_entity(props={"appearance": "瘦高", "speech_style": "短句", "goal": ""})
        text = static_prompt_from_world_entity(ent)
        self.assertIn("外貌：瘦高", text)
        self.assertIn("语言习惯：短句", text)
        self.assertNotIn("目标", text)  # 空字段跳过

    def test_background_field_rendered(self):
        # M4 收尾：旧档案迁移并入 background（启动数据迁移摘 legacy_profile 键）
        ent = _world_entity(props={"background": "出身寒门，少年流落"})
        text = static_prompt_from_world_entity(ent)
        self.assertIn("背景：出身寒门，少年流落", text)

    def test_empty_props(self):
        self.assertEqual(static_prompt_from_world_entity(_world_entity()), "")


class DynamicStateTests(unittest.TestCase):
    def test_dead(self):
        cs = {"alive": False}
        self.assertEqual(dynamic_state_text(cs, {}), "已死亡")

    def test_located(self):
        cs = {"alive": True, "location_id": "loc-北岸要塞", "label": ""}
        locs = {"loc-北岸要塞": _loc("北岸要塞")}
        self.assertEqual(dynamic_state_text(cs, locs), "位于北岸要塞")

    def test_in_transit_label_carried(self):
        cs = {"alive": True, "location_id": "loc-官道", "label": "在途（进度 40%）"}
        locs = {"loc-官道": _loc("官道")}
        self.assertEqual(dynamic_state_text(cs, locs), "位于官道，在途（进度 40%）")

    def test_no_state_returns_empty(self):
        self.assertEqual(dynamic_state_text(None, {}), "")
        self.assertEqual(dynamic_state_text({}, {}), "")


class AdapterShapeTests(unittest.TestCase):
    """下游（_characters_text / hard_constraints / sediment 冲突检测）零改动的形状契约。"""

    def test_character_adapter_duck_shape(self):
        ent = _world_entity(
            importance=10,
            props={"appearance": "瘦高", "background": "旧档案"},
        )
        cs = {"alive": True, "location_id": "loc-北岸要塞", "label": ""}
        adapter = WorldEntityAdapter(ent, cs, {"loc-北岸要塞": _loc("北岸要塞")})
        # _entity_name / _characters_text 访问链
        self.assertEqual(adapter.character.name, "林尘")
        self.assertIn("外貌：瘦高", adapter.character.static_prompt)
        self.assertIn("背景：旧档案", adapter.character.static_prompt)
        self.assertEqual(adapter.character.dynamic_state, "位于北岸要塞")
        self.assertEqual(adapter.character.aliases, ["小尘"])
        # importance 1-10 → 旧 1-4 口径
        self.assertEqual(adapter.character.importance_level, 4)
        # 原始引用保留
        self.assertIs(adapter.world_entity, ent)

    def test_character_adapter_without_events(self):
        adapter = WorldEntityAdapter(_world_entity(importance=2), None, {})
        self.assertEqual(adapter.character.dynamic_state, "")
        self.assertEqual(adapter.character.importance_level, 1)

    def test_asset_adapter_shape(self):
        ent = _world_entity(entity_type="asset", name="扳手", intro="锈迹斑斑", props={})
        a = WorldAssetAdapter(ent)
        self.assertEqual(a.name, "扳手")
        self.assertEqual(a.static_description, "锈迹斑斑")
        self.assertEqual(a.current_state, "")

    def test_asset_adapter_intro_fallback_to_props(self):
        ent = _world_entity(entity_type="asset", name="扳手", intro="", props={"description": "铁制"})
        a = WorldAssetAdapter(ent)
        self.assertEqual(a.static_description, "铁制")

    def test_relation_adapter_shape(self):
        rel = SimpleNamespace(
            id="r-1",
            source_entity_id="e-1",
            target_entity_id="e-2",
            relation_type="ally",
            label="结盟",
            note="战俘营结义",
        )
        ents = {"e-1": _world_entity(name="林尘"), "e-2": _world_entity(id="e-2", name="老烟")}
        r = WorldRelationAdapter(rel, ents)
        self.assertEqual(r.source_character.name, "林尘")
        self.assertEqual(r.target_character.name, "老烟")
        self.assertEqual(r.relationship_type, "ally")
        self.assertEqual(r.description, "结盟（战俘营结义）")
        # 端点缺失不炸：空名
        r2 = WorldRelationAdapter(rel, {})
        self.assertEqual(r2.source_character.name, "")


if __name__ == "__main__":
    unittest.main()
