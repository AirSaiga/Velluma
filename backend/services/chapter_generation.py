"""
章节生成服务模块 (Facade)。

职责：统一导出所有章节生成相关的服务函数，供上层 (API 路由) 消费。
内部实现分布在：
- llm_client.py: LLM 调用封装
- prompts/: 提示词构建（按Agent类型拆分）
- agentic_workflow.py: 代理工作流
- character_state.py: 角色状态管理

设计模式：Facade Pattern，隐藏底层复杂度，提供统一入口。
"""

from backend.services.agentic_workflow import (
    generate_agentic_chapter_stream,
    generate_agentic_chapter_stream_with_confirmed_beats,
    preview_agentic_beats,
)
from backend.services.workflows.refining import refine_draft
from backend.services.character_state import update_character_dynamic_state
from backend.services.llm_client import call_llm, generate_stream_response
from backend.services.prompts import (
    build_chapter_prompt,
    build_draft_agent_prompt,
    build_review_agent_prompt,
    build_refine_agent_prompt,
    parse_review_result,
)

__all__ = [
    "build_chapter_prompt",
    "generate_stream_response",
    "build_draft_agent_prompt",
    "build_review_agent_prompt",
    "build_refine_agent_prompt",
    "parse_review_result",
    "call_llm",
    "generate_agentic_chapter_stream",
    "generate_agentic_chapter_stream_with_confirmed_beats",
    "preview_agentic_beats",
    "update_character_dynamic_state",
    "refine_draft",
]
