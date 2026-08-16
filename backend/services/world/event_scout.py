# Velluma - 候选事件抽取组件（W4 写作→世界回流的生产端）
# AGPL-3.0
"""
从 settle（段落锁死）/ finish（完稿）的正文抽取候选世界事件（docs/world-writing-bridge.md §4.5）。

组件契约：run(chapter_id, db, snapshot, budget, source=, text=)——orchestrator 注册，
settle/finish 各触发一次。复刻 extract_emergent_facts 的分层哲学：
LLM 只产草稿 → 落 pending 候选（与事件账本物理隔离）→ 作者 ✓ 才转正。

- settle：text=锁死段落（短文本，便宜）
- finish：text 缺省取 chapters.content_text（整章，截 4000 字）
- 幂等去重：pending 池里同章同 (event_type, summary) 不重复建
- 失败/无实体/正文过短 → 返回 0，绝不阻塞 settle/finish 主流程

副作用：写 world_event_candidates（pending）。警示：绝不写 world_events。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chapter
from backend.repositories.world_repository import WorldRepository
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


async def run(
    chapter_id: str,
    db: AsyncSession,
    snapshot: Dict[str, Any],
    budget: int,
    source: str = "settle",
    text: str = "",
    **kw,
) -> Dict[str, Any]:
    """抽取候选事件 → pending 池。返回 {created: N}。"""
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        return {"created": 0}

    body = (text or "").strip() or (chapter.content_text or "").strip()
    if len(body) < _MIN_TEXT_LEN:
        return {"created": 0}

    book_id = str(chapter.book_id)
    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    if not entities:
        return {"created": 0}
    locations = await repo.locations.list_by_book(book_id)
    t = (await resolve_narrative_time(db, chapter)).t

    system_prompt, user_prompt = build_event_candidates_prompt(
        body, t, entities, locations, max_candidates=_MAX_CANDIDATES
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
        parsed = parse_json_safe(raw) or _safe_json(raw)
    except Exception as e:
        logger.warning(f"[event_scout] LLM 抽取失败（不阻塞主流程）: {e}")
        return {"created": 0}

    items = parsed.get("candidates") if isinstance(parsed, dict) else None
    if not isinstance(items, list) or not items:
        return {"created": 0}

    # 幂等去重：pending 池同章同 (event_type, summary) 跳过
    existing = await repo.candidates.list_by_book(book_id, status="pending", chapter_id=chapter_id)
    seen = {
        ((c.draft or {}).get("event_type"), (c.draft or {}).get("summary"))
        for c in existing
    }

    created = 0
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
        seen.add(key)
        await repo.candidates.create(book_id, chapter_id, draft, source=source)
        created += 1

    return {"created": created}
