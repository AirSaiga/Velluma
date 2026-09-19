# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 读者清单与开章卡（两面「镜子」，01 下一阶段设计稿）
"""
只呈现作者自己录进系统的数据——零 LLM、零剧情建议、零修改建议
（docs/next-phase/01-opening-card-and-reader-ledger.md）。

三条显示规则（两功能共同宪法，任何一行不许违反）：
1. 集合由「作者一句话能复述的规则」定义；计数=真实总数；相关性算不出时退
   全书口径并带 scope 徽标（"presence"=与在场相关 / "book"=全书）；
2. 点一下就地展开完整内容（表/里/揭示计划原文），不跳世界页；
3. 空集零像素——键缺席而不是空数组（响应增量最小）。

数据源全部现成：read_merge_reveals（揭示合并读，已扩文本三件）+
PlotLedger open（线头）+ build_scene_slice（此刻/在场，复用不平行实现）。

副作用：无（纯读）。LLM 调用：零。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PlotLedger
from backend.repositories.intent_repository import IntentRepository

logger = logging.getLogger(__name__)

# 超载降级阈值（01 §1 超载推论；占位待 M3 真实数据校准）
OVERLOAD_THRESHOLD = 6


def _slim_row(r: Dict[str, Any]) -> Dict[str, Any]:
    """开章卡/读者清单的行形状（列表行 + 展开内容一并带上，规则二就地展开）。"""
    return {
        "label": str(r.get("label") or ""),
        "expected_chapter": r.get("expected_reveal_chapter"),
        "public_text": str(r.get("public_text") or ""),
        "canon_text": str(r.get("canon_text") or ""),
        "reveal_plan": str(r.get("reveal_plan") or ""),
        "source": str(r.get("source") or ""),
    }


async def load_reveal_rows(db: AsyncSession, book_id: str) -> List[Dict[str, Any]]:
    """全量揭示行（不经章窗）——开章卡 L1/L2 与读者清单共用的底料。"""
    rows = await IntentRepository(db).read_merge_reveals(book_id, chapter_number=None)
    return [_slim_row(r) for r in rows]


# ============================================================
# 功能二：读者清单（完稿报告「读者此刻」栏）
# ============================================================

async def load_reader_ledger(
    db: AsyncSession, book_id: str, current_chapter: int
) -> Optional[Dict[str, Any]]:
    """按章号把揭示计划折成三段清单：本章新知道 / 已经知道 / 还不知道（按计划章分桶）。

    空集段缺席（规则三）；三段全空返回 None（finish 响应不设 reader_ledger 键）。
    纯章号算术——系统不知道正文写没写，核对动作永远是作者的。
    """
    rows = await load_reveal_rows(db, book_id)
    new_known: List[Dict[str, Any]] = []
    known: List[Dict[str, Any]] = []
    upcoming: Dict[int, List[Dict[str, Any]]] = {}
    unscheduled: List[Dict[str, Any]] = []
    for r in rows:
        ch = r.get("expected_chapter")
        if ch is None:
            unscheduled.append(r)
        elif int(ch) == current_chapter:
            new_known.append(r)
        elif int(ch) < current_chapter:
            known.append(r)
        else:
            upcoming.setdefault(int(ch), []).append(r)
    out: Dict[str, Any] = {}
    if new_known:
        out["new_known"] = new_known
    if known:
        # 已经知道按揭示先后排（近的在前——完稿时刻最该记得的是刚抖出来的）
        known.sort(key=lambda r: int(r["expected_chapter"] or 0), reverse=True)
        out["known"] = known
    if upcoming:
        # 还不知道：按计划章升序成前瞻时间线（第 N 章、第 M 章…）
        out["upcoming"] = [
            {"chapter": ch, "items": items} for ch, items in sorted(upcoming.items())
        ]
    if unscheduled:
        out["unscheduled"] = unscheduled
    return out or None


# ============================================================
# 功能一：开章卡（进入空章的「打算」页，≤4 行小字）
# ============================================================

async def build_opening_card(
    db: AsyncSession, book_id: str, chapter: Any
) -> Dict[str, Any]:
    """空章开写前的四行镜子（每行独立空集消失；全空返回 {}）。

    L1 该揭（预期 ≤ 本章，逾期深度降序）/ L2 别说破（预期 > 本章，scope 圈定）/
    L3 线头（PlotLedger open 计数 + 最久）/ L4 此刻（scene_slice 现成）。
    """
    current = int(getattr(chapter, "chapter_number", 0) or 0)
    card: Dict[str, Any] = {}
    if current:
        rows = await load_reveal_rows(db, book_id)

        # ---- 在场集（复用 scene_slice，禁止平行实现）：空章常见无在场 → 退全书口径 ----
        present_names: List[str] = []
        slice_data: Dict[str, Any] = {}
        try:
            from backend.services.world.scene_slice import build_scene_slice

            slice_data = await build_scene_slice(db, book_id, chapter)
            present_names = [str(p.get("name") or "") for p in slice_data.get("presence") or []]
            present_names = [n for n in present_names if n]
        except Exception as e:
            logger.debug(f"[opening_card] scene_slice 失败（按无在场继续）: {e}")

        # ---- L1 该揭：预期 ≤ 本章（含逾期；逾期最深的排最前）----
        due = [r for r in rows if r.get("expected_chapter") is not None
               and int(r["expected_chapter"]) <= current]
        if due:
            due.sort(key=lambda r: int(r["expected_chapter"] or 0))
            for r in due:
                r["overdue_by"] = max(0, current - int(r["expected_chapter"] or 0))
            card["due_reveals"] = due

        # ---- L2 别说破：预期 > 本章 ∩ 在场（无在场 → 全书口径 + 徽标）----
        untold = [r for r in rows
                  if r.get("expected_chapter") is not None
                  and int(r["expected_chapter"]) > current]
        if untold:
            if present_names:
                related = [r for r in untold
                           if any(n and n in r["label"] for n in present_names)]
                # 在场相关集合为空（真相都不挂当前在场者）→ 退全书口径明示，
                # 不显示「假装相关」的空集（规则一：宁可全书也不假装）
                if related:
                    card["untold"] = {"scope": "presence", "items": related}
                else:
                    card["untold"] = {"scope": "book", "items": untold}
            else:
                card["untold"] = {"scope": "book", "items": untold}

        # ---- L3 线头：全书 open 伏笔计数 + 最久吊的章数（真实总数，不截断）----
        hooks = (await db.execute(
            select(PlotLedger).where(
                PlotLedger.book_id == book_id,
                PlotLedger.status == "open",
            )
        )).scalars().all()
        if hooks:
            items = []
            oldest = 0
            for h in hooks:
                open_for = None
                if h.created_at_chapter is not None and current:
                    open_for = max(0, current - int(h.created_at_chapter))
                    oldest = max(oldest, open_for)
                items.append({
                    "content": str(h.content or "")[:60],
                    "ledger_key": str(h.ledger_key or ""),
                    "chapters_open": open_for,
                })
            items.sort(key=lambda r: -(r["chapters_open"] or 0))
            card["threads"] = {"count": len(items), "oldest": oldest, "items": items}

        # ---- L4 此刻：时间/地点/谁在场（scene_slice 现成）----
        # 规则三：无世界数据的书（zero 兜底时刻且无地点无在场）整行消失——
        # 「第1年1月1日」对旧表书是噪音不是信息
        scene = slice_data.get("scene") or {}
        t = slice_data.get("t")
        t_source = str(slice_data.get("t_source") or "")
        if t is not None and (scene or present_names or t_source not in ("", "zero")):
            card["scene"] = {
                "t": t,
                "t_source": t_source,
                "location": str(scene.get("path") or scene.get("name") or ""),
                "present": present_names[:6],
            }
    return card
