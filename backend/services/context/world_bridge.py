# Velluma - 世界设定层 → 生成流桥接
# AGPL-3.0
"""
world_* 六表 → SettingsBundle 的读时映射（docs/world-unified-settings.md §5）。

三原则：读时适配（不动写路径）、世界优先 / 旧表兜底、世界快照作为新增上下文。

- resolve_narrative_time：章节叙事时间四级降级（本章锚 → 前序最近锚 →
  事件最大时刻 → 0），供时间切片推演。
- WorldEntityAdapter / WorldAssetAdapter / WorldRelationAdapter：把 world ORM
  包装成旧 Character/Asset/Relationship 的视图形状——下游消费方
  （hard_constraints / soft_constraints / _characters_text / sediment 冲突检测
  的 `ent.character.static_prompt` 鸭子取值链）零改动吃到世界数据。
- load_world_overlay：WorldRepository 一站式加载 + t 时刻切片，供
  settings_bundle 装配；世界页无实体时返回 None（旧表兜底，未迁移书零影响）。

副作用：无（纯查询）。警示：本模块绝不写任何表。
"""
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chapter, WorldEvent
from backend.repositories.world_repository import WorldRepository


# ============================================================
# 叙事时间解析（时间切片的 t 从哪来）
# ============================================================

class NarrativeTime(NamedTuple):
    """叙事时刻解析结果（docs/world-writing-bridge.md §4.1）。

    source 四级降级来源：
    - chapter_anchor：本章 narrative_time（世界页时间轴右键锚定）
    - prev_anchor：前序最近已锚章
    - max_event：事件流最大 time_start（"写到最远处"）
    - zero：空世界兜底
    """

    t: int
    source: str


async def resolve_narrative_time(db: AsyncSession, chapter: Any) -> NarrativeTime:
    """四级降级解析本章的世界时间切片时刻 t（带来源）。

    ① 本章 narrative_time（世界页时间轴右键锚定）
    ② 前序最近已锚章（chapter_number 更小且 narrative_time 非空的最大者）
    ③ 事件流最大 time_start（世界至少有事件，取"写到最远处"）
    ④ 0（空世界兜底，与 GET /world/state 默认一致）
    """
    nt = getattr(chapter, "narrative_time", None)
    if nt is not None:
        return NarrativeTime(int(nt), "chapter_anchor")

    book_id = getattr(chapter, "book_id", None)
    if book_id is None:
        return NarrativeTime(0, "zero")
    chapter_number = getattr(chapter, "chapter_number", None) or 0

    # ② 前序最近已锚章
    stmt = (
        select(Chapter.narrative_time)
        .where(
            Chapter.book_id == book_id,
            Chapter.narrative_time.isnot(None),
            Chapter.chapter_number < chapter_number,
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    prev = result.scalar_one_or_none()
    if prev is not None:
        return NarrativeTime(int(prev), "prev_anchor")

    # ③ 事件最大时刻
    stmt2 = select(func.max(WorldEvent.time_start)).where(WorldEvent.book_id == book_id)
    r2 = await db.execute(stmt2)
    max_ev = r2.scalar_one_or_none()
    if max_ev is not None:
        return NarrativeTime(int(max_ev), "max_event")

    return NarrativeTime(0, "zero")


# ============================================================
# 视图适配器（world ORM → 旧形状鸭子类型）
# ============================================================

class _Ns:
    """简单只读命名空间（视图对象）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# 结构化档案字段 → 中文标签（props 键序即拼接序）
_STRUCTURED_FIELDS = (
    ("appearance", "外貌"),
    ("personality", "性格"),
    ("background", "背景"),
    ("goal", "目标"),
    ("motive", "动机"),
    ("speech_style", "语言习惯"),
    ("habits", "习惯"),
    ("skills", "技能"),
)


def static_prompt_from_world_entity(ent: Any) -> str:
    """WorldEntity → 旧 Character.static_prompt 等价文本。

    结构化 props 字段（键：值；M4 收尾后旧档案迁移并入 background，由
    启动数据迁移兜底摘键，这里不再回退读 legacy_profile）。
    下游自带截断（_characters_text 截 200），这里不做长度控制。
    """
    props = getattr(ent, "props", None) or {}
    if not isinstance(props, dict):
        props = {}
    parts = []
    for key, label in _STRUCTURED_FIELDS:
        v = str(props.get(key) or "").strip()
        if v:
            parts.append(f"{label}：{v}")
    return "\n".join(parts)


def dynamic_state_text(
    char_state: Optional[Dict[str, Any]],
    loc_by_id: Dict[str, Any],
) -> str:
    """时间切片的 character_state → 旧 Character.dynamic_state 等价文本。

    「位于北岸要塞」「在途（进度 40%），位于官道」「已死亡」；
    无事态记录（该实体没录过事件）返回空串——下游 `if dynamic:` 自然跳过。
    """
    if not isinstance(char_state, dict) or not char_state:
        return ""
    if not char_state.get("alive", False):
        return "已死亡"
    parts: List[str] = []
    loc = loc_by_id.get(str(char_state.get("location_id") or ""))
    loc_name = (getattr(loc, "name", "") or "") if loc is not None else ""
    if loc_name:
        parts.append(f"位于{loc_name}")
    label = str(char_state.get("label") or "").strip()
    if label:
        parts.append(label)
    return "，".join(parts)


class WorldEntityAdapter:
    """WorldEntity(character) → 旧 ChapterEntity 视图形状。

    访问链兼容：ent.character.name / .static_prompt / .dynamic_state / .aliases /
    .importance_level（importance 1-10 归一到旧 1-4 口径）。
    """

    def __init__(self, ent: Any, char_state: Optional[Dict[str, Any]], loc_by_id: Dict[str, Any]):
        self.world_entity = ent  # 原始引用（后续阶段消费）
        imp = int(getattr(ent, "importance", 1) or 1)
        self.character = _Ns(
            name=ent.name or "",
            static_prompt=static_prompt_from_world_entity(ent),
            dynamic_state=dynamic_state_text(char_state, loc_by_id),
            aliases=list(getattr(ent, "aliases", None) or []),
            importance_level=max(1, min(4, (imp + 2) // 3)),
        )


class WorldAssetAdapter:
    """WorldEntity(asset) → 旧 Asset 视图形状（name / static_description / current_state）。"""

    def __init__(self, ent: Any):
        self.world_entity = ent
        self.name = ent.name or ""
        props = getattr(ent, "props", None) or {}
        desc = str(props.get("description") or "").strip() if isinstance(props, dict) else ""
        self.static_description = (getattr(ent, "intro", "") or "") or desc
        # 资产无静态时变状态（事件溯源哲学）；空串 → 下游 asset_states 自然跳过
        self.current_state = ""


class WorldRelationAdapter:
    """WorldRelation → 旧 CharacterRelationship 视图形状。

    _relationships_text 消费 source_character.name / target_character.name /
    relationship_type / description。
    """

    def __init__(self, rel: Any, entities_by_id: Dict[str, Any]):
        self.world_relation = rel
        src = entities_by_id.get(str(rel.source_entity_id))
        tgt = entities_by_id.get(str(rel.target_entity_id))
        self.source_character = _Ns(name=(src.name or "") if src is not None else "")
        self.target_character = _Ns(name=(tgt.name or "") if tgt is not None else "")
        self.relationship_type = rel.relation_type or "custom"
        note = str(getattr(rel, "note", "") or "").strip()
        label = str(getattr(rel, "label", "") or "").strip()
        self.description = f"{label}（{note}）" if label and note else (label or note)


# ============================================================
# overlay 装配（settings_bundle 调用）
# ============================================================

async def load_world_overlay(
    book_id: str,
    db: AsyncSession,
    chapter: Any,
) -> Optional[Dict[str, Any]]:
    """加载世界数据覆盖层；世界页无实体时返回 None（旧表兜底）。

    Returns:
        {entities, assets, locations, relationships, world_state, world_time}
        - entities/relationships 按时间切片排序/过滤：本章时刻有事态的实体优先，
          关系只保留 t 时刻活跃边（static 或锚事件已回放）
    """
    repo = WorldRepository(db)
    entities_all = await repo.entities.list_by_book(book_id)
    if not entities_all:
        return None

    nt = await resolve_narrative_time(db, chapter)
    t = nt.t
    state = await repo.compute_world_state(book_id, t)
    locations = await repo.locations.list_by_book(book_id)
    relations = await repo.relations.list_by_book(book_id)

    entities_by_id = {str(e.id): e for e in entities_all}
    loc_by_id = {str(loc.id): loc for loc in locations}
    char_states: Dict[str, Dict[str, Any]] = {
        str(cs.get("entity_id")): cs for cs in state.get("character_states", [])
    }

    # 角色适配：切片时刻有事态者优先，其次重要度；上限 16（prompt 预算护栏）
    characters = [
        WorldEntityAdapter(e, char_states.get(str(e.id)), loc_by_id)
        for e in entities_all
        if e.entity_type == "character"
    ]
    characters.sort(
        key=lambda a: (
            0 if str(a.world_entity.id) in char_states else 1,
            -int(getattr(a.world_entity, "importance", 1) or 1),
        )
    )
    characters = characters[:16]

    assets_all = [e for e in entities_all if e.entity_type == "asset"]
    assets_all.sort(key=lambda e: -int(getattr(e, "importance", 1) or 1))
    assets = [WorldAssetAdapter(e) for e in assets_all[:8]]

    # 关系：只保留 t 时刻活跃边
    active_rel_ids = {
        str(rs.get("relation_id"))
        for rs in state.get("relation_states", [])
        if rs.get("active")
    }
    relationships = [
        WorldRelationAdapter(r, entities_by_id)
        for r in relations
        if str(r.id) in active_rel_ids
    ][:8]

    return {
        "entities": characters,
        "assets": assets,
        "locations": locations[:12],  # WorldLocation 自带 name，_locations_text 直接吃
        "relationships": relationships,
        "world_state": state,
        "world_time": t,
        "world_time_source": nt.source,
    }
