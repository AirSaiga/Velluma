# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
双轨生成工作流 (Dual Track Workflow) - V3.5 双轨对抗架构

职责：整合 Track A (节拍扩写) 和 Track B (短文生成)，实现并行生成 + 对抗校对。

核心流程：
1. Phase 1: 节拍生成 (复用原有 planning)
2. Phase 2: 双轨并行生成
   - Track A: 节拍扩写 (execute_draft_stage)
   - Track B: 短文生成 (SketchGenerator)
3. Phase 3: 节拍统稿 (stitch_chunks)
4. Phase 4: 对抗校对 (AdversarialAligner)
5. Phase 5: 融合精修 (可选)

优势：
- 并行生成保证速度
- Sketch 提供连贯性锚点
- 对抗校对检测并修复节拍间断层
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from backend.services.workflows.drafting import execute_draft_stage, BeatDraftResult
from backend.services.workflows.stitching import stitch_chunks
from backend.services.workflows.sketch_generator import (
    SketchGenerator, 
    SketchResult, 
    SketchGeneratorConfig
)
from backend.services.workflows.adversarial_aligner import (
    AdversarialAligner,
    AdjustmentPlan,
    AdversarialAlignerConfig
)
from backend.services.prompt_logger import PromptLogger
from backend.schemas import DraftingFeatureFlags, WorkflowTier

logger = logging.getLogger(__name__)


@dataclass
class DualTrackConfig:
    """双轨工作流配置"""
    # 是否启用 Track B (短文生成)
    enable_sketch_track: bool = True
    
    # 是否启用对抗校对
    enable_adversarial_alignment: bool = True
    
    # 是否使用 Sketch 指导精修
    use_sketch_for_refinement: bool = True
    
    # 对抗校对触发阈值（对齐度低于此值触发精修）
    alignment_threshold: float = 70.0
    
    # Sketch 生成器配置
    sketch_config: Optional[SketchGeneratorConfig] = None
    
    # 对抗校对器配置
    aligner_config: Optional[AdversarialAlignerConfig] = None


@dataclass
class DualTrackResult:
    """双轨工作流结果"""
    # 最终正文
    final_text: str
    
    # Track A 结果
    beat_drafts: List[BeatDraftResult]
    stitched_draft: str
    
    # Track B 结果（可选）
    sketch_result: Optional[SketchResult]
    
    # 对抗校对结果（可选）
    adjustment_plan: Optional[AdjustmentPlan]
    
    # 统计信息
    stats: Dict[str, Any]
    
    # 调试信息
    debug_info: Dict[str, Any]


class DualTrackWorkflow:
    """
    双轨生成工作流
    
    使用示例：
        workflow = DualTrackWorkflow(
            api_key=api_key,
            base_url=base_url,
            reasoning_model=reasoning_model,
            creative_model=creative_model,
            config=DualTrackConfig(),
        )
        
        result = await workflow.execute(
            chapter=chapter,
            book=book,
            beats=beats,
            entities=entities,
            relationships=relationships,
            word_count=word_count,
        )
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str,
        reasoning_model: str,
        creative_model: str,
        config: Optional[DualTrackConfig] = None,
        feature_flags: Optional[DraftingFeatureFlags] = None,
        prompt_logger: Optional[PromptLogger] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.reasoning_model = reasoning_model
        self.creative_model = creative_model
        self.config = config or DualTrackConfig()
        self.feature_flags = feature_flags or DraftingFeatureFlags()
        self.prompt_logger = prompt_logger
    
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
        workflow_tier: Optional[WorkflowTier] = None,
        anchor_pov: Optional[str] = None,
    ) -> DualTrackResult:
        """
        执行双轨生成工作流
        
        Args:
            chapter: 章节实体
            book: 书籍实体
            beats: 节拍列表
            entities: 角色实体列表
            relationships: 角色关系列表
            word_count: 目标总字数
            previous_summary: 上一章摘要
            relevant_memories: RAG 相关记忆
            locations: 地图地点列表
            physical_state_lock: 物理状态锁
            entity_spatial_ledger: 角色空间账本
            chapter_assets_schema: 章节资产模式
            workflow_tier: 工作流层级
            anchor_pov: 锚定视角角色
            
        Returns:
            DualTrackResult: 包含最终正文和完整流程结果
        """
        import time
        total_start = time.perf_counter()
        
        logger.info(f"[DualTrack] 启动双轨生成工作流，节拍数: {len(beats)}, 目标字数: {word_count}")
        
        # ===================================================================
        # Phase 2: 双轨并行生成
        # ===================================================================
        
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
        
        # Track B: 短文生成（如果启用）
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
            )
            
            # 并行执行双轨
            logger.info("[DualTrack] 并行执行 Track A (节拍扩写) 和 Track B (短文生成)")
            beat_drafts, sketch_result = await asyncio.gather(
                track_a_task,
                track_b_task,
                return_exceptions=True
            )
            
            # 处理异常
            if isinstance(beat_drafts, Exception):
                logger.error(f"[DualTrack] Track A 失败: {beat_drafts}")
                raise beat_drafts
            if isinstance(sketch_result, Exception):
                logger.warning(f"[DualTrack] Track B 失败: {sketch_result}，将继续使用 Track A 结果")
                sketch_result = None
        else:
            # 仅执行 Track A
            logger.info("[DualTrack] 仅执行 Track A (节拍扩写)")
            beat_drafts = await track_a_task
            sketch_result = None
        
        track_time = time.perf_counter() - total_start
        logger.info(f"[DualTrack] 双轨生成完成，耗时: {track_time:.2f}s")
        
        # ===================================================================
        # Phase 3: 节拍统稿
        # ===================================================================
        
        logger.info("[DualTrack] 开始统稿 (Stitching)")
        stitch_start = time.perf_counter()
        
        # 提取 chunks
        chunks = [draft.draft_chunk for draft in beat_drafts]
        
        stitched_draft = await stitch_chunks(
            chapter=chapter,
            beats=beats,
            chunks=chunks,
            word_count=word_count,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.creative_model,
        )
        
        stitch_time = time.perf_counter() - stitch_start
        logger.info(f"[DualTrack] 统稿完成，耗时: {stitch_time:.2f}s，字数: {len(stitched_draft)}")
        
        # ===================================================================
        # Phase 4: 对抗校对（如果启用且有 Sketch）
        # ===================================================================
        
        adjustment_plan = None
        final_text = stitched_draft
        
        if self.config.enable_adversarial_alignment and sketch_result and sketch_result.sketch_text:
            logger.info("[DualTrack] 开始对抗校对")
            align_start = time.perf_counter()
            
            try:
                adjustment_plan = await self._execute_adversarial_alignment(
                    draft_text=stitched_draft,
                    sketch_result=sketch_result,
                    beats=beats,
                    chapter=chapter,
                    book=book,
                )
                
                align_time = time.perf_counter() - align_start
                logger.info(f"[DualTrack] 对抗校对完成，耗时: {align_time:.2f}s，对齐度得分: {adjustment_plan.alignment_score:.1f}")
                
                # 如果需要调整且启用了自动修复，执行修复
                if adjustment_plan.needs_adjustment and self.config.use_sketch_for_refinement:
                    logger.info(f"[DualTrack] 对齐度 {adjustment_plan.alignment_score:.1f} 低于阈值 {self.config.alignment_threshold}，执行融合精修")
                    final_text = await self._execute_fusion_refinement(
                        stitched_draft=stitched_draft,
                        sketch_result=sketch_result,
                        adjustment_plan=adjustment_plan,
                        beats=beats,
                        chapter=chapter,
                        book=book,
                    )
                else:
                    logger.info("[DualTrack] 对齐度良好或禁用自动修复，跳过融合精修")
                    
            except Exception as e:
                logger.error(f"[DualTrack] 对抗校对失败: {e}，使用统稿结果")
                final_text = stitched_draft
        else:
            logger.info("[DualTrack] 跳过对抗校对")
        
        total_time = time.perf_counter() - total_start
        
        # 构建统计信息
        stats = {
            "total_time": total_time,
            "track_time": track_time,
            "stitch_time": stitch_time if 'stitch_time' in dir() else 0,
            "final_word_count": len(final_text),
            "beat_count": len(beats),
            "alignment_score": adjustment_plan.alignment_score if adjustment_plan else None,
        }
        
        # 构建调试信息
        debug_info = {
            "track_a_prompts": [p for draft in beat_drafts for p in draft.prompts],
            "track_b_prompts": sketch_result.prompts if sketch_result else [],
            "adjustment_analysis": adjustment_plan.analysis_prompts if adjustment_plan else [],
        }
        
        logger.info(f"[DualTrack] 双轨工作流完成，总耗时: {total_time:.2f}s，最终字数: {len(final_text)}")
        
        return DualTrackResult(
            final_text=final_text,
            beat_drafts=beat_drafts,
            stitched_draft=stitched_draft,
            sketch_result=sketch_result,
            adjustment_plan=adjustment_plan,
            stats=stats,
            debug_info=debug_info,
        )
    
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
        workflow_tier: Optional[WorkflowTier] = None,
    ) -> List[BeatDraftResult]:
        """执行 Track A: 节拍扩写"""
        return await execute_draft_stage(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beats=beats,
            open_hooks=[],  # 已在 beats 中
            api_key=self.api_key,
            base_url=self.base_url,
            reasoning_model=self.reasoning_model,
            creative_model=self.creative_model,
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
    ) -> SketchResult:
        """执行 Track B: 短文生成，并记录 Prompt 到日志"""
        # 计算目标字数
        config = self.config.sketch_config or SketchGeneratorConfig()
        target_words = int(word_count * config.sketch_ratio)
        target_words = max(config.min_words, min(target_words, config.max_words))
        
        # 构建 Prompt（用于日志记录）
        generator = SketchGenerator(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.creative_model,
            config=config,
        )
        
        system_prompt, user_prompt = generator.build_sketch_prompt(
            chapter=chapter,
            book=book,
            beats=beats,
            entities=entities,
            relationships=relationships,
            target_words=target_words,
            previous_summary=previous_summary,
            anchor_pov=anchor_pov,
        )
        
        # 记录 Prompt 到日志（如果提供了 prompt_logger）
        if self.prompt_logger:
            stage_idx = self.prompt_logger.start_stage(
                stage_name="SKETCH_GENERATION",
                iteration=1,
            )
            self.prompt_logger.log_inputs(
                target_words=target_words,
                beat_count=len(beats),
                sketch_ratio=config.sketch_ratio,
                temperature=config.temperature,
            )
            self.prompt_logger.log_prompts(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.creative_model,
                temperature=config.temperature,
                max_tokens=int(target_words * 2.5),
                prompt_label="SKETCH",
            )
        
        # 执行生成
        result = await generator.generate(
            chapter=chapter,
            book=book,
            beats=beats,
            entities=entities,
            relationships=relationships,
            word_count=word_count,
            previous_summary=previous_summary,
            anchor_pov=anchor_pov,
        )
        
        # 记录输出到日志
        if self.prompt_logger and result:
            self.prompt_logger.log_outputs(
                word_count=result.word_count,
                turn_markers_count=len(result.turn_markers),
                generation_time=result.generation_time,
                sketch_preview=result.sketch_text[:500] if result.sketch_text else "",
            )
            self.prompt_logger.end_stage(success=bool(result.sketch_text))
        
        return result
    
    async def _execute_adversarial_alignment(
        self,
        draft_text: str,
        sketch_result: SketchResult,
        beats: List[dict],
        chapter: Any,
        book: Any,
    ) -> AdjustmentPlan:
        """执行对抗校对"""
        aligner = AdversarialAligner(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.reasoning_model,  # 使用推理模型
            config=self.config.aligner_config or AdversarialAlignerConfig(),
        )
        
        return await aligner.align(
            draft_text=draft_text,
            sketch_result=sketch_result,
            beats=beats,
            chapter=chapter,
            book=book,
        )
    
    async def _execute_fusion_refinement(
        self,
        stitched_draft: str,
        sketch_result: SketchResult,
        adjustment_plan: AdjustmentPlan,
        beats: List[dict],
        chapter: Any,
        book: Any,
    ) -> str:
        """
        执行融合精修
        
        基于对抗校对结果，使用 Sketch 的连贯性特征修复 Draft 的问题。
        """
        logger.info(f"[DualTrack] 执行融合精修，修复 {len(adjustment_plan.gaps)} 个问题")
        
        # 简化实现：返回统稿结果（实际实现应该根据 adjustment_plan 进行精修）
        # 实际实现应该：
        # 1. 对于 SEGMENT_BOUNDARY 问题，用 Sketch 中的对应过渡替换
        # 2. 对于 BEAT_DESIGN 问题，调整 entry/exit state
        # 3. 对于其他问题，局部重写
        
        # TODO: 实现完整的融合精修逻辑
        
        return stitched_draft


# =============================================================================
# 便捷函数：与原有 agentic_workflow 集成
# =============================================================================

async def execute_dual_track_generation(
    chapter: Any,
    book: Any,
    beats: List[dict],
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    workflow_tier: Optional[WorkflowTier] = None,
    anchor_pov: Optional[str] = None,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    enable_dual_track: bool = True,
    prompt_logger: Optional[PromptLogger] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    便捷函数：执行双轨生成
    
    这是与原有 agentic_workflow 集成的入口函数。
    
    Returns:
        Tuple[str, Dict]: (最终正文, 调试信息)
    """
    if not enable_dual_track:
        # 回退到原有单轨流程
        from backend.services.workflows.drafting import execute_draft_stage
        from backend.services.workflows.stitching import stitch_chunks
        
        beat_drafts = await execute_draft_stage(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beats=beats,
            open_hooks=[],
            api_key=api_key,
            base_url=base_url,
            reasoning_model=reasoning_model,
            creative_model=creative_model,
            word_count=word_count,
            previous_summary=previous_summary,
            relevant_memories=relevant_memories,
            locations=locations,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            workflow_tier=workflow_tier,
            feature_flags=feature_flags,
        )
        
        chunks = [draft.draft_chunk for draft in beat_drafts]
        final_text = await stitch_chunks(
            chapter=chapter,
            beats=beats,
            chunks=chunks,
            word_count=word_count,
            api_key=api_key,
            base_url=base_url,
            model=creative_model,
        )
        
        return final_text, {"mode": "single_track"}
    
    # 执行双轨流程
    config = DualTrackConfig(
        enable_sketch_track=True,
        enable_adversarial_alignment=True,
        use_sketch_for_refinement=True,
    )
    
    workflow = DualTrackWorkflow(
        api_key=api_key,
        base_url=base_url,
        reasoning_model=reasoning_model,
        creative_model=creative_model,
        config=config,
        feature_flags=feature_flags,
        prompt_logger=prompt_logger,
    )
    
    result = await workflow.execute(
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
    )
    
    debug_info = {
        "mode": "dual_track",
        "stats": result.stats,
        "alignment_score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
        "needs_adjustment": result.adjustment_plan.needs_adjustment if result.adjustment_plan else False,
        "passed": not (result.adjustment_plan.needs_adjustment if result.adjustment_plan else False),
        "iterations": 1,  # 双轨模式目前只执行一轮
        "revision_count": 1 if result.adjustment_plan and result.adjustment_plan.needs_adjustment else 0,
    }
    
    return result.final_text, debug_info
