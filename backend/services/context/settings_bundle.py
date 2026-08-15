# Velluma - 自适应辅助设定数据加载器（NLE-ADF 3.0）
# AGPL-3.0
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
)
from backend.services.context.loader import load_full_chapter_context
from backend.services.canon.consistency import build_canon_context_for_prompt
from backend.services.workflows.adf.setting_resolver import build_worldview_text


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
    style_blacklist: List[str] = field(default_factory=list)
    rolling_summary: str = ""
    # 章节元信息（便捷访问）
    chapter_id: str = ""
    book_id: Optional[str] = None
    chapter_number: Optional[int] = None
    outline_text: str = ""
    content_text: str = ""

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
            "worldview_text": self.worldview_text,
            "open_hooks": _hooks_text(self.open_hooks),
            "outline_text": self.outline_text,
            "previous_summary": self.previous_summary or "",
            "chapter_card": _chapter_card_text(self.chapter_card),
            "style_negative": _style_negative_text(self.style_card, self.style_blacklist),
            "rolling_summary": self.rolling_summary[:500] if self.rolling_summary else "",
            "core_motifs_taboos": self.core_motifs_taboos[:300] if self.core_motifs_taboos else "",
        }

    # ===== 分级访问：校对强度不同 =====

    def hard_constraints(self) -> Dict[str, Any]:
        """硬约束（违反=设定崩坏，组件必须校对拦截）。

        - canon_private_labels：Canon [private] 节点的标签词（正文不许直接说出）
        - canon_public_facts：Canon [public] 已建立事实（必须一致）
        - banned_words：禁词合并（style_blacklist + StyleCard.negative_list + 禁词表）
        - character_statics：角色永恒设定（防 OOC）
        - core_motifs_taboos：书级核心母题禁忌
        """
        return {
            "canon_private_labels": _extract_canon_private_labels(self.canon_context),
            "canon_public_facts": _extract_canon_public_facts(self.canon_context),
            "banned_words": _merge_banned_words(self.style_card, self.style_blacklist),
            "character_statics": {
                _entity_name(e): (_get_attr_nested(e, "character", "static_prompt") or "")
                for e in self.entities if _entity_name(e)
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
            "rolling_summary": self.rolling_summary[:500] if self.rolling_summary else "",
            "purpose": _get_attr(self.chapter_card, "purpose") or "",
        }

    def proper_nouns(self, limit: int = 20) -> List[str]:
        """提取角色名 + 资产名（专名表，防缝合时称呼漂移）。"""
        names: List[str] = []
        for e in self.entities:
            name = _entity_name(e)
            if name and name not in names:
                names.append(name)
        for a in self.assets:
            name = getattr(a, "name", "") or ""
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
            "description": (e.get("description") or "")[:40],
            "tension": e.get("current_tension") or 5,
        }
        for e in active[:3]
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
    except Exception:
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
        except Exception:
            bundle.book = None

    # ---- 章级绑定池（角色/资产/地点/关系/伏笔）----
    repos = _build_repos(db)
    try:
        ctx = await load_full_chapter_context(chapter_id, repos)
    except Exception:
        ctx = None
    if ctx:
        bundle.entities = ctx.entities or []
        bundle.assets = ctx.assets or []
        bundle.locations = ctx.locations or []
        bundle.relationships = ctx.relationships or []
        bundle.open_hooks = ctx.open_hooks or []
        bundle.previous_summary = ctx.previous_summary

    # ---- 书级 Canon 图谱 ----
    if bundle.book_id:
        try:
            bundle.canon_context = await build_canon_context_for_prompt(
                db, bundle.book_id, chapter_number=bundle.chapter_number,
            )
        except Exception:
            bundle.canon_context = ""

    # ---- 世界观设定 ----
    if bundle.book:
        try:
            bundle.worldview_text = build_worldview_text(bundle.book)
        except Exception:
            bundle.worldview_text = ""

    # ---- 章节卡（must_hit_events / foreshadow_ops / continuity / purpose）----
    if bundle.book_id:
        try:
            from backend.models import ChapterCard, StyleCard as StyleCardModel
            cc_result = await db.execute(
                select(ChapterCard).where(ChapterCard.chapter_id == chapter_id).limit(1)
            )
            bundle.chapter_card = cc_result.scalar_one_or_none()
            # 书级 StyleCard（chapter_id=null）
            sc_result = await db.execute(
                select(StyleCardModel).where(
                    StyleCardModel.book_id == bundle.book_id,
                    StyleCardModel.chapter_id.is_(None),
                ).limit(1)
            )
            bundle.style_card = sc_result.scalar_one_or_none()
        except Exception:
            pass

    # ---- 书级硬约束 ----
    if bundle.book:
        bundle.core_motifs_taboos = getattr(bundle.book, "core_motifs_taboos", "") or ""
        bundle.style_blacklist = getattr(bundle.book, "style_blacklist", []) or []
        bundle.rolling_summary = getattr(bundle.book, "rolling_summary", "") or ""

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


def _characters_text(entities: List[Any]) -> str:
    """本章角色文本（名 + 永恒设定 + 此刻状态）。"""
    lines = []
    for ent in (entities or [])[:8]:
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
            parts.append(str(static)[:200])
        if dynamic:
            parts.append(f"此刻：{str(dynamic)[:150]}")
        lines.append(f"- {name}：{'｜'.join(parts)}" if parts else f"- {name}")
    return "\n".join(lines) if lines else "（未指定）"


def _assets_text(assets: List[Any]) -> str:
    """本章资产文本。"""
    lines = []
    for a in (assets or [])[:8]:
        name = getattr(a, "name", "") or ""
        desc = getattr(a, "static_description", "") or ""
        if name:
            lines.append(f"- {name}{'：' + desc[:120] if desc else ''}")
    return "\n".join(lines) if lines else "（未指定）"


def _locations_text(locations: List[Any]) -> str:
    """本章地点文本。"""
    lines = []
    for loc in (locations or [])[:6]:
        name = getattr(loc, "name", "") or ""
        if name:
            lines.append(f"- {name}")
    return "\n".join(lines) if lines else "（未指定）"


def _relationships_text(relationships: List[Any]) -> str:
    """本章角色关系文本。"""
    lines = []
    for r in (relationships or [])[:8]:
        src = getattr(r, "source_character", None)
        tgt = getattr(r, "target_character", None)
        rel = getattr(r, "relationship_type", "") or getattr(r, "description", "") or ""
        src_name = getattr(src, "name", "") if src else ""
        tgt_name = getattr(tgt, "name", "") if tgt else ""
        if src_name and tgt_name and rel:
            lines.append(f"- {src_name} ↔ {tgt_name}：{rel[:80]}")
    return "\n".join(lines) if lines else "（未指定）"


def _hooks_text(hooks: List[Any]) -> str:
    """开放伏笔文本。"""
    lines = []
    for h in (hooks or [])[:8]:
        if isinstance(h, dict):
            content = h.get("content", "") or ""
            key = h.get("ledger_key", "") or ""
        else:
            content = getattr(h, "content", "") or ""
            key = getattr(h, "ledger_key", "") or ""
        if content:
            lines.append(f"- [{key}] {content[:120]}" if key else f"- {content[:120]}")
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
    return [l.strip() for l in labels if l.strip()][:10]


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
    return [ln[:120] for ln in lines][:10]


def _merge_banned_words(style_card: Any, style_blacklist: List[str]) -> List[str]:
    """合并禁词来源：style_blacklist（书级）+ StyleCard.negative_list + 反 AI 腔禁词表。"""
    words: List[str] = []
    # 书级 style_blacklist
    for w in (style_blacklist or []):
        if isinstance(w, str) and w not in words:
            words.append(w)
        elif isinstance(w, dict):
            term = w.get("word") or w.get("phrase") or ""
            if term and term not in words:
                words.append(term)
    # StyleCard.negative_list
    neg = _get_attr(style_card, "negative_list") or []
    for item in neg:
        if isinstance(item, str) and item not in words:
            words.append(item)
        elif isinstance(item, dict):
            term = item.get("word") or item.get("phrase") or ""
            if term and term not in words:
                words.append(term)
    # 反 AI 腔禁词表（复用）
    try:
        from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
        for w in DEFAULT_BAN_LIST.banned_words:
            if w not in words:
                words.append(w)
    except Exception:
        pass
    return words[:60]  # 上限防 prompt 膨胀


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
        hit_lines = [h.get("event", "") if isinstance(h, dict) else str(h) for h in hits[:8]]
        parts.append("必达事件：" + "；".join(hit_lines))
    ops = _get_attr(card, "foreshadow_ops") or []
    if ops:
        op_lines = []
        for op in ops[:6]:
            if isinstance(op, dict):
                op_lines.append(f"{op.get('action', '')}{op.get('note', '')}")
            else:
                op_lines.append(str(op))
        parts.append("伏笔操作：" + "；".join(op_lines))
    cont = _get_attr(card, "continuity") or {}
    if isinstance(cont, dict) and cont:
        parts.append(f"衔接：{cont.get('from_chapter', '')} → 本章（{cont.get('time_gap', '')}）")
    return "\n".join(parts)


def _style_negative_text(style_card: Any, style_blacklist: List[str]) -> str:
    """禁词/禁句式文本。"""
    words = _merge_banned_words(style_card, style_blacklist)
    return "、".join(words[:30]) if words else ""


def _must_hit_events_text(card: Any) -> str:
    """必达事件文本（软约束参考）。"""
    if not card:
        return ""
    hits = _get_attr(card, "must_hit_events") or []
    lines = []
    for h in hits[:8]:
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
    for op in ops[:6]:
        if isinstance(op, dict):
            lines.append(f"{op.get('action', '')} {op.get('note', '')}".strip())
        else:
            lines.append(str(op))
    return "；".join(l for l in lines if l)
