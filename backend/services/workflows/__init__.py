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
工作流阶段模块（统一出口）。

职责：聚合 V4.1 双轨工作流的各阶段处理函数，提供统一的导入入口。

CP1.0 死代码清理：删除了对以下死模块的重导出（文件本身也一并删除）：
- types.py（WorkflowState 从不实例化）
- context.py（被 services/context/loader.py 取代）
- reviewing.py（被 adversarial_aligner.py 取代）
- drafting_core/、drafting_prose_modules/、drafting_qc.py（死代码带）

模块组织（CP1.0 后）：
- planning.py: 规划阶段（节拍拆分 + POV 锚点分配）
- drafting.py: 起草阶段（_execute_unified_path 唯一活路径）
- drafting_utils.py: 起草公共工具（quick_qc 等）
- drafting_thinking.py: 思考层（Scene Intent + Subconscious 批量）
- stitching.py: 统稿阶段
- refining.py: 精修阶段
- dual_track.py: 双轨主类
- sketch_generator.py: Track B 速写
- adversarial_aligner.py: 对抗校对
- validators.py: 代码级校验器（CP1.1 fail-fast 复活用）
- utils.py: 工具函数（clean_llm_output 等）
"""

from backend.services.workflows.planning import generate_beats
from backend.services.workflows.drafting import execute_draft_stage, BeatDraftResult
from backend.services.workflows.stitching import stitch_chunks
from backend.services.workflows.refining import refine_draft, refine_single_beat
# 从 dual_track 包导入（工作流类、子模块）
from backend.services.workflows.dual_track import (
    DualTrackWorkflow,
    DualTrackResult,
    DualTrackConfig,
    fusion_refine,
)
# execute_dual_track_generation 定义在 dual_track.py 文件中，不是包中
from backend.services.workflows.dual_track import execute_dual_track_generation
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

__all__ = [
    "generate_beats",
    "execute_draft_stage",
    "BeatDraftResult",
    "stitch_chunks",
    "refine_draft",
    "refine_single_beat",
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
