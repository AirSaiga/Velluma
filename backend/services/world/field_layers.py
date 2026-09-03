# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""实体档案字段级真相分层（2026-09-03）——共享判据唯一权威。

字段内容本身即「里」（作者不两边维护）；分层元数据存 world_entities.field_layers：
    {field_key: {level: "private"|"partial", public_text?: str, reveal_chapter?: int|null}}
缺键 = 公开（零存储）。本模块是纯函数层，被以下消费线共用：
    - world_bridge.static_prompt_from_world_entity（档案拼装拆分）
    - canon/consistency.py build_canon_context_for_prompt（[private] 虚拟条目注入）
    - canon/consistency.py check_consistency（泄密短语源扩展）
    - repositories/intent_repository.read_merge_reveals（揭示临近第三来源）
    - validation/ghost_guard（上屏前泄底快检扩展）

标签口径对齐前端 entitySchema（说话风格/能力），与 world_bridge._STRUCTURED_FIELDS
的既有拼接标签（语言习惯/技能）是两套词——后者为零变化契约不动。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

# 档案字段 key → 用户词标签（对齐 frontend/src/features/world/engine/entitySchema.ts）
FIELD_LAYER_LABELS: Dict[str, str] = {
    # 一句话简介（2026-09-03 实测补入：作者最常把混合内容写在这里——
    # 「飞行速度很快」是表，「5 马赫/10G」是里；全文不在 props 而在 ent.intro）
    "intro": "一句话",
    # character
    "appearance": "外貌",
    "personality": "性格",
    "background": "背景",
    "goal": "目标",
    "motive": "动机",
    "speech_style": "说话风格",
    "habits": "习惯",
    "skills": "能力",
    # faction
    "ideology": "理念",
    "structure": "组织结构",
    "territory_note": "领地说明",
    # asset
    "description": "描述",
    "origin": "来历",
}

INTRO_FIELD_KEY = "intro"

LEVEL_PRIVATE = "private"  # 秘密：只有 AI 知道，绝不直接写出
LEVEL_PARTIAL = "partial"  # 半露：读者只知 public_text（表），其余 AI 死守


@dataclass(frozen=True)
class FieldLayerEntry:
    """一条分层字段的规范化视图（full_text 来自 props，空全文不产生条目）。"""

    field_key: str
    label: str
    level: str  # LEVEL_PRIVATE / LEVEL_PARTIAL（其余值不入迭代）
    full_text: str
    public_text: str  # 表；仅 partial 有意义，可空
    reveal_chapter: Optional[int]


def get_field_layers(ent: Any) -> Dict[str, Any]:
    """防御性读取 ent.field_layers（非 dict / None / 坏行一律兜底）。"""
    raw = getattr(ent, "field_layers", None)
    return raw if isinstance(raw, dict) else {}


def iter_field_layers(ent: Any) -> Iterator[FieldLayerEntry]:
    """遍历实体的分层字段（仅 private/partial 且全文字段非空的条目）。"""
    layers = get_field_layers(ent)
    if not layers:
        return
    props = getattr(ent, "props", None)
    props = props if isinstance(props, dict) else {}
    for key, spec in layers.items():
        if not isinstance(spec, dict):
            continue
        level = str(spec.get("level") or "")
        if level not in (LEVEL_PRIVATE, LEVEL_PARTIAL):
            continue
        if str(key) == INTRO_FIELD_KEY:
            full = str(getattr(ent, "intro", "") or "").strip()
        else:
            full = str(props.get(key) or "").strip()
        if not full:
            continue
        public_text = str(spec.get("public_text") or "").strip()
        raw_ch = spec.get("reveal_chapter")
        try:
            reveal_chapter = int(raw_ch) if raw_ch is not None and str(raw_ch).strip() else None
        except (TypeError, ValueError):
            reveal_chapter = None
        if reveal_chapter is not None and reveal_chapter <= 0:
            reveal_chapter = None
        yield FieldLayerEntry(
            field_key=str(key),
            label=FIELD_LAYER_LABELS.get(str(key), str(key)),
            level=level,
            full_text=full,
            public_text=public_text,
            reveal_chapter=reveal_chapter,
        )


def layered_profile_value(ent: Any, field_key: str, full_text: str) -> Optional[str]:
    """档案装配侧单字段取值：返回 None = 该字段不进档案文本。

    - private → None（整段隐去，真相走 canon [private] 虚拟条目）
    - partial → public_text（表顶替全文）；表为空 = 安全缺省按 private → None
    - 未分层 → full_text 原样（零变化契约）
    """
    spec = get_field_layers(ent).get(field_key)
    if not isinstance(spec, dict):
        return full_text
    level = str(spec.get("level") or "")
    if level == LEVEL_PRIVATE:
        return None
    if level == LEVEL_PARTIAL:
        public_text = str(spec.get("public_text") or "").strip()
        return public_text or None
    return full_text
