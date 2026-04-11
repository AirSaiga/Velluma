"""
融合精修模块 (Fusion Refinement) - 基于调整计划精修章节内容。

职责：
- 根据对抗校对结果精修章节
- 支持按节拍和全局两种精修模式
- 管理精修过程中的参数调整

主要功能：
- 执行节拍级精修
- 执行全局精修
- 构建修复指导

依赖项：
- backend.services.workflows.refining: 原有精修逻辑
- backend.services.workflows.dual_track_helpers: 辅助函数

使用方式：
    from backend.services.workflows.dual_track.fusion_refinement import (
        fusion_refine,
        refine_by_beats,
        refine_globally,
    )
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.refining import refine_single_beat, refine_draft
from backend.services.workflows.dual_track_helpers import (
    segment_draft_by_beats,
    build_revision_guide,
)

if TYPE_CHECKING:
    from backend.services.workflows.adversarial_aligner import AdjustmentPlan
    from backend.services.workflows.sketch_generator import SketchResult

logger = logging.getLogger(__name__)


async def fusion_refine(
    stitched_draft: str,
    sketch_result: "SketchResult",
    adjustment_plan: "AdjustmentPlan",
    beats: List[dict],
    chapter: Any,
    book: Any,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    融合精修主入口。

    根据调整计划选择合适的精修模式。

    Args:
        stitched_draft: 拼接后的草稿
        sketch_result: 速写结果
        adjustment_plan: 调整计划
        beats: 节拍列表
        chapter: 章节对象
        book: 书籍对象
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称

    Returns:
        精修后的文本
    """
    import time
    refine_start = time.perf_counter()

    if not adjustment_plan.gaps:
        logger.info("[FusionRefine] 无差异，跳过精修")
        return stitched_draft

    beats_to_refine = set(adjustment_plan.beat_adjustments.keys())

    if not beats_to_refine:
        if adjustment_plan.global_adjustments:
            logger.info("[FusionRefine] 执行全局精修")
            return await refine_globally(
                stitched_draft=stitched_draft,
                sketch_result=sketch_result,
                global_adjustments=adjustment_plan.global_adjustments,
                chapter=chapter,
                book=book,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
        logger.info("[FusionRefine] 无可执行项，跳过精修")
        return stitched_draft

    logger.info(f"[FusionRefine] 执行节拍级精修，{len(beats_to_refine)} 个节拍")

    result = await refine_by_beats(
        stitched_draft=stitched_draft,
        sketch_result=sketch_result,
        adjustment_plan=adjustment_plan,
        beats=beats,
        chapter=chapter,
        book=book,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )

    refine_time = time.perf_counter() - refine_start
    logger.info(f"[FusionRefine] 精修完成，耗时={refine_time:.2f}s")

    return result


async def refine_by_beats(
    stitched_draft: str,
    sketch_result: "SketchResult",
    adjustment_plan: "AdjustmentPlan",
    beats: List[dict],
    chapter: Any,
    book: Any,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    按节拍精修。

    对指定节拍进行精修，保留其他节拍不变。

    Args:
        stitched_draft: 拼接后的草稿
        sketch_result: 速写结果
        adjustment_plan: 调整计划
        beats: 节拍列表
        chapter: 章节对象
        book: 书籍对象
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称

    Returns:
        精修后的文本
    """
    beats_to_refine = set(adjustment_plan.beat_adjustments.keys())
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
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    previous_tail=previous_tail,
                    beat_id=beat.get("beat_id"),
                )
                refined_segments.append(refined_segment)
            except Exception as e:
                logger.error(f"[FusionRefine] 节拍 {beat_index} 精修失败: {e}")
                refined_segments.append(segment)
        else:
            refined_segments.append(segment)

    return "\n\n".join(refined_segments)


async def refine_globally(
    stitched_draft: str,
    sketch_result: "SketchResult",
    global_adjustments: List[str],
    chapter: Any,
    book: Any,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    全局精修。

    对整个章节进行精修，适用于全局性问题。

    Args:
        stitched_draft: 拼接后的草稿
        sketch_result: 速写结果
        global_adjustments: 全局调整建议
        chapter: 章节对象
        book: 书籍对象
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称

    Returns:
        精修后的文本
    """
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
            f"\n\n【Sketch 连贯性参考（仅供借鉴）】\n"
            f"{sketch_preview}..."
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
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        return refined_text
    except Exception as e:
        logger.error(f"[FusionRefine] 全局精修失败: {e}，返回原文")
        return stitched_draft


class FusionRefinementConfig:
    """
    融合精修配置。

    字段说明：
    - min_word_count_ratio: 精修后最小字数比例
    - max_refine_beats: 最大精修节拍数
    - use_sketch_reference: 是否使用 Sketch 作为参考
    """
    min_word_count_ratio: float = 0.9
    max_refine_beats: int = 10
    use_sketch_reference: bool = True
