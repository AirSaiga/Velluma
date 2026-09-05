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
提示词构建模块（统一出口）。

职责：聚合所有 Agent 提示词构建函数，提供统一的导入入口。

设计模式：Facade Pattern，隐藏底层实现细节。

模块组织：
- review_prompts.py: 精修（Refine）提示词（唯一在役消费：refining.py）
- format_prompts.py: 文本格式整理提示词
- （2026-09-01 归档：bsadf/chapter_card/inspiration_prompts 零运行路径 → _deprecated）
- （2026-09-05 归档：chapter_prompts/draft_prompts 全家/review_prompts 死函数——
  V3 生成链 + global_sys_prompt 死线 → _deprecated）

使用场景：
- agentic_workflow.py: 调用各 Agent 提示词构建函数
- routes/: 直接导入使用

业务规则：
- 所有 prompt 函数遵循一致的返回格式：(system_prompt: str, user_prompt: str)
- 解析函数负责将 LLM 输出转换为结构化数据
"""

# 2026-09-05 归档：chapter_prompts / draft_prompts 全家 / review_prompts 死函数
# （V3 生成链 + global_sys_prompt 死线）→ backend/_deprecated/services/prompts/。
# review_prompts 仅剩在役的 build_refine_agent_prompt（refining.py 消费）。
from backend.services.prompts.review_prompts import build_refine_agent_prompt
from backend.services.prompts.format_prompts import build_formatting_prompt

__all__ = [
    # Review & Refine
    "build_refine_agent_prompt",
    # Others
    "build_formatting_prompt",
]
