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
提示词构建模块（统一出口）。

职责：聚合所有 Agent 提示词构建函数，提供统一的导入入口。

设计模式：Facade Pattern，隐藏底层实现细节。

模块组织：
- chapter_prompts.py: 基础章节生成提示词
- draft_prompts.py: 主笔 Agent 提示词（初稿生成）
- planner_prompts.py: 规划师 Agent 提示词（故事节奏拆分）
- scene_intent_prompts.py: 场景意图分析提示词
- stitch_prompts.py: 统稿 Agent 提示词（片段拼接）
- review_prompts.py: 审阅/精修 Agent 提示词
- format_prompts.py: 文本格式整理提示词
- inspiration_prompts.py: 灵感生成提示词

使用场景：
- agentic_workflow.py: 调用各 Agent 提示词构建函数
- routes/: 直接导入使用

业务规则：
- 所有 prompt 函数遵循一致的返回格式：(system_prompt: str, user_prompt: str)
- 解析函数负责将 LLM 输出转换为结构化数据
"""

from backend.services.prompts.chapter_prompts import build_chapter_prompt
from backend.services.prompts.draft_prompts import (
    build_draft_agent_prompt,
    build_chunk_draft_prompt,
    build_subconscious_prompt,
    build_prose_draft_prompt,
    # V4.0 Cognitive Streaming (NEW)
    build_prose_draft_prompt_v25,
    build_micro_review_prompt,
    build_emotional_update_prompt,
    # V4.0+ Dynamic State Update (NEW)
    build_dynamic_state_update_prompt,
)
from backend.services.prompts.planner_prompts import build_planner_agent_prompt, parse_planner_result, parse_planner_full_result
from backend.services.prompts.scene_intent_prompts import build_scene_intent_prompt, parse_scene_intent_result
from backend.services.prompts.stitch_prompts import build_stitch_prompt
from backend.services.prompts.review_prompts import (
    build_review_agent_prompt,
    build_refine_agent_prompt,
    parse_review_result,
    build_chunk_review_prompt,
    build_chunk_refine_prompt,
)
from backend.services.prompts.format_prompts import build_formatting_prompt
from backend.services.prompts.pov_prompts import build_pov_assignment_prompt, parse_pov_assignment_result, build_anchor_pov_prompt, parse_anchor_pov_result

__all__ = [
    # Chapter & Draft
    "build_chapter_prompt",
    "build_draft_agent_prompt",
    "build_chunk_draft_prompt",
    # Iceberg Model (NEW)
    "build_subconscious_prompt",
    "build_prose_draft_prompt",
    # V4.0 Cognitive Streaming (NEW)
    "build_prose_draft_prompt_v25",
    "build_micro_review_prompt",
    "build_emotional_update_prompt",
    # V4.0+ Dynamic State Update (NEW)
    "build_dynamic_state_update_prompt",
    # Review & Refine
    "build_refine_agent_prompt",
    "build_review_agent_prompt",
    "parse_review_result",
    "build_chunk_review_prompt",
    "build_chunk_refine_prompt",
    # Planning
    "build_planner_agent_prompt",
    "parse_planner_result",
    "parse_planner_full_result",
    # Scene Intent
    "build_scene_intent_prompt",
    "parse_scene_intent_result",
    # Others
    "build_formatting_prompt",
    "build_stitch_prompt",
    "build_pov_assignment_prompt",
    "parse_pov_assignment_result",
    "build_anchor_pov_prompt",
    "parse_anchor_pov_result",
]
