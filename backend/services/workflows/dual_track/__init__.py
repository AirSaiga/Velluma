"""
双轨工作流模块 - 实现双轨对抗架构。

职责：
- 整合 Track A (节拍扩写) 和 Track B (短文生成)
- 实现并行生成 + 对抗校对的架构
- 解决并行生成连贯性差的问题

模块结构：
- dual_track_workflow.py: 主工作流类
- stitching.py: 统稿器
- fusion_refinement.py: 融合精修
- tracks/: 双轨实现
- config/: 配置类

重要说明：
- execute_dual_track_generation 函数定义在 backend/services/workflows/dual_track.py
- 由于包名与文件名的命名冲突，使用 __getattr__ + importlib 直接加载文件

使用方式：
    from backend.services.workflows.dual_track import execute_dual_track_generation
    from backend.services.workflows.dual_track import DualTrackWorkflow, stitch_beats
"""

import importlib.util
import os

from backend.services.workflows.dual_track.dual_track_workflow import (
    DualTrackWorkflow,
    DualTrackResult,
)
from backend.services.workflows.dual_track.config.dual_track_config import (
    DualTrackConfig,
    SketchConfig,
    AlignerConfig,
)
from backend.services.workflows.stitching import stitch_chunks
from backend.services.workflows.dual_track.stitching import (
    stitch_beats,
    build_persistent_state_anchors,
)
from backend.services.workflows.dual_track.fusion_refinement import fusion_refine
from backend.services.workflows.sketch_generator import SketchGenerator, SketchResult, SketchGeneratorConfig
from backend.services.workflows.adversarial_aligner import (
    AdversarialAligner,
    AdversarialAlignerConfig,
    AdjustmentPlan,
    AlignmentGap,
    GapType,
    GapSource,
    GapSeverity,
)

__all__ = [
    # 主工作流
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


def __getattr__(name: str):
    """延迟导入 execute_dual_track_generation 以避免循环导入。"""
    if name == "execute_dual_track_generation":
        # 直接加载 backend/services/workflows/dual_track.py 文件
        # 避免与 dual_track/ 包名冲突
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "workflows",
            "dual_track.py"
        )
        spec = importlib.util.spec_from_file_location("dual_track_module", module_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.execute_dual_track_generation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
