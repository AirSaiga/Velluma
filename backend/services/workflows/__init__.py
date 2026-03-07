"""
工作流阶段模块（统一出口）。

职责：聚合 Agentic 工作流的各阶段处理函数，提供统一的导入入口。

设计模式：Facade Pattern，将复杂的工作流拆分为独立的阶段模块。

模块组织：
- context.py: 上下文加载（角色、关系、伏笔、记忆）
- planning.py: 规划阶段（故事节奏拆分）
- drafting.py: 生成阶段（并行生成多个故事片段）
- stitching.py: 统稿阶段（片段拼接成完整章节）
- reviewing.py: 审查阶段（质量检查、逻辑校验）
- refining.py: 精修阶段（基于反馈重写）
- utils.py: 工具函数

使用场景：
- agentic_workflow.py: 调用各阶段函数组装完整工作流
- routes/: 直接导入使用

业务流程：
1. load_chapter_context: 加载上下文数据
2. generate_beats: 生成故事节拍
3. generate_chunks_parallel: 并行生成片段
4. stitch_chunks: 统稿拼接
5. review_draft: 质量审查
6. refine_draft: 精修重写（如审查未通过）

业务规则：
- 所有阶段函数都是 async 函数，支持流式输出
- 返回格式统一为异步生成器或结构化数据
"""

from backend.services.workflows.context import load_chapter_context
from backend.services.workflows.planning import generate_beats
from backend.services.workflows.drafting import generate_chunks_parallel
from backend.services.workflows.stitching import stitch_chunks
from backend.services.workflows.reviewing import review_draft
from backend.services.workflows.refining import refine_draft

__all__ = [
    "load_chapter_context",
    "generate_beats",
    "generate_chunks_parallel",
    "stitch_chunks",
    "review_draft",
    "refine_draft",
]
