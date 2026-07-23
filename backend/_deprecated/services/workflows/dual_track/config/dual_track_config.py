"""
双轨工作流配置 - 定义双轨架构的配置类。

职责：
- 定义双轨生成的核心配置
- 管理 Track A 和 Track B 的参数
- 控制对抗校对的阈值

使用方式：
    from backend.services.workflows.dual_track.config import DualTrackConfig, SketchConfig, AlignerConfig

    config = DualTrackConfig(
        enable_sketch_track=True,
        enable_adversarial_alignment=True,
    )
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SketchConfig:
    """
    Sketch 轨道配置。

    业务含义：
    - 控制短文生成轨道的参数
    - 管理 Sketch 的字数占比和生成质量

    字段说明：
    - sketch_ratio: Sketch 字数占总字数比例 (0.2-0.7)
    - min_words: Sketch 最小字数
    - max_words: Sketch 最大字数
    - temperature: 生成温度
    """
    sketch_ratio: float = 0.45
    min_words: int = 500
    max_words: int = 2000
    temperature: float = 0.7

    def validate(self) -> None:
        """验证配置合法性"""
        if not 0.1 <= self.sketch_ratio <= 0.8:
            raise ValueError(f"sketch_ratio 必须在 0.1-0.8 之间，当前值: {self.sketch_ratio}")
        if self.min_words < 100:
            raise ValueError(f"min_words 不能小于 100")
        if self.max_words < self.min_words:
            raise ValueError(f"max_words 不能小于 min_words")


@dataclass
class AlignerConfig:
    """
    对抗校对器配置。

    业务含义：
    - 控制对抗校对的敏感度和阈值
    - 管理 Gap 检测的参数

    字段说明：
    - min_acceptable_score: 可接受的最低对齐分数
    - structural_offset_threshold: 结构偏差阈值
    - emotion_diff_threshold: 情绪差异阈值
    - temperature: 分析温度
    - max_analysis_tokens: 分析最大 Token 数
    """
    min_acceptable_score: float = 70.0
    structural_offset_threshold: float = 15.0
    emotion_diff_threshold: float = 2.0
    temperature: float = 0.1
    max_analysis_tokens: int = 2000

    def validate(self) -> None:
        """验证配置合法性"""
        if not 0 <= self.min_acceptable_score <= 100:
            raise ValueError(
                f"min_acceptable_score 必须在 0-100 之间，当前值: {self.min_acceptable_score}"
            )


@dataclass
class DualTrackConfig:
    """
    双轨工作流配置。

    业务含义：
    - 控制双轨架构的整体行为
    - 管理 Sketch 轨道和对齐器的开关和参数

    设计决策：
    - 支持独立开关每个轨道
    - 配置有默认值，可快速启动
    - 提供 validate 方法进行配置校验

    使用示例：
        config = DualTrackConfig(
            enable_sketch_track=True,
            enable_adversarial_alignment=True,
            sketch_config=SketchConfig(sketch_ratio=0.5),
            aligner_config=AlignerConfig(min_acceptable_score=75.0),
        )
    """

    # 开关配置
    enable_sketch_track: bool = True
    """是否启用 Sketch 轨道 (Track B)"""

    enable_adversarial_alignment: bool = True
    """是否启用对抗校对"""

    use_sketch_for_refinement: bool = True
    """是否使用 Sketch 指导精修"""

    # Sketch 配置
    sketch_config: Optional[SketchConfig] = field(default_factory=SketchConfig)
    """Sketch 轨道配置"""

    # Aligner 配置
    aligner_config: Optional[AlignerConfig] = field(default_factory=AlignerConfig)
    """对抗校对器配置"""

    # 高级配置
    alignment_threshold: float = 70.0
    """对齐分数阈值（低于此值触发精修）"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DualTrackConfig":
        """
        从字典创建配置。

        Args:
            data: 配置字典

        Returns:
            DualTrackConfig: 配置实例
        """
        sketch_data = data.get("sketch_config", {})
        aligner_data = data.get("aligner_config", {})

        sketch_config = None
        if sketch_data or data.get("sketch_ratio"):
            sketch_config = SketchConfig(
                sketch_ratio=sketch_data.get("sketch_ratio", data.get("sketch_ratio", 0.45)),
                min_words=sketch_data.get("min_words", 500),
                max_words=sketch_data.get("max_words", 2000),
                temperature=sketch_data.get("temperature", 0.7),
            )

        aligner_config = None
        if aligner_data or data.get("min_acceptable_score"):
            aligner_config = AlignerConfig(
                min_acceptable_score=aligner_data.get(
                    "min_acceptable_score", data.get("min_acceptable_score", 70.0)
                ),
                structural_offset_threshold=aligner_data.get("structural_offset_threshold", 15.0),
                emotion_diff_threshold=aligner_data.get("emotion_diff_threshold", 2.0),
                temperature=aligner_data.get("temperature", 0.1),
                max_analysis_tokens=aligner_data.get("max_analysis_tokens", 2000),
            )

        return cls(
            enable_sketch_track=data.get("enable_sketch_track", True),
            enable_adversarial_alignment=data.get("enable_adversarial_alignment", True),
            use_sketch_for_refinement=data.get("use_sketch_for_refinement", True),
            sketch_config=sketch_config,
            aligner_config=aligner_config,
            alignment_threshold=data.get("alignment_threshold", 70.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典。

        Returns:
            Dict[str, Any]: 配置字典
        """
        return {
            "enable_sketch_track": self.enable_sketch_track,
            "enable_adversarial_alignment": self.enable_adversarial_alignment,
            "use_sketch_for_refinement": self.use_sketch_for_refinement,
            "alignment_threshold": self.alignment_threshold,
            "sketch_config": {
                "sketch_ratio": self.sketch_config.sketch_ratio,
                "min_words": self.sketch_config.min_words,
                "max_words": self.sketch_config.max_words,
                "temperature": self.sketch_config.temperature,
            } if self.sketch_config else None,
            "aligner_config": {
                "min_acceptable_score": self.aligner_config.min_acceptable_score,
                "structural_offset_threshold": self.aligner_config.structural_offset_threshold,
                "emotion_diff_threshold": self.aligner_config.emotion_diff_threshold,
                "temperature": self.aligner_config.temperature,
                "max_analysis_tokens": self.aligner_config.max_analysis_tokens,
            } if self.aligner_config else None,
        }

    def validate(self) -> None:
        """验证配置合法性"""
        if self.sketch_config:
            self.sketch_config.validate()
        if self.aligner_config:
            self.aligner_config.validate()
        if not 0 <= self.alignment_threshold <= 100:
            raise ValueError(
                f"alignment_threshold 必须在 0-100 之间，当前值: {self.alignment_threshold}"
            )

    def is_valid(self) -> bool:
        """
        检查配置是否合法。

        Returns:
            bool: 是否合法
        """
        try:
            self.validate()
            return True
        except ValueError:
            return False
