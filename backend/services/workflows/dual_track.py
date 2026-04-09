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
双轨生成工作流 (Dual Track Workflow) - V3.5 双轨对抗架构。

职责：
- 整合 Track A (节拍扩写) 和 Track B (短文生成)
- 实现并行生成 + 对抗校对的架构
- 解决并行生成连贯性差的问题

核心流程：
1. Phase 1: 节拍生成 (复用原有 planning)
2. Phase 2: 双轨并行生成
   - Track A: 节拍扩写 (execute_draft_stage)
   - Track B: 短文生成 (SketchGenerator)
3. Phase 3: 节拍统稿 (stitch_chunks)
4. Phase 4: 对抗校对 (AdversarialAligner)
5. Phase 5: 融合精修 (可选)

子模块：
- dual_track_helpers: 文本分段、修复指导构建、Sketch 参考提取

依赖项：
- backend.services.workflows.drafting: 节拍扩写
- backend.services.workflows.sketch_generator: 短文生成
- backend.services.workflows.adversarial_aligner: 对抗校对

使用方式：
    result = await execute_dual_track_generation(chapter, book, beats, ...)
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
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
from backend.services.workflows.dual_track_helpers import (
    segment_draft_by_beats,
    build_revision_guide,
    extract_sketch_reference,
)
from backend.services.utils.prompt_logger import PromptLogger
from backend.services.utils.logging import get_runtime_logger

from backend.schemas import DraftingFeatureFlags, WorkflowTier

logger = get_runtime_logger(__name__)


@dataclass
class DualTrackConfig:
    enable_sketch_track: bool = True
    enable_adversarial_alignment: bool = True
    use_sketch_for_refinement: bool = True
    alignment_threshold: float = 70.0
    sketch_config: Optional[SketchGeneratorConfig] = None
    aligner_config: Optional[AdversarialAlignerConfig] = None


@dataclass
class DualTrackResult:
    final_text: str
    beat_drafts: List[BeatDraftResult]
    stitched_draft: str
    sketch_result: Optional[SketchResult]
    adjustment_plan: Optional[AdjustmentPlan]
    stats: Dict[str, Any]
    debug_info: Dict[str, Any]


class DualTrackWorkflow:

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
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> DualTrackResult:
        import time
        total_start = time.perf_counter()

        logger.info(f"[DualTrack] 阶段=START 状态=RUNNING beats={len(beats)} word_count={word_count}")
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
        )
        await self._emit_progress(progress_callback, "TRACK_GENERATION_DONE", f"双轨生成完成，耗时 {track_time:.1f}s")
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
        final_text, adjustment_plan = await self._run_alignment_and_refinement(
            chapter=chapter,
            book=book,
            beats=beats,
            stitched_draft=stitched_draft,
            sketch_result=sketch_result,
        )
        total_time = time.perf_counter() - total_start

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

        logger.info(f"[DualTrack] 阶段=DONE 状态=SUCCESS total={total_time:.2f}s words={len(final_text)}")

        return DualTrackResult(
            final_text=final_text,
            beat_drafts=beat_drafts,
            stitched_draft=stitched_draft,
            sketch_result=sketch_result,
            adjustment_plan=adjustment_plan,
            stats=stats,
            debug_info=debug_info,
        )

    async def _emit_progress(
        self,
        progress_callback: Optional[Callable[..., Any]],
        event: str,
        message: str,
        **kwargs: Any,
    ) -> None:
        if progress_callback:
            await progress_callback(event=event, message=message, **kwargs)

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
        workflow_tier: Optional[WorkflowTier],
        anchor_pov: Optional[str],
    ) -> Tuple[List[BeatDraftResult], Optional[SketchResult], float]:
        import time
        parallel_start_wall = time.time()
        parallel_start_perf = time.perf_counter()

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
            if isinstance(beat_drafts, Exception):
                logger.error(f"[DualTrack] Track A 失败: {beat_drafts}")
                raise beat_drafts
            if isinstance(sketch_result, Exception):
                logger.warning(f"[DualTrack] Track B 失败: {sketch_result}，将继续使用 Track A 结果")
                sketch_result = None
        else:
            beat_drafts = await track_a_task
            sketch_result = None

        track_time = time.perf_counter() - parallel_start_perf
        logger.info(f"[DualTrack] 阶段=DRAFTING 状态=SUCCESS duration={track_time:.2f}s")
        self._log_drafting_stage(
            beat_drafts=beat_drafts,
            beats=beats,
            word_count=word_count,
            parallel_start_wall=parallel_start_wall,
        )
        return beat_drafts, sketch_result, track_time

    def _log_drafting_stage(
        self,
        beat_drafts: List[BeatDraftResult],
        beats: List[dict],
        word_count: int,
        parallel_start_wall: float,
    ) -> None:
        if not self.prompt_logger:
            return
        self.prompt_logger.start_stage("DRAFTING", iteration=1)
        self.prompt_logger.log_data["stages"][-1]["start_time"] = parallel_start_wall
        self.prompt_logger.log_inputs(
            beat_count=len(beats),
            word_count=word_count,
            note="与SKETCH_GENERATION并行执行，elapsed为Track A真实耗时",
        )
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
                for d in beat_drafts
            ],
        )
        self.prompt_logger.end_stage(success=True)

    async def _run_stitching_stage(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        beat_drafts: List[BeatDraftResult],
        sketch_result: Optional[SketchResult],
        word_count: int,
        anchor_pov: Optional[str],
        progress_callback: Optional[Callable[..., Any]],
    ) -> Tuple[str, float]:
        import time
        await self._emit_progress(progress_callback, "STITCHING", "正在统稿拼接各节拍内容...")
        stitch_start = time.perf_counter()
        chunks = [draft.draft_chunk for draft in beat_drafts]
        persistent_state_anchors = self._build_persistent_state_anchors(beats)
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
        logger.info(f"[DualTrack] 阶段=STITCHING 状态=SUCCESS duration={stitch_time:.2f}s words={len(stitched_draft)}")
        if self.prompt_logger:
            self.prompt_logger.log_outputs(
                stitched_word_count=len(stitched_draft),
                stitched_text=stitched_draft,
            )
            self.prompt_logger.end_stage(success=bool(stitched_draft))
        return stitched_draft, stitch_time

    def _build_persistent_state_anchors(self, beats: List[dict]) -> List[Dict[str, str]]:
        persistent_state_anchors: List[Dict[str, str]] = []
        for i, beat in enumerate(beats):
            exit_state = beat.get("exit_state", "")
            if exit_state:
                persistent_state_anchors.append(
                    {
                        "anchor_type": f"beat_{i + 1}_exit",
                        "description": f"Beat {i + 1} 退出状态: {exit_state}",
                    }
                )
        return persistent_state_anchors

    async def _run_alignment_and_refinement(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        stitched_draft: str,
        sketch_result: Optional[SketchResult],
    ) -> Tuple[str, Optional[AdjustmentPlan]]:
        import time
        adjustment_plan = None
        final_text = stitched_draft
        if not (self.config.enable_adversarial_alignment and sketch_result and sketch_result.sketch_text):
            logger.info("[DualTrack] 阶段=REVIEWING 状态=SKIPPED reason=disabled_or_no_sketch")
            return final_text, adjustment_plan
        align_start = time.perf_counter()
        if self.prompt_logger:
            self.prompt_logger.start_stage("ADVERSARIAL_ALIGNMENT", iteration=1)
            self.prompt_logger.log_inputs(
                draft_word_count=len(stitched_draft),
                sketch_word_count=sketch_result.word_count,
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
            logger.info(f"[DualTrack] 阶段=REVIEWING 状态=SUCCESS duration={align_time:.2f}s score={adjustment_plan.alignment_score:.1f}")
            if self.prompt_logger:
                for ap in (adjustment_plan.analysis_prompts or []):
                    self.prompt_logger.log_prompts(
                        system_prompt=ap.get("system_prompt", ""),
                        user_prompt=ap.get("user_prompt", ""),
                        model=self.reasoning_model,
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
            if adjustment_plan.needs_adjustment and self.config.use_sketch_for_refinement:
                final_text = await self._run_fusion_refinement(
                    chapter=chapter,
                    book=book,
                    beats=beats,
                    stitched_draft=stitched_draft,
                    sketch_result=sketch_result,
                    adjustment_plan=adjustment_plan,
                )
            else:
                logger.info("[DualTrack] 阶段=REFINING 状态=SKIPPED reason=not_needed_or_disabled")
        except Exception as e:
            logger.error(f"[DualTrack] 阶段=REVIEWING 状态=FAILED error={e}")
            if self.prompt_logger:
                self.prompt_logger.log_outputs(error=str(e))
                self.prompt_logger.end_stage(success=False)
            final_text = stitched_draft
        return final_text, adjustment_plan

    async def _run_fusion_refinement(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        stitched_draft: str,
        sketch_result: SketchResult,
        adjustment_plan: AdjustmentPlan,
    ) -> str:
        logger.info(
            f"[DualTrack] 阶段=REFINING 状态=RUNNING reason=low_score "
            f"score={adjustment_plan.alignment_score:.1f} threshold={self.config.alignment_threshold}"
        )
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
            return final_text
        except Exception as refine_e:
            logger.error(f"[DualTrack] 阶段=REFINING 状态=FAILED error={refine_e}")
            if self.prompt_logger:
                self.prompt_logger.log_outputs(error=str(refine_e))
                self.prompt_logger.end_stage(success=False)
            return stitched_draft

    def _build_stats(
        self,
        total_time: float,
        track_time: float,
        stitch_time: float,
        final_text: str,
        beats: List[dict],
        adjustment_plan: Optional[AdjustmentPlan],
    ) -> Dict[str, Any]:
        return {
            "total_time": total_time,
            "track_time": track_time,
            "stitch_time": stitch_time,
            "final_word_count": len(final_text),
            "beat_count": len(beats),
            "alignment_score": adjustment_plan.alignment_score if adjustment_plan else None,
        }

    def _build_debug_info(
        self,
        beat_drafts: List[BeatDraftResult],
        sketch_result: Optional[SketchResult],
        adjustment_plan: Optional[AdjustmentPlan],
    ) -> Dict[str, Any]:
        return {
            "track_a_prompts": [p for draft in beat_drafts for p in (draft.prompts or [])],
            "track_b_prompts": getattr(sketch_result, "prompts", []) if sketch_result else [],
            "adjustment_analysis": getattr(adjustment_plan, "analysis_prompts", []) if adjustment_plan else [],
        }

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
        return await execute_draft_stage(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beats=beats,
            open_hooks=[],
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
        config = self.config.sketch_config or SketchGeneratorConfig()
        target_words = int(word_count * config.sketch_ratio)
        target_words = max(config.min_words, min(target_words, config.max_words))

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

        if self.prompt_logger and result:
            self.prompt_logger.log_outputs(
                word_count=result.word_count,
                turn_markers_count=len(result.turn_markers),
                generation_time=result.generation_time,
                sketch_text=result.sketch_text,
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
        aligner = AdversarialAligner(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.reasoning_model,
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
        import time
        refine_start = time.perf_counter()

        if not adjustment_plan.gaps:
            logger.info("[DualTrack] 阶段=REFINING 状态=SKIPPED reason=no_gaps")
            return stitched_draft

        beats_to_refine = set(adjustment_plan.beat_adjustments.keys())

        if not beats_to_refine:
            if adjustment_plan.global_adjustments:
                logger.info("[DualTrack] 阶段=REFINING 状态=RUNNING mode=global")
                return await self._execute_global_refinement(
                    stitched_draft=stitched_draft,
                    sketch_result=sketch_result,
                    global_adjustments=adjustment_plan.global_adjustments,
                    chapter=chapter,
                    book=book,
                )
            logger.warning("[DualTrack] 阶段=REFINING 状态=SKIPPED reason=no_actionable_items")
            return stitched_draft

        logger.info(f"[DualTrack] 阶段=REFINING 状态=RUNNING mode=beat_count count={len(beats_to_refine)}")

        draft_segments = segment_draft_by_beats(stitched_draft, beats)

        refined_segments = []
        for i, (beat, segment) in enumerate(zip(beats, draft_segments)):
            beat_index = i + 1

            if beat_index in beats_to_refine:
                issues = adjustment_plan.beat_adjustments.get(beat_index, [])
                revision_guide = build_revision_guide(
                    issues=issues,
                    gaps=[g for g in adjustment_plan.gaps if g.beat_index == beat_index],
                    sketch_result=sketch_result,
                    beat_index=beat_index,
                    total_beats=len(beats),
                )

                previous_tail = refined_segments[-1][-300:] if refined_segments else ""

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
                    logger.error(f"[DualTrack] 阶段=REFINING 状态=FAILED beat={beat_index} error={e}")
                    refined_segments.append(segment)
            else:
                refined_segments.append(segment)

        final_text = "\n\n".join(refined_segments)

        refine_time = time.perf_counter() - refine_start
        logger.info(f"[DualTrack] 阶段=REFINING 状态=SUCCESS duration={refine_time:.2f}s fixed={len(beats_to_refine)}")

        return final_text

    async def _execute_global_refinement(
        self,
        stitched_draft: str,
        sketch_result: SketchResult,
        global_adjustments: List[str],
        chapter: Any,
        book: Any,
    ) -> str:
        original_word_count = len(stitched_draft)
        min_word_count = int(original_word_count * 0.9)

        revision_plan = (
            f"【字数约束 - 最高优先级】\n"
            f"原文字数约 {original_word_count} 字，精修后**不得低于 {min_word_count} 字**。\n"
            f"严禁通过删段、合并段落或省略细节来缩减字数。如需改动，只能用等量或更多文字替换，不能净减少内容。\n\n"
            f"【全局修复建议】\n" + "\n".join(f"- {adj}" for adj in global_adjustments)
        )

        if sketch_result and sketch_result.sketch_text:
            sketch_preview = sketch_result.sketch_text[:800]
            revision_plan += (
                f"\n\n【Sketch 连贯性参考（仅供借鉴，不是要求缩短到 Sketch  长度）】\n"
                f"{sketch_preview}..."
            )

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
    if not enable_dual_track:
        logger.warning(
            "[DualTrack] enable_dual_track=False 已废弃，"
            "后续版本将移除此参数。当前仍执行双轨流程。"
        )

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
        "iterations": 1,
        "revision_count": 1 if result.adjustment_plan and result.adjustment_plan.needs_adjustment else 0,
    }

    return result.final_text, debug_info
