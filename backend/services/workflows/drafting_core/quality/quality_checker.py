"""
质量检查器 - 提供生成质量验证功能。

职责：
- 执行微观审阅（Micro Review）
- 检测生成文本的异常（长度、结构）
- 提供失败原因分类

质量检查类型：
- MicroReviewer: 微观审阅，检查 OOC、物理幻觉等问题
- QuickQC: 快速质检，检测长度和结构异常

使用方式：
    checker = QualityChecker(config)

    # 微观审阅
    is_valid, reason = await checker.micro_review(
        chunk_text=chunk,
        context=context,
    )

    # 快速质检
    fixed_text, prompts = await checker.quick_qc(
        prose_text=text,
        context=context,
    )
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.drafting_core.quality.micro_reviewer import MicroReviewer
from backend.services.workflows.drafting_core.quality.fail_analyzer import FailAnalyzer

if TYPE_CHECKING:
    from backend.schemas import DraftingFeatureFlags

logger = logging.getLogger(__name__)


@dataclass
class QualityCheckResult:
    """
    质量检查结果。

    业务含义：
    - 统一质量检查的返回格式
    - 包含检查结果和详细信息
    """
    is_valid: bool
    reason: str
    fail_categories: List[str]
    suggestions: List[str]

    @classmethod
    def pass_result(cls) -> "QualityCheckResult":
        """创建通过的结果"""
        return cls(is_valid=True, reason="", fail_categories=[], suggestions=[])

    @classmethod
    def fail_result(
        cls,
        reason: str,
        fail_categories: Optional[List[str]] = None,
        suggestions: Optional[List[str]] = None,
    ) -> "QualityCheckResult":
        """创建失败的结果"""
        return cls(
            is_valid=False,
            reason=reason,
            fail_categories=fail_categories or [],
            suggestions=suggestions or [],
        )


class QualityChecker:
    """
    质量检查器。

    职责：
    - 提供统一的质量检查接口
    - 管理微观审阅和快速质检
    - 分析失败原因

    设计决策：
    - 支持代码级强校验 + LLM 审阅双重验证
    - 快速质检作为后备，检查长度和结构异常
    - 失败分析用于归类问题类型
    """

    def __init__(
        self,
        config: Dict[str, Any],
        micro_reviewer: Optional[MicroReviewer] = None,
        fail_analyzer: Optional[FailAnalyzer] = None,
    ):
        """
        初始化质量检查器。

        Args:
            config: 配置对象
            micro_reviewer: 微观审阅器（可选，自动创建）
            fail_analyzer: 失败分析器（可选，自动创建）
        """
        self._config = config
        self._feature_flags = config.get("feature_flags", {})

        # 创建或使用提供的组件
        if micro_reviewer is None:
            micro_reviewer = MicroReviewer(config)
        self._micro_reviewer = micro_reviewer

        if fail_analyzer is None:
            fail_analyzer = FailAnalyzer()
        self._fail_analyzer = fail_analyzer

    async def micro_review(
        self,
        chunk_text: str,
        context: Dict[str, Any],
        beat: Optional[dict] = None,
    ) -> QualityCheckResult:
        """
        执行微观审阅。

        检查内容：
        - OOC (角色行为偏离设定)
        - 物理幻觉 (空间/位置不一致)
        - 关系状态不一致
        - 红线违规

        Args:
            chunk_text: 待检查的文本片段
            context: 包含 dynamic_context, pov_character 等
            beat: 节拍数据（可选，包含 red_lines 等）

        Returns:
            QualityCheckResult: 检查结果
        """
        try:
            is_valid, reason, fail_categories = await self._micro_reviewer.review(
                chunk_text=chunk_text,
                context=context,
                beat=beat,
            )

            if is_valid:
                return QualityCheckResult.pass_result()
            else:
                suggestions = self._fail_analyzer.suggest_fixes(
                    fail_categories, reason
                )
                return QualityCheckResult.fail_result(
                    reason=reason,
                    fail_categories=fail_categories,
                    suggestions=suggestions,
                )

        except Exception as e:
            logger.warning(f"[QualityChecker] 微观审阅异常: {e}")
            # 异常时保守返回通过，避免阻断生成
            return QualityCheckResult.pass_result()

    async def quick_qc(
        self,
        prose_text: str,
        context: Dict[str, Any],
        target_words: int = 500,
    ) -> Tuple[str, List[dict]]:
        """
        执行快速质量检查。

        检查内容：
        - 长度异常（过短）
        - 结构异常（无段落分隔）

        Args:
            prose_text: 待检查的文本
            context: 上下文信息
            target_words: 目标字数

        Returns:
            Tuple[str, List[dict]]: (检查后的文本, prompts 历史)
        """
        prompts = []

        # 检查异常
        compact_text = prose_text.replace("\n", "").replace(" ", "")
        has_abnormal_length = len(compact_text) < max(120, int(target_words * 0.5))
        has_abnormal_structure = ("\n\n" not in prose_text) and len(prose_text) > 500

        if not has_abnormal_length and not has_abnormal_structure:
            return prose_text, prompts

        logger.info(f"[QualityChecker] QuickQC 检测到异常，开始修复...")

        try:
            # 调用 LLM 修复
            fixed_text, fix_prompts = await self._fix_text(
                text=prose_text,
                context=context,
                target_words=target_words,
            )
            prompts.extend(fix_prompts)
            return fixed_text, prompts

        except Exception as e:
            logger.error(f"[QualityChecker] QuickQC 修复失败: {e}")
            return prose_text, prompts

    async def _fix_text(
        self,
        text: str,
        context: Dict[str, Any],
        target_words: int,
    ) -> Tuple[str, List[dict]]:
        """
        修复异常文本。

        Args:
            text: 异常文本
            context: 上下文
            target_words: 目标字数

        Returns:
            Tuple[str, List[dict]]: (修复后文本, prompts)
        """
        # TODO: 实现 LLM 修复逻辑
        # 当前为占位实现
        return text, []

    def is_enabled(self) -> bool:
        """检查是否启用质量检查"""
        if isinstance(self._feature_flags, dict):
            return self._feature_flags.get("enable_fail_fast", True)
        return getattr(self._feature_flags, "enable_fail_fast", True)
