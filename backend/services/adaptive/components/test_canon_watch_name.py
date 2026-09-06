# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - canon_watch 出场判定形状修复单测（2026-08-26 实测事故）
"""出场提醒形状事故回归锁：

实测（最终武装 26 次心跳 hints 恒 0）：bundle.entities 两种来源都不在顶层挂
.name——旧 ChapterEntity 与 world 桥 WorldEntityAdapter 均为 ent.character.name
访问链（settings_bundle._entity_name 一直是对的）。canon_watch._name_of 旧实现
读顶层 .name 恒空 → 角色出场提醒自诞生起零命中。

运行：python -m pytest backend/services/adaptive/components/test_canon_watch_name.py -v
"""

from types import SimpleNamespace

from backend.services.adaptive.components.canon_watch import (
    _entity_brief,
    _name_in_text,
    _name_of,
    _token_spans,
)


def _adapter(name="林尘", static="统合局后勤技工，嗜书如命"):
    """world 桥 WorldEntityAdapter 形状（.character.name 访问链）。"""
    return SimpleNamespace(
        world_entity=SimpleNamespace(name=name),
        character=SimpleNamespace(
            name=name, static_prompt=static, dynamic_state="位于员工宿舍",
            aliases=[], importance_level=2,
        ),
    )


def _old_chapter_entity(name="白霆"):
    """旧 ChapterEntity 形状（.character 关系链）。"""
    return SimpleNamespace(character=SimpleNamespace(name=name))


class TestNameOfShapes:
    def test_world_adapter_name_extracted(self):
        assert _name_of(_adapter()) == "林尘"

    def test_old_chapter_entity_shape(self):
        assert _name_of(_old_chapter_entity()) == "白霆"

    def test_top_level_name_still_works(self):
        """dict 桩与顶层 name 对象（历史测试形态）不回退。"""
        assert _name_of({"name": "红月"}) == "红月"
        assert _name_of({"character": {"name": "血噬"}}) == "血噬"
        assert _name_of(SimpleNamespace(name="统合局")) == "统合局"

    def test_none_and_empty(self):
        assert _name_of(None) == ""
        assert _name_of(SimpleNamespace()) == ""


class TestEntityBriefShapes:
    def test_adapter_uses_static_prompt(self):
        brief = _entity_brief(_adapter())
        assert "技工" in brief

    def test_old_description_role_fallback(self):
        ent = SimpleNamespace(description="老牌指挥官", role="军官")
        assert "军官" in _entity_brief(ent) and "指挥官" in _entity_brief(ent)

    def test_generic_fallback(self):
        assert _entity_brief(None) == "本章绑定角色"


class TestAppearanceScanEndToEnd:
    def test_real_paragraph_fires_for_mentioned_character(self):
        """端到端复现事故现场：正文含「林尘」→ 判定出场（词边界正常）。"""
        recent = "这是林尘昨晚睡前翻书时撇到的话，在这个世道，"
        spans = _token_spans(recent)
        ents = [_adapter(name="林尘"), _old_chapter_entity(name="白霆")]
        hit = [n for e in ents if (n := _name_of(e)) and len(n) >= 2
               and _name_in_text(n, recent, spans)]
        assert hit == ["林尘"]
