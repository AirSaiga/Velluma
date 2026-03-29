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
增强伏笔系统 - 伏笔检索和遗漏检测增强模块。

职责：
- 增强伏笔的检索评分
- 伏笔遗漏检测增强
- 伏笔记忆注入

业务场景：
- RAG 检索中的伏笔优先召回
- 章节审阅时的伏笔遗漏检测
- 伏笔相关记忆增强

主要功能：
- 伏笔关联度评分
- 伏笔遗漏检测
- 伏笔记忆注入

依赖项：
- backend.services.rag.foreshadowing_tracker: 基础伏笔追踪
- backend.services.rag.foreshadowing_detector: 基础伏笔检测
- backend.services.rag.foreshadowing_types: 伏笔类型定义

使用方式：
    injector = EnhancedHookMemoryInjector(tracker, detector)
    items = await injector.inject_hook_memories(context, db)
"""

import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PlotLedger
from backend.services.rag.retrieval_types import (
    RetrievedItem,
    MemoryType,
    ContentPriority,
    ContentType,
    RetrievalMethod,
)
from backend.services.rag.foreshadowing_types import (
    HookStatus,
    HookPriority,
    HookClosureType,
    HookMetadata,
    HookDetectionResult,
    HookClosureCheckResult,
    HookScoringConfig,
)
from backend.services.rag.foreshadowing_tracker import EnhancedForeshadowingTracker
from backend.services.rag.foreshadowing_detector import (
    EnhancedHookOmissionDetector,
    EnhancedHookMemoryInjector,
)

logger = logging.getLogger(__name__)


async def create_and_track_hook(
    db: AsyncSession,
    book_id: UUID,
    chapter_id: Optional[UUID],
    content: str,
    created_at_chapter: int,
    ledger_key: str = "",
    priority: HookPriority = HookPriority.SUB_PLOT,
    character_names: List[str] = None,
) -> Optional[PlotLedger]:
    try:
        meta = {
            "priority": priority.value,
            "characters": character_names or [],
            "keywords": re.findall(r'[\u4e00-\u9fa5]{2,}', content),
        }

        hook = PlotLedger(
            book_id=book_id,
            chapter_id=chapter_id,
            content=content,
            ledger_key=ledger_key or f"hook-{uuid4().hex[:8]}",
            status=HookStatus.OPEN.value,
            created_at_chapter=created_at_chapter,
            meta=meta,
        )

        db.add(hook)
        await db.commit()

        injector = EnhancedHookMemoryInjector(db)
        await injector.inject_hook_to_memory(hook)

        logger.info(f"[create_and_track_hook] 伏笔已创建: {hook.id}")
        return hook

    except Exception as e:
        logger.error(f"[create_and_track_hook] 创建失败: {e}")
        return None


async def get_hooks_for_chapter_context(
    db: AsyncSession,
    book_id: UUID,
    chapter_number: int,
    max_hooks: int = 10,
) -> List[RetrievedItem]:
    tracker = EnhancedForeshadowingTracker(db)
    open_hooks = await tracker.get_open_hooks(book_id, chapter_number)

    items = []
    for hook in open_hooks[:max_hooks]:
        item = RetrievedItem(
            memory_type=MemoryType.OPEN_HOOK,
            source_id=hook.get("hook_id", ""),
            content=hook.get("content", ""),
            chapter_number=hook.get("chapter_number", 0),
            character_names=hook.get("character_names", []),
            keywords=hook.get("keywords", []),
            priority=ContentPriority.HIGH,
            content_type=ContentType.FULL_TEXT,
            original_length=len(hook.get("content", "")),
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="未闭合伏笔",
        )

        item.score.urgency_score = hook.get("urgency_score", 0)
        item.score.total_score = hook.get("urgency_score", 0)

        items.append(item)

    return items
