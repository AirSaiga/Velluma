# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""势力（faction）档案通路对拍（2026-09-04 审计修复）。

背景：faction 此前没有任何 prompt 通路——适配层只装配 character/asset，
UI 可编辑可分层的理念/组织/领地字段对生成层完全不存在；私有势力更是从
所有通道静默消失（_entity_secret_text 与 asset 共口径只读 props.description，
而 faction 字段根本不是 description）。修复后：

1. faction_prompt_text：公开势力档案进知识平面（恒选软条目）；
2. 私有势力走 secrets 通道（整档案，respect_layers=False）；
3. 称呼表收录势力名（AI 必须能原样称呼它看得见的势力）；
4. 零变化契约：无 faction 的书 bundle.factions 恒空 → 零条目、逐字节不变。
"""
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List

from backend.services.context.world_bridge import (
    WorldFactionView,
    _entity_secret_text,
    faction_prompt_text,
)
from backend.services.world.field_layers import LEVEL_PARTIAL, LEVEL_PRIVATE


def _faction(props=None, layers=None, visibility="public", name="北岸统合局", intro=None):
    return SimpleNamespace(
        entity_type="faction",
        name=name,
        props=props or {},
        field_layers=layers or {},
        visibility=visibility,
        aliases=["统合局"],
        id="fid-1",
        **({"intro": intro} if intro is not None else {}),
    )


_PROPS = {
    "ideology": "秩序高于一切",
    "structure": "三席议会",
    "territory_note": "北岸码头区",
}


# ============================================================
# 1. faction_prompt_text（档案拼装）
# ============================================================

def test_faction_prompt_public_fields_all_present():
    text = faction_prompt_text(_faction(props=_PROPS, intro="掌控北岸的军事化政权"))
    assert text == "一句话：掌控北岸的军事化政权\n理念：秩序高于一切\n组织：三席议会\n领地：北岸码头区"


def test_faction_prompt_layers_private_hidden_partial_public_text():
    layers = {
        "ideology": {"level": LEVEL_PRIVATE},
        "structure": {"level": LEVEL_PARTIAL, "public_text": "委员会制"},
        "territory_note": {"level": LEVEL_PARTIAL, "public_text": ""},  # 表空=按秘密
    }
    text = faction_prompt_text(_faction(props=_PROPS, layers=layers))
    assert "理念" not in text and "秩序高于一切" not in text
    assert "组织：委员会制" in text and "三席议会" not in text
    assert "领地" not in text and "码头" not in text


def test_faction_prompt_respect_layers_false_keeps_full():
    layers = {"ideology": {"level": LEVEL_PRIVATE}}
    text = faction_prompt_text(_faction(props=_PROPS, layers=layers), respect_layers=False)
    assert "理念：秩序高于一切" in text


def test_faction_prompt_empty_zero_change():
    """无 intro 无字段：空串（下游判空跳过）。"""
    assert faction_prompt_text(_faction()) == ""


# ============================================================
# 2. 私有势力 secrets 通道
# ============================================================

def test_private_faction_secret_text_is_full_profile():
    """整人 private 势力 = 全档案进 secrets（修复前恒空 → 从所有通道消失）。"""
    ent = _faction(props=_PROPS, visibility="private", intro="掌控北岸的军事化政权")
    text = _entity_secret_text(ent)
    assert "理念：秩序高于一切" in text
    assert "一句话：掌控北岸的军事化政权" in text


def test_public_faction_unaffected_by_secret_path():
    """公开势力的分层字段在 secrets 视角同样全量（secrets 只收 private 实体，
    本函数级对拍只验 respect_layers=False 口径不被 visibility 影响）。"""
    ent = _faction(props=_PROPS)
    assert "理念：秩序高于一切" in _entity_secret_text(ent)


# ============================================================
# 3. 知识平面：条目化 + 恒选
# ============================================================

@dataclass
class _Bundle:
    entities: List[Any] = field(default_factory=list)
    assets: List[Any] = field(default_factory=list)
    factions: List[Any] = field(default_factory=list)
    locations: List[Any] = field(default_factory=list)
    relationships: List[Any] = field(default_factory=list)
    open_hooks: List[Any] = field(default_factory=list)
    book: Any = None
    world_sourced: bool = True
    world_state: Dict[str, Any] = field(default_factory=dict)
    world_time: int = 0


def test_knowledge_entries_include_faction():
    from backend.services.context.knowledge_plane import build_knowledge_entries
    bundle = _Bundle(factions=[WorldFactionView(_faction(props=_PROPS, intro="掌控北岸的军事化政权"))])
    entries = build_knowledge_entries(bundle)
    faction_entries = [e for e in entries if e.kind == "faction"]
    assert len(faction_entries) == 1
    e = faction_entries[0]
    assert e.key == "faction:北岸统合局"
    assert "理念：秩序高于一切" in e.body
    assert "统合局" in e.aliases


def test_knowledge_entries_zero_change_without_factions():
    """无 faction 书：零 faction 条目（零变化契约）。"""
    from backend.services.context.knowledge_plane import build_knowledge_entries
    entries = build_knowledge_entries(_Bundle())
    assert not [e for e in entries if e.kind == "faction"]


def test_faction_entry_selected_as_constant():
    """faction 恒选进前缀（软层，逃逸阀可丢）。"""
    from backend.services.context.knowledge_plane import (
        build_knowledge_entries,
        select_knowledge,
    )
    bundle = _Bundle(factions=[WorldFactionView(_faction(props=_PROPS))])
    entries = build_knowledge_entries(bundle)
    selected, unselected, mentioned = select_knowledge(entries, bundle, "")
    assert any(e.kind == "faction" and e.selector == "恒选·势力" for e in selected)


# ============================================================
# 4. 前缀签名：改势力设定必须换签名（防「改了设定前缀不刷新」）
# ============================================================

def test_prefix_signature_changes_with_faction_content():
    from backend.services.context.knowledge_plane import _prefix_signature
    b1 = _Bundle(factions=[WorldFactionView(_faction(props=_PROPS))])
    changed = dict(_PROPS)
    changed["ideology"] = "自由高于秩序"
    b2 = _Bundle(factions=[WorldFactionView(_faction(props=changed))])
    assert _prefix_signature(b1) != _prefix_signature(b2)


def test_prefix_signature_zero_change_without_factions():
    from backend.services.context.knowledge_plane import _prefix_signature
    assert _prefix_signature(_Bundle()) == _prefix_signature(_Bundle(factions=[]))
