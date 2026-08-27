# Velluma - Intent 仓储（B2 · docs/world-kernel-foundation.md §3）
# AGPL-3.0
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
        """
        bid = UUID(str(book_id))
        out: List[Dict[str, str]] = []
        seen = set()
        for it in await self.list_open(bid, kinds=["foreshadow", "expectation", "promise"],
                                       before_chapter=before_chapter):
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
        # 旧表兜底：plot_ledgers open 行（迁移后已复制的会因内容归一命中 seen 跳过）
        legacy = await self._db.execute(
            select(PlotLedger).where(
                PlotLedger.book_id == bid,
                PlotLedger.status == "open",
                *( [PlotLedger.created_at_chapter < before_chapter]
                   if before_chapter is not None else [] ),
            ).order_by(PlotLedger.created_at_chapter.desc())
        )
        for row in legacy.scalars().all():
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

        过滤：距本章 ≤ within_chapters 章（C3 口径不变）。
        """
        from backend.models import CanonNode

        bid = UUID(str(book_id))
        out: List[Dict[str, Any]] = []
        seen_ref = set()
        for it in await self.list_open(bid, kinds=["reveal"]):
            target_ch = it.window_chapter_end or it.window_chapter_start
            if chapter_number is not None and target_ch is not None:
                if not (chapter_number <= target_ch <= chapter_number + within_chapters):
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
            })
        # 旧源兜底：canon_nodes.expected_reveal_chapter（被迁移复制的按 ref 去重）
        q = select(CanonNode).where(
            CanonNode.book_id == bid,
            CanonNode.expected_reveal_chapter.isnot(None),
        )
        if chapter_number is not None:
            q = q.where(
                CanonNode.expected_reveal_chapter >= chapter_number,
                CanonNode.expected_reveal_chapter <= chapter_number + within_chapters,
            )
        for node in (await self._db.execute(q)).scalars().all():
            if str(node.id) in seen_ref:
                continue
            out.append({
                "label": node.label or "真相揭示",
                "expected_reveal_chapter": node.expected_reveal_chapter,
                "canon_node_id": str(node.id),
                "source": "canon",
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
