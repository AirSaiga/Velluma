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

职责：
- 封装上下文加载逻辑
- 支持 V1/V2/V3 版本上下文组装
- 提供按阶段获取上下文的能力

业务场景：
- Agentic 工作流的上下文准备阶段
- Planning/Drafting/Review 各阶段的上下文注入
- V3.8 增强 RAG 系统的集成

子模块分工：
- context_basic.py: 基础上下文加载（角色、关系、伏笔等）
- context_enhanced.py: V3 增强上下文（含 RAG 检索）

主要功能：
- 基础上下文组装
- 增强 RAG 上下文
- 按阶段获取上下文

依赖项：
- backend.services.rag: RAG 检索系统
- backend.models: 数据模型

使用方式：
    context = await load_chapter_context(chapter_id, db, ...)
"""

import logging
from typing import Any, Optional, Dict, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.workflows.context_basic import (
    load_chapter_context,
    _load_basic_context,
    _load_entities,
    _load_relationships,
    _load_previous_summary,
    _load_open_hooks,
    _load_previous_world_terminal_state,
)
from backend.services.workflows.context_enhanced import (
    load_chapter_context_v2,
    load_chapter_context_v3,
    NEW_RAG_AVAILABLE,
)

try:
    from backend.services.rag import (
        WorkflowRetrievalIntegrator,
        WorkflowStage,
        ContextPackage,
        RetrievalResult,
    )
except ImportError:
    WorkflowRetrievalIntegrator = None
    WorkflowStage = None
    ContextPackage = None
    RetrievalResult = None

logger = logging.getLogger(__name__)


async def get_context_for_stage(
    chapter_id: Any,
    db: AsyncSession,
    stage: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Optional[ContextPackage], Optional[RetrievalResult]]:
    if not NEW_RAG_AVAILABLE:
        logger.warning("[Context] 新 RAG 系统不可用")
        return None, None

    stage_map = {
        "assembling": WorkflowStage.ASSEMBLING,
        "planning": WorkflowStage.PLANNING,
        "drafting": WorkflowStage.DRAFTING,
        "reviewing": WorkflowStage.REVIEWING,
        "refining": WorkflowStage.REFINING,
    }
    workflow_stage = stage_map.get(stage, WorkflowStage.ASSEMBLING)

    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.retrieve_chapter_context(
        chapter_id=chapter_id,
        api_key=api_key,
        base_url=base_url,
        stage=workflow_stage,
    )


async def get_planning_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="planning"
    )


async def get_drafting_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="drafting"
    )


async def get_reviewing_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Optional[dict[str, Any]], List[Dict[str, Any]]]:
    context = await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="reviewing"
    )

    if not context:
        return None, []

    omissions = []
    if NEW_RAG_AVAILABLE and context.get("chapter"):
        try:
            from backend.services.rag import EnhancedForeshadowingTracker, EnhancedHookOmissionDetector

            tracker = EnhancedForeshadowingTracker(db)
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
    db: AsyncSession,
    review_issues: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="refining"
    )
