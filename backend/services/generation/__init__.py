# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
章节生成服务模块 - 统一导出入口。

职责：
- 统一导出章节生成相关服务
- 提供提示词构建、LLM 调用、发布等功能

子模块：
- chapter.py: 章节生成主服务
- publish.py: 章节发布服务
- inspiration.py: 灵感生成
- memory_scorer.py: 记忆评分
- background_manager.py: 后台生成管理

主要功能：
- 章节提示词构建
- 流式生成响应
- 角色状态更新
- 章节摘要生成
- 灵感扩展

依赖项：
- backend.services.llm: LLM 调用接口
- backend.services.prompts: 提示词模板
- backend.models: 数据模型
"""

from .chapter import (
    build_chapter_prompt,
    generate_stream_response,
    build_draft_agent_prompt,
    build_review_agent_prompt,
    build_refine_agent_prompt,
    parse_review_result,
    call_llm,
    update_character_dynamic_state,
    refine_draft,
)
from .publish import (
    generate_chapter_summary,
    generate_summary_embedding,
    update_character_states,
    CharacterUpdateResult,
)
from .inspiration import (
    expand_inspiration,
    expand_outline,
)
from .memory_scorer import (
    compute_memory_score,
    calculate_time_decay_score,
)

__all__ = [
    # Chapter generation
    "build_chapter_prompt",
    "generate_stream_response",
    "build_draft_agent_prompt",
    "build_review_agent_prompt",
    "build_refine_agent_prompt",
    "parse_review_result",
    "call_llm",
    "update_character_dynamic_state",
    "refine_draft",
    # Publish
    "generate_chapter_summary",
    "generate_summary_embedding",
    "update_character_states",
    "CharacterUpdateResult",
    # Inspiration
    "expand_inspiration",
    "expand_outline",
    # Memory scorer
    "compute_memory_score",
    "calculate_time_decay_score",
]
