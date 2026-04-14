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

职责：聚合 Agentic 工作流的各阶段处理函数，提供统一的导入入口。

设计模式：Facade Pattern，将复杂的工作流拆分为独立的阶段模块。

模块组织：
- types.py: 工作流类型定义（WorkflowStage, WorkflowState, WorkflowResult）
- context.py: 上下文加载（角色、关系、伏笔、记忆）
- planning.py: 规划阶段（故事节奏拆分）
- drafting.py: 生成阶段（并行生成多个故事片段）
- stitching.py: 统稿阶段（片段拼接成完整章节）
- reviewing.py: 审查阶段（质量检查、逻辑校验）
- refining.py: 精修阶段（基于反馈重写）
- dual_track.py: 双轨生成（V4.0：节拍扩写 + 短文生成 + 对抗校对）
- sketch_generator.py: 短文生成器（Track B）
- adversarial_aligner.py: 对抗校对器
- utils.py: 工具函数

业务流程：
1. load_chapter_context_v3: 加载上下文数据 (V4.0)
2. generate_beats: 生成故事节拍
3. generate_chunks_parallel: 并行生成片段（单轨模式）
4. execute_dual_track_generation: 双轨生成（推荐）
5. stitch_chunks: 统稿拼接
6. review_draft: 质量审查
7. refine_draft: 精修重写（如审查未通过）
"""

from backend.services.workflows.types import (
    WorkflowStage,
    WorkflowState,
    WorkflowResult,
)
from backend.services.workflows.context import (
    load_chapter_context_v3,
    get_context_for_stage,
    get_planning_context,
    get_drafting_context,
    get_reviewing_context,
    get_refining_context,
)
from backend.services.workflows.planning import generate_beats
from backend.services.workflows.drafting_core import (
    ProseGenerationService,
    GenerationStrategy,
    ContextManager,
    QualityChecker,
    execute_draft_stage,
    BeatDraftResult,
)
from backend.services.workflows.drafting_prose_modules import (
    micro_review_assertion,
    quick_qc,
)
from backend.services.workflows.stitching import stitch_chunks
from backend.services.workflows.reviewing import review_draft
from backend.services.workflows.refining import refine_draft
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
    "WorkflowStage",
    "WorkflowState",
    "WorkflowResult",
    "load_chapter_context_v3",
    "get_context_for_stage",
    "get_planning_context",
    "get_drafting_context",
    "get_reviewing_context",
    "get_refining_context",
    "generate_beats",
    "execute_draft_stage",
    "BeatDraftResult",
    "micro_review_assertion",
    "quick_qc",
    "stitch_chunks",
    "review_draft",
    "refine_draft",
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
