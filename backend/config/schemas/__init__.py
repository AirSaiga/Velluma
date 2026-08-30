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
配置 Schema 模块 - 统一导出入口。

职责：
- 统一导出生成配置相关的数据模型
- 提供配置对象的类型定义

子模块：
- generation_config.py: 生成配置对象定义

主要功能：
- GenerationConfig: 统一生成配置
- StoryConfig: 故事语义配置
- ChapterPlan: 章节规划配置
- LLMConfig: 模型配置
- RAGPolicy: RAG 检索策略
- WorkflowPolicy: 工作流策略

依赖项：
- pydantic: 数据验证
"""

from backend.config.schemas.generation_config import (
    GenerationConfig,
    StoryConfig,
    ChapterPlan,
    LLMConfig,
    RAGPolicy,
    WorkflowPolicy,
    ValidationPolicy,
    FeatureFlags,
    ReasoningSettings,
    MemoryStrategy,
    CreativityLevel,
    RefinementDepth,
    EditorMode,
    WorkflowTier,
    PacingStyle,
    ReasoningEffort,
)

__all__ = [
    "GenerationConfig",
    "StoryConfig",
    "ChapterPlan",
    "LLMConfig",
    "RAGPolicy",
    "WorkflowPolicy",
    "ValidationPolicy",
    "FeatureFlags",
    "ReasoningSettings",
    "MemoryStrategy",
    "CreativityLevel",
    "RefinementDepth",
    "EditorMode",
    "WorkflowTier",
    "PacingStyle",
    "ReasoningEffort",
]
