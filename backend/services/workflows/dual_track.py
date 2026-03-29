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
from backend.services.workflows.refining import refine_single_beat, refine_draft
from backend.services.workflows.sketch_generator import (
    SketchGenerator, 
    SketchResult, 
    SketchGeneratorConfig
)
from backend.services.workflows.adversarial_aligner import (
    AdversarialAligner,
    AdjustmentPlan,
    AdversarialAlignerConfig,
    GapSource,
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
        sketch_model: Optional[str] = None,
        config: Optional[DualTrackConfig] = None,
        feature_flags: Optional[DraftingFeatureFlags] = None,
        prompt_logger: Optional[PromptLogger] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.reasoning_model = reasoning_model
        self.creative_model = creative_model
        self.sketch_model = sketch_model or creative_model
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
        progress_callback: Optional[callable] = None,
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
        
        # 辅助函数：发送进度事件
        async def _emit_progress(event: str, message: str, **kwargs):
            if progress_callback:
                await progress_callback(event=event, message=message, **kwargs)
        
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
        # ── 并行阶段开始时记录 wall time，用于 DRAFTING stage 的 post-hoc 补录 ──
        parallel_start_wall = time.time()
        parallel_start_perf = time.perf_counter()
        
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
        
        track_time = time.perf_counter() - parallel_start_perf
        logger.info(f"[DualTrack] 双轨生成完成，耗时: {track_time:.2f}s")
        
        # 发送双轨生成完成进度事件
        await _emit_progress("TRACK_GENERATION_DONE", f"双轨生成完成，耗时 {track_time:.1f}s")
        
        # ── DRAFTING 阶段日志（post-hoc 补录，主协程串行写入，无竞态风险）──
        # Track A 与 Track B 并行执行，SKETCH_GENERATION 日志已由 _execute_track_b 内部写入
        # DRAFTING 在此处补录，并将 start_time 回写为并行阶段的真实起始时间
        if self.prompt_logger and isinstance(beat_drafts, list):
            self.prompt_logger.start_stage("DRAFTING", iteration=1)
            # 回写真实起始时间，使 end_stage 计算出正确的 elapsed
            self.prompt_logger.log_data["stages"][-1]["start_time"] = parallel_start_wall
            self.prompt_logger.log_inputs(
                beat_count=len(beats),
                word_count=word_count,
                note="与SKETCH_GENERATION并行执行，elapsed为Track A真实耗时",
            )
            # ── 记录每个 Beat 的详细 prompts（Scene Intent / Subconscious / Prose Draft）──
            for draft in beat_drafts:
                for p in (draft.prompts or []):
                    self.prompt_logger.log_prompts(
                        system_prompt=p.get("system_prompt", ""),
                        user_prompt=p.get("user_prompt", ""),
                        model=self.reasoning_model if p.get("stage") in ["SCENE_INTENT", "SUBCONSCIOUS"] else self.creative_model,
                        temperature=p.get("temperature", 0.7),
                        prompt_label=f"{p.get('stage', 'UNKNOWN')}_BEAT_{draft.beat_index}",
                    )
            total_draft_words = sum(len(d.draft_chunk) for d in beat_drafts)
            self.prompt_logger.log_outputs(
                beat_count=len(beat_drafts),
                total_draft_words=total_draft_words,
                beat_previews=[
                    {"id": d.beat_id, "words": len(d.draft_chunk), "preview": d.draft_chunk[:300]}
                    for d in beat_drafts  # 全量输出，含预览
                ],
            )
            self.prompt_logger.end_stage(success=True)
        
        # ===================================================================
        # Phase 3: 节拍统稿
        # ===================================================================
        
        logger.info("[DualTrack] 开始统稿 (Stitching)")
        await _emit_progress("STITCHING", "正在统稿拼接各节拍内容...")
        stitch_start = time.perf_counter()
        
        # 提取 chunks
        chunks = [draft.draft_chunk for draft in beat_drafts]
        
        # V3.5: 从 beats 构建持久状态锚点，供统稿阶段平滑跨 Beat 状态
        persistent_state_anchors = []
        for i, beat in enumerate(beats):
            exit_state = beat.get("exit_state", "")
            if exit_state:
                persistent_state_anchors.append({
                    "anchor_type": f"beat_{i + 1}_exit",
                    "description": f"Beat {i + 1} 退出状态: {exit_state}",
                })
        
        # ── STITCHING 阶段日志 ──
        if self.prompt_logger:
            self.prompt_logger.start_stage("STITCHING", iteration=1)
            self.prompt_logger.log_inputs(
                beat_count=len(beats),
                chunks_count=len(chunks),
                word_count=word_count,
            )
        
        stitched_draft = await stitch_chunks(
            chapter=chapter,
            beats=beats,
            chunks=chunks,
            word_count=word_count,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.creative_model,
            anchor_pov=anchor_pov,
            prompt_logger=self.prompt_logger,
            sketch_text=sketch_result.sketch_text if sketch_result else None,
            book=book,
            persistent_state_anchors=persistent_state_anchors or None,
        )
        
        stitch_time = time.perf_counter() - stitch_start
        logger.info(f"[DualTrack] 统稿完成，耗时: {stitch_time:.2f}s，字数: {len(stitched_draft)}")
        
        if self.prompt_logger:
            self.prompt_logger.log_outputs(
                stitched_word_count=len(stitched_draft),
                stitched_text=stitched_draft,  # 完整统稿正文
            )
            self.prompt_logger.end_stage(success=bool(stitched_draft))
        
        # ===================================================================
        # Phase 4: 对抗校对（如果启用且有 Sketch）
        # ===================================================================
        
        adjustment_plan = None
        final_text = stitched_draft
        
        if self.config.enable_adversarial_alignment and sketch_result and sketch_result.sketch_text:
            logger.info("[DualTrack] 开始对抗校对")
            align_start = time.perf_counter()
            
            # ── ADVERSARIAL_ALIGNMENT 阶段日志 ──
            if self.prompt_logger:
                self.prompt_logger.start_stage("ADVERSARIAL_ALIGNMENT", iteration=1)
                self.prompt_logger.log_inputs(
                    draft_word_count=len(stitched_draft),
                    sketch_word_count=sketch_result.word_count if sketch_result else 0,
                    alignment_threshold=self.config.alignment_threshold,
                )
            
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
                
                if self.prompt_logger:
                    # 将对抗校对器在信息对齐分析中使用的 LLM prompt 注入日志
                    for ap in (adjustment_plan.analysis_prompts or []):
                        self.prompt_logger.log_prompts(
                            system_prompt=ap.get("system_prompt", ""),
                            user_prompt=ap.get("user_prompt", ""),
                            model=self.reasoning_model,  # 对抗校对使用推理模型
                            temperature=self.config.aligner_config.temperature if self.config.aligner_config else 0.1,
                            max_tokens=self.config.aligner_config.max_analysis_tokens if self.config.aligner_config else 2000,
                            prompt_label=ap.get("stage", "INFO_ALIGNMENT_ANALYSIS"),
                        )
                    self.prompt_logger.log_outputs(
                        alignment_score=adjustment_plan.alignment_score,
                        needs_adjustment=adjustment_plan.needs_adjustment,
                        gaps_count=len(adjustment_plan.gaps) if adjustment_plan.gaps else 0,
                    )
                    self.prompt_logger.end_stage(success=True)
                
                # 如果需要调整且启用了自动修复，执行修复
                if adjustment_plan.needs_adjustment and self.config.use_sketch_for_refinement:
                    logger.info(f"[DualTrack] 对齐度 {adjustment_plan.alignment_score:.1f} 低于阈值 {self.config.alignment_threshold}，执行融合精修")
                    if self.prompt_logger:
                        self.prompt_logger.start_stage("FUSION_REFINEMENT", iteration=1)
                        self.prompt_logger.log_inputs(
                            alignment_score=adjustment_plan.alignment_score,
                            gaps_count=len(adjustment_plan.gaps) if adjustment_plan.gaps else 0,
                            beats_to_refine=list(adjustment_plan.beat_adjustments.keys()) if adjustment_plan.beat_adjustments else [],
                            has_global_adjustments=bool(adjustment_plan.global_adjustments),
                        )
                    try:
                        final_text = await self._execute_fusion_refinement(
                            stitched_draft=stitched_draft,
                            sketch_result=sketch_result,
                            adjustment_plan=adjustment_plan,
                            beats=beats,
                            chapter=chapter,
                            book=book,
                        )
                        if self.prompt_logger:
                            self.prompt_logger.log_outputs(
                                final_word_count=len(final_text),
                                stitched_word_count=len(stitched_draft),
                                word_diff=len(final_text) - len(stitched_draft),
                            )
                            self.prompt_logger.end_stage(success=True)
                    except Exception as refine_e:
                        logger.error(f"[DualTrack] 融合精修失败: {refine_e}，使用统稿结果")
                        if self.prompt_logger:
                            self.prompt_logger.log_outputs(error=str(refine_e))
                            self.prompt_logger.end_stage(success=False)
                        final_text = stitched_draft
                else:
                    logger.info("[DualTrack] 对齐度良好或禁用自动修复，跳过融合精修")
                    
            except Exception as e:
                logger.error(f"[DualTrack] 对抗校对失败: {e}，使用统稿结果")
                if self.prompt_logger:
                    self.prompt_logger.log_outputs(error=str(e))
                    self.prompt_logger.end_stage(success=False)
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
        chapter_assets_schema: str = "",
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
            model=self.sketch_model,
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
            chapter_assets_schema=chapter_assets_schema,
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
                model=self.sketch_model,
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
            chapter_assets_schema=chapter_assets_schema,
        )
        
        # 记录输出到日志
        if self.prompt_logger and result:
            self.prompt_logger.log_outputs(
                word_count=result.word_count,
                turn_markers_count=len(result.turn_markers),
                generation_time=result.generation_time,
                sketch_text=result.sketch_text,  # 完整速写正文
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
        
        修复策略：
        1. SEGMENT_BOUNDARY 问题：提取 Sketch 中对应位置的过渡文本作为参考
        2. BEAT_DESIGN 问题：调整 entry/exit state 后重写
        3. 其他问题：基于 fix_suggestion 进行局部重写
        """
        import time
        refine_start = time.perf_counter()
        
        # 如果没有需要修复的问题，直接返回
        if not adjustment_plan.gaps:
            logger.info("[DualTrack] 无需修复的问题，跳过融合精修")
            return stitched_draft
        
        # 获取需要修复的 beat 索引
        beats_to_refine = set(adjustment_plan.beat_adjustments.keys())
        
        if not beats_to_refine:
            # 只有全局问题，尝试进行全局精修
            if adjustment_plan.global_adjustments:
                logger.info("[DualTrack] 检测到全局问题，执行全局精修")
                return await self._execute_global_refinement(
                    stitched_draft=stitched_draft,
                    sketch_result=sketch_result,
                    global_adjustments=adjustment_plan.global_adjustments,
                    chapter=chapter,
                    book=book,
                )
            logger.warning("[DualTrack] 无可执行的精修任务，返回原文")
            return stitched_draft
        
        logger.info(f"[DualTrack] 执行融合精修，需修复 {len(beats_to_refine)} 个 Beat")
        
        # 将统稿文本按 beat 分段
        draft_segments = self._segment_draft_by_beats(stitched_draft, beats)
        
        # 逐个 beat 进行精修
        refined_segments = []
        for i, (beat, segment) in enumerate(zip(beats, draft_segments)):
            beat_index = i + 1  # 1-based
            
            if beat_index in beats_to_refine:
                # 构建修复指导
                issues = adjustment_plan.beat_adjustments.get(beat_index, [])
                revision_guide = self._build_revision_guide(
                    issues=issues,
                    gaps=[g for g in adjustment_plan.gaps if g.beat_index == beat_index],
                    sketch_result=sketch_result,
                    beat_index=beat_index,
                    total_beats=len(beats),
                )
                
                # 获取前文衔接
                previous_tail = refined_segments[-1][-300:] if refined_segments else ""
                
                logger.debug(f"[DualTrack] 精修 Beat {beat_index}，问题数: {len(issues)}")
                
                try:
                    refined_segment = await refine_single_beat(
                        beat=beat,
                        original_chunk=segment,
                        revision_guide=revision_guide,
                        issue_descriptions=issues,
                        chapter=chapter,
                        book=book,
                        api_key=self.api_key,
                        base_url=self.base_url,
                        model=self.reasoning_model,
                        previous_tail=previous_tail,
                        beat_id=beat.get("beat_id"),
                        prompt_logger=self.prompt_logger,
                    )
                    refined_segments.append(refined_segment)
                except Exception as e:
                    logger.error(f"[DualTrack] Beat {beat_index} 精修失败: {e}，使用原文")
                    refined_segments.append(segment)
            else:
                # 无需修复，保留原文
                refined_segments.append(segment)
        
        # 合并精修后的片段
        final_text = "\n\n".join(refined_segments)
        
        refine_time = time.perf_counter() - refine_start
        logger.info(f"[DualTrack] 融合精修完成，耗时: {refine_time:.2f}s，修复 {len(beats_to_refine)} 个 Beat")
        
        return final_text
    
    def _segment_draft_by_beats(self, draft_text: str, beats: List[dict]) -> List[str]:
        """
        将统稿文本按 beat 数量分段
        
        使用启发式方法：按段落分割后，根据 beat 的目标字数比例分配段落。
        """
        if not beats:
            return [draft_text]
        
        # 按双换行分割段落
        paragraphs = [p.strip() for p in draft_text.split("\n\n") if p.strip()]
        
        if not paragraphs:
            # 如果没有段落分隔，尝试按单换行分割
            paragraphs = [p.strip() for p in draft_text.split("\n") if p.strip()]
        
        if not paragraphs:
            return [draft_text]
        
        # 计算每个 beat 的目标字数比例
        total_target = sum(beat.get("word_count_target", 1) or beat.get("target_words", 1) or 1 for beat in beats)
        beat_ratios = []
        for beat in beats:
            target = beat.get("word_count_target", 1) or beat.get("target_words", 1) or 1
            beat_ratios.append(target / total_target)
        
        # 按比例分配段落
        total_chars = sum(len(p) for p in paragraphs)
        segments = []
        para_idx = 0
        
        for beat_idx, ratio in enumerate(beat_ratios):
            target_chars = int(total_chars * ratio)
            segment_paragraphs = []
            current_chars = 0
            
            while para_idx < len(paragraphs) and current_chars < target_chars:
                segment_paragraphs.append(paragraphs[para_idx])
                current_chars += len(paragraphs[para_idx])
                para_idx += 1
            
            # 确保最后一个 beat 获得剩余所有段落
            if beat_idx == len(beat_ratios) - 1:
                segment_paragraphs.extend(paragraphs[para_idx:])
            
            segments.append("\n\n".join(segment_paragraphs) if segment_paragraphs else "")
        
        return segments
    
    def _build_revision_guide(
        self,
        issues: List[str],
        gaps: List[Any],
        sketch_result: SketchResult,
        beat_index: int,
        total_beats: int,
    ) -> str:
        """
        构建修复指导文本
        
        包含：问题描述、Sketch 参考片段、特殊处理建议
        """
        guide_parts = []
        
        # 1. 问题描述
        if issues:
            guide_parts.append("【需要修复的问题】")
            for issue in issues:
                guide_parts.append(f"- {issue}")
        
        # 2. 根据问题类型添加特殊处理建议
        for gap in gaps:
            if gap.source == GapSource.SEGMENT_BOUNDARY:
                guide_parts.append("\n【特殊处理】这是节拍衔接问题，请参考 Sketch 中自然流畅的过渡方式，软化生硬的场景切换。")
            elif gap.source == GapSource.BEAT_DESIGN:
                guide_parts.append(f"\n【特殊处理】这是节拍设计问题，请确保 entry_state 和 exit_state 正确衔接。")
        
        # 3. 提取 Sketch 参考
        sketch_reference = self._extract_sketch_reference(
            sketch_text=sketch_result.sketch_text,
            beat_index=beat_index,
            total_beats=total_beats,
        )
        if sketch_reference:
            guide_parts.append(f"\n【Sketch 连贯性参考】\n以下是 Sketch 中对应位置的文本，参考其自然过渡和情绪流动：\n---\n{sketch_reference}\n---")
        
        return "\n".join(guide_parts)
    
    def _extract_sketch_reference(
        self,
        sketch_text: str,
        beat_index: int,
        total_beats: int,
    ) -> str:
        """
        从 Sketch 中提取对应 beat 位置的参考文本
        
        按位置比例截取 Sketch 的相应片段（±10% 范围）
        """
        if not sketch_text or total_beats == 0:
            return ""
        
        sketch_length = len(sketch_text)
        
        # 计算 beat 在全文中的位置范围
        start_ratio = max(0, (beat_index - 1) / total_beats - 0.05)
        end_ratio = min(1, beat_index / total_beats + 0.05)
        
        start_pos = int(sketch_length * start_ratio)
        end_pos = int(sketch_length * end_ratio)
        
        # 调整到段落边界
        while start_pos > 0 and sketch_text[start_pos] not in "\n。！？":
            start_pos -= 1
        while end_pos < sketch_length - 1 and sketch_text[end_pos] not in "\n。！？":
            end_pos += 1
        
        reference = sketch_text[start_pos:end_pos + 1].strip()
        
        # 限制长度
        if len(reference) > 500:
            reference = reference[:500] + "..."
        
        return reference
    
    async def _execute_global_refinement(
        self,
        stitched_draft: str,
        sketch_result: SketchResult,
        global_adjustments: List[str],
        chapter: Any,
        book: Any,
    ) -> str:
        """
        执行全局精修（针对无法定位到具体 beat 的问题）
        
        使用全局 Refine 模式，将整个文本和修改建议发送给 LLM。
        注意：必须携带字数下限约束，防止 LLM 将全文压缩成摘要。
        """
        original_word_count = len(stitched_draft)
        min_word_count = int(original_word_count * 0.9)  # 最多允许缩减 10%
        
        # 字数约束放在最前面，优先级最高
        revision_plan = (
            f"【字数约束 - 最高优先级】\n"
            f"原文字数约 {original_word_count} 字，精修后**不得低于 {min_word_count} 字**。\n"
            f"严禁通过删段、合并段落或省略细节来缩减字数。如需改动，只能用等量或更多文字替换，不能净减少内容。\n\n"
            f"【全局修复建议】\n" + "\n".join(f"- {adj}" for adj in global_adjustments)
        )
        
        if sketch_result and sketch_result.sketch_text:
            # 添加 Sketch 作为参考，但明确其角色是"参考"而非"目标"
            sketch_preview = sketch_result.sketch_text[:800]
            revision_plan += (
                f"\n\n【Sketch 连贯性参考（仅供借鉴，不是要求缩短到 Sketch 长度）】\n"
                f"{sketch_preview}..."
            )
        
        # 记录 prompt（在调用前构建 prompt 用于日志）
        if self.prompt_logger:
            self.prompt_logger.log_prompts(
                system_prompt="[global_refinement] 调用 refine_draft",
                user_prompt=f"revision_plan_preview={revision_plan[:300]}...",
                model=self.reasoning_model,
                temperature=0.7,
                max_tokens=10000,
                prompt_label="GLOBAL_REFINEMENT",
            )
        
        try:
            refined_text = await refine_draft(
                chapter=chapter,
                book=book,
                entities=[],
                relationships=[],
                current_draft=stitched_draft,
                revision_plan=revision_plan,
                word_count=original_word_count,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.reasoning_model,
            )
            return refined_text
        except Exception as e:
            logger.error(f"[DualTrack] 全局精修失败: {e}，返回原文")
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
    
    注意：enable_dual_track 参数已废弃，后续全部使用双轨模式。
    保留该参数仅为向后兼容，实际上始终执行双轨流程。
    
    Returns:
        Tuple[str, Dict]: (最终正文, 调试信息)
    """
    if not enable_dual_track:
        # 已废弃：即使传入 False，也执行双轨流程
        # 记录警告日志提示调用方更新代码
        logger.warning(
            "[DualTrack] enable_dual_track=False 已废弃，"
            "后续版本将移除此参数。当前仍执行双轨流程。"
        )
    
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
