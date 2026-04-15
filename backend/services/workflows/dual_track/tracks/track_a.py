"""
Track A - 节拍扩写轨道。

职责：
- 执行节拍扩写任务
- 复用 drafting 工作流的生成逻辑
- 支持并发控制和失败处理

依赖项：
- backend.services.workflows.drafting: execute_draft_stage

使用方式：
    from backend.services.workflows.dual_track.tracks.track_a import TrackAExecutor

    executor = TrackAExecutor(api_key, base_url, reasoning_model, creative_model)
    beat_drafts = await executor.execute(chapter, book, beats, ...)
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.services.workflows.drafting import execute_draft_stage, BeatDraftResult

if TYPE_CHECKING:
    from backend.schemas import DraftingFeatureFlags, WorkflowTier

logger = logging.getLogger(__name__)


class TrackAExecutor:
    """
    Track A 执行器 - 节拍扩写。

    职责：
    - 调用 execute_draft_stage 执行节拍扩写
    - 管理并发度和失败重试
    - 收集调试信息

    设计决策：
    - 直接委托给 execute_draft_stage，保持一致性
    - 不添加额外的抽象层，避免复杂度
    """

    def __init__(
        self,
        feature_flags: Optional["DraftingFeatureFlags"] = None,
    ):
        """
        初始化 Track A 执行器。

        Args:
            feature_flags: 功能标志
        """
        self.feature_flags = feature_flags

    async def execute(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        entities: List[Any],
        relationships: List[Any],
        word_count: int,
        previous_summary: Optional[str] = None,
        relevant_memories: Optional[List[Any]] = None,
        locations: Optional[List[Any]] = None,
        physical_state_lock: Optional[str] = None,
        entity_spatial_ledger: Optional[Dict[str, Any]] = None,
        chapter_assets_schema: str = "",
        workflow_tier: Optional["WorkflowTier"] = None,
    ) -> List[BeatDraftResult]:
        """
        执行 Track A - 节拍扩写。

        职责：调用 execute_draft_stage 生成各节拍的内容。

        Args:
            chapter: 章节对象
            book: 书籍对象
            beats: 剧情节拍列表
            entities: 角色实体列表
            relationships: 角色关系列表
            word_count: 目标字数
            previous_summary: 前情摘要
            relevant_memories: 相关记忆列表
            locations: 地点列表
            physical_state_lock: 物理状态锁
            entity_spatial_ledger: 实体空间台账
            chapter_assets_schema: 章节资产模式
            workflow_tier: 工作流层级

        Returns:
            List[BeatDraftResult]: 节拍扩写结果列表

        Raises:
            Exception: 如果生成失败
        """
        logger.info(f"[TrackA] 开始执行节拍扩写，beats={len(beats)}, word_count={word_count}")

        try:
            beat_drafts = await execute_draft_stage(
                chapter=chapter,
                book=book,
                entities=entities,
                relationships=relationships,
                beats=beats,
                open_hooks=[],
                word_count=word_count,
                previous_summary=previous_summary,
                relevant_memories=relevant_memories,
                locations=locations,
                enable_qc=True,
                feature_flags=self.feature_flags,
                physical_state_lock=physical_state_lock,
                entity_spatial_ledger=entity_spatial_ledger,
                chapter_assets_schema=chapter_assets_schema,
                workflow_tier=workflow_tier,
            )

            logger.info(f"[TrackA] 执行完成，成功生成 {len(beat_drafts)} 个节拍")
            return beat_drafts

        except Exception as e:
            logger.error(f"[TrackA] 执行失败: {e}")
            raise
