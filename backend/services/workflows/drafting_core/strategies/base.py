"""
生成策略基类 - 定义策略接口和公共逻辑。

职责：
- 定义所有生成策略的统一接口
- 提供策略共用的辅助方法
- 封装 Beat 上下文构建逻辑

设计模式：策略模式 (Strategy Pattern)
- 允许在运行时切换生成策略
- 每个策略独立实现，互不影响
- 便于添加新策略（如未来的 CascadeStrategy）

使用方式：
    class MyStrategy(GenerationStrategy):
        async def execute(self, beats, context) -> GenerationResult:
            # 实现具体策略
            ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Awaitable

from backend.schemas import DraftingFeatureFlags


@dataclass
class BeatContext:
    """
    单个 Beat 的执行上下文。

    业务含义：
    - 封装单个 Beat 生成所需的所有信息
    - 减少策略实现中的参数传递
    - 便于添加 Beat 级别的状态

    字段说明：
    - beat: 故事节拍数据
    - beat_index: 节拍索引 (从 0 开始)
    - total_beats: 总节拍数
    - scene_intent: 场景意图
    - subconscious: 潜意识思考
    - target_words: 目标字数
    """
    beat: dict
    beat_index: int
    total_beats: int
    scene_intent: dict = field(default_factory=dict)
    subconscious: str = ""
    target_words: int = 500

    @property
    def beat_number(self) -> int:
        """1-based 节拍编号"""
        return self.beat_index + 1

    @property
    def is_first(self) -> bool:
        """是否第一个节拍"""
        return self.beat_index == 0

    @property
    def is_last(self) -> bool:
        """是否最后一个节拍"""
        return self.beat_index == self.total_beats - 1


@dataclass
class GenerationResult:
    """
    生成结果数据类。

    业务含义：
    - 统一所有策略的返回格式
    - 包含生成文本和元数据
    """
    text: str
    prompts: List[dict] = field(default_factory=list)
    beat_index: int = 0
    generation_time: float = 0.0
    success: bool = True
    error_message: Optional[str] = None


class GenerationStrategy(ABC):
    """
    生成策略抽象基类。

    职责：
    - 定义策略的统一接口
    - 提供策略共用的辅助方法
    - 管理上下文初始化

    子类需要实现：
    - execute(): 执行生成的核心逻辑
    - _create_beat_context(): 创建单个 Beat 的上下文
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm_client: Any,
        quality_checker: Optional[Any] = None,
        retry_engine: Optional[Any] = None,
    ):
        """
        初始化策略。

        Args:
            config: 策略配置，包含 feature_flags 等
            llm_client: LLM 客户端实例
            quality_checker: 质量检查器（可选）
            retry_engine: 重试引擎（可选）
        """
        self._config = config
        self._llm_client = llm_client
        self._quality_checker = quality_checker
        self._retry_engine = retry_engine
        self._feature_flags = config.get("feature_flags", DraftingFeatureFlags())

    @property
    def feature_flags(self) -> DraftingFeatureFlags:
        """获取功能标志"""
        return self._feature_flags

    @abstractmethod
    async def execute(
        self,
        beats: List[dict],
        scene_intent_results: List[dict],
        subconscious_results: List[str],
        context: Dict[str, Any],
    ) -> List[GenerationResult]:
        """
        执行生成策略。

        Args:
            beats: 故事节拍列表
            scene_intent_results: 场景意图结果
            subconscious_results: 潜意识思考结果
            context: 生成上下文

        Returns:
            List[GenerationResult]: 每个节拍的生成结果
        """
        pass

    def _create_beat_context(
        self,
        beat: dict,
        beat_index: int,
        total_beats: int,
        scene_intent: dict,
        subconscious: str,
        target_words: int,
    ) -> BeatContext:
        """
        创建单个 Beat 的上下文。

        Args:
            beat: 节拍数据
            beat_index: 节拍索引
            total_beats: 总节拍数
            scene_intent: 场景意图
            subconscious: 潜意识思考
            target_words: 目标字数

        Returns:
            BeatContext: Beat 执行上下文
        """
        return BeatContext(
            beat=beat,
            beat_index=beat_index,
            total_beats=total_beats,
            scene_intent=scene_intent or {"intent_label": "默认", "goal": beat.get("summary", "")},
            subconscious=subconscious or "",
            target_words=target_words,
        )

    def _calculate_target_words(
        self,
        beat: dict,
        total_words: int,
        total_beats: int,
    ) -> int:
        """
        计算单个 Beat 的目标字数。

        基于 Beat 的 weight 和 pacing_type 计算权重。

        Args:
            beat: 节拍数据
            total_words: 总目标字数
            total_beats: 总节拍数

        Returns:
            int: 该节拍的目标字数
        """
        weight = beat.get("weight", 1)
        pacing_multiplier = {
            "fast": 0.8,
            "medium": 1.0,
            "slow": 1.3,
        }.get(beat.get("pacing_type", "medium"), 1.0)

        base_words = total_words / total_beats
        return int(base_words * weight * pacing_multiplier)
