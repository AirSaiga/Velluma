# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - Intent 仓储（B2 · docs/world-kernel-foundation.md §3）
"""统一意图存储的读合并层（双读过渡期唯一读口）。

双读纪律（docs/world-kernel-construction-plan.md §3）：
- world_intents（新表）优先；旧表（plot_ledgers / canon 揭示列 / 期待账本）
  兜底——迁移脚本复制后，旧表行按 source_key 去重不再重复出现；
- 回退路径：任何时点可把消费方切回旧表直读（旧表在过渡期恒为事实源备份）；
- 写路径：过渡期写侧仍走旧表（UI 不动）；IntentRepository 只读 + 迁移写入。

副作用：无（纯查询；迁移写入走 migrate_to_intents 的独立入口）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PlotLedger, WorldIntent

# 活跃生命周期（未兑现/未放弃）
ACTIVE_LIFECYCLES = ("declared", "tentative")


def _normalize(text: str) -> str:
    return "".join((text or "").split())


class IntentRepository:
    """意图读合并仓储（过渡期只读）。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_open(
        self,
        book_id: UUID | str,
        kinds: Optional[List[str]] = None,
        before_chapter: Optional[int] = None,
    ) -> List[WorldIntent]:
        """开放的意图（生命周期活跃 + 章窗口过滤）。"""
        bid = book_id if isinstance(book_id, UUID) else UUID(str(book_id))
        q = select(WorldIntent).where(
            WorldIntent.book_id == bid,
            WorldIntent.lifecycle.in_(ACTIVE_LIFECYCLES),
        )
        if kinds:
            q = q.where(WorldIntent.kind.in_(kinds))
        if before_chapter is not None:
            q = q.where(
                (WorldIntent.window_chapter_start.is_(None))
                | (WorldIntent.window_chapter_start < before_chapter)
            )
        q = q.order_by(WorldIntent.created_at.desc())
        return list((await self._db.execute(q)).scalars().all())

    async def read_merge_hooks(
        self,
        book_id: UUID | str,
        before_chapter: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """伏笔/期待钩子的合并读（新表优先 + plot_ledgers 兜底，按内容归一去重）。

        返回形状与 loader.load_open_hooks 的 dict 对齐（hook_id/ledger_key/content）
        ——消费方零改动切换。

        legacy 副本让位（2026-08-28 审计修复）：过渡期写侧仍走旧表，迁移复制出的
        intent 行若不随源行生死，被关闭/回收的钩子会从新表「复活」（隔离库复现：
        迁移→旧表置 closed→合并读仍返回该钩子）。规则：source_key 带 legacy: 前缀
        且源行仍存在 → 让位给源（终结不复活、内容以源为准防编辑双条）；源行被
        物理删除 → 副本独立生效。效果=过渡期合并读与旧表直读一致（回退路径语义）。
        """
        from backend.models import Book

        bid = UUID(str(book_id))
        # 旧表全量（过渡期事实源；不只 open——终结行是让位判据）
        legacy_rows = (await self._db.execute(
            select(PlotLedger).where(PlotLedger.book_id == bid)
            .order_by(PlotLedger.created_at_chapter.desc())
        )).scalars().all()
        legacy_by_id = {str(r.id): r for r in legacy_rows}
        # 期待账本源（legacy:reader_mirror 副本的让位判据）
        book = await self._db.get(Book, bid)
        mirror_ids: set = set()
        if book is not None and isinstance(getattr(book, "reader_mirror", None), dict):
            mirror_ids = {
                str(e.get("id"))
                for e in (book.reader_mirror.get("expectations") or [])
                if isinstance(e, dict)
            }

        def _superseded_by_source(source_key: Optional[str]) -> bool:
            sk = source_key or ""
            if not sk.startswith("legacy:"):
                return False
            # legacy:plot_ledgers:{row_id} / legacy:reader_mirror:{book_id}:{eid}
            parts = sk.split(":")
            if len(parts) >= 3 and parts[1] == "plot_ledgers":
                return parts[2] in legacy_by_id
            if len(parts) >= 4 and parts[1] == "reader_mirror":
                return parts[3] in mirror_ids
            return False

        out: List[Dict[str, str]] = []
        seen = set()
        for it in await self.list_open(bid, kinds=["foreshadow", "expectation", "promise"],
                                       before_chapter=before_chapter):
            if _superseded_by_source(it.source_key):
                continue
            content = (it.target_text or "").strip()
            if not content:
                continue
            key = _normalize(content)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "hook_id": f"intent:{it.id}",
                "ledger_key": it.source_key or f"intent:{it.kind}",
                "content": content,
            })
        # 旧表兜底：open 行（迁移副本已让位+内容归一，不会重复出现）
        for row in legacy_rows:
            if str(getattr(row, "status", "")) != "open":
                continue
            ch_anchor = getattr(row, "created_at_chapter", None)
            # 与 SQL NULL 三值语义对齐：无锚行不进「第 N 章之前」窗口
            if before_chapter is not None and (ch_anchor is None or ch_anchor >= before_chapter):
                continue
            content = str(getattr(row, "content", "") or "").strip()
            if not content or _normalize(content) in seen:
                continue
            seen.add(_normalize(content))
            out.append({
                "hook_id": str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or ""),
                "ledger_key": str(getattr(row, "ledger_key", "") or ""),
                "content": content,
            })
        return out

    async def read_merge_reveals(
        self,
        book_id: UUID | str,
        chapter_number: Optional[int] = None,
        within_chapters: int = 2,
    ) -> List[Dict[str, Any]]:
        """揭示临近的合并读（新表 reveal 意图 + canon 节点 expected_reveal_chapter 兜底）。

        过滤：距本章 ≤ within_chapters 章（C3 口径），下界含逾期 1 章
        （2026-08-28 恢复 B2 切换前的 -1≤gap≤2 口径——错过的揭示计划恰是
        最要紧的提醒，切换 read_merge 时曾被静默收窄为 [0, +2]）。
        legacy 副本让位（同 read_merge_hooks 修复）：canon 节点仍存在时以节点
        现状为准——揭示计划被清空/改期后迁移副本不再复活提醒。
        """
        from backend.models import CanonNode

        bid = UUID(str(book_id))
        nodes = (await self._db.execute(
            select(CanonNode).where(CanonNode.book_id == bid)
        )).scalars().all()
        node_by_id = {str(n.id): n for n in nodes}

        out: List[Dict[str, Any]] = []
        seen_ref = set()

        def _node_text_row(node) -> Dict[str, Any]:
            """canon 节点 → 行文本三件（表/里/揭示计划原文）——01 开章卡与读者
            清单的展开内容（规则二：一次点击彻底回答）。加键是纯增量，
            既有消费方只读 label/expected_reveal_chapter/canon_node_id。"""
            return {
                "public_text": str(node.public_text or "").strip(),
                "canon_text": str(node.canon_text or "").strip(),
                "reveal_plan": str(getattr(node, "reveal_plan", None) or "").strip(),
            }

        for it in await self.list_open(bid, kinds=["reveal"]):
            sk = it.source_key or ""
            parts = sk.split(":", 2)
            if len(parts) == 3 and parts[0] == "legacy" and parts[1] == "canon_reveal":
                if parts[2] in node_by_id:
                    continue  # 节点仍在 → 让位（以 canon 现状为准）
            target_ch = it.window_chapter_end or it.window_chapter_start
            if chapter_number is not None and target_ch is not None:
                if not (chapter_number - 1 <= target_ch <= chapter_number + within_chapters):
                    continue
            if it.target_ref:
                if it.target_ref in seen_ref:
                    continue
                seen_ref.add(it.target_ref)
            out.append({
                "label": (it.target_text or "").strip() or "揭示计划",
                "expected_reveal_chapter": target_ch,
                "canon_node_id": it.target_ref,
                "source": "intent",
                **(_node_text_row(node_by_id[it.target_ref])
                   if it.target_ref in node_by_id else {}),
            })
        # 旧源兜底：canon_nodes.expected_reveal_chapter（让位+ref 去重后不重复）
        for node in nodes:
            if node.expected_reveal_chapter is None:
                continue
            if chapter_number is not None and not (
                chapter_number - 1
                <= node.expected_reveal_chapter
                <= chapter_number + within_chapters
            ):
                continue
            if str(node.id) in seen_ref:
                continue
            out.append({
                "label": node.label or "真相揭示",
                "expected_reveal_chapter": node.expected_reveal_chapter,
                "canon_node_id": str(node.id),
                "source": "canon",
                **_node_text_row(node),
            })
        # 第三来源（2026-09-03 字段级真相分层）：实体档案分层字段的 reveal_chapter
        # （「第几章揭」），标签「实体名·字段名」；整人 private 实体跳过（与
        # canon 注入/泄密检测同口径）。无分层的书零行为变化。
        from backend.models import WorldEntity
        from backend.services.world.field_layers import iter_field_layers

        entities = (await self._db.execute(
            select(WorldEntity).where(WorldEntity.book_id == bid)
        )).scalars().all()
        for ent in entities:
            if getattr(ent, "visibility", "public") == "private":
                continue
            for entry in iter_field_layers(ent):
                if entry.reveal_chapter is None:
                    continue
                if chapter_number is not None and not (
                    chapter_number - 1
                    <= entry.reveal_chapter
                    <= chapter_number + within_chapters
                ):
                    continue
                ref = f"field:{ent.id}:{entry.field_key}"
                if ref in seen_ref:
                    continue
                seen_ref.add(ref)
                out.append({
                    "label": f"{ent.name}·{entry.label}",
                    "expected_reveal_chapter": entry.reveal_chapter,
                    "canon_node_id": None,
                    "source": "field_layer",
                    # 字段分层的表/里：字段内容即「里」，半露的表在 layer spec
                    "public_text": entry.public_text,
                    "canon_text": entry.full_text,
                    "reveal_plan": "",
                })
        return out


# ============================================================
# 迁移核心（scripts/migrate_to_intents.py 与测试共用；幂等）
# ============================================================

async def migrate_legacy_to_intents(db: AsyncSession) -> Dict[str, int]:
    """旧源 → world_intents 幂等复制（B2 迁移；source_key 去重）。

    覆盖三个结构化旧源：
    1. plot_ledgers（status=open 的伏笔/期待行）→ kind=foreshadow/expectation；
    2. canon_nodes.expected_reveal_chapter + reveal_plan → kind=reveal
       （target_ref=canon 节点 id，命题引用形态）；
    3. books.reader_mirror 期待账本 → kind=expectation（free_text 过渡态）。

    明确不迁（作者主权）：chapters.outline_text 大纲节拍（自由文本，作者
    逐拍编辑的事实源，结构化属未来作者显式动作）；chapters.spine 锚点
    （spine 已是章级意图存储，等跨章查询需求出现再投影）。
    返回 {源: 复制条数}。
    """
    from backend.models import Book, CanonNode

    counts = {"plot_ledgers": 0, "canon_reveal": 0, "reader_mirror": 0}
    existing_keys = {
        row for (row,) in await db.execute(select(WorldIntent.source_key))
        if row
    }

    def _add(**kw) -> bool:
        skey = kw.get("source_key")
        if skey and skey in existing_keys:
            return False
        existing_keys.add(skey)
        db.add(WorldIntent(**kw))
        return True

    # 1. plot_ledgers
    rows = (await db.execute(
        select(PlotLedger).where(PlotLedger.status == "open")
    )).scalars().all()
    for row in rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        entry_type = str(getattr(row, "entry_type", "foreshadow") or "foreshadow")
        kind = "expectation" if entry_type == "expectation" else "foreshadow"
        if _add(
            book_id=row.book_id, kind=kind, scope="book",
            target_type="free_text", target_text=content,
            window_chapter_start=getattr(row, "created_at_chapter", None),
            lifecycle="declared", provenance="author",
            source_key=f"legacy:plot_ledgers:{row.id}",
        ):
            counts["plot_ledgers"] += 1

    # 2. canon 揭示计划
    nodes = (await db.execute(
        select(CanonNode).where(CanonNode.expected_reveal_chapter.isnot(None))
    )).scalars().all()
    for node in nodes:
        if _add(
            book_id=node.book_id, kind="reveal", scope="book",
            target_type="proposition_ref", target_ref=str(node.id),
            target_text=(node.reveal_plan or node.label or "").strip(),
            window_chapter_end=node.expected_reveal_chapter,
            lifecycle="declared", provenance="author",
            source_key=f"legacy:canon_reveal:{node.id}",
        ):
            counts["canon_reveal"] += 1

    # 3. 期待账本（books.reader_mirror JSONB）
    books = (await db.execute(select(Book))).scalars().all()
    for book in books:
        raw = getattr(book, "reader_mirror", None)
        if not isinstance(raw, dict):
            continue
        for e in raw.get("expectations") or []:
            if not isinstance(e, dict):
                continue
            desc = str(e.get("description") or "").strip()
            eid = str(e.get("id") or "")
            if not desc or not eid:
                continue
            if _add(
                book_id=book.id, kind="expectation", scope="book",
                target_type="free_text", target_text=desc,
                lifecycle="tentative" if e.get("status") == "setup" else "declared",
                provenance="author",
                source_key=f"legacy:reader_mirror:{book.id}:{eid}",
            ):
                counts["reader_mirror"] += 1

    await db.flush()
    return counts
