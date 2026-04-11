"""
小说正文生成服务 - 提供统一的生成接口。

职责：
- 协调多种生成策略的执行
- 管理上下文和状态
- 提供质量检查和重试机制

使用方式：
    from backend.services.workflows.drafting import ProseGenerationService

    service = ProseGenerationService(config, llm_client)
    results = await service.generate_prose(
        beats=beats,
        scene_intent_results=scene_intents,
        subconscious_results=subcons,
        context=context,
    )
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.drafting_core.strategies.base import GenerationStrategy, GenerationResult
from backend.services.workflows.drafting_core.strategies.factory import StrategyFactory
from backend.services.workflows.drafting_core.context.context_manager import ContextManager
from backend.services.workflows.drafting_core.context.state_updater import StateUpdater
from backend.services.workflows.drafting_core.quality.quality_checker import QualityChecker
from backend.services.workflows.drafting_core.retry.retry_engine import RetryEngine

if TYPE_CHECKING:
    from backend.services.llm import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class ProseGenerationStats:
    """
    生成统计信息。

    业务含义：
    - 记录生成过程的性能指标
    - 用于调试和优化
    """
    total_time: float = 0.0
    beat_count: int = 0
    total_words: int = 0
    success_count: int = 0
    retry_count: int = 0
    failed_beats: List[int] = field(default_factory=list)


class ProseGenerationService:
    """
    小说正文生成服务。

    职责：
    - 提供统一的生成接口
    - 管理策略选择和执行
    - 协调上下文管理和质量检查

    设计决策：
    - 使用策略模式支持多种生成策略
    - 上下文管理器统一管理状态
    - 质量检查器和重试引擎作为共享组件

    使用示例：
        service = ProseGenerationService(config, llm_client)

        results = await service.generate_prose(
            beats=beats,
            scene_intent_results=scene_intents,
            subconscious_results=subcons,
            context={
                "chapter": chapter,
                "book": book,
                "entities": entities,
                "relationships": relationships,
                "word_count": word_count,
            },
        )
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm_client: Optional["LLMClient"] = None,
        strategy_type: Optional[str] = None,
    ):
        """
        初始化生成服务。

        Args:
            config: 配置对象，包含：
                - feature_flags: 功能标志
                - strategy_type: 策略类型 (serial/parallel/semi_parallel)
            llm_client: LLM 客户端实例
            strategy_type: 策略类型（可选，优先级高于 config）
        """
        self._config = config
        self._llm_client = llm_client

        # 创建核心组件
        self._quality_checker = QualityChecker(config)
        self._retry_engine = RetryEngine(config)
        self._context_manager = ContextManager(config)
        self._state_updater = StateUpdater(config)

        # 创建策略工厂
        self._strategy_factory = StrategyFactory(
            config=config,
            llm_client=llm_client,
            quality_checker=self._quality_checker,
            retry_engine=self._retry_engine,
        )

        # 选择策略
        self._strategy_type = strategy_type or config.get("strategy_type", "semi_parallel")
        self._strategy = self._strategy_factory.create_strategy(self._strategy_type)

    @property
    def strategy_type(self) -> str:
        """获取当前策略类型"""
        return self._strategy_type

    async def generate_prose(
        self,
        beats: List[dict],
        scene_intent_results: List[dict],
        subconscious_results: List[str],
        context: Dict[str, Any],
    ) -> Tuple[List[GenerationResult], ProseGenerationStats]:
        """
        生成小说正文。

        职责：这是服务的主入口方法，协调整个生成流程。

        Args:
            beats: 故事节拍列表
            scene_intent_results: 场景意图结果
            subconscious_results: 潜意识思考结果
            context: 生成上下文，包含：
                - chapter: 章节对象
                - book: 书籍对象
                - entities: 实体列表
                - relationships: 关系列表
                - word_count: 目标字数
                - previous_summary: 前情摘要
                - relevant_memories: 相关记忆
                - locations: 地点列表
                - physical_state_lock: 物理状态锁
                - entity_spatial_ledger: 实体空间台账
                - chapter_assets_schema: 章节资产模式

        Returns:
            Tuple[List[GenerationResult], ProseGenerationStats]:
                - 生成结果列表
                - 统计信息
        """
        start_time = time.perf_counter()
        stats = ProseGenerationStats(beat_count=len(beats))

        logger.info(
            f"[ProseGenerationService] 开始生成，策略={self._strategy_type}, "
            f"Beats={len(beats)}, 字数目标={context.get('word_count', 0)}"
        )

        try:
            # 执行策略
            results = await self._strategy.execute(
                beats=beats,
                scene_intent_results=scene_intent_results,
                subconscious_results=subconscious_results,
                context=context,
            )

            # 统计
            for i, result in enumerate(results):
                if result.success:
                    stats.success_count += 1
                    stats.total_words += len(result.text)
                else:
                    stats.failed_beats.append(i)

            stats.total_time = time.perf_counter() - start_time

            logger.info(
                f"[ProseGenerationService] 生成完成，"
                f"成功={stats.success_count}/{stats.beat_count}, "
                f"字数={stats.total_words}, 耗时={stats.total_time:.2f}s"
            )

            return results, stats

        except Exception as e:
            logger.error(f"[ProseGenerationService] 生成失败: {e}")
            stats.total_time = time.perf_counter() - start_time
            raise

    def set_strategy(self, strategy_type: str) -> None:
        """
        切换生成策略。

        Args:
            strategy_type: 策略类型 (serial/parallel/semi_parallel)
        """
        self._strategy_type = strategy_type
        self._strategy = self._strategy_factory.create_strategy(strategy_type)
        logger.info(f"[ProseGenerationService] 策略切换为: {strategy_type}")

    def get_available_strategies(self) -> List[str]:
        """获取可用的策略列表"""
        return StrategyFactory.get_available_strategies()


# =============================================================================
# 便捷函数
# =============================================================================

async def generate_prose_serial(
    beats: List[dict],
    context: Dict[str, Any],
    **kwargs,
) -> List[GenerationResult]:
    """
    便捷函数：使用串行策略生成正文。

    Args:
        beats: 故事节拍列表
        context: 生成上下文
        **kwargs: 其他参数

    Returns:
        List[GenerationResult]: 生成结果
    """
    service = ProseGenerationService(
        config={**kwargs, "strategy_type": "serial"},
        llm_client=kwargs.get("llm_client"),
    )
    results, _ = await service.generate_prose(beats, [], [], context)
    return results


async def generate_prose_parallel(
    beats: List[dict],
    context: Dict[str, Any],
    **kwargs,
) -> List[GenerationResult]:
    """
    便捷函数：使用并行策略生成正文。

    Args:
        beats: 故事节拍列表
        context: 生成上下文
        **kwargs: 其他参数

    Returns:
        List[GenerationResult]: 生成结果
    """
    service = ProseGenerationService(
        config={**kwargs, "strategy_type": "parallel"},
        llm_client=kwargs.get("llm_client"),
    )
    results, _ = await service.generate_prose(beats, [], [], context)
    return results
