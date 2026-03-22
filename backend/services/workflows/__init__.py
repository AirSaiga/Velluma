"""
工作流阶段模块（统一出口）。

职责：聚合 Agentic 工作流的各阶段处理函数，提供统一的导入入口。

设计模式：Facade Pattern，将复杂的工作流拆分为独立的阶段模块。

模块组织：
- context.py: 上下文加载（角色、关系、伏笔、记忆）
- planning.py: 规划阶段（故事节奏拆分）
- drafting.py: 生成阶段（并行生成多个故事片段）
- stitching.py: 统稿阶段（片段拼接成完整章节）
- reviewing.py: 审查阶段（质量检查、逻辑校验）
- refining.py: 精修阶段（基于反馈重写）
- dual_track.py: 双轨生成（V3.5 新增：节拍扩写 + 短文生成 + 对抗校对）
- sketch_generator.py: 短文生成器（Track B）
- adversarial_aligner.py: 对抗校对器
- utils.py: 工具函数

使用场景：
- agentic_workflow.py: 调用各阶段函数组装完整工作流
- routes/: 直接导入使用

业务流程：
1. load_chapter_context: 加载上下文数据
2. generate_beats: 生成故事节拍
3. generate_chunks_parallel: 并行生成片段（单轨模式）
4. execute_dual_track_generation: 双轨生成（推荐）
5. stitch_chunks: 统稿拼接
6. review_draft: 质量审查
7. refine_draft: 精修重写（如审查未通过）

业务规则：
- 所有阶段函数都是 async 函数，支持流式输出
- 返回格式统一为异步生成器或结构化数据
"""

from backend.services.workflows.context import load_chapter_context
from backend.services.workflows.planning import generate_beats
from backend.services.workflows.drafting import generate_chunks_parallel
from backend.services.workflows.stitching import stitch_chunks
from backend.services.workflows.reviewing import review_draft
from backend.services.workflows.refining import refine_draft

# V3.5 双轨架构新增（带错误处理，避免影响原有功能）
try:
    from backend.services.workflows.dual_track import (
        DualTrackWorkflow,
        DualTrackResult,
        DualTrackConfig,
        execute_dual_track_generation,
    )
    from backend.services.workflows.sketch_generator import (
        SketchGenerator,
        SketchResult,
        SketchGeneratorConfig,
        TurnMarker,
    )
    from backend.services.workflows.adversarial_aligner import (
        AdversarialAligner,
        AdjustmentPlan,
        AdversarialAlignerConfig,
        AlignmentGap,
        GapType,
        GapSource,
        GapSeverity,
    )
    DUAL_TRACK_AVAILABLE = True
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"[Workflows] 双轨架构模块加载失败: {e}")
    DUAL_TRACK_AVAILABLE = False
    # 定义占位符
    DualTrackWorkflow = None
    DualTrackResult = None
    DualTrackConfig = None
    execute_dual_track_generation = None
    SketchGenerator = None
    SketchResult = None
    SketchGeneratorConfig = None
    TurnMarker = None
    AdversarialAligner = None
    AdjustmentPlan = None
    AdversarialAlignerConfig = None
    AlignmentGap = None
    GapType = None
    GapSource = None
    GapSeverity = None

__all__ = [
    # 原有模块
    "load_chapter_context",
    "generate_beats",
    "generate_chunks_parallel",
    "stitch_chunks",
    "review_draft",
    "refine_draft",
    # V3.5 双轨架构（可能为 None 如果加载失败）
    "DUAL_TRACK_AVAILABLE",
    "DualTrackWorkflow",
    "DualTrackResult",
    "DualTrackConfig",
    "execute_dual_track_generation",
    "SketchGenerator",
    "SketchResult",
    "SketchGeneratorConfig",
    "TurnMarker",
    "AdversarialAligner",
    "AdjustmentPlan",
    "AdversarialAlignerConfig",
    "AlignmentGap",
    "GapType",
    "GapSource",
    "GapSeverity",
]
