"""
生成策略工厂 - 根据配置创建合适的策略实例。

职责：
- 根据配置选择合适的生成策略
- 统一策略实例的创建逻辑
- 管理策略的生命周期

支持的策略：
- serial: 串行滑动窗口策略
- parallel: 并行策略
- semi_parallel: 半并行策略

使用方式：
    factory = StrategyFactory(config, llm_client)
    strategy = factory.create_strategy("serial")
"""

from typing import Any, Dict, Optional, TYPE_CHECKING

from backend.services.workflows.drafting_core.strategies.base import GenerationStrategy
from backend.services.workflows.drafting_core.strategies.serial_strategy import SerialStrategy
from backend.services.workflows.drafting_core.strategies.parallel_strategy import ParallelStrategy
from backend.services.workflows.drafting_core.strategies.semi_parallel_strategy import SemiParallelStrategy
from backend.services.workflows.drafting_core.quality.quality_checker import QualityChecker
from backend.services.workflows.drafting_core.retry.retry_engine import RetryEngine

if TYPE_CHECKING:
    from backend.services.llm import LLMClient


class StrategyFactory:
    """
    生成策略工厂。

    职责：
    - 根据配置创建合适的策略实例
    - 管理策略共用的组件（质量检查器、重试引擎）
    - 提供策略选择逻辑

    设计决策：
    - 使用工厂模式统一策略创建
    - 质量检查器和重试引擎作为共享组件注入
    - 支持策略类型自动检测
    """

    STRATEGY_TYPE_SERIAL = "serial"
    STRATEGY_TYPE_PARALLEL = "parallel"
    STRATEGY_TYPE_SEMI_PARALLEL = "semi_parallel"

    # 策略类型别名
    STRATEGY_ALIASES = {
        "rolling": STRATEGY_TYPE_SERIAL,
        "cascade": STRATEGY_TYPE_SEMI_PARALLEL,
        "fast": STRATEGY_TYPE_PARALLEL,
    }

    def __init__(
        self,
        config: Dict[str, Any],
        llm_client: "LLMClient",
        quality_checker: Optional[QualityChecker] = None,
        retry_engine: Optional[RetryEngine] = None,
    ):
        """
        初始化策略工厂。

        Args:
            config: 策略配置，包含：
                - strategy_type: 策略类型 (serial/parallel/semi_parallel)
                - feature_flags: 功能标志
                - max_parallel_beats: 最大并行数
            llm_client: LLM 客户端实例
            quality_checker: 质量检查器（可选，自动创建）
            retry_engine: 重试引擎（可选，自动创建）
        """
        self._config = config
        self._llm_client = llm_client

        # 创建或使用提供的组件
        if quality_checker is None:
            quality_checker = QualityChecker(config)
        self._quality_checker = quality_checker

        if retry_engine is None:
            retry_engine = RetryEngine(config)
        self._retry_engine = retry_engine

    def create_strategy(
        self,
        strategy_type: Optional[str] = None,
    ) -> GenerationStrategy:
        """
        创建策略实例。

        Args:
            strategy_type: 策略类型，如果为 None 则从配置自动检测

        Returns:
            GenerationStrategy: 策略实例

        Raises:
            ValueError: 不支持的策略类型
        """
        # 自动检测策略类型
        if strategy_type is None:
            strategy_type = self._detect_strategy_type()

        # 解析别名
        strategy_type = self.STRATEGY_ALIASES.get(strategy_type, strategy_type)

        # 创建策略实例
        strategy_config = self._build_strategy_config(strategy_type)

        if strategy_type == self.STRATEGY_TYPE_SERIAL:
            return SerialStrategy(
                config=strategy_config,
                llm_client=self._llm_client,
                quality_checker=self._quality_checker,
                retry_engine=self._retry_engine,
            )
        elif strategy_type == self.STRATEGY_TYPE_PARALLEL:
            return ParallelStrategy(
                config=strategy_config,
                llm_client=self._llm_client,
                quality_checker=self._quality_checker,
                retry_engine=self._retry_engine,
            )
        elif strategy_type == self.STRATEGY_TYPE_SEMI_PARALLEL:
            return SemiParallelStrategy(
                config=strategy_config,
                llm_client=self._llm_client,
                quality_checker=self._quality_checker,
                retry_engine=self._retry_engine,
            )
        else:
            raise ValueError(f"不支持的策略类型: {strategy_type}")

    def _detect_strategy_type(self) -> str:
        """
        从配置自动检测策略类型。

        检测逻辑：
        1. 如果 force_parallel_prose=True，使用并行策略
        2. 如果 semi_parallel_prose=True，使用半并行策略
        3. 默认使用串行策略

        Returns:
            str: 检测到的策略类型
        """
        feature_flags = self._config.get("feature_flags", {})

        if feature_flags.get("force_parallel_prose", False):
            return self.STRATEGY_TYPE_PARALLEL
        elif feature_flags.get("semi_parallel_prose", True):
            return self.STRATEGY_TYPE_SEMI_PARALLEL
        else:
            return self.STRATEGY_TYPE_SERIAL

    def _build_strategy_config(self, strategy_type: str) -> Dict[str, Any]:
        """
        构建策略配置。

        Args:
            strategy_type: 策略类型

        Returns:
            Dict[str, Any]: 策略配置
        """
        base_config = {
            "strategy_type": strategy_type,
            "feature_flags": self._config.get("feature_flags", {}),
            "max_parallel_beats": self._config.get("max_parallel_beats", 6),
        }

        # 策略特定的配置
        if strategy_type == self.STRATEGY_TYPE_PARALLEL:
            base_config["shared_initial_state"] = True
        elif strategy_type == self.STRATEGY_TYPE_SEMI_PARALLEL:
            base_config["shared_initial_state"] = False
            # Cascade 模式在 Beat 数量少于等于 2 时降级为串行
            base_config["cascade_fallback_threshold"] = 2

        return base_config

    @staticmethod
    def get_available_strategies() -> list:
        """获取所有可用的策略类型"""
        return [
            StrategyFactory.STRATEGY_TYPE_SERIAL,
            StrategyFactory.STRATEGY_TYPE_PARALLEL,
            StrategyFactory.STRATEGY_TYPE_SEMI_PARALLEL,
        ]
