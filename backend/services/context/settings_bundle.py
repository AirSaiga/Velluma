# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 自适应辅助设定数据加载器（NLE-ADF 3.0）
"""
作者主导写作流程的设定数据共享加载器。

设计意图：把原本锁在「整章生成管线」里的设定数据查询能力解放出来，
供自适应辅助（perceive / stitch-ghost / settle / detect-branch / plan-suggest）
端点共用。所有查询均不依赖生成 run，只吃 chapter_id + db session。

三池数据：
1. 章级绑定（角色/资产/地点/关系/开放伏笔）—— load_full_chapter_context
2. 书级 Canon 图谱（[public] 已建立事实 / [private] 秘密真相）—— build_canon_context_for_prompt
3. 世界观设定 —— build_worldview_text

副作用：无（纯查询）。警示：Canon/世界观加载失败降级为空，不阻塞辅助。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories import (
    AssetRepository,
    ChapterAssetRepository,
    ChapterRepository,
    MapLocationRepository,
    MemoryRepository,
    PlotLedgerRepository,
    RelationshipRepository,
    BookRepository,
    StyleCardRepository,
)
from backend.services.context.budget import (
    BANNED_WORDS_MERGED_MAX_ENTRIES,
    CORE_MOTIFS_MAX_CHARS,
    PROPER_NOUNS_MAX_ENTRIES,
    READER_EXPECTATION_DESC_MAX_CHARS,
    READER_EXPECTATION_MAX_ENTRIES,
    ROLLING_SUMMARY_MAX_CHARS,
    STYLE_PARAGRAPH_RHYTHM_MAX_CHARS,
    STYLE_POSITIVE_MAX_LINES,
    STYLE_PROFILE_VALUE_MAX_CHARS,
)
from backend.services.context.loader import load_full_chapter_context
from backend.services.canon.consistency import build_canon_context_for_prompt
from backend.services.workflows.adf.setting_resolver import build_worldview_text

logger = logging.getLogger(__name__)


# ============================================================
# 设定 bundle 数据容器
# ============================================================

@dataclass
class SettingsBundle:
    """自适应辅助的设定数据一次性快照。

    所有 adaptive 端点共用此结构，避免重复查询 DB。
    字段全部允许为空（降级路径：设定缺失时辅助仍可跑，只是建议变弱）。
    设定分三级（hard_constraints / soft_constraints / nutrients），校对强度不同。
    """
    chapter: Any = None
    book: Any = None
    # 章级绑定（作者在资产面板勾选的）
    entities: List[Any] = field(default_factory=list)
    assets: List[Any] = field(default_factory=list)
    locations: List[Any] = field(default_factory=list)
    relationships: List[Any] = field(default_factory=list)
    open_hooks: List[Any] = field(default_factory=list)
    previous_summary: Optional[str] = None
    # 书级 Canon 图谱
    canon_context: str = ""
    # 世界观设定
    worldview_text: str = ""
    # 章节卡（must_hit_events / foreshadow_ops / continuity / purpose / word_target）
    chapter_card: Any = None
    # 文风卡（negative_list / positive_profile / dialogue_ratio_target）
    style_card: Any = None
    # 书级硬约束
    core_motifs_taboos: str = ""
    rolling_summary: str = ""
    # 章节元信息（便捷访问）
    chapter_id: str = ""
    book_id: Optional[str] = None
    chapter_number: Optional[int] = None
    outline_text: str = ""
    content_text: str = ""
    # ---- 世界设定层桥接（world_bridge；docs/reports/world-unified-settings.md §5）----
    # world 优先时 entities/assets/locations/relationships 已换为适配器视图对象
    world_sourced: bool = False
    # 势力通路（2026-09-04 审计修复）：公开 faction 的知识平面视图
    # （WorldFactionView，static_prompt 已按字段分层拆好）。无 faction 书恒空
    # 列表，消费侧零行渲染（零变化契约）。
    factions: List[Any] = field(default_factory=list)
    world_time: int = 0  # 时间切片时刻 t（叙事时间四级降级解析）
    # t 的解析来源（A4/B2 来源可见性；load_world_overlay 透传，零行为变化）：
    # chapter_anchor=本章锚 | prev_anchor=前序最近锚 | max_event=事件最大时刻 | zero=空世界
    world_time_source: str = "zero"
    world_state: Dict[str, Any] = field(default_factory=dict)  # t 时刻推演快照
    # D4-3 空间常识块（docs/reports/map-scale-spatial.md §5）：双门槛（world_sourced 且
    # 已标定）才有内容；未标定恒空串——四模式 prompt 逐字节零变化
    spatial_brief: str = ""
    # A1 私有通道（docs/reports/foundation-hardening.md §3.1，D5 语义「AI 知晓但绝不
    # 直接写出」）：visibility=private 世界实体（character/faction/asset 统一）的
    # [{name, text}]，由 world_bridge.load_world_overlay 供给。进 prompt 走
    # adaptive_prompts._secrets_block（canon 块后）；_characters_text 等装配层
    # 同步排除这些实体（双轨纪律：文本轨排除 private props，算法轨吃适配器全量）。
    character_secrets: List[Dict[str, str]] = field(default_factory=list)
    # 字段级真相分层（2026-09-03）：分层档案字段的快检源
    # [{name, label, level, text, public_text}]——prompt 轨由 canon [private]
    # 虚拟条目承载（consistency.py），本列表供 ghost_guard 上屏前泄底快检
    # （secret_leak 同款判据，partial 剔除表短语）；整人 private 实体不入列
    # （其档案已整体在 character_secrets）。
    field_layer_secrets: List[Dict[str, str]] = field(default_factory=list)
    # ---- 禁忌面归一（任务包 A，services/style/prohibitions.py 唯一权威）----
    # 四源合并（SystemCliche + negative_list + style_blacklist + 静态反 AI 词）
    # 的编译视图。None = 未加载/加载失败——任务包 B 起旧三源合并回退已删，
    # None 时消费侧降级为空（load_prohibition_set 内部各层独立降级，整体
    # None 仅在极端异常时出现）。类型 Any：避免与 ORM 层耦合。
    prohibitions: Any = None
    # ---- 写作规矩按书覆盖（质感契约收编批）----
    # 系统质感契约（services/style/texture_contracts.py 唯一权威）的本书
    # 定制：{contract_key: {"body": str}}。None/{} = 全部系统默认（prompt
    # 逐字节零变化）；body 覆盖只换正文，块头「最高优先级」框定恒由系统持有。
    texture_contracts: Optional[Dict[str, Dict[str, str]]] = None

    def to_prompt_context(self) -> Dict[str, Any]:
        """生成供 prompt 拼接的扁平 dict（文本化版本）。

        调用方据此拼 prompt，不必关心 ORM 结构。
        """
        return {
            "characters": _characters_text(self.entities),
            "assets": _assets_text(self.assets),
            "locations": _locations_text(self.locations),
            "relationships": _relationships_text(self.relationships),
            "canon_context": self.canon_context,
            # A1 私有通道：结构化 [{name, text}]（渲染口径统一在
            # adaptive_prompts._secrets_block，此处不做文本拼接）
            "character_secrets": self.character_secrets,
            "worldview_text": self.worldview_text,
            "open_hooks": _hooks_text(self.open_hooks),
            "outline_text": self.outline_text,
            "previous_summary": self.previous_summary or "",
            "chapter_card": _chapter_card_text(self.chapter_card),
            # 禁忌面归一：prohibitions 已加载时走唯一权威（四源合并、全量——
            # 知识检索平面 v3.1：条目截断退役，选中即完整）；None 降级空串
            "style_negative": (
                "、".join(self.prohibitions.words(10 ** 6))
                if self.prohibitions is not None
                else ""
            ),
            "style_positive": render_style_positive(self.style_card),
            "rolling_summary": self.rolling_summary[:ROLLING_SUMMARY_MAX_CHARS] if self.rolling_summary else "",
            "core_motifs_taboos": self.core_motifs_taboos[:CORE_MOTIFS_MAX_CHARS] if self.core_motifs_taboos else "",
        }

    # ===== 分级访问：校对强度不同 =====

    def hard_constraints(self) -> Dict[str, Any]:
        """硬约束（违反=设定崩坏，组件必须校对拦截）。

        - canon_private_labels：Canon [private] 节点的标签词（正文不许直接说出）
        - canon_public_facts：Canon [public] 已建立事实（必须一致）
        - banned_words：禁词合并（StyleCard.negative_list + 禁词表等四源，prohibitions 唯一权威；
          全量，供 prompt 注入）
        - banned_words_blocker：仅 blocker 硬禁档（生成侧 _violates 校对专用，提醒级不拦）
        - character_statics：角色永恒设定（防 OOC）。⚠ A1 起排除 private 实体——
          唯一消费方 build_dock_generator_prompt 把它拼进挂件生发 prompt（prompt
          轨必须排除 private props）；算法轨需要全量档案的（如 sediment 冲突检测）
          直读适配器 ent.character.static_prompt，不走本字段（双轨纪律）
        - core_motifs_taboos：书级核心母题禁忌
        """
        return {
            "canon_private_labels": _extract_canon_private_labels(self.canon_context),
            "canon_public_facts": _extract_canon_public_facts(self.canon_context),
            # 禁忌面归一：prohibitions 已加载时走唯一权威（四源合并、前
            # BANNED_WORDS_MERGED_MAX_ENTRIES 条）；None（极端加载失败）降级空表
            "banned_words": (
                self.prohibitions.words(BANNED_WORDS_MERGED_MAX_ENTRIES)
                if self.prohibitions is not None
                else []
            ),
            # 生成侧校对专用（2026-08-25 A2 修复）：只收 blocker 硬禁档。
            # 提醒级词归 prompt 软提醒与审计统计，不再把挂件/走向卡静默杀死
            # （事故：负面清单误录角色名，锚定挂件被 _violates 全部丢弃）
            "banned_words_blocker": (
                self.prohibitions.words(BANNED_WORDS_MERGED_MAX_ENTRIES, severity="blocker")
                if self.prohibitions is not None
                else []
            ),
            "character_statics": {
                _entity_name(e): (_get_attr_nested(e, "character", "static_prompt") or "")
                for e in self.entities
                if _entity_name(e) and not _entity_is_private(e)
            },
            "core_motifs_taboos": self.core_motifs_taboos or "",
        }

    def soft_constraints(self) -> Dict[str, Any]:
        """软约束（参考，可偏离，偏离要感知）。"""
        return {
            "character_dynamics": {
                _entity_name(e): (_get_attr_nested(e, "character", "dynamic_state") or "")
                for e in self.entities if _entity_name(e)
            },
            "asset_states": {
                (getattr(a, "name", "") or ""): (getattr(a, "current_state", "") or "")
                for a in self.assets if getattr(a, "name", "")
            },
            "open_hooks": _hooks_text(self.open_hooks),
            "must_hit_events": _must_hit_events_text(self.chapter_card),
            "foreshadow_ops": _foreshadow_ops_text(self.chapter_card),
            # 读者期待（书级 reader_mirror JSONB，随 book 对象零额外查询）：
            # 活跃条目按张力降序前 3，供方向权重（读者力）与 dock 零件生发消费
            "reader_expectations": _reader_expectations_view(self.book),
            # 文风画像（S2 E2）：正面画像文本化（句长节奏/词汇层级等五维 + 段落节奏 +
            # 对话占比目标），stitch-ghost 各模式 prompt 与心跳组件经此获得——
            # 此前 adaptive 只消费负面清单，作者填得最认真的正面画像进不了主线
            "style_positive": render_style_positive(self.style_card),
        }

    def nutrients(self) -> Dict[str, Any]:
        """养料（生成素材，自由使用）。"""
        return {
            "characters": _characters_text(self.entities),
            "assets": _assets_text(self.assets),
            "locations": _locations_text(self.locations),
            "relationships": _relationships_text(self.relationships),
            "worldview_text": self.worldview_text,
            "previous_summary": self.previous_summary or "",
            "rolling_summary": self.rolling_summary[:ROLLING_SUMMARY_MAX_CHARS] if self.rolling_summary else "",
            "purpose": _get_attr(self.chapter_card, "purpose") or "",
        }

    def proper_nouns(self, limit: int = PROPER_NOUNS_MAX_ENTRIES) -> List[str]:
        """提取角色名 + 资产名 + 势力名（专名表，防缝合时称呼漂移）。"""
        names: List[str] = []
        for e in self.entities:
            name = _entity_name(e)
            if name and name not in names:
                names.append(name)
        for a in self.assets:
            name = getattr(a, "name", "") or ""
            if name and name not in names:
                names.append(name)
        for f in self.factions:  # 势力通路（2026-09-04）：AI 必须能原样称呼它看得见的势力
            name = getattr(f, "name", "") or ""
            if name and name not in names:
                names.append(name)
        return names[:limit]


def _reader_expectations_view(book: Any) -> List[Dict[str, Any]]:
    """从 Book.reader_mirror JSONB 提取活跃期待（方向权重读者力 / dock 零件生发用）。

    只暴露 type / description(截40字) / tension 三字段——张力数字进权重算法，
    描述文本进 dock prompt，均有界。账本缺失/损坏一律降级为空列表（不阻塞辅助层）。
    """
    raw = getattr(book, "reader_mirror", None) if book is not None else None
    if not isinstance(raw, dict):
        return []
    items = raw.get("expectations") or []
    active = [
        e for e in items
        if isinstance(e, dict) and e.get("status") in ("setup", "accumulating")
    ]
    active.sort(key=lambda e: -(e.get("current_tension") or 0))
    return [
        {
            "type": e.get("type") or "",
            "description": (e.get("description") or "")[:READER_EXPECTATION_DESC_MAX_CHARS],
            "tension": e.get("current_tension") or 5,
        }
        for e in active[:READER_EXPECTATION_MAX_ENTRIES]
        if e.get("description")
    ]


# ============================================================
# 主加载入口
# ============================================================

async def load_chapter_settings_bundle(
    chapter_id: str,
    db: AsyncSession,
) -> SettingsBundle:
    """加载自适应辅助所需的全套设定数据（一次查询）。

    不依赖生成 run。任何子查询失败降级为空字段，绝不抛异常阻塞辅助。

    Args:
        chapter_id: 章节 ID
        db: 异步 DB session

    Returns:
        SettingsBundle：即使全失败也返回结构完整的空 bundle
    """
    bundle = SettingsBundle(chapter_id=chapter_id)

    # ---- 章节本体 + 书 ----
    chapter_repo = ChapterRepository(db)
    book_repo = BookRepository(db)
    try:
        chapter = await chapter_repo.get_by_id(chapter_id)
    except Exception as e:
        logger.debug("[settings_bundle] 章节本体查询降级: %s", e)
        chapter = None
    if not chapter:
        return bundle  # 章节不存在，返回空 bundle
    bundle.chapter = chapter
    bundle.book_id = str(chapter.book_id) if chapter.book_id else None
    bundle.chapter_number = getattr(chapter, "chapter_number", None)
    bundle.outline_text = getattr(chapter, "outline_text", "") or ""
    bundle.content_text = getattr(chapter, "content_text", "") or ""

    if bundle.book_id:
        try:
            bundle.book = await book_repo.get_by_id(bundle.book_id)
        except Exception as e:
            logger.debug("[settings_bundle] 书档案查询降级: %s", e)
            bundle.book = None

    # ---- 章级绑定池（角色/资产/地点/关系/伏笔）----
    repos = _build_repos(db)
    try:
        ctx = await load_full_chapter_context(chapter_id, repos)
    except Exception as e:
        logger.debug("[settings_bundle] 章级绑定池加载降级: %s", e)
        ctx = None
    if ctx:
        bundle.entities = ctx.entities or []
        bundle.assets = ctx.assets or []
        bundle.locations = ctx.locations or []
        bundle.relationships = ctx.relationships or []
        bundle.open_hooks = ctx.open_hooks or []
        bundle.previous_summary = ctx.previous_summary

    # ---- 世界设定层桥接：world 优先 / 旧表兜底（读时映射，不动写路径）----
    # 世界页有实体 → entities/assets/locations/relationships 覆盖为 world 适配器
    # （旧形状视图对象，下游 hard/soft/nutrients 零改动），并携带 t 时刻推演快照。
    # 世界页无实体 / 桥接失败 → 保持旧表数据（未迁移书行为与现状完全一致）。
    if bundle.book_id:
        try:
            from backend.services.context.world_bridge import load_world_overlay
            overlay = await load_world_overlay(bundle.book_id, db, chapter)
            if overlay is not None:
                bundle.entities = overlay["entities"]
                bundle.assets = overlay["assets"]
                # 势力通路（2026-09-04 审计修复）：公开 faction 的知识平面视图
                bundle.factions = overlay.get("factions") or []
                bundle.locations = overlay["locations"]
                bundle.relationships = overlay["relationships"]
                bundle.world_state = overlay["world_state"]
                bundle.world_time = overlay["world_time"]
                bundle.world_time_source = overlay.get("world_time_source") or "zero"
                # A1 私有通道：private 实体档案走 secrets（prompt 侧 _secrets_block
                # 消费）；entities/assets 装配层已同步排除（见 _characters_text 等）
                bundle.character_secrets = overlay.get("secrets") or []
                # 字段级真相分层（2026-09-03）：适配器算法轨自带全量
                # world_entity，从此派生快检源（零额外查询）
                from backend.services.world.field_layers import iter_field_layers
                fl_secrets: List[Dict[str, str]] = []
                for _ad in list(bundle.entities) + list(bundle.assets) + list(bundle.factions):
                    _ent = getattr(_ad, "world_entity", None)
                    if _ent is None or getattr(_ent, "visibility", "public") == "private":
                        continue
                    for _e in iter_field_layers(_ent):
                        fl_secrets.append({
                            "name": getattr(_ent, "name", "") or "",
                            "label": _e.label,
                            "level": _e.level,
                            "text": _e.full_text,
                            "public_text": _e.public_text,
                        })
                bundle.field_layer_secrets = fl_secrets
                bundle.world_sourced = True
        except Exception as e:
            # 降级：world 桥失败走旧表（辅助不因桥接阻塞）；DEBUG 显形防静默
            logger.debug("[settings_bundle] world 桥降级走旧表: %s", e)

    # ---- D4-3 空间常识块（双门槛：world_sourced 且已标定；失败静默空串零变化） ----
    if bundle.world_sourced and bundle.book_id:
        try:
            from backend.models import Book as _Book
            _book = await db.get(_Book, bundle.book_id)
            if _book is not None and getattr(_book, "map_scale", None):
                from backend.services.world.scene_slice import build_scene_slice
                _slice = await build_scene_slice(db, bundle.book_id, bundle.chapter)
                bundle.spatial_brief = _slice.get("spatial_brief") or ""
        except Exception as e:
            logger.debug("[settings_bundle] 空间常识块降级为空: %s", e)
            bundle.spatial_brief = ""

    # ---- 书级 Canon 图谱 ----
    if bundle.book_id:
        try:
            bundle.canon_context = await build_canon_context_for_prompt(
                db, bundle.book_id, chapter_number=bundle.chapter_number,
            )
        except Exception as e:
            logger.debug("[settings_bundle] Canon 上下文降级为空: %s", e)
            bundle.canon_context = ""

    # ---- 世界观设定 ----
    if bundle.book:
        try:
            bundle.worldview_text = build_worldview_text(bundle.book)
        except Exception as e:
            logger.debug("[settings_bundle] 世界观文本降级为空: %s", e)
            bundle.worldview_text = ""

    # ---- 章节卡（must_hit_events / foreshadow_ops / continuity / purpose）----
    if bundle.book_id:
        try:
            from backend.models import ChapterCard
            cc_result = await db.execute(
                select(ChapterCard).where(ChapterCard.chapter_id == chapter_id).limit(1)
            )
            bundle.chapter_card = cc_result.scalar_one_or_none()
            # 生效 StyleCard（Phase 4 整卡覆盖语义）：章级特例卡存在即为本章
            # 完整文风定义（负面清单亦整体替换书级），否则回退书级卡。
            bundle.style_card = await StyleCardRepository(db).get_effective_card(
                bundle.book_id, chapter_id,
            )
        except Exception as e:
            logger.debug("[settings_bundle] 章节/文风卡加载降级: %s", e)

    # ---- 书级硬约束 ----
    if bundle.book:
        bundle.core_motifs_taboos = getattr(bundle.book, "core_motifs_taboos", "") or ""
        bundle.rolling_summary = getattr(bundle.book, "rolling_summary", "") or ""

    # ---- 写作规矩按书覆盖（质感契约收编批；纯读列，失败/无列=系统默认）----
    if bundle.book is not None:
        try:
            _tc = getattr(bundle.book, "texture_contracts", None)
            bundle.texture_contracts = _tc if isinstance(_tc, dict) and _tc else None
        except Exception as e:
            logger.debug("[settings_bundle] 质感契约读取降级: %s", e)
            bundle.texture_contracts = None

    # ---- 禁忌面（任务包 A 归一：四源合并唯一权威）----
    # load_prohibition_set 内部各层独立降级；整体异常时置 None，
    # 消费侧（to_prompt_context / hard_constraints / ghost_guard）回退旧路径。
    try:
        from backend.services.style.prohibitions import load_prohibition_set
        bundle.prohibitions = await load_prohibition_set(
            db, book=bundle.book, style_card=bundle.style_card,
        )
    except Exception as e:
        logger.debug("[settings_bundle] 禁忌面加载降级为 None: %s", e)
        bundle.prohibitions = None

    # 链路可见性：一次装配的命中面一行账（章节号/世界源/绑定池/Canon/双卡/禁忌）
    logger.info(
        "[settings_bundle] ch=%s book=%s world=%s ent=%d ast=%d loc=%d rel=%d "
        "hooks=%d canon=%d字 章卡=%s 风卡=%s 禁忌=%s",
        bundle.chapter_number, bool(bundle.book), bundle.world_sourced,
        len(bundle.entities), len(bundle.assets), len(bundle.locations),
        len(bundle.relationships), len(bundle.open_hooks),
        len(bundle.canon_context), bool(bundle.chapter_card),
        bool(bundle.style_card), bundle.prohibitions is not None,
    )

    return bundle


# ============================================================
# 内部工具
# ============================================================

def _build_repos(db: AsyncSession) -> Dict[str, Any]:
    """构造 load_full_chapter_context 所需的 repository dict。"""
    return {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "chapter_asset": ChapterAssetRepository(db),
        "asset": AssetRepository(db),
        "map_location": MapLocationRepository(db),
        "memory": MemoryRepository(db),
        "relationship": RelationshipRepository(db),
    }


def _entity_name(ent: Any) -> str:
    """从 ChapterEntity 提取角色名（兼容 ORM 与 dict）。"""
    char = getattr(ent, "character", None)
    if char is None and isinstance(ent, dict):
        char = ent.get("character")
    if char is None:
        return ""
    return getattr(char, "name", "") or (char.get("name", "") if isinstance(char, dict) else "") or ""


def _entity_is_private(ent: Any) -> bool:
    """A1 私有判定（docs/reports/foundation-hardening.md §3.1，D5 语义）。

    - world 适配器：读 world_entity.visibility（world_entities.visibility 列，
      models.py；character/faction/asset 三类统一）
    - 旧表 ChapterEntity.character：Character 模型**无 visibility 列**（2026-08-20
      查证）——防御性读取，未来旧表若加列则自动同待遇；不加则恒公开
      （未迁移书零变化）。
    判定只服务 prompt 文本装配层；算法轨（sediment 等）直读适配器全量，与本函数无关。
    """
    if _get_attr_nested(ent, "world_entity", "visibility") == "private":
        return True
    if _get_attr_nested(ent, "character", "visibility") == "private":
        return True
    return False


def _characters_text(entities: List[Any]) -> str:
    """本章角色文本（名 + 永恒设定 + 此刻状态）。

    A1 私有通道：private 实体整行跳过（其档案经 bundle.character_secrets 走
    prompt 私有块「知晓但绝不写出」，双轨纪律）。
    知识检索平面 v3.1（2026-08-27）：字符截断与条目数上限全部退役——
    选中即完整是设计公理（docs/knowledge-retrieval-plane.md §1），
    体量由选择器与逃逸阀管辖，不再由渲染层腰斩。
    """
    lines = []
    for ent in (entities or []):
        if _entity_is_private(ent):
            continue
        char = getattr(ent, "character", None)
        if char is None and isinstance(ent, dict):
            char = ent.get("character")
        if char is None:
            continue
        name = _entity_name(ent) or "未命名"
        static = getattr(char, "static_prompt", None) or (char.get("static_prompt") if isinstance(char, dict) else None)
        dynamic = getattr(char, "dynamic_state", None) or (char.get("dynamic_state") if isinstance(char, dict) else None)
        parts = []
        if static:
            parts.append(str(static))
        if dynamic:
            parts.append(f"此刻：{dynamic}")
        lines.append(f"- {name}：{'｜'.join(parts)}" if parts else f"- {name}")
    return "\n".join(lines) if lines else "（未指定）"


def _assets_text(assets: List[Any]) -> str:
    """本章资产文本（A1：private 资产跳过，其简介走 secrets 通道，同角色口径）。"""
    lines = []
    for a in (assets or []):
        if _entity_is_private(a):
            continue
        name = getattr(a, "name", "") or ""
        desc = getattr(a, "static_description", "") or ""
        if name:
            lines.append(f"- {name}{'：' + desc if desc else ''}")
    return "\n".join(lines) if lines else "（未指定）"


def _locations_text(locations: List[Any]) -> str:
    """本章地点文本。"""
    lines = []
    for loc in (locations or []):
        name = getattr(loc, "name", "") or ""
        if name:
            lines.append(f"- {name}")
    return "\n".join(lines) if lines else "（未指定）"


def _relationships_text(relationships: List[Any]) -> str:
    """本章角色关系文本。"""
    lines = []
    for r in (relationships or []):
        src = getattr(r, "source_character", None)
        tgt = getattr(r, "target_character", None)
        rel = getattr(r, "relationship_type", "") or getattr(r, "description", "") or ""
        src_name = getattr(src, "name", "") if src else ""
        tgt_name = getattr(tgt, "name", "") if tgt else ""
        if src_name and tgt_name and rel:
            lines.append(f"- {src_name} ↔ {tgt_name}：{rel}")
    return "\n".join(lines) if lines else "（未指定）"


def _hooks_text(hooks: List[Any]) -> str:
    """开放伏笔文本。"""
    lines = []
    for h in (hooks or []):
        if isinstance(h, dict):
            content = h.get("content", "") or ""
            key = h.get("ledger_key", "") or ""
        else:
            content = getattr(h, "content", "") or ""
            key = getattr(h, "ledger_key", "") or ""
        if content:
            lines.append(f"- [{key}] {content}" if key else f"- {content}")
    return "\n".join(lines) if lines else "（无）"


# ============================================================
# 分级访问辅助函数（hard_constraints / soft_constraints 用）
# ============================================================

def _get_attr(obj: Any, attr: str) -> Any:
    """安全取属性（ORM 或 dict）。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)


def _get_attr_nested(obj: Any, *attrs: str) -> Any:
    """链式取嵌套属性（如 entity.character.static_prompt）。"""
    cur = obj
    for a in attrs:
        cur = _get_attr(cur, a)
        if cur is None:
            return None
    return cur


def _extract_canon_private_labels(canon_context: str) -> List[str]:
    """从 canon_context 提取 [private] 段的标签词（正文不许直接说出的核心名词）。

    校对用：生成的挂件/正文里若出现这些词，判为泄密。
    """
    if not canon_context or "[private]" not in canon_context:
        return []
    import re
    start = canon_context.find("[private]")
    end = canon_context.find("## ", start + 10)
    if end < 0:
        end = len(canon_context)
    section = canon_context[start:end]
    labels = re.findall(r"^-\s+([^：:\n]{2,})[：:]", section, re.MULTILINE)
    return [l.strip() for l in labels if l.strip()]


def _extract_canon_public_facts(canon_context: str) -> List[str]:
    """从 canon_context 提取 [public] 段的事实行（必须一致的已建立事实）。"""
    if not canon_context or "[public]" not in canon_context:
        return []
    start = canon_context.find("[public]")
    end = canon_context.find("## ", start + 10)
    if end < 0:
        end = len(canon_context)
    section = canon_context[start:end]
    lines = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("- ")]
    return lines


def _chapter_card_text(card: Any) -> str:
    """章节卡文本（purpose + must_hit + foreshadow_ops + continuity）。"""
    if not card:
        return ""
    parts = []
    purpose = _get_attr(card, "purpose") or ""
    if purpose:
        parts.append(f"主旨：{purpose}")
    hits = _get_attr(card, "must_hit_events") or []
    if hits:
        hit_lines = [h.get("event", "") if isinstance(h, dict) else str(h) for h in hits]
        parts.append("必达事件：" + "；".join(hit_lines))
    ops = _get_attr(card, "foreshadow_ops") or []
    if ops:
        op_lines = []
        for op in ops:
            if isinstance(op, dict):
                op_lines.append(f"{op.get('action', '')}{op.get('note', '')}")
            else:
                op_lines.append(str(op))
        parts.append("伏笔操作：" + "；".join(op_lines))
    cont = _get_attr(card, "continuity") or {}
    if isinstance(cont, dict) and cont:
        parts.append(f"衔接：{cont.get('from_chapter', '')} → 本章（{cont.get('time_gap', '')}）")
    return "\n".join(parts)


# ============================================================
# 文风画像公共渲染器（S2 E2）
# ============================================================

# positive_profile 五维的展示名（与文风页高级面板/提炼 prompt 同一套词）
_PROFILE_LABELS = {
    "sentence_rhythm": "句长节奏",
    "vocabulary": "词汇层级",
    "register": "语域偏好",
    "opening_habit": "开头习惯",
    "ending_habit": "结尾习惯",
}


def render_style_positive(style_card: Any) -> str:
    """把 StyleCard 的正面画像渲染为 prompt 用文本（画像 ≤10 行）。

    包含：positive_profile 五维（键名翻译为中文标签）+ 段落节奏。
    空卡/无有效字段 → 空串（调用方 prompt 零变化）。
    独立成公共函数供 adaptive 路由与 bundle 内部共用（单一渲染口径）。

    2026-09-14 去参数化（第三期审计 docs/reports/style-parameter-effectiveness-audit.md）：
    意图旋钮行（style_knobs）彻底移除——rhythm/dialogue 早已零注入（编译进检索器
    且数学空转），density/warmth 与白描封杀令指令内战；对话占比目标不再进任何
    prompt（对账/漂移提示改语料实测锚）。「范例>形容」：注意力让给亲笔样本。
    """
    if style_card is None:
        return ""
    lines: List[str] = []
    positive = _get_attr(style_card, "positive_profile")
    if isinstance(positive, dict):
        for key, value in positive.items():
            text = str(value or "").strip()
            if not text:
                continue
            label = _PROFILE_LABELS.get(key, key)
            lines.append(f"- {label}：{text[:STYLE_PROFILE_VALUE_MAX_CHARS]}")
    paragraph_rhythm = _get_attr(style_card, "paragraph_rhythm")
    if paragraph_rhythm:
        lines.append(f"- 段落节奏：{str(paragraph_rhythm)[:STYLE_PARAGRAPH_RHYTHM_MAX_CHARS]}")
    return "\n".join(lines[:STYLE_POSITIVE_MAX_LINES])


def _must_hit_events_text(card: Any) -> str:
    """必达事件文本（软约束参考）。"""
    if not card:
        return ""
    hits = _get_attr(card, "must_hit_events") or []
    lines = []
    for h in hits:
        if isinstance(h, dict):
            lines.append(h.get("event", ""))
        else:
            lines.append(str(h))
    return "；".join(l for l in lines if l)


def _foreshadow_ops_text(card: Any) -> str:
    """伏笔操作文本（软约束参考）。"""
    if not card:
        return ""
    ops = _get_attr(card, "foreshadow_ops") or []
    lines = []
    for op in ops:
        if isinstance(op, dict):
            lines.append(f"{op.get('action', '')} {op.get('note', '')}".strip())
        else:
            lines.append(str(op))
    return "；".join(l for l in lines if l)
