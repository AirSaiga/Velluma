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
起草提示词模块 - 统一导出入口。

职责：
- 作为起草相关提示词模块的 Facade 层
- 重新导出所有起草相关的提示构建函数
- 提供统一的导入入口

子模块：
- draft_prompts_utils: 文本规范化、边界渲染等工具函数
- draft_prompts_subconscious: 潜意识提示构建
- draft_prompts_prose: 正文起草提示构建
- draft_prompts_legacy: 遗留版本起草提示
- draft_prompts_review: 微审阅提示构建

业务场景：
- 章节起草阶段提示词构建
- Beat 粒度的文本生成

依赖项：
- backend.services.prompts.*: 各子模块实现

使用方式：
    from backend.services.prompts.draft_prompts import build_draft_agent_prompt
"""

from backend.services.prompts.draft_prompts_utils import (
    _normalize_text,
    _normalize_text_list,
    _render_boundary_constraints,
    _render_scene_intent_prompt,
    _render_style_control_prompt,
    _format_entity_spatial_ledger,
)
from backend.services.prompts.draft_prompts_subconscious import build_subconscious_prompt
from backend.services.prompts.draft_prompts_prose import (
    build_prose_draft_prompt,
    build_prose_draft_prompt_v25,
)
from backend.services.prompts.draft_prompts_legacy import (
    build_draft_agent_prompt,
    build_chunk_draft_prompt,
)
from backend.services.prompts.draft_prompts_review import (
    build_micro_review_prompt,
    build_emotional_update_prompt,
    build_dynamic_state_update_prompt,
)

__all__ = [
    "_normalize_text",
    "_normalize_text_list",
    "_render_boundary_constraints",
    "_render_scene_intent_prompt",
    "_render_style_control_prompt",
    "_format_entity_spatial_ledger",
    "build_subconscious_prompt",
    "build_prose_draft_prompt",
    "build_prose_draft_prompt_v25",
    "build_draft_agent_prompt",
    "build_chunk_draft_prompt",
    "build_micro_review_prompt",
    "build_emotional_update_prompt",
    "build_dynamic_state_update_prompt",
]
