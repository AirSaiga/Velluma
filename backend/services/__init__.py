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
服务层统一出口模块。

职责：聚合后端业务逻辑服务，提供统一的导入入口。

设计模式：Facade Pattern，封装底层复杂实现。

模块组织：
- generation/: 章节生成服务（统一导出各类生成函数）
- orchestration/: Agentic 工作流（多轮迭代生成）
- llm/: LLM 调用封装（支持多模型、重试机制）
- state_machine/: 角色状态管理
- prompts/: 按 Agent 类型拆分的提示词模块
- workflows/: 工作流阶段模块
- context/: 上下文数据加载服务
- utils/: 通用工具模块
- world/: 世界状态服务
- rag/: RAG 检索服务

使用场景：
- routes/: 业务路由层，通过此模块调用底层服务
- main.py: 应用入口，注册路由

业务规则：
- 所有导出函数均为 async 函数或返回异步生成器
- API Key 由调用方传入，服务层不存储敏感信息

向后兼容：
- 为避免破坏现有代码，保留旧路径的别名导入

迁移说明 (2026-03-30)：
- 已移除 LegacyServiceClass 别名机制
- 服务导入路径已统一规范化
- 旧代码请直接导入具体模块（如 from backend.services.generation import xxx）
"""

from backend.services.generation import (
    build_chapter_prompt,
    generate_stream_response,
    update_character_dynamic_state,
    preview_agentic_beats,
    generate_chapter_summary,
    generate_summary_embedding,
    expand_inspiration,
    expand_outline,
    persist_checkpoint,
    resolve_run_id,
)

from backend.services.context import (
    load_full_chapter_context,
    load_chapter,
    load_book,
    load_chapter_entities,
    load_character_relationships,
    ChapterContext,
)

from backend.services.orchestration import (
    resolve_high_level_params,
    preview_agentic_beats,
    map_tension_to_workflow_tier,
    save_story_beats,
    build_physical_state_lock,
)

from backend.services.utils import (
    ServiceLogger,
    build_sse_event,
    build_sse_metric_frame,
    build_sse_done,
    build_sse_error,
    build_sse_text_chunk,
    LOG_PREFIX_DUAL_TRACK,
    LOG_PREFIX_RAG,
    LOG_PREFIX_WORKFLOW,
    LOG_PREFIX_SUMMARY,
    LOG_PREFIX_PROMPT_LOGGER,
    LOG_PREFIX_SYSTEM,
    TimeoutManager,
    timed,
    sanitize_user_content,
    PromptLogger,
)

from backend.services.world import (
    extract_world_state_snapshot,
    update_character_physical_state,
    CharacterInfo,
)
