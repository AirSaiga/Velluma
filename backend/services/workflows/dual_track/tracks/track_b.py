"""
Track B - 短文生成轨道。

职责：
- 生成连贯的速写短文
- 作为 Track A 的对齐参考
- 提供情绪和节奏的自然流动

核心特性：
- 连续叙述流：不标记节拍边界
- 强连贯性：情绪、节奏、信息一气呵成
- 转折点映射：记录关键转折位置

依赖项：
- backend.services.workflows.sketch_generator: SketchGenerator

使用方式：
    from backend.services.workflows.dual_track.tracks.track_b import TrackBExecutor

    executor = TrackBExecutor(api_key, base_url, sketch_model, config)
    sketch_result = await executor.execute(chapter, book, beats, ...)
"""

import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.services.workflows.sketch_generator import (
    SketchGenerator,
    SketchResult,
    SketchGeneratorConfig,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TrackBExecutor:
    """
    Track B 执行器 - 短文生成。

    职责：
    - 调用 SketchGenerator 生成连贯速写
    - 管理生成配置和目标字数
    - 收集调试信息

    设计决策：
    - 独立执行，不依赖 Track A
    - 专注于流畅性而非精确性
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        config: Optional[SketchGeneratorConfig] = None,
    ):
        """
        初始化 Track B 执行器。

        Args:
            api_key: API 密钥
            base_url: API 端点
            model: 生成模型
            config: 生成配置
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.config = config or SketchGeneratorConfig()
        self.generator = SketchGenerator(
            api_key=api_key,
            base_url=base_url,
            model=model,
            config=self.config,
        )

    def calculate_target_words(self, word_count: int) -> int:
        """
        计算 Sketch 目标字数。

        基于 sketch_ratio 比例计算，同时限制在 min/max 范围内。

        Args:
            word_count: 正文目标字数

        Returns:
            int: Sketch 目标字数
        """
        target_words = int(word_count * self.config.sketch_ratio)
        return max(self.config.min_words, min(target_words, self.config.max_words))

    async def execute(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        entities: List[Any],
        relationships: List[Any],
        word_count: int,
        previous_summary: Optional[str] = None,
        anchor_pov: Optional[str] = None,
        chapter_assets_schema: str = "",
    ) -> SketchResult:
        """
        执行 Track B - 短文生成。

        职责：生成连贯的速写短文作为对齐参考。

        Args:
            chapter: 章节对象
            book: 书籍对象
            beats: 剧情节拍列表
            entities: 角色实体列表
            relationships: 角色关系列表
            word_count: 正文目标字数
            previous_summary: 前情摘要
            anchor_pov: 锚定视角角色
            chapter_assets_schema: 章节资产模式

        Returns:
            SketchResult: 速写生成结果

        Raises:
            Exception: 如果生成失败
        """
        target_words = self.calculate_target_words(word_count)
        logger.info(
            f"[TrackB] 开始生成速写，beats={len(beats)}, "
            f"target_words={target_words} ({self.config.sketch_ratio*100:.0f}%)"
        )

        start_time = time.perf_counter()

        try:
            result = await self.generator.generate(
                chapter=chapter,
                book=book,
                beats=beats,
                entities=entities,
                relationships=relationships,
                word_count=word_count,
                previous_summary=previous_summary,
                anchor_pov=anchor_pov,
                chapter_assets_schema=chapter_assets_schema,
            )

            elapsed = time.perf_counter() - start_time
            logger.info(
                f"[TrackB] 生成完成，elapsed={elapsed:.2f}s, "
                f"word_count={result.word_count}"
            )

            return result

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            logger.error(f"[TrackB] 生成失败 (elapsed={elapsed:.2f}s): {e}")
            raise
