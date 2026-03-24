"""
服务层统一出口模块。

职责：聚合后端业务逻辑服务，提供统一的导入入口。

设计模式：Facade Pattern，封装底层复杂实现。

模块组织：
- chapter_generation.py: 章节生成服务（统一导出各类生成函数）
- agentic_workflow.py: Agentic 工作流（多轮迭代生成）
- llm_client.py: LLM 调用封装（支持多模型、重试机制）
- character_state.py: 角色状态管理
- prompt_builder.py: 提示词构建（已拆分为 prompts/ 目录）
- prompts/: 按 Agent 类型拆分的提示词模块
- workflows/: 工作流阶段模块

使用场景：
- routes/: 业务路由层，通过此模块调用底层服务
- main.py: 应用入口，注册路由

业务规则：
- 所有导出函数均为 async 函数或返回异步生成器
- API Key 由调用方传入，服务层不存储敏感信息
"""

from backend.services.chapter_generation import (
    build_chapter_prompt,
    generate_stream_response,
    update_character_dynamic_state,
)
