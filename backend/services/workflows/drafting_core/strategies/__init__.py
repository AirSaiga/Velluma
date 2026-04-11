"""
生成策略模块 - 实现多种正文生成策略。

策略类型：
- SerialStrategy: 串行滑动窗口策略，保持完整上下文连贯性
- ParallelStrategy: 并行策略，极速生成但可能损失连贯性
- SemiParallelStrategy: 半并行策略，平衡速度与连贯性

使用方式：
    from backend.services.workflows.drafting_core.strategies import (
        SerialStrategy,
        ParallelStrategy,
        SemiParallelStrategy,
        StrategyFactory,
    )

    factory = StrategyFactory(config)
    strategy = factory.create_strategy(strategy_type)
"""

from backend.services.workflows.drafting_core.strategies.base import GenerationStrategy
from backend.services.workflows.drafting_core.strategies.serial_strategy import SerialStrategy
from backend.services.workflows.drafting_core.strategies.parallel_strategy import ParallelStrategy
from backend.services.workflows.drafting_core.strategies.semi_parallel_strategy import SemiParallelStrategy
from backend.services.workflows.drafting_core.strategies.factory import StrategyFactory

__all__ = [
    "GenerationStrategy",
    "SerialStrategy",
    "ParallelStrategy",
    "SemiParallelStrategy",
    "StrategyFactory",
]
