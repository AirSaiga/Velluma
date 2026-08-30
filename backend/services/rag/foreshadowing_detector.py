# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
伏笔遗漏检测器 - 检测章节中未闭合的伏笔。

职责：
- 检测章节中是否存在已创建但未闭合的伏笔
- 分析伏笔遗漏的风险
- 为审阅阶段提供伏笔检查建议

业务场景：
- 章节审阅时的伏笔检查
- 生成前检查伏笔遗漏风险
- 提醒作者注意伏笔管理

主要功能：
- 遗漏伏笔识别
- 遗漏风险评估
- 闭合建议生成

依赖项：
- backend.services.rag.foreshadowing_tracker: 伏笔追踪器
- backend.models: PlotLedger 模型

使用方式：
    omissions = await detector.detect_omissions(text, book_id, chapter_number)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from uuid import UUID

from backend.models import PlotLedger, MemoryChunk
from backend.services.rag.foreshadowing_types import (
    HookStatus,
    HookPriority,
    HookDetectionResult,
    HookClosureCheckResult,
)
from backend.services.rag.foreshadowing_tracker import EnhancedForeshadowingTracker

if TYPE_CHECKING:
    from backend.repositories.memory_repository import MemoryRepository

logger = logging.getLogger(__name__)


class EnhancedHookOmissionDetector:

    def __init__(self, tracker: EnhancedForeshadowingTracker):
        self.tracker = tracker

    async def detect_omissions(
        self,
        text: str,
        book_id: UUID,
        chapter_number: int,
    ) -> List[Dict[str, Any]]:
        open_hooks = await self.tracker.get_open_hooks(book_id, chapter_number)

        if not open_hooks:
            return []

        closure_results = await self.tracker.check_closure(
            text, open_hooks, chapter_number
        )

        omissions = []

        for result in closure_results:
            hook_info = next(
                (h for h in open_hooks if h.get("hook_id") == result.hook_id),
                {}
            )

            if result.is_closed:
                continue

            is_omission, severity = self._is_omission(
                hook_info, result, chapter_number
            )

            if is_omission:
                omissions.append({
                    "hook_id": result.hook_id,
                    "content": result.hook_content,
                    "priority": hook_info.get("priority", HookPriority.SUB_PLOT.value),
                    "open_duration": chapter_number - hook_info.get("chapter_number", 0),
                    "severity": severity,
                    "is_addressed": result.is_addressed,
                    "suggestion": result.suggestion,
                    "urgency_score": hook_info.get("urgency_score", 0),
                })

        severity_order = {"critical": 0, "major": 1, "minor": 2, "info": 3}
        omissions.sort(key=lambda x: (
            severity_order.get(x.get("severity", "info"), 3),
            -x.get("urgency_score", 0),
        ))

        return omissions

    def _is_omission(
        self,
        hook_info: Dict[str, Any],
        closure_result: HookClosureCheckResult,
        chapter_number: int,
    ) -> Tuple[bool, str]:
        priority = hook_info.get("priority", HookPriority.SUB_PLOT.value)
        created_chapter = hook_info.get("chapter_number", 0)
        open_duration = chapter_number - created_chapter

        if priority == HookPriority.MAIN_PLOT.value:
            if open_duration >= 5:
                return True, "critical"
            elif open_duration >= 3:
                return True, "major"
            elif open_duration >= 2 and not closure_result.is_addressed:
                return True, "minor"

        elif priority == HookPriority.SUB_PLOT.value:
            if open_duration >= 8:
                return True, "major"
            elif open_duration >= 5:
                return True, "minor"

        elif priority == HookPriority.WORLD_BUILDING.value:
            if open_duration >= 12:
                return True, "minor"

        else:
            if open_duration >= 15:
                return True, "info"

        return False, "info"

    def get_repair_suggestion(self, omission: Dict[str, Any]) -> str:
        priority = omission.get("priority", "")
        content = omission.get("content", "")
        is_addressed = omission.get("is_addressed", False)
        open_duration = omission.get("open_duration", 0)

        if priority == HookPriority.MAIN_PLOT.value:
            if is_addressed:
                return f"主线伏笔「{content[:20]}...」已提及，建议在下一章明确闭合"
            return f"主线伏笔「{content[:20]}...」已开放{open_duration}章，需优先安排揭示情节"

        elif priority == HookPriority.SUB_PLOT.value:
            if is_addressed:
                return f"支线伏笔「{content[:20]}...」已提及，可在未来2-3章内闭合"
            return f"支线伏笔「{content[:20]}...」建议在近期章节中回应"

        else:
            if is_addressed:
                return f"伏笔「{content[:20]}...」可作为背景线索继续铺垫"
            return f"伏笔「{content[:20]}...」可作为选择性处理或忽略"


class EnhancedHookMemoryInjector:
    """伏笔记忆注入器 - 将伏笔内容注入到记忆系统。

    迁移说明 (2026-03-30)：
    - 已移除废弃的 db 参数，强制使用 memory_repository
    - 所有数据库操作通过 Repository 执行
    """

    def __init__(
        self,
        memory_repository: "MemoryRepository",
    ):
        self._memory_repo = memory_repository

    async def inject_hook_to_memory(
        self,
        hook: PlotLedger,
        embedding_func: Optional[callable] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> bool:
        try:
            existing = await self._memory_repo.find_one(
                conditions=[
                    MemoryChunk.book_id == hook.book_id,
                    MemoryChunk.chunk_text == hook.content,
                ]
            )

            if existing:
                logger.debug(f"[HookMemoryInjector] 伏笔记忆已存在: {hook.id}")
                return True

            memory = MemoryChunk(
                book_id=hook.book_id,
                chapter_id=hook.chapter_id,
                chunk_text=hook.content,
            )

            if embedding_func and api_key and hook.content:
                try:
                    embedding = await embedding_func(
                        hook.content, api_key, base_url
                    )
                    if embedding:
                        memory.embedding = embedding
                except Exception as e:
                    logger.warning(f"[HookMemoryInjector] 获取向量失败: {e}")

            await self._memory_repo.add_refresh_and_commit(memory)

            logger.info(f"[HookMemoryInjector] 伏笔已注入记忆系统: {hook.id}")
            return True

        except Exception as e:
            logger.error(f"[HookMemoryInjector] 注入失败: {e}")
            return False
