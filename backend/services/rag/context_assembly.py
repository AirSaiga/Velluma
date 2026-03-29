"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
上下文组装模块 - RAG 检索结果组装为可用上下文。

职责：
- 协调多个 RAG 组件完成上下文组装
- 调用检索器获取记忆
- 调用打包器构建上下文包
- 集成伏笔检测

业务场景：
- 章节生成前的上下文准备
- 规划阶段的记忆加载
- 起草阶段的上下文注入

主要功能：
- 检索策略执行
- 上下文打包
- 伏笔遗漏检测

依赖项：
- backend.services.rag.retriever: 记忆检索器
- backend.services.rag.context_packager: 上下文打包器
- backend.services.rag.foreshadowing: 伏笔追踪

使用方式：
    context = await assemble_chapter_context(chapter_id, db, api_key, strategy=...)
"""

import logging

from backend.services.rag.retrieval_types import (
    RetrievalStrategy,
    ContextPackage,
    RetrievalResult,
)
from backend.services.rag.retriever import (
    retrieve_chapter_memories,
)
from backend.services.rag.context_packager import (
    build_context_package,
)
from backend.services.rag.foreshadowing import (
    ForeshadowingTracker,
    HookOmissionDetector,
)


logger = logging.getLogger(__name__)


async def assemble_chapter_context(
    chapter_id: str,
    db,
    api_key: str,
    base_url: str = None,
    strategy: RetrievalStrategy = RetrievalStrategy.BALANCED_REFERENCE,
    stage: str = "drafting",
) -> tuple:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from backend.models import (
        Chapter, Book, ChapterEntity, CharacterRelationship,
        PlotLedger, ChapterMapLocation,
    )
    from backend.world_state_schemas import WorldTerminalState

    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()

    if not chapter:
        raise ValueError(f"章节不存在: {chapter_id}")

    book_result = await db.execute(
        select(Book).where(Book.id == chapter.book_id)
    )
    book = book_result.scalar_one_or_none()

    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = list(entities_result.scalars().all())

    character_ids = [e.entity_id for e in entities]

    if character_ids:
        relationships_result = await db.execute(
            select(CharacterRelationship)
            .options(
                selectinload(CharacterRelationship.source_character),
                selectinload(CharacterRelationship.target_character),
            )
            .where(
                CharacterRelationship.source_char_id.in_(character_ids),
                CharacterRelationship.target_char_id.in_(character_ids),
            )
        )
        relationships = list(relationships_result.scalars().all())
    else:
        relationships = []

    hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            PlotLedger.created_at_chapter < chapter.chapter_number,
        )
    )
    open_hooks = [
        {
            "hook_id": str(h.id),
            "ledger_key": h.ledger_key or "",
            "content": h.content or "",
        }
        for h in hook_result.scalars().all()
    ]

    previous_summary = None
    if chapter.chapter_number > 1:
        prev_result = await db.execute(
            select(Chapter).where(
                Chapter.book_id == chapter.book_id,
                Chapter.chapter_number == chapter.chapter_number - 1,
            )
        )
        prev_chapter = prev_result.scalar_one_or_none()
        if prev_chapter:
            previous_summary = prev_chapter.summary

    previous_world_state = None
    if chapter.chapter_number > 1:
        prev_result = await db.execute(
            select(Chapter).where(
                Chapter.book_id == chapter.book_id,
                Chapter.chapter_number == chapter.chapter_number - 1,
            )
        )
        prev_chapter = prev_result.scalar_one_or_none()
        if prev_chapter and prev_chapter.world_snapshot:
            previous_world_state = WorldTerminalState.from_chapter_snapshot(
                prev_chapter.world_snapshot
            )

    result = await retrieve_chapter_memories(
        chapter=chapter,
        book=book,
        db=db,
        entities=entities,
        relationships=relationships,
        open_hooks=open_hooks,
        previous_summary=previous_summary,
        previous_world_state=previous_world_state,
        strategy=strategy,
        api_key=api_key,
        base_url=base_url,
    )

    package = build_context_package(result, stage=stage)

    return package, result


async def get_context_for_planning(
    chapter_id: str,
    db,
    api_key: str,
    base_url: str = None,
) -> ContextPackage:
    package, _ = await assemble_chapter_context(
        chapter_id, db, api_key, base_url,
        strategy=RetrievalStrategy.BALANCED_REFERENCE,
        stage="planning",
    )
    return package


async def get_context_for_drafting(
    chapter_id: str,
    db,
    api_key: str,
    base_url: str = None,
) -> ContextPackage:
    package, _ = await assemble_chapter_context(
        chapter_id, db, api_key, base_url,
        strategy=RetrievalStrategy.BALANCED_REFERENCE,
        stage="drafting",
    )
    return package


async def get_context_for_reviewing(
    chapter_id: str,
    db,
    api_key: str = None,
    base_url: str = None,
) -> ContextPackage:
    package, _ = await assemble_chapter_context(
        chapter_id, db, api_key, base_url,
        strategy=RetrievalStrategy.CHARACTER_FOCUSED,
        stage="reviewing",
    )
    return package


async def check_foreshadowing_omissions(
    chapter_id: str,
    chapter_text: str,
    db,
) -> list:
    from sqlalchemy import select
    from backend.models import Chapter

    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()

    if not chapter:
        return []

    tracker = ForeshadowingTracker(db)
    detector = HookOmissionDetector(tracker)

    return await detector.detect_omissions(
        text=chapter_text,
        book_id=chapter.book_id,
        chapter_number=chapter.chapter_number,
    )
