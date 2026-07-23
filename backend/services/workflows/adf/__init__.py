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
ADF（Anchor-Driven Flow）工作流包（V3.2 新建）。

包结构（设计文档 §6.1）：
- types.py:                dataclass（ChapterClimax / StoryContext / SegmentResult / GenerationResult 等）
- spine_track_builder.py:  Phase 1 脉络轨构建（纯算法）
- anchor_designer.py:      Phase 2 远端锚设计（1 次 reasoning）
- tier_decider.py:         Phase 3 定档（0 LLM，复用 V3.1 tier_classifier）
- forward_flow_writer.py:  Phase 4 正向流写作（N 次 creative）★ 核心
- anchor_auditor.py:       Phase 5 锚点审计（1 次 reasoning）
- refiner.py:              Phase 6 条件补埋（0-K 次 creative）
- adf_workflow.py:         主类 ADFWorkflow（编排上述 Phase）

与 detonation/ 包（V3.0/V3.1）的关系：
- 完全独立的包，零代码交叉
- 共享层（call_llm / RunRecorder / tier_classifier / 文风体系）通过参数或 import 复用
- 入口端点 /generate-adf 调用本包；旧 /generate（V3.1）继续走 UnifiedWorkflow

使用示例：
    from backend.services.workflows.adf import ADFWorkflow

    workflow = ADFWorkflow(
        chapter=chapter, book=book, chapter_card=cc, entities=entities,
        style_card=sc, recorder=recorder, request=req,
    )
    result = await workflow.execute(progress_callback=cb)
"""

from backend.services.workflows.adf.types import (
    # 远端锚
    ClimaxSpec,
    Precondition,
    EmotionCurveSample,
    EmotionCurve,
    ChapterClimax,
    # 脉络轨
    EntryState,
    ExitExpectation,
    ChapterPosition,
    StoryContext,
    # 写作产出
    SegmentResult,
    # 审校与总结果
    StructureCheck,
    GenerationResult,
    # 转换工具
    climax_to_dict,
    story_context_to_dict,
    audit_to_dict,
)
from backend.services.workflows.adf.story_context_builder import (
    build_story_context,
    format_entry_state_for_prompt,
    format_exit_expectation_for_prompt,
    format_chapter_position_for_prompt,
)
from backend.services.workflows.adf.climax_designer import design_chapter_climax
from backend.services.workflows.adf.tier_decider import (
    decide_tier,
    TIER_TARGET_WORD_COUNT,
    TIER_MAX_SEGMENTS,
)
from backend.services.workflows.adf.segment_writer import (
    write_chapter_segments,
    scan_unlanded_preconditions,
    build_soft_hints,
    update_precondition_landed_state,
)
from backend.services.workflows.adf.structure_checker import run_structure_check
from backend.services.workflows.adf.refiner import refine_missing_preconditions
from backend.services.workflows.adf.adf_workflow import ADFWorkflow
from backend.services.workflows.adf.storyboard import (
    plan_storyboard,
    get_shot_constraint,
    get_transition_hint,
    SHOT_LABELS,
    TRANS_LABELS,
)

__all__ = [
    # 类型
    "ClimaxSpec",
    "Precondition",
    "EmotionCurveSample",
    "EmotionCurve",
    "ChapterClimax",
    "EntryState",
    "ExitExpectation",
    "ChapterPosition",
    "StoryContext",
    "SegmentResult",
    "StructureCheck",
    "GenerationResult",
    # 转换工具
    "climax_to_dict",
    "story_context_to_dict",
    "audit_to_dict",
    # Phase 1
    "build_story_context",
    "format_entry_state_for_prompt",
    "format_exit_expectation_for_prompt",
    "format_chapter_position_for_prompt",
    # Phase 2
    "design_chapter_climax",
    # Phase 3
    "decide_tier",
    "TIER_TARGET_WORD_COUNT",
    "TIER_MAX_SEGMENTS",
    # Phase 4
    "write_chapter_segments",
    "scan_unlanded_preconditions",
    "build_soft_hints",
    "update_precondition_landed_state",
    # Phase 5
    "run_structure_check",
    # Phase 6
    "refine_missing_preconditions",
    # 主类
    "ADFWorkflow",
    # V4.3 Storyboard（镜头景别）
    "plan_storyboard",
    "get_shot_constraint",
    "get_transition_hint",
    "SHOT_LABELS",
    "TRANS_LABELS",
]
