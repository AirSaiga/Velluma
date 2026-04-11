"""
双轨工作流 - 实现双轨对抗架构的核心逻辑。

职责：
- 整合 Track A (节拍扩写) 和 Track B (短文生成)
- 实现并行生成 + 对抗校对的架构
- 管理工作流的各个阶段

工作流阶段：
1. Phase 1: 双轨并行生成
   - Track A: 节拍扩写
   - Track B: 短文生成
2. Phase 2: 节拍统稿
3. Phase 3: 对抗校对
4. Phase 4: 融合精修（可选）

使用方式：
    from backend.services.workflows.dual_track import DualTrackWorkflow, DualTrackConfig

    config = DualTrackConfig()
    workflow = DualTrackWorkflow(api_key, base_url, reasoning_model, creative_model, config)
    result = await workflow.execute(chapter, book, beats, ...)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.dual_track.config.dual_track_config import DualTrackConfig, SketchConfig, AlignerConfig

if TYPE_CHECKING:
    from backend.models import Chapter, Book

logger = logging.getLogger(__name__)


@dataclass
class DualTrackResult:
    """
    双轨工作流执行结果。

    业务含义：
    - 统一双轨工作流的返回格式
    - 包含最终文本、中间结果和统计信息
    """
    final_text: str
    """最终文本"""

    beat_drafts: List[Any] = field(default_factory=list)
    """节拍扩写结果列表"""

    stitched_draft: str = ""
    """统稿后的草稿"""

    sketch_result: Optional[Any] = None
    """Sketch 生成结果"""

    adjustment_plan: Optional[Any] = None
    """对抗校对生成的调整计划"""

    stats: Dict[str, Any] = field(default_factory=dict)
    """统计信息"""

    debug_info: Dict[str, Any] = field(default_factory=dict)
    """调试信息"""


class DualTrackWorkflow:
    """
    双轨工作流。

    职责：
    - 协调 Track A 和 Track B 的并行执行
    - 管理统稿和对抗校对流程
    - 处理工作流的各个阶段

    设计决策：
    - Track A 和 Track B 并行执行，提高效率
    - 使用回调机制报告进度
    - 支持从检查点恢复
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        reasoning_model: str,
        creative_model: str,
        sketch_model: Optional[str] = None,
        config: Optional[DualTrackConfig] = None,
        feature_flags: Optional[Any] = None,
        prompt_logger: Optional[Any] = None,
    ):
        """
        初始化双轨工作流。

        Args:
            api_key: API 密钥
            base_url: API 端点
            reasoning_model: 推理模型
            creative_model: 创意模型
            sketch_model: Sketch 模型（可选，默认使用 creative_model）
            config: 双轨配置
            feature_flags: 功能标志
            prompt_logger: Prompt 日志记录器
        """
        self.api_key = api_key
        self.base_url = base_url
        self.reasoning_model = reasoning_model
        self.creative_model = creative_model
        self.sketch_model = sketch_model or creative_model
        self.config = config or DualTrackConfig()
        self.feature_flags = feature_flags
        self.prompt_logger = prompt_logger

    async def execute(
        self,
        chapter: "Chapter",
        book: "Book",
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
        workflow_tier: Optional[str] = None,
        anchor_pov: Optional[str] = None,
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> DualTrackResult:
        """
        执行双轨工作流。

        职责：这是工作流的主入口方法，协调整个双轨生成流程。

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
            anchor_pov: 锚点视角角色
            progress_callback: 进度回调函数

        Returns:
            DualTrackResult: 工作流执行结果

        Raises:
            ValueError: 如果 beats 为空
        """
        if not beats:
            raise ValueError("beats 不能为空")

        total_start = time.perf_counter()

        logger.info(
            f"[DualTrackWorkflow] 阶段=START 状态=RUNNING "
            f"beats={len(beats)} word_count={word_count}"
        )

        # Phase 1: 双轨并行生成
        beat_drafts, sketch_result, track_time = await self._run_parallel_tracks(
            chapter=chapter,
            book=book,
            beats=beats,
            entities=entities,
            relationships=relationships,
            word_count=word_count,
            previous_summary=previous_summary,
            relevant_memories=relevant_memories,
            locations=locations,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            workflow_tier=workflow_tier,
            anchor_pov=anchor_pov,
            progress_callback=progress_callback,
        )

        await self._emit_progress(
            progress_callback,
            "TRACK_GENERATION_DONE",
            f"双轨生成完成，耗时 {track_time:.1f}s"
        )

        # Phase 2: 统稿
        stitched_draft, stitch_time = await self._run_stitching_stage(
            chapter=chapter,
            book=book,
            beats=beats,
            beat_drafts=beat_drafts,
            sketch_result=sketch_result,
            word_count=word_count,
            anchor_pov=anchor_pov,
            progress_callback=progress_callback,
        )

        # Phase 3: 对抗校对和精修
        final_text, adjustment_plan = await self._run_alignment_and_refinement(
            chapter=chapter,
            book=book,
            beats=beats,
            stitched_draft=stitched_draft,
            sketch_result=sketch_result,
            progress_callback=progress_callback,
        )

        total_time = time.perf_counter() - total_start

        # 构建统计信息
        stats = self._build_stats(
            total_time=total_time,
            track_time=track_time,
            stitch_time=stitch_time,
            final_text=final_text,
            beats=beats,
            adjustment_plan=adjustment_plan,
        )

        debug_info = self._build_debug_info(
            beat_drafts=beat_drafts,
            sketch_result=sketch_result,
            adjustment_plan=adjustment_plan,
        )

        logger.info(
            f"[DualTrackWorkflow] 阶段=DONE 状态=SUCCESS "
            f"total={total_time:.2f}s words={len(final_text)}"
        )

        return DualTrackResult(
            final_text=final_text,
            beat_drafts=beat_drafts,
            stitched_draft=stitched_draft,
            sketch_result=sketch_result,
            adjustment_plan=adjustment_plan,
            stats=stats,
            debug_info=debug_info,
        )

    async def _run_parallel_tracks(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        entities: List[Any],
        relationships: List[Any],
        word_count: int,
        previous_summary: Optional[str],
        relevant_memories: Optional[List[Any]],
        locations: Optional[List[Any]],
        physical_state_lock: Optional[str],
        entity_spatial_ledger: Optional[Dict[str, Any]],
        chapter_assets_schema: str,
        workflow_tier: Optional[str],
        anchor_pov: Optional[str],
        progress_callback: Optional[Callable],
    ) -> Tuple[List[Any], Optional[Any], float]:
        """
        执行双轨并行生成。

        Track A 和 Track B 并行执行：
        - Track A: 节拍扩写（复用 drafting 工作流）
        - Track B: 短文生成（生成连贯的 Sketch）

        Args:
            ... (同 execute 方法)

        Returns:
            Tuple[List, Optional, float]: (beat_drafts, sketch_result, track_time)
        """
        import time as time_module

        parallel_start_perf = time_module.perf_counter()

        # Track A: 节拍扩写
        track_a_task = self._execute_track_a(
            chapter=chapter,
            book=book,
            beats=beats,
            entities=entities,
            relationships=relationships,
            word_count=word_count,
            previous_summary=previous_summary,
            relevant_memories=relevant_memories,
            locations=locations,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            workflow_tier=workflow_tier,
        )

        # Track B: 短文生成（可选）
        if self.config.enable_sketch_track:
            track_b_task = self._execute_track_b(
                chapter=chapter,
                book=book,
                beats=beats,
                entities=entities,
                relationships=relationships,
                word_count=word_count,
                previous_summary=previous_summary,
                anchor_pov=anchor_pov,
                chapter_assets_schema=chapter_assets_schema,
            )
            beat_drafts, sketch_result = await asyncio.gather(
                track_a_task,
                track_b_task,
                return_exceptions=True,
            )

            # 处理异常
            if isinstance(beat_drafts, Exception):
                logger.error(f"[DualTrackWorkflow] Track A 失败: {beat_drafts}")
                raise beat_drafts
            if isinstance(sketch_result, Exception):
                logger.warning(
                    f"[DualTrackWorkflow] Track B 失败: {sketch_result}，继续使用 Track A 结果"
                )
                sketch_result = None
        else:
            beat_drafts = await track_a_task
            sketch_result = None

        track_time = time_module.perf_counter() - parallel_start_perf
        logger.info(
            f"[DualTrackWorkflow] 阶段=DRAFTING 状态=SUCCESS duration={track_time:.2f}s"
        )

        return beat_drafts, sketch_result, track_time

    async def _run_stitching_stage(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        beat_drafts: List[Any],
        sketch_result: Optional[Any],
        word_count: int,
        anchor_pov: Optional[str],
        progress_callback: Optional[Callable],
    ) -> Tuple[str, float]:
        """
        执行统稿阶段。

        将多个 Beat 的生成结果拼接成完整的章节草稿。

        Args:
            ... (参数同前)

        Returns:
            Tuple[str, float]: (stitched_draft, stitch_time)
        """
        import time as time_module

        await self._emit_progress(
            progress_callback, "STITCHING", "正在统稿拼接各节拍内容..."
        )

        stitch_start = time_module.perf_counter()

        # 构建持久状态锚点
        persistent_state_anchors = self._build_persistent_state_anchors(beats)

        # 调用统稿逻辑
        chunks = [draft.draft_chunk for draft in beat_drafts]

        # TODO: 调用实际的 stitch_chunks 函数
        # 这里使用简单的拼接作为占位
        stitched_draft = "\n\n".join(chunks)

        stitch_time = time_module.perf_counter() - stitch_start
        logger.info(
            f"[DualTrackWorkflow] 阶段=STITCHING 状态=SUCCESS "
            f"duration={stitch_time:.2f}s words={len(stitched_draft)}"
        )

        return stitched_draft, stitch_time

    async def _run_alignment_and_refinement(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        stitched_draft: str,
        sketch_result: Optional[Any],
        progress_callback: Optional[Callable],
    ) -> Tuple[str, Optional[Any]]:
        """
        执行对抗校对和精修。

        Args:
            ... (参数同前)

        Returns:
            Tuple[str, Optional[Any]]: (final_text, adjustment_plan)
        """
        adjustment_plan = None
        final_text = stitched_draft

        # 检查是否启用对抗校对
        if not (self.config.enable_adversarial_alignment and sketch_result):
            logger.info(
                "[DualTrackWorkflow] 阶段=REVIEWING 状态=SKIPPED "
                "reason=disabled_or_no_sketch"
            )
            return final_text, adjustment_plan

        # TODO: 调用实际的对抗校对逻辑
        # 这里暂时跳过
        logger.info(
            f"[DualTrackWorkflow] 阶段=REVIEWING 状态=RUNNING "
            "对抗校对（占位实现）"
        )

        return final_text, adjustment_plan

    async def _execute_track_a(
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
        workflow_tier: Optional[str] = None,
    ) -> List[Any]:
        """
        执行 Track A: 节拍扩写。

        复用 drafting 工作流。

        Args:
            ... (参数同前)

        Returns:
            List[Any]: 节拍扩写结果列表
        """
        # TODO: 调用实际的 execute_draft_stage
        # 这里返回占位数据
        from backend.services.workflows.drafting import BeatDraftResult

        results = []
        for i, beat in enumerate(beats):
            results.append(
                BeatDraftResult(
                    beat_id=beat.get("beat_id"),
                    beat_index=i,
                    draft_chunk=f"[Beat {i + 1} 占位内容]",
                )
            )

        return results

    async def _execute_track_b(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        entities: List[Any],
        relationships: List[Any],
        word_count: int,
        previous_summary: Optional[str] = None,
        anchor_pov: Optional[str] = None,
        chapter_assets_schema: str = "",
    ) -> Any:
        """
        执行 Track B: 短文生成。

        生成连贯的 Sketch 作为对齐参考。

        Args:
            ... (参数同前)

        Returns:
            Any: Sketch 生成结果
        """
        # 计算 Sketch 目标字数
        sketch_config = self.config.sketch_config or SketchConfig()
        target_words = int(word_count * sketch_config.sketch_ratio)
        target_words = max(sketch_config.min_words, min(target_words, sketch_config.max_words))

        # TODO: 调用实际的 SketchGenerator
        # 这里返回占位数据
        from backend.services.workflows.sketch_generator import SketchResult

        return SketchResult(
            sketch_text=f"[Sketch 占位内容，约 {target_words} 字]",
            word_count=target_words,
            turn_markers=[],
            emotion_arc=[],
            generation_time=0.0,
        )

    def _build_persistent_state_anchors(self, beats: List[dict]) -> List[Dict[str, str]]:
        """构建持久状态锚点"""
        anchors = []
        for i, beat in enumerate(beats):
            exit_state = beat.get("exit_state", "")
            if exit_state:
                anchors.append({
                    "anchor_type": f"beat_{i + 1}_exit",
                    "description": f"Beat {i + 1} 退出状态: {exit_state}",
                })
        return anchors

    def _build_stats(
        self,
        total_time: float,
        track_time: float,
        stitch_time: float,
        final_text: str,
        beats: List[dict],
        adjustment_plan: Optional[Any],
    ) -> Dict[str, Any]:
        """构建统计信息"""
        return {
            "total_time": total_time,
            "track_time": track_time,
            "stitch_time": stitch_time,
            "final_word_count": len(final_text),
            "beat_count": len(beats),
            "alignment_score": (
                adjustment_plan.alignment_score
                if adjustment_plan
                else None
            ),
        }

    def _build_debug_info(
        self,
        beat_drafts: List[Any],
        sketch_result: Optional[Any],
        adjustment_plan: Optional[Any],
    ) -> Dict[str, Any]:
        """构建调试信息"""
        return {
            "track_a_prompts": [
                p
                for draft in beat_drafts
                for p in getattr(draft, "prompts", [])
            ],
            "track_b_prompts": getattr(sketch_result, "prompts", []) if sketch_result else [],
            "adjustment_analysis": (
                getattr(adjustment_plan, "analysis_prompts", [])
                if adjustment_plan
                else []
            ),
        }

    async def _emit_progress(
        self,
        callback: Optional[Callable],
        event: str,
        message: str,
        **kwargs,
    ) -> None:
        """发送进度事件"""
        if callback:
            await callback(event=event, message=message, **kwargs)
