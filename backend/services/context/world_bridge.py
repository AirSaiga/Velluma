# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 世界设定层 → 生成流桥接
"""
world_* 六表 → SettingsBundle 的读时映射（docs/reports/world-unified-settings.md §5）。

三原则：读时适配（不动写路径）、世界优先 / 旧表兜底、世界快照作为新增上下文。

- resolve_narrative_time：章节叙事时间四级降级（本章锚 → 前序最近锚 →
  事件最大时刻 → 0），供时间切片推演。
- WorldEntityAdapter / WorldAssetAdapter / WorldRelationAdapter：把 world ORM
  包装成旧 Character/Asset/Relationship 的视图形状——下游消费方
  （hard_constraints / soft_constraints / _characters_text / sediment 冲突检测
  的 `ent.character.static_prompt` 鸭子取值链）零改动吃到世界数据。
  ⚠ 适配器永远携带全量档案（双轨纪律的「算法轨」）——private 过滤只发生在
  settings_bundle 的 prompt 文本装配层（A1，docs/reports/foundation-hardening.md §3.1）。
- load_world_overlay：WorldRepository 一站式加载 + t 时刻切片，供
  settings_bundle 装配；世界页无实体时返回 None（旧表兜底，未迁移书零影响）。
  另产 secrets 通道（A1）：visibility=private 实体（character/faction/asset
  统一）的结构化文本经此暴露——「AI 知晓但绝不能直接写出」（D5 语义）。

副作用：无（纯查询）。警示：本模块绝不写任何表。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, NamedTuple, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chapter, WorldEvent
from backend.repositories.world_repository import WorldRepository
from backend.services.world.field_layers import layered_profile_value

logger = logging.getLogger(__name__)


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

    chapter_number 仅 prev_anchor 时有值（来源章号。A4 来源可见展示用，
    docs/reports/foundation-hardening.md §2.2——纯附加信息，t/source 解析语义零变化）。
    """

    t: int
    source: str
    chapter_number: Optional[int] = None


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

    # ② 前序最近已锚章（顺带取章号——A4「来自第N章锚」展示，不改取值语义）
    stmt = (
        select(Chapter.narrative_time, Chapter.chapter_number)
        .where(
            Chapter.book_id == book_id,
            Chapter.narrative_time.isnot(None),
            Chapter.chapter_number < chapter_number,
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    prev_row = result.first()
    if prev_row is not None:
        return NarrativeTime(
            int(prev_row.narrative_time),
            "prev_anchor",
            int(prev_row.chapter_number) if prev_row.chapter_number is not None else None,
        )

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


def static_prompt_from_world_entity(ent: Any, respect_layers: bool = True) -> str:
    """WorldEntity → 旧 Character.static_prompt 等价文本。

    结构化 props 字段（键：值；M4 收尾后旧档案迁移并入 background，由
    启动数据迁移兜底摘键，这里不再回退读 legacy_profile）。
    下游自带截断（_characters_text 截 200），这里不做长度控制。

    respect_layers（2026-09-03 字段级真相分层）：private 级字段整段隐去、
    partial 级以「表」（public_text）顶替全文；无 field_layers 逐字节零变化。
    整人 private 实体走 secrets 通道时须传 False——全档案本是秘密，再按字段
    拆分会把 private 字段从所有通道抹掉（AI 连知晓都做不到）。
    """
    props = getattr(ent, "props", None) or {}
    if not isinstance(props, dict):
        props = {}
    parts = []
    # 一句话简介（2026-09-04 审计修复：intro 此前不进任何生成通道，而地点
    # intro 进——「标私密反而 AI 才看得见」倒挂）。分层语义与结构化字段一致：
    # private 整句隐去（canon [private] 虚拟条目接管）、partial 以表顶替；
    # 无 intro/无分层逐字节零变化。整人 private（respect_layers=False）随
    # 全档案进 secrets 通道，intro 本就该 AI 知晓。
    intro_raw = str(getattr(ent, "intro", "") or "").strip()
    if intro_raw:
        intro_v = layered_profile_value(ent, "intro", intro_raw) if respect_layers else intro_raw
        if intro_v and str(intro_v).strip():
            parts.append(f"一句话：{str(intro_v).strip()}")
    for key, label in _STRUCTURED_FIELDS:
        v = str(props.get(key) or "").strip()
        if not v:
            continue
        if respect_layers:
            v = layered_profile_value(ent, key, v) or ""
            if not v:
                continue
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
        intro = (getattr(ent, "intro", "") or "")
        # 字段级真相分层（2026-09-03，含一句话）：intro/description 按分层拆分——
        # 秘密整段隐去并回退到下一段未隐去内容，半露以表顶替；无分层逐字节零变化
        # （whitespace-only intro 的旧真值性也保留）。
        intro_v = layered_profile_value(ent, "intro", intro)
        if intro_v:
            self.static_description = intro_v
        else:
            self.static_description = layered_profile_value(ent, "description", desc) or ""
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

# faction 档案字段 → 拼接标签（键与 field_layers.FIELD_LAYER_LABELS 对齐，
# 拼接标签沿用档案装配口径；intro 特例取 ent.intro 非 props，同角色档案）
_FACTION_FIELDS = (
    ("ideology", "理念"),
    ("structure", "组织"),
    ("territory_note", "领地"),
)


def faction_prompt_text(ent: Any, respect_layers: bool = True) -> str:
    """Faction 实体 → prompt 档案文本（2026-09-04 审计修复）。

    faction 此前没有任何 prompt 通路：适配层只装配 character/asset，UI 可编辑
    可分层的理念/组织/领地字段对生成层完全不存在（「AI 所见=作者所见」违例）。
    本函数与 static_prompt_from_world_entity 同构：一句话 intro 打头 +
    三字段拼接；respect_layers 语义一致（private 隐去/partial 以表顶替）；
    整人 private 势力走 secrets 通道时传 False（全档案皆是秘密，不按字段拆）。
    """
    parts: List[str] = []
    intro_raw = str(getattr(ent, "intro", "") or "").strip()
    if intro_raw:
        intro_v = layered_profile_value(ent, "intro", intro_raw) if respect_layers else intro_raw
        if intro_v and str(intro_v).strip():
            parts.append(f"一句话：{str(intro_v).strip()}")
    props = getattr(ent, "props", None) or {}
    if not isinstance(props, dict):
        props = {}
    for key, label in _FACTION_FIELDS:
        v = str(props.get(key) or "").strip()
        if not v:
            continue
        if respect_layers:
            v = layered_profile_value(ent, key, v) or ""
            if not v:
                continue
        parts.append(f"{label}：{v}")
    return "\n".join(parts)


class WorldFactionView:
    """faction → 知识平面条目视图（knowledge_plane 按属性鸭子类型读取）。

    static_prompt 已按 respect_layers=True 拆好——公开势力的私密字段不进
    正文知识块（真相照旧走 canon [private] 虚拟条目）。
    """

    def __init__(self, ent: Any):
        self.world_entity = ent
        self.name = (getattr(ent, "name", "") or "").strip()
        self.static_prompt = faction_prompt_text(ent, respect_layers=True)
        self.aliases = [str(a).strip() for a in (getattr(ent, "aliases", None) or []) if str(a).strip()]
        self.entity_id = str(getattr(ent, "id", "") or "")


def _entity_secret_text(ent: Any) -> str:
    """私有实体的结构化拼接文本（A1 secrets 通道；与各适配器注入正文的口径一致）。

    - character → static_prompt_from_world_entity（八字段结构化拼接，键序即拼接序）
    - faction → faction_prompt_text（2026-09-04 修复：原与 asset 共口径只读
      props.description，faction 字段是 ideology/structure/territory_note →
      文本恒空，私有势力从所有通道静默消失）
    - asset → WorldAssetAdapter.static_description 同口径
      （intro 优先，回退 props.description）
    空文本的私有实体不进通道（无秘密可保，占行反而浪费 prompt）。
    上限截断不在本层——由 prompt 侧 _secrets_block 统一控制（A3a 收编点）。
    """
    etype = getattr(ent, "entity_type", "") or ""
    if etype == "character":
        # 整人 private = 全档案皆是秘密，字段分层不再适用（否则 private 字段会被
        # 从 secrets 通道也抹掉）；故此处显式关闭分层拆分。
        return static_prompt_from_world_entity(ent, respect_layers=False)
    if etype == "faction":
        # 同 character 口径：整人 private 势力不按字段拆
        return faction_prompt_text(ent, respect_layers=False)
    props = getattr(ent, "props", None) or {}
    desc = str(props.get("description") or "").strip() if isinstance(props, dict) else ""
    return (getattr(ent, "intro", "") or "").strip() or desc


async def load_world_overlay(
    book_id: str,
    db: AsyncSession,
    chapter: Any,
) -> Optional[Dict[str, Any]]:
    """加载世界数据覆盖层；世界页无实体时返回 None（旧表兜底）。

    Returns:
        {entities, assets, factions, locations, relationships, world_state, world_time, secrets}
        - entities/relationships 按时间切片排序/过滤：本章时刻有事态的实体优先，
          关系只保留 t 时刻活跃边（static 或锚事件已回放）；本章钉了场景地点时
          在场实体与任一端点在场的活跃边排最前（A2 在场提权，无钉排序与旧逻辑逐一致）
        - factions（2026-09-04 势力通路）：公开 faction 的知识平面视图
          （WorldFactionView；private 走 secrets）
        - secrets（A1 私有通道）：visibility=private 实体（character/faction/asset
          统一，不受 16/8 截断影响——秘密宁全勿缺）的 [{name, text}]。适配器本体
          不动（sediment 冲突检测等算法消费者继续吃全量），过滤发生在
          settings_bundle 的 prompt 文本装配层。
    """
    repo = WorldRepository(db)
    entities_all = await repo.entities.list_by_book(book_id)
    if not entities_all:
        # 数据源决策行：世界页无实体 → 消费方保持旧表数据（未迁移书行为不变）
        logger.info("[world_bridge] 书 %s 无世界实体 → 旧表兜底", book_id)
        return None

    nt = await resolve_narrative_time(db, chapter)
    t = nt.t
    # 世界内核 B1（docs/world-kernel-foundation.md §3）：世界状态消费收口到
    # Fold API 唯一入口——四域模态封闭由此保证，禁止旁路直调仓储折叠
    from backend.services.world.fold import fold as world_fold
    state = (await world_fold(
        db, book_id, t=t, domains=("truth",), perspective_set=(),
    ))["truth"]
    locations = await repo.locations.list_by_book(book_id)
    relations = await repo.relations.list_by_book(book_id)

    entities_by_id = {str(e.id): e for e in entities_all}
    loc_by_id = {str(loc.id): loc for loc in locations}
    char_states: Dict[str, Dict[str, Any]] = {
        str(cs.get("entity_id")): cs for cs in state.get("character_states", [])
    }

    # A2 在场提权（docs/reports/foundation-hardening.md §2.3）：本章钉了场景地点时，
    # 切片时刻位于该地点的实体构成「在场集」作排序第一键——当前场景的次要角色
    # 不再被高重要度远端角色挤出 16 名单。无场景钉时在场集恒空、第一键恒 0，
    # 排序与旧逻辑逐一致（零变化契约）。chapter 走 getattr 防御（鸭子类型对象）。
    # 死者不进在场集：death 不清 location_id，不拦截则尸体原位会一直占在场名额。
    # 场景作用域（location-interior 二期）：钉到房间时祖先（基地）上的角色也算
    # 在场——「在建筑物里」是「在这个房间的场景里」的合理上界；顶层钉=精确匹配同旧。
    from backend.services.world.location_tree import scene_scope_ids

    scene_loc_id = str(getattr(chapter, "scene_location_id", None) or "")
    scene_scope = scene_scope_ids(locations, scene_loc_id)
    present_ids: set = set()
    if scene_scope:
        for eid, cs in char_states.items():
            if not (cs or {}).get("alive", False):
                continue
            if str((cs or {}).get("location_id") or "") in scene_scope:
                present_ids.add(eid)

    # 角色适配：在场 → 切片时刻有事态 → 重要度降序；上限见 budget（prompt 预算护栏）
    characters = [
        WorldEntityAdapter(e, char_states.get(str(e.id)), loc_by_id)
        for e in entities_all
        if e.entity_type == "character"
    ]
    characters.sort(
        key=lambda a: (
            0 if (not scene_loc_id or str(a.world_entity.id) in present_ids) else 1,
            0 if str(a.world_entity.id) in char_states else 1,
            -int(getattr(a.world_entity, "importance", 1) or 1),
        )
    )

    assets_all = [e for e in entities_all if e.entity_type == "asset"]
    assets_all.sort(key=lambda e: -int(getattr(e, "importance", 1) or 1))
    assets = [WorldAssetAdapter(e) for e in assets_all]

    # 势力通路（2026-09-04 审计修复）：公开 faction 的档案进知识平面（恒选，
    # 数量少体量小）；private 势力继续走下方 secrets 通道。无 faction 书恒空
    # 列表，消费侧零行渲染（零变化契约）。
    factions = [
        WorldFactionView(e)
        for e in entities_all
        if e.entity_type == "faction" and (getattr(e, "visibility", None) or "public") == "public"
    ]
    factions.sort(key=lambda v: -int(getattr(v.world_entity, "importance", 1) or 1))

    # 关系：只保留 t 时刻活跃边；有场景钉时任一端点在场的边提前（仍截 budget 上限）
    active_rel_ids = {
        str(rs.get("relation_id"))
        for rs in state.get("relation_states", [])
        if rs.get("active")
    }
    relationships = [
        WorldRelationAdapter(r, entities_by_id)
        for r in relations
        if str(r.id) in active_rel_ids
    ]
    if scene_loc_id:
        relationships.sort(
            key=lambda ra: (
                0
                if (
                    str(ra.world_relation.source_entity_id) in present_ids
                    or str(ra.world_relation.target_entity_id) in present_ids
                )
                else 1
            )
        )

    # A1 私有通道（docs/reports/foundation-hardening.md §3.1，D5 拍板）：private 实体的
    # 档案不进正文上下文（过滤在 settings_bundle 装配层），改走 secrets——
    # AI 知晓这些秘密以协助铺垫与暗示，但 prompt 侧要求绝不直接写出。
    # 无私有实体 → 空列表（下游块渲染零变化）。
    secrets: List[Dict[str, Any]] = []
    for e in entities_all:
        if (getattr(e, "visibility", None) or "public") != "private":
            continue
        text = _entity_secret_text(e)
        if (e.name or "").strip() and text:
            secrets.append({"name": (e.name or "").strip(), "text": text})

    # 数据源决策行：world 优先命中面（t 切片时刻/来源 + 各池计数）
    logger.info(
        "[world_bridge] 书 %s → world 优先（t=%d 源=%s 角色=%d 资产=%d 势力=%d "
        "地点=%d 活跃关系=%d 秘密=%d）",
        book_id, t, nt.source, len(characters), len(assets), len(factions),
        len(locations), len(relationships), len(secrets),
    )
    return {
        "entities": characters,
        "assets": assets,
        "factions": factions,
        # 知识检索平面 v3.1（2026-08-27）：实体/资产/关系/地点的数量上限全部退役——
        # 选择（在场/提及/邻近）在消费侧 knowledge_plane 完成，桥接层只排序不裁剪；
        # 排序（在场→有事态→重要度）保留，供 UI 与选择器复用同一顺序
        "locations": locations,
        "relationships": relationships,
        "world_state": state,
        "world_time": t,
        "world_time_source": nt.source,
        "secrets": secrets,
    }
