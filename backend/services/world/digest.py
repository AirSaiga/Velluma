# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 冷层世界总账 digest（B8 · docs/world-cognition-architecture.md §2）
"""节级键控的世界总账：事实节纯代码 + 综合节结构化 ops + 预算分池。

三条承重规则（导师审阅修正后的形态，拒绝自由文本增量合并）：
1. 事实节零 LLM——fold truth + 实体档案纯代码渲染（在场全节 ≤150 字，
   离场一行码 ≤40 字，已闭环弧线归档出局）；
2. 综合节 LLM 只输出 ops（ADD/UPDATE/DELETE/NOOP per section），代码执行；
   输入=权威折叠态+旧节文本（仅措辞连续），禁止「请合并进旧摘要」式改述；
3. source_refs 承担 dirty-tracking：world_version 变更 → diff 脏节 → 只再生
   脏节；未变节 frozen 逐字节冻结（前缀缓存友好）。

门控纪律（docs/reports/world-kernel-construction-plan.md §9）：DIGEST_ENABLED 默认
False——stitch 消费双门（B0 manifest 数据 + 双模型对照）未开前不接生成
主链；finish/audit 侧验证先行。Kill criterion：上线 N 章采纳率/canon 合规
无可测提升 → 回退 v3.1 全注入，本模块维护停用。

副作用：digest 编译有 LLM 调用（预算分池 DIGEST_DAILY_LLM_CALLS，
与 auto-read 的 30/日 隔离——共池会互相饿死）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ---- 门控与预算 ----
DIGEST_ENABLED = False           # 双门签发前保持关闭（kill-safe）
DIGEST_DAILY_LLM_CALLS = 12      # 综合节编译的独立日池（与 auto-read 分池）

SECTION_TEMPLATES = {
    "suspended": "悬而未决",   # 综合节：悬置之事
    "tension": "弧线张力",     # 综合节
    "tone": "基调",            # 综合节
}


def render_fact_sections(
    fold_truth: Dict[str, Any],
    entity_names: Dict[str, str],
    entity_archives: Optional[Dict[str, str]] = None,
    max_present_sections: int = 12,
) -> List[Dict[str, Any]]:
    """事实节渲染（纯代码零 LLM）：t 时刻状态 → 有界节列表。

    在场/有事态实体全节（名+状态+档案摘录 ≤150 字）；其余实体一行码
    （≤40 字）；无状态实体不出节（诚实降级）。
    """
    entity_archives = entity_archives or {}
    sections: List[Dict[str, Any]] = []
    states = fold_truth.get("character_states") or []
    present_count = 0
    for cs in states:
        eid = str(cs.get("entity_id") or "")
        name = entity_names.get(eid) or eid
        alive = bool(cs.get("alive", False))
        loc = entity_names.get(str(cs.get("location_id") or ""), "")
        state_txt = "已死亡" if not alive else (f"位于{loc}" if loc else "有事态")
        body = f"{name}：{state_txt}"
        archive = (entity_archives.get(eid) or "").strip()
        if archive and present_count < max_present_sections:
            body += "｜" + archive[:150]
            present_count += 1
        else:
            body = body[:40] + ("…" if len(body) > 40 else "")  # 离场一行码
        sections.append({
            "section_key": f"entity:{name}",
            "text": body,
            "source_refs": {"entity_ids": [eid], "state": state_txt},
            "derived": "code",
        })
    return sections


def parse_ops(raw: str) -> List[Dict[str, str]]:
    """LLM 综合节输出 → 结构化 ops（代码执行，拒绝自由改述）。

    合法 op：{"op": "ADD|UPDATE|DELETE|NOOP", "section_key": str, "text": str}
    非法/残缺条目静默丢弃（宁缺勿残）。
    """
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("ops") or []
    ops: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "").upper()
        key = str(item.get("section_key") or "").strip()
        text = str(item.get("text") or "").strip()
        if op in ("ADD", "UPDATE") and key and text:
            ops.append({"op": op, "section_key": key, "text": text})
        elif op == "DELETE" and key:
            ops.append({"op": "DELETE", "section_key": key})
        elif op == "NOOP" and key:
            ops.append({"op": "NOOP", "section_key": key})
    return ops


async def compile_digest(
    db: AsyncSession,
    book_id: UUID | str,
    t: int,
) -> Dict[str, Any]:
    """冷层编译入口：事实节（纯代码）+ 综合节 ops（LLM，预算闸内）。

    Returns: {sections, ops_applied, skipped}——skipped 含门控/预算原因（人话）。
    """
    bid = book_id if isinstance(book_id, UUID) else UUID(str(book_id))
    from backend.services.world.fold import fold

    truth = (await fold(db, bid, t=t, domains=("truth",), perspective_set=()))["truth"]

    # 实体名/档案映射（一次轻查询）
    from backend.models import WorldEntity

    rows = (await db.execute(
        select(WorldEntity.id, WorldEntity.name, WorldEntity.props, WorldEntity.importance)
        .where(WorldEntity.book_id == bid)
    )).all()
    entity_names = {str(eid): (name or "") for eid, name, _, _ in rows}
    loc_names = dict(entity_names)
    entity_archives = {}
    for eid, name, props, _imp in rows:
        if isinstance(props, dict) and str(props.get("background") or "").strip():
            entity_archives[str(eid)] = str(props.get("background"))

    fact_sections = render_fact_sections(truth, entity_names, entity_archives)

    # 综合节：门控 + 预算（分池）
    ops_applied: List[Dict[str, str]] = []
    skipped: List[str] = []
    if not DIGEST_ENABLED:
        skipped.append("门控未开：stitch 双门（manifest 数据+双模型对照）签发前综合节不编译")
    else:
        used = await _count_digest_llm_24h(db, bid)
        if used >= DIGEST_DAILY_LLM_CALLS:
            skipped.append(f"日预算已满（{used}/{DIGEST_DAILY_LLM_CALLS}，与自动阅读分池）")
        else:
            ops_applied = await _compile_synthesis_sections(db, bid, truth, fact_sections)

    return {"sections": fact_sections, "ops_applied": ops_applied, "skipped": skipped}


async def _count_digest_llm_24h(db: AsyncSession, book_id: UUID) -> int:
    """综合节编译的滚动 24h 计数（generation_runs 台账，stage=world.digest.compile）。"""
    from datetime import datetime, timedelta, timezone as _tz

    from backend.models import Chapter, GenerationRun

    window_start = datetime.now(_tz.utc).replace(tzinfo=None) - timedelta(hours=24)
    stmt = (
        select(func.count(GenerationRun.id))
        .join(Chapter, GenerationRun.chapter_id == Chapter.id)
        .where(
            Chapter.book_id == book_id,
            GenerationRun.created_at >= window_start,
            GenerationRun.stage == "world.digest.compile",
        )
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def _compile_synthesis_sections(
    db: AsyncSession, book_id: UUID, truth: Dict[str, Any], fact_sections: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """综合节 LLM 编译（悬置之事/弧线张力/基调）——只输出 ops，代码执行。"""
    from backend.models import WorldIntent

    intents = (await db.execute(
        select(WorldIntent).where(
            WorldIntent.book_id == book_id,
            WorldIntent.lifecycle.in_(("declared", "tentative")),
        )
    )).scalars().all()
    loops = [f"{it.kind}: {(it.target_text or '')[:40]}" for it in intents][:12]

    fact_brief = "\n".join(s["text"] for s in fact_sections[:16])
    system = (
        "你是长篇小说的世界总账编撰员。基于权威事实（折叠态与事实节）与开放意图，"
        "只输出三类综合节的结构化操作。规则：旧节文本仅用于措辞连续，事实以输入为准；"
        f"综合节共三种 key：{list(SECTION_TEMPLATES.keys())}；每节 ≤80 字。"
        '只输出 JSON：{"ops": [{"op": "ADD|UPDATE|DELETE|NOOP", "section_key": "...", "text": "..."}]}'
    )
    user = (
        f"# 权威事实（折叠态 t 时刻）\n{fact_brief}\n\n"
        f"# 开放意图（作者未兑现的打算）\n" + ("\n".join(loops) if loops else "（无）")
        + "\n\n请输出综合节 ops。"
    )
    from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage

    result = await call_llm_with_usage(
        system_prompt=system, user_prompt=user,
        model_type="creative", temperature=0.3, max_tokens=1200,
        reasoning_config=REASONING_DISABLED,
    )
    return parse_ops(result.content or "")
