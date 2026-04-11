"""
Drafting 子系统 - 小说正文生成的核心模块。

职责：
- 提供多种生成策略（串行/并行/半并行）
- 管理上下文传递和状态更新
- 提供质量检查和重试机制

模块结构：
- strategies/: 生成策略实现
- context/: 上下文管理器
- quality/: 质量检查器
- retry/: 重试引擎

使用方式：
    from backend.services.workflows.drafting_core import ProseGenerationService

    service = ProseGenerationService(config, llm_client)
    result = await service.generate_prose(beats, context)

迁移说明 (2026-04-11)：
- 目录从 drafting 重命名为 drafting_core 以避免与 drafting.py 冲突
- 新增子模块结构
"""

# 从子模块导入
from backend.services.workflows.drafting_core.prose_generation import ProseGenerationService
from backend.services.workflows.drafting_core.strategies.base import GenerationStrategy
from backend.services.workflows.drafting_core.context.context_manager import ContextManager
from backend.services.workflows.drafting_core.quality.quality_checker import QualityChecker

# 从原 drafting.py 导入（保持向后兼容）
from backend.services.workflows.drafting import execute_draft_stage, BeatDraftResult

__all__ = [
    "ProseGenerationService",
    "GenerationStrategy",
    "ContextManager",
    "QualityChecker",
    "execute_draft_stage",
    "BeatDraftResult",
]
