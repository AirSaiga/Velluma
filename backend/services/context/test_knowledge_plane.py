# Velluma - 知识检索平面一期单测（docs/knowledge-retrieval-plane.md）
# AGPL-3.0
"""knowledge_plane 的行为锁：条目化/选择器/时态渲染/逃逸阀/零变化契约。

纯算法测试（无 DB/LLM）：bundle 用命名空间对象伪造，形状对齐
world_bridge 适配器（ent.character.name/.static_prompt/.dynamic_state、
ent.world_entity.id/.visibility）与 legacy ChapterEntity。
"""
import unittest

from backend.services.context import knowledge_plane as kp


class _Ns:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _entity(eid, name, static="", dynamic="", aliases=None, visibility="public"):
    return _Ns(
        character=_Ns(name=name, static_prompt=static, dynamic_state=dynamic,
                      aliases=aliases or []),
        world_entity=_Ns(id=eid, visibility=visibility),
    )


def _bundle(entities=None, assets=None, locations=None, relations=None, hooks=None,
            worldview=None, scene_loc="", states=None, world_sourced=True,
            world_time=3520, source="zero", content="", prev="", book=None):
    return _Ns(
        entities=entities or [], assets=assets or [], locations=locations or [],
        relationships=relations or [], open_hooks=hooks or [],
        book=book if book is not None else _Ns(worldview_settings=worldview),
        chapter=_Ns(scene_location_id=scene_loc),
        world_state={"character_states": states or []},
        world_sourced=world_sourced,
        world_time=world_time, world_time_source=source,
        content_text=content, previous_summary=prev,
        prohibitions=None,
    )


class TestEntryBuilding(unittest.TestCase):
    def test_private_entity_excluded(self):
        ent = _entity("e9", "暗线者", static="秘密档案", visibility="private")
        entries = kp.build_knowledge_entries(_bundle(entities=[ent]))
        self.assertEqual(entries, [])

    def test_worldview_items_parsed_and_legacy_string(self):
        wv = {"version": 1, "items": [{"id": "w1", "title": "机甲分级", "content": "D级机甲……"}]}
        entries = kp.build_knowledge_entries(_bundle(worldview=wv))
        self.assertEqual([e.kind for e in entries], ["worldview"])
        self.assertIn("机甲分级", entries[0].body)
        legacy = kp.build_knowledge_entries(_bundle(worldview="灵气复苏的世界"))
        self.assertEqual(legacy[0].title, "世界观")


class TestSelectors(unittest.TestCase):
    def _world(self):
        loc = _Ns(id="loc1", name="北岸要塞")
        e1 = _entity("e1", "林尘", static="外貌：清瘦\n性格：执拗")          # 在场
        e2 = _entity("e2", "红月", static="背景：旧时代残党")               # 已死亡
        e3 = _entity("e3", "白露", static="语言习惯：短句")                  # 未在场，正文提及
        e4 = _entity("e4", "远方角色")                                      # 未在场未提及
        states = [
            {"entity_id": "e1", "alive": True, "location_id": "loc1"},
            {"entity_id": "e2", "alive": False, "location_id": "loc9"},
            {"entity_id": "e3", "alive": True, "location_id": "loc2", "label": "在途（40%）"},
            {"entity_id": "e4", "alive": True, "location_id": "loc3"},
        ]
        b = _bundle(
            entities=[e1, e2, e3, e4], locations=[loc],
            scene_loc="loc1", states=states,
            content="<p>林尘擦了擦手，想起白露说过的螺丝规格。</p>",
        )
        return b

    def test_present_dead_mention_selected_and_reason(self):
        b = self._world()
        entries = kp.build_knowledge_entries(b)
        selected, unselected = kp.select_knowledge(entries, b, b.content_text)
        keys = [e.key for e in selected]
        self.assertIn("entity:林尘", keys)
        self.assertIn("entity:红月", keys)
        self.assertIn("entity:白露", keys)          # 提及（本章全文）
        self.assertNotIn("entity:远方角色", keys)   # 未在场未提及
        reasons = {u["key"]: u["reason"] for u in unselected}
        self.assertEqual(reasons.get("entity:远方角色"), "未在场且未提及")

    def test_hard_flags(self):
        b = self._world()
        entries = kp.build_knowledge_entries(b)
        selected, _ = kp.select_knowledge(entries, b, b.content_text)
        by = {e.key: e for e in selected}
        self.assertTrue(by["entity:林尘"].hard)   # 在场=硬
        self.assertTrue(by["entity:红月"].hard)   # 死亡=硬
        self.assertFalse(by["entity:白露"].hard)  # 提及=软

    def test_relation_needs_both_endpoints(self):
        b = self._world()
        rel = _Ns(
            source_character=_Ns(name="林尘"),
            target_character=_Ns(name="白露"),
            relationship_type="ally", description="并肩（旧识）",
        )
        rel_far = _Ns(
            source_character=_Ns(name="林尘"),
            target_character=_Ns(name="远方角色"),
            relationship_type="rival", description="",
        )
        b.relationships = [rel, rel_far]
        entries = kp.build_knowledge_entries(b)
        selected, unselected = kp.select_knowledge(entries, b, b.content_text)
        keys = [e.key for e in selected]
        self.assertIn("relation:林尘~白露", keys)
        reasons = {u["key"] for u in unselected}
        self.assertIn("relation:林尘~远方角色", reasons)

    def test_legacy_mode_all_entities_author_selected(self):
        ent = _entity("e1", "旧表角色", static="档案")
        b = _bundle(entities=[ent], world_sourced=False, states=[], content="")
        entries = kp.build_knowledge_entries(b)
        selected, unselected = kp.select_knowledge(entries, b, "")
        self.assertEqual([e.key for e in selected], ["entity:旧表角色"])
        self.assertEqual(selected[0].selector, "作者显式·章级绑定")
        self.assertEqual(unselected, [])

    def test_escape_valve_drops_whole_soft_entries_only(self):
        b = self._world()
        # 塞入大量软条目（未提及实体不进选择，改用 hook 塞软体积）
        hooks = [{"content": f"伏笔{i}：" + "线" * 120} for i in range(40)]
        b.open_hooks = hooks
        entries = kp.build_knowledge_entries(b)
        original = kp.KG_BUDGET_CHARS
        kp.KG_BUDGET_CHARS = 600  # 压低逃逸阀
        try:
            selected, unselected = kp.select_knowledge(entries, b, b.content_text)
        finally:
            kp.KG_BUDGET_CHARS = original
        keys = [e.key for e in selected]
        self.assertIn("entity:林尘", keys)          # 硬层永不丢
        dropped = [u for u in unselected if u["reason"] == "预算整条丢弃"]
        self.assertTrue(dropped)                     # 软条目整条丢弃
        kept_hook = [e for e in selected if e.kind == "hook"]
        total = sum(len(e.body) for e in selected)
        self.assertLessEqual(total + 200, 600 + max(len(e.body) for e in kept_hook + [e for e in selected]))  # 近似界


class TestRendering(unittest.TestCase):
    def _kv(self, **kw):
        b = self._render_world(**kw)
        return kp.build_knowledge_view(b), b

    def _render_world(self, content="<p>林尘擦了擦手。</p>"):
        loc = _Ns(id="loc1", name="北岸要塞")
        e1 = _entity("e1", "林尘", static="外貌：清瘦\n性格：执拗，认死理")
        e2 = _entity("e2", "红月", static="背景：旧时代残党")
        states = [
            {"entity_id": "e1", "alive": True, "location_id": "loc1"},
            {"entity_id": "e2", "alive": False, "location_id": "loc9"},
        ]
        return _bundle(
            entities=[e1, e2], locations=[loc], scene_loc="loc1", states=states,
            source="chapter_anchor",
            worldview={"version": 1, "items": [
                {"id": "w1", "title": "机甲分级", "content": "D" * 600},
            ]},
            content=content, prev="上一章结尾：他关上了灯。",
        )

    def test_temporal_prefix_and_fold_priority_note(self):
        kv, _ = self._kv()
        self.assertIn("【此刻·t=3520·位于北岸要塞】", kv.entities_text)
        self.assertIn("以【此刻】为准", kv.entities_text)
        self.assertIn("档案（作者录入，未删节）", kv.entities_text)

    def test_dead_marked_no_speak(self):
        kv, _ = self._kv()
        self.assertIn("红月【已死亡·不得出场、不得开口】", kv.entities_text)
        self.assertIn("已死亡", kv.recency_pin)

    def test_worldview_full_no_truncation(self):
        kv, _ = self._kv()
        self.assertIn("D" * 600, kv.worldview_text)   # 600 字全文在，无 200 截断

    def test_scene_identity(self):
        kv, _ = self._kv()
        self.assertIn("北岸要塞", kv.scene_identity)
        self.assertIn("t=3520", kv.scene_identity)
        self.assertIn("本章锚", kv.scene_identity)

    def test_recency_pin_compact(self):
        kv, _ = self._kv()
        self.assertTrue(kv.recency_pin.startswith("【此刻·切记】"))
        self.assertIn("在场：林尘", kv.recency_pin)
        self.assertIn("场景：北岸要塞", kv.recency_pin)

    def test_previous_summary_full_passthrough(self):
        kv, _ = self._kv()
        self.assertEqual(kv.previous_summary, "上一章结尾：他关上了灯。")

    def test_zero_change_empty_bundle(self):
        kv = kp.build_knowledge_view(_bundle())
        self.assertEqual(kv.total_chars(), 0)
        self.assertEqual(
            [kv.scene_identity, kv.entities_text, kv.worldview_text,
             kv.relations_text, kv.negative_constraints, kv.recency_pin,
             kv.previous_summary],
            ["", "", "", "", "", "", ""],
        )
        self.assertEqual(kv.unselected, [])

    def test_negative_constraints_full(self):
        class _Proh:
            @staticmethod
            def words(n, severity=None):
                return ["冷冽", "深邃", "自定义禁词"]
        b = self._render_world()
        b.prohibitions = _Proh()
        kv = kp.build_knowledge_view(b)
        self.assertIn("自定义禁词", kv.negative_constraints)


class TestRenderSystemBlocksOrder(unittest.TestCase):
    """注入序与任务平权在 render_system_blocks 层的锁（v3.1 §6）。"""

    def test_fact_blocks_precede_style_blocks(self):
        blocks = dict(
            __import__("backend.services.prompts.adaptive_prompts", fromlist=["x"])
            .render_system_blocks(
                style_positive="- 句长节奏：短句为主",
                proper_nouns=["林尘"],
                scene_identity="# 场景身份（事实层，生成以此为准）\n本章场景：北岸要塞",
                entities_text="# 在场与相关人物\n- 林尘〔在场〕",
                worldview_text="# 世界观（完整注入，未删节）\n- 机甲分级：…",
            )
        )
        self.assertIn("场景身份", blocks["scene"])
        self.assertIn("在场", blocks["entities"])
        self.assertIn("世界观", blocks["worldview"])
        # 块序：事实层（scene/entities/worldview）先于文风层（style_positive）
        order = [k for k, _ in
                 __import__("backend.services.prompts.adaptive_prompts", fromlist=["x"])
                 .render_system_blocks(
                     style_positive="- 句长节奏：短",
                     proper_nouns=["林尘"],
                     scene_identity="# 场景身份",
                     entities_text="# 在场与相关人物",
                     worldview_text="# 世界观",
                 )]
        self.assertLess(order.index("scene"), order.index("style_positive"))
        self.assertLess(order.index("entities"), order.index("author_samples"))
        self.assertLess(order.index("worldview"), order.index("echoes"))

    def test_no_light_mode_style_compression(self):
        """公理二任务平权：continue 档画像不再压缩（C3 轻档已退役）。"""
        from backend.services.prompts.adaptive_prompts import render_system_blocks
        full = "- 句长节奏：短句\n- 词汇层级：书面\n- 语域偏好：冷"
        cont = dict(render_system_blocks(style_positive=full, mode="continue"))
        self.assertEqual(cont["style_positive"].count("词汇层级"), 1)
        self.assertEqual(cont["style_positive"].count("语域偏好"), 1)

    def test_entities_replace_proper_nouns_when_present(self):
        from backend.services.prompts.adaptive_prompts import render_system_blocks
        keys = [k for k, _ in render_system_blocks(
            proper_nouns=["林尘"], entities_text="# 在场与相关人物\n- 林尘",
        )]
        self.assertNotIn("proper_nouns", keys)
        keys2 = [k for k, _ in render_system_blocks(proper_nouns=["林尘"])]
        self.assertIn("proper_nouns", keys2)  # 无实体数据时专名兜底


if __name__ == "__main__":
    unittest.main()
