# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：auto-read / read-entities —— 系统自己去读（切章发枪 + 全书通读认人）。

红线：只产候选进 pending 池（物理隔离），作者 ✓ 才转正；成本护栏在
read_budget（哈希幂等 + 章级间隔 + 每书每日上限）；read-entities 只产草稿不落库。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.services.adaptive.observing import (
    flush_adaptive_records,
    get_adaptive_recorder,
)

from .schemas import AutoReadResponse, ReadEntitiesRequest, ReadEntitiesResponse

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# 端点 5.7：auto-read / read-entities — 系统自己去读（2026-08-25 战略定稿）
# ============================================================
# 观察触发权从手动（Ctrl+Enter 沉淀）扩展到系统自然时机：切章发枪、全书通读。
# 红线不变：只产候选进 pending 池（物理隔离），作者 ✓ 才转正——喂养从
# 「作者要做的事」变成「作者要批的事」。成本护栏全在 read_budget（哈希幂等 +
# 章级间隔 + 每书每日上限）；event_scout 内部已有「学着闭嘴」静音双闸。
# read-entities 只产草稿不落库（实体建设永远是作者动作，批量确认走前端）。


@router.post("/{chapter_id}/adaptive/auto-read", response_model=AutoReadResponse)
async def auto_read_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """读一章 → 世界事件候选进收件箱。幂等（哈希不变不重读），随处发枪安全。"""
    from backend.services.adaptive.read_budget import (
        AUTO_READ_DAILY_CAP,
        AUTO_READ_SKIP_REASONS,
        content_fingerprint,
        count_auto_reads_24h,
        decide_auto_read,
    )

    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        return AutoReadResponse(ran=False, skipped={"code": "no_chapter", "reason": "章节不存在"})

    from backend.services.rag.memory_indexing import _html_to_plain
    plain = _html_to_plain(chapter.content_text or "").strip()
    book_id = str(chapter.book_id)
    daily_used = await count_auto_reads_24h(db, book_id)
    state = dict(chapter.auto_read_state or {})
    fp = content_fingerprint(plain)
    ok, code = decide_auto_read(
        text_len=len(plain), state=state, fingerprint=fp, daily_used=daily_used,
    )
    if not ok:
        return AutoReadResponse(
            ran=False,
            skipped={"code": code or "", "reason": AUTO_READ_SKIP_REASONS.get(code or "", "")},
        )

    from backend.services.world import event_scout
    result = await event_scout.run(str(chapter.id), db, {}, 0, source="auto_read", text=plain)
    await flush_adaptive_records(chapter_id)
    if result.get("skipped"):
        # 跳过（无实体/LLM 失败等）不写幂等锚——保留下次重试的资格
        return AutoReadResponse(ran=False, skipped=result["skipped"])

    chapter.auto_read_state = {
        **state,
        "hash": fp,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "last_created": result.get("created", 0),
    }
    await db.commit()
    return AutoReadResponse(
        ran=True,
        created=result.get("created", 0),
        suppressed_muted=result.get("suppressed_muted", 0),
        suppressed_rejected=result.get("suppressed_rejected", 0),
        budget={"daily_used": daily_used + 1, "daily_cap": AUTO_READ_DAILY_CAP},
    )


@router.post("/{chapter_id}/adaptive/read-entities", response_model=ReadEntitiesResponse)
async def read_chapter_entities(
    chapter_id: str,
    payload: Optional[ReadEntitiesRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """全书通读·阶段 A：从正文抽实体/地点候选——只产草稿不落库（作者批量过目后才建）。

    长章折叠策略：≤5000 字全量；超长取头 4000 + 尾 1000（实体介绍密度
    前重后轻，尾部带上防漏后期登场角色）。
    """
    from backend.services.adaptive.emergent_facts import extract_emergent_facts
    from backend.services.adaptive.read_budget import (
        AUTO_READ_DAILY_CAP,
        AUTO_READ_SKIP_REASONS,
        content_fingerprint,
        count_auto_reads_24h,
        decide_auto_read,
    )

    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        return ReadEntitiesResponse(ran=False, skipped={"code": "no_chapter", "reason": "章节不存在"})

    from backend.services.rag.memory_indexing import _html_to_plain
    plain = _html_to_plain(chapter.content_text or "").strip()
    book_id = str(chapter.book_id)
    daily_used = await count_auto_reads_24h(db, book_id)
    state = dict(chapter.auto_read_state or {})
    fp = content_fingerprint(plain)
    ok, code = decide_auto_read(
        text_len=len(plain), state=state, fingerprint=fp,
        hash_key="entities_hash", ts_key="entities_last_run_at",
        daily_used=daily_used,
        force=bool(payload and payload.force),
    )
    if not ok:
        return ReadEntitiesResponse(
            ran=False,
            skipped={"code": code or "", "reason": AUTO_READ_SKIP_REASONS.get(code or "", "")},
        )

    # 已有实体名单注入前文摘要位（防重复提名已有角色；语义复用 prev_state_summary
    # 槽——它本就是「前文已知状态」的注入口）
    from backend.repositories.world_repository import WorldRepository
    existing = await WorldRepository(db).entities.list_by_book(book_id)
    known = [str(getattr(e, "name", "") or "") for e in existing if getattr(e, "name", None)]
    prev_state = ("已知实体名单（勿重复抽取）：" + "、".join(known[:50])) if known else ""

    segment = plain if len(plain) <= 5000 else plain[:4000] + "\n……\n" + plain[-1000:]
    facts = await extract_emergent_facts(
        segment,
        beat_id=f"auto_read_{chapter_id}",
        prev_state_summary=prev_state,
        recorder=get_adaptive_recorder(str(chapter_id)),
        # 自动认人独立记账：用量面板与自动阅读预算闸按链路区分
        # （2026-09-10 前与手动沉淀共用 loop3.emergent_facts，面板混流不可分）
        stage="adaptive.read_entities",
    )
    await flush_adaptive_records(chapter_id)

    # 失败不写幂等锚（02 候选回流修缮 P6，与 auto_read 事件阶段同纪律）：
    # extract 带 failed 标记区分「LLM 失败」与「无涌现」——失败保留重试资格，
    # 下次进「通读本书」或正文变化时重跑；无涌现照写锚（空手而归也是合法结果）。
    # 间隔时间键与事件侧分立（entities_last_run_at）：认人刚跑完不封锁记事
    if facts.failed:
        return ReadEntitiesResponse(
            ran=False,
            skipped={"code": "llm_failed", "reason": AUTO_READ_SKIP_REASONS["llm_failed"]},
        )
    chapter.auto_read_state = {
        **state,
        "entities_hash": fp,
        "entities_last_run_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()
    return ReadEntitiesResponse(
        ran=True,
        entities=list(facts.new_entities or []),
        locations=list(facts.new_locations or []),
    )
