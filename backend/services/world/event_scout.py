# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 候选事件抽取组件（W4 写作→世界回流的生产端）
"""
从 settle（段落锁死）/ finish（完稿）的正文抽取候选世界事件（docs/world-writing-bridge.md §4.5）。

组件契约：run(chapter_id, db, snapshot, budget, source=, text=)——orchestrator 注册，
settle/finish 各触发一次。复刻 extract_emergent_facts 的分层哲学：
LLM 只产草稿 → 落 pending 候选（与事件账本物理隔离）→ 作者 ✓ 才转正。

- settle：text=锁死段落（短文本，便宜）
- finish：text 缺省取 chapters.content_text（整章，截 4000 字）
- 幂等去重三道闸（A5a 升级，防「同一事件换措辞重复提议」）：
  ① prompt 排除块：t 之前最近 15 条已入账事件注入「勿重复提取」
  ② 落池前纯算法预筛：draft.summary 与已入账 note 归一化（去空白/标点）
    子串重合即跳过——宁漏勿误（短于 4 字的归一化文本不参与比对）
  ③ pending 池同章同 (event_type, summary) 不重复建（原有行为不变）
- 失败/无实体/正文过短 → 返回 0 + skipped 原因（P3-4/C6：机器可读短码 +
  人话一句——轻设定书收件箱永空且不可见，带原因给前端空态一句提示），
  绝不阻塞 settle/finish 主流程

副作用：写 world_event_candidates（pending）。警示：绝不写 world_events。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chapter, WorldEvent
from backend.repositories.world_repository import WorldRepository
from backend.services.adaptive.quiet_learning import load_muted_keys, muted_event_types
from backend.services.context.world_bridge import resolve_narrative_time
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.prompts.world_event_prompts import (
    _safe_json,
    build_event_candidates_prompt,
)
from backend.services.world.event_parser import normalize_draft

logger = logging.getLogger(__name__)

_MIN_TEXT_LEN = 20      # 正文过短（如空段/一两字）不浪费 LLM
_MAX_CANDIDATES = 6
_MAX_RECENT_EVENTS = 15   # 排除块/预筛取 t 之前最近 N 条（prompt 预算与查全的折中）

# P3-4（C6）跳过原因短码 → 人话（作者语言口径，上屏原文；堆栈/技术词不上屏）
_SCOUT_SKIP_REASONS = {
    "no_chapter": "章节暂时读不到，稍后再试",
    "short_text": "这段正文还太短，AI 还发现不了世界变化",
    "no_entities": "世界页还没有角色——建几个角色后，AI 才能从正文发现世界变化",
    "llm_failed": "这次提取没成功（不影响写作），下次沉淀或完稿时会再试",
}

# 归一化：去全部空白 + 中西文标点（比较只认实词字形，措辞/标点差异归零）。
# 标点集经 re.escape 逐字转义进字符类——防手写转义/引号拼接出错。
_CJK_PUNCT = "，。！？；：、“”‘’（）《》〈〉【】〔〕…—～·"
_ASCII_PUNCT = ".,!?;:'\"()[]{}<>-_/\\"
_STRIP_RE = re.compile("[\\s" + re.escape(_CJK_PUNCT) + re.escape(_ASCII_PUNCT) + "]+")
_MIN_NORM_LEN = 4  # 归一化后短于此不参与比对（防「死了」「搬家」类短词误杀新事件）


def _normalize_for_dedup(s: str) -> str:
    return _STRIP_RE.sub("", s or "")


def _is_ledger_duplicate(summary: str, recent_notes: List[str]) -> bool:
    """纯算法预筛：summary 与已入账 note 归一化后互为子串 → 判重。

    双向 containment（summary ⊂ note 或 note ⊂ summary）：前者挡「账本详情
    被缩写重提」，后者挡「候选把账本原话扩写重提」。宁漏勿误：任一侧
    归一化后 <4 字直接放行（信息量不足，宁可让 LLM/作者多看一眼）。
    """
    a = _normalize_for_dedup(summary)
    if len(a) < _MIN_NORM_LEN:
        return False
    for note in recent_notes:
        b = _normalize_for_dedup(note)
        if len(b) < _MIN_NORM_LEN:
            continue
        if a in b or b in a:
            return True
    return False


# 公开别名（routes/world.py 转正判重同用——归一化判重判据只此一处，勿平行实现）
normalize_for_dedup = _normalize_for_dedup
is_ledger_duplicate = _is_ledger_duplicate


def _skip(code: str) -> Dict[str, Any]:
    """P3-4（C6）：跳过返回 {created: 0, skipped: {code, reason}}。

    消费方（orchestrator.on_settle/on_finish）只在「无候选产出」时透出 skipped，
    正常产出时该键缺席（零变化契约）；LLM 找不到候选/全被去重筛掉不算跳过，不带原因。
    """
    return {"created": 0, "skipped": {"code": code, "reason": _SCOUT_SKIP_REASONS[code]}}


async def run(
    chapter_id: str,
    db: AsyncSession,
    snapshot: Dict[str, Any],
    budget: int,
    source: str = "settle",
    text: str = "",
    **kw,
) -> Dict[str, Any]:
    """抽取候选事件 → pending 池。返回 {created: N}（跳过时附 skipped 原因）。"""
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        return _skip("no_chapter")

    body = (text or "").strip() or (chapter.content_text or "").strip()
    if len(body) < _MIN_TEXT_LEN:
        return _skip("short_text")

    book_id = str(chapter.book_id)
    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    if not entities:
        return _skip("no_entities")
    locations = await repo.locations.list_by_book(book_id)
    t = (await resolve_narrative_time(db, chapter)).t

    # 已入账去重素材：t 之前最近 N 条（复用本函数已持有的 db 会话，不新建连接；
    # repo 惯约向 UUID 列传 str book_id）。prompt 排除块 + 落池预筛共用一份数据。
    recent_events = list(
        (
            await db.execute(
                select(WorldEvent)
                .where(WorldEvent.book_id == book_id, WorldEvent.time_start <= t)
                .order_by(WorldEvent.time_start.desc(), WorldEvent.sequence_num.desc())
                .limit(_MAX_RECENT_EVENTS)
            )
        )
        .scalars()
        .all()
    )

    # 学着闭嘴（2026-08-25 战略定稿）：作者多次 ✗ 的事件类型静音——prompt 排除 +
    # 落池过滤双闸。失败静默按无静音继续：学习链路故障绝不阻塞候选生产。
    try:
        muted_types = muted_event_types(await load_muted_keys(db, book_id))
    except Exception as e:
        logger.debug(f"[event_scout] 静音集加载失败（按无静音继续）: {e}")
        muted_types = set()

    system_prompt, user_prompt = build_event_candidates_prompt(
        body, t, entities, locations, max_candidates=_MAX_CANDIDATES,
        recent_events=recent_events,
        muted_types=sorted(muted_types) or None,
    )
    try:
        from backend.services.utils.json_safe import parse_json_safe

        resp = await call_llm_with_usage(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="creative",
            temperature=0.1,
            max_tokens=1500,
            reasoning_config=REASONING_DISABLED,
        )
        if isinstance(resp, tuple):
            raw = str(resp[0]) if resp[0] is not None else ""
        else:
            raw = getattr(resp, "content", "") or ""
        if not isinstance(resp, tuple):
            from backend.services.adaptive.observing import get_adaptive_recorder
            get_adaptive_recorder(str(chapter_id)).record_result(
                f"adaptive.event_scout.{source}", resp, model_slot="creative")
        parsed = parse_json_safe(raw) or _safe_json(raw)
    except Exception as e:
        logger.warning(f"[event_scout] LLM 抽取失败（不阻塞主流程）: {e}")
        return _skip("llm_failed")

    items = parsed.get("candidates") if isinstance(parsed, dict) else None
    if not isinstance(items, list) or not items:
        return {"created": 0}

    # 幂等去重闸升级（2026-08-25 全书通读实测）：pending 池判重从「同章同
    # (type,summary)」扩为**全书级归一化子串判重**——同一事件在不同章被重复
    # 抽取（前文回顾/跨章场景）是通读场景的常态，同章幂等拦不住。
    # seen 保留本批内去重（同次 LLM 输出的重复条）。
    existing = await repo.candidates.list_by_book(book_id, status="pending")
    pending_notes = [str((c.draft or {}).get("summary") or "") for c in existing]
    seen = {
        ((c.draft or {}).get("event_type"), (c.draft or {}).get("summary"))
        for c in existing
    }
    # 账本预筛素材：已入账事件的 note（与 prompt 排除块同源）
    ledger_notes = [str(getattr(e, "note", None) or "") for e in recent_events]

    created = 0
    suppressed_muted = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            draft = normalize_draft(item, t, entities, locations)
        except Exception:
            continue
        key = (draft["event_type"], draft["summary"])
        if not draft["summary"] or key in seen:
            continue
        if _is_ledger_duplicate(draft["summary"], ledger_notes):
            continue  # 已入账事件的换皮重提，不入池省一次作者裁决
        if _is_ledger_duplicate(draft["summary"], pending_notes):
            continue  # 全书 pending 池判重：跨章/换措辞的重复候选不再出生
        if muted_types and draft["event_type"] in muted_types:
            suppressed_muted += 1
            continue  # 学着闭嘴落池过滤闸（与 prompt 排除双保险；作者可在收件箱恢复该类型）
        seen.add(key)
        await repo.candidates.create(book_id, chapter_id, draft, source=source)
        created += 1

    result: Dict[str, Any] = {"created": created}
    if suppressed_muted:
        result["suppressed_muted"] = suppressed_muted  # 仅在有静音拦截时带出（零变化契约）
    return result
