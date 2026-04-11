"""
双轨模块 - 对齐实现。

职责：
- 提供对抗校对的执行器
- 支持差异检测和修复计划生成

子模块：
- adversarial_aligner.py: 对抗校对器

使用方式：
    from backend.services.workflows.dual_track.alignment import (
        AdversarialAligner,
        AdjustmentPlan,
        AlignmentGap,
        GapType,
        GapSource,
        GapSeverity,
    )

    aligner = AdversarialAligner(api_key, base_url, model, config)
    plan = await aligner.align(draft_text, sketch_result, beats, ...)
"""

from backend.services.workflows.dual_track.alignment.adversarial_aligner import (
    AdversarialAligner,
    AdversarialAlignerConfig,
    AdjustmentPlan,
    AlignmentGap,
    GapType,
    GapSource,
    GapSeverity,
)

__all__ = [
    "AdversarialAligner",
    "AdversarialAlignerConfig",
    "AdjustmentPlan",
    "AlignmentGap",
    "GapType",
    "GapSource",
    "GapSeverity",
]
