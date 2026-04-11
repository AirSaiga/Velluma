"""
双轨工作流模块 - 实现双轨对抗架构。

职责：
- 整合 Track A (节拍扩写) 和 Track B (短文生成)
- 实现并行生成 + 对抗校对的架构
- 解决并行生成连贯性差的问题

模块结构：
- stitching.py: 统稿器
- fusion_refinement.py: 融合精修
- alignment/: 对抗校对
- tracks/: 双轨实现
- config/: 配置类

重要说明：
- DualTrackWorkflow 类定义在 backend/services/workflows/dual_track.py
- 由于包名与文件名的命名冲突，使用 __getattr__ + importlib 直接从文件导入
- 这确保使用完整实现而非占位代码

使用方式：
    from backend.services.workflows.dual_track import execute_dual_track_generation
    from backend.services.workflows.dual_track import DualTrackWorkflow, stitch_beats
"""

import importlib.util
import os

# 直接导入子模块中的类和函数（这些是独立模块，不依赖 dual_track.py）
from backend.services.workflows.dual_track.config.dual_track_config import (
    DualTrackConfig,
    SketchConfig,
    AlignerConfig,
)
from backend.services.workflows.dual_track.stitching import (
    stitch_beats,
    build_persistent_state_anchors,
)
from backend.services.workflows.dual_track.fusion_refinement import fusion_refine
from backend.services.workflows.sketch_generator import (
    SketchGenerator,
    SketchResult,
    SketchGeneratorConfig,
)
from backend.services.workflows.adversarial_aligner import (
    AdversarialAligner,
    AdversarialAlignerConfig,
    AdjustmentPlan,
    AlignmentGap,
    GapType,
    GapSource,
    GapSeverity,
)
# stitch_chunks 在外部模块
from backend.services.workflows.stitching import stitch_chunks

# 延迟导入主模块中的类和函数
_dummy_module = None


def __getattr__(name: str):
    """从 dual_track.py 文件延迟导入类和函数，避免与包名冲突。"""
    global _dummy_module

    # 加载主文件模块（只加载一次）
    if _dummy_module is None:
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "workflows",
            "dual_track.py"
        )
        spec = importlib.util.spec_from_file_location("_dual_track_module", module_path)
        if spec and spec.loader:
            _dummy_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_dummy_module)

    # 处理 DualTrackWorkflow 和 DualTrackResult
    if name in ("DualTrackWorkflow", "DualTrackResult"):
        if hasattr(_dummy_module, name):
            return getattr(_dummy_module, name)

    # 处理 execute_dual_track_generation
    if name == "execute_dual_track_generation":
        if hasattr(_dummy_module, name):
            return getattr(_dummy_module, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# __all__ 必须在模块级别定义
__all__ = [
    # 主工作流（延迟导入）
    "DualTrackWorkflow",
    "DualTrackResult",
    # 配置
    "DualTrackConfig",
    "SketchConfig",
    "AlignerConfig",
    # 统稿
    "stitch_chunks",
    "stitch_beats",
    "build_persistent_state_anchors",
    # 融合精修
    "fusion_refine",
    # Sketch 生成
    "SketchGenerator",
    "SketchResult",
    "SketchGeneratorConfig",
    # 对抗校对
    "AdversarialAligner",
    "AdversarialAlignerConfig",
    "AdjustmentPlan",
    "AlignmentGap",
    "GapType",
    "GapSource",
    "GapSeverity",
    # 延迟导入的函数
    "execute_dual_track_generation",
]
