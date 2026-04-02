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
上下文组装工作流 - 统一导出入口。

迁移说明 (2026-03-30)：
- 所有函数已迁移到使用 Repository 模式
- 新接口使用 repositories 参数
- 旧的 db 参数版本已移除

使用方式：
    repos = {
        "chapter": ChapterRepository(db),
        ...
    }
    context = await get_planning_context(chapter_id, repos)
"""

import logging
from typing import Any, Optional, Dict, List, Tuple, Union

from backend.services.workflows.context_basic import (
    load_chapter_context as _load_chapter_context_basic,
    load_chapter_context as load_chapter_context,
)
from backend.services.workflows.context_enhanced import (
    load_chapter_context_v2,
    load_chapter_context_v3,
    NEW_RAG_AVAILABLE,
)

logger = logging.getLogger(__name__)


async def get_context_for_stage(
    chapter_id: Any,
    repositories: Dict[str, Any],
    stage: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Optional[Any], Optional[Any]]:
    if not NEW_RAG_AVAILABLE:
        logger.warning("[Context] 新 RAG 系统不可用")
        return None, None

    stage_map = {
        "assembling": 1,  # WorkflowStage.ASSEMBLING
        "planning": 2,    # WorkflowStage.PLANNING
        "drafting": 3,    # WorkflowStage.DRAFTING
        "reviewing": 4,   # WorkflowStage.REVIEWING
        "refining": 5,    # WorkflowStage.REFINING
    }

    return await load_chapter_context_v3(
        chapter_id, repositories, api_key, base_url,
        stage=stage_map.get(stage, "assembling")
    )


async def get_planning_context(
    chapter_id: Any,
    repositories: Dict[str, Any],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await load_chapter_context_v3(
        chapter_id, repositories, api_key, base_url,
        stage="planning"
    )


async def get_drafting_context(
    chapter_id: Any,
    repositories: Dict[str, Any],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await load_chapter_context_v3(
        chapter_id, repositories, api_key, base_url,
        stage="drafting"
    )


async def get_reviewing_context(
    chapter_id: Any,
    repositories: Dict[str, Any],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Optional[dict[str, Any]], List[Dict[str, Any]]]:
    context = await load_chapter_context_v3(
        chapter_id, repositories, api_key, base_url,
        stage="reviewing"
    )

    if not context:
        return None, []

    omissions = []
    if NEW_RAG_AVAILABLE and context.get("chapter"):
        try:
            from backend.services.rag import EnhancedForeshadowingTracker, EnhancedHookOmissionDetector

            plot_repo = repositories.get("plot_ledger")
            if plot_repo:
                tracker = EnhancedForeshadowingTracker(plot_repo)
                detector = EnhancedHookOmissionDetector(tracker)

                chapter = context["chapter"]
                chapter_text = chapter.draft_text or ""

                if chapter_text:
                    omissions = await detector.detect_omissions(
                        chapter_text,
                        chapter.book_id,
                        chapter.chapter_number,
                    )
        except Exception as e:
            logger.warning(f"[Context] 伏笔遗漏检测失败: {e}")

    return context, omissions


async def get_refining_context(
    chapter_id: Any,
    repositories: Dict[str, Any],
    review_issues: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await load_chapter_context_v3(
        chapter_id, repositories, api_key, base_url,
        stage="refining"
    )
