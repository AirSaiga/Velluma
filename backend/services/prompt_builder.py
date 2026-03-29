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
Prompt 构建器重导出模块 - 提供统一的 Prompt 构建接口。

职责：
- 重新导出所有 Prompt 构建函数
- 作为 services 层的统一入口点
- 简化其他模块的导入路径

业务场景：
- workflow 模块调用 Prompt 构建函数
- orchestration 模块使用 Prompt 模板
- 统一管理 Prompt 相关导入

主要功能：
- 章节生成 Prompt 构建
- Agent Prompt 构建（Planner/Draft/Review/Refine）
- Prompt 结果解析

依赖项：
- backend.services.prompts: 实际实现模块

使用方式：
    from backend.services.prompt_builder import build_planner_agent_prompt
"""

from backend.services.prompts import (
    build_chapter_prompt,
    build_chunk_draft_prompt,
    build_draft_agent_prompt,
    build_planner_agent_prompt,
    build_refine_agent_prompt,
    build_review_agent_prompt,
    build_scene_intent_prompt,
    build_stitch_prompt,
    parse_planner_result,
    parse_review_result,
    parse_scene_intent_result,
)

__all__ = [
    "build_chapter_prompt",
    "build_chunk_draft_prompt",
    "build_draft_agent_prompt",
    "build_planner_agent_prompt",
    "build_refine_agent_prompt",
    "build_review_agent_prompt",
    "build_scene_intent_prompt",
    "build_stitch_prompt",
    "parse_planner_result",
    "parse_review_result",
    "parse_scene_intent_result",
]
