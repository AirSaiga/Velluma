"""
上下文管理模块 - 管理生成过程中的上下文状态。

职责：
- 初始化各种生成策略所需的上下文
- 更新 Beat 之间的状态传递
- 管理 Rolling Prefix（滚动前缀）

上下文类型：
- SerialContext: 串行策略上下文，实时更新状态
- ParallelContext: 并行策略上下文，共享初始状态
- SemiParallelContext: 半并行上下文，与串行类似

使用方式：
    from backend.services.workflows.drafting_core.context import ContextManager

    manager = ContextManager(config)
    context = await manager.create_context(beats, entities, relationships)
"""

from backend.services.workflows.drafting_core.context.context_manager import ContextManager
from backend.services.workflows.drafting_core.context.state_updater import StateUpdater

__all__ = [
    "ContextManager",
    "StateUpdater",
]
