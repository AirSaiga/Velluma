"""
参数调整器 - 根据失败类型动态调整生成参数。

职责：
- 分析失败原因推断失败类型（红线/OOC/物理幻觉等）
- 根据失败类型调整温度和提示词
- 提供修复建议用于下一轮生成

失败类型：
- 红线: 违反禁忌内容
- 物理幻觉: 空间/位置不一致
- OOC: 角色行为偏离设定
- 关系: 关系状态不一致
- 文风: 文笔质量问题

使用方式：
    adjuster = ParameterAdjuster(config)
    new_temp, hint = adjuster.adjust(
        current_temp=0.7,
        fail_categories=["文风"],
        fail_reason="文本过于平淡",
    )
"""

from typing import Any, Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.schemas import DraftingFeatureFlags


class ParameterAdjuster:
    """
    参数调整器。

    职责：
    - 根据失败类型调整生成参数
    - 生成修正提示词引导下一轮生成

    设计决策：
    - 文风问题：提高温度，增加创造性
    - 其他问题：降低温度，保持稳定性，并添加修正提示
    """

    # 失败类型关键词映射
    FAIL_CATEGORY_KEYWORDS = {
        "红线": ["红线", "禁忌", "禁止", "red_line"],
        "物理幻觉": ["物理", "空间", "位置", "幻觉", "瞬移", "physical"],
        "OOC": ["ooc", "角色", "设定", "性格", "行为偏离", "character"],
        "关系": ["关系", "态度", "信任", "敌对", "友好", "relation"],
        "文风": ["文风", "白开水", "ai味", "平淡", "机械", "套路", "模板", "style"],
    }

    def __init__(
        self,
        config: Dict[str, Any],
        temperature_step: float = 0.2,
        min_temperature: float = 0.3,
        max_temperature: float = 1.0,
    ):
        """
        初始化参数调整器。

        Args:
            config: 配置对象，包含 feature_flags
            temperature_step: 温度调整步长
            min_temperature: 最低温度
            max_temperature: 最高温度
        """
        self._config = config
        self._temp_step = temperature_step
        self._min_temp = min_temperature
        self._max_temp = max_temperature

        # 从配置读取步长
        feature_flags = config.get("feature_flags", {})
        if isinstance(feature_flags, dict):
            self._temp_step = feature_flags.get(
                "fail_fast_temperature_step", temperature_step
            )

    def adjust(
        self,
        current_temp: float,
        fail_categories: List[str],
        fail_reason: str,
    ) -> Tuple[float, str]:
        """
        根据失败原因调整参数。

        Args:
            current_temp: 当前温度
            fail_categories: 失败类型列表
            fail_reason: 失败原因描述

        Returns:
            Tuple[float, str]: (新温度, 修正提示)
        """
        # 判断是否文风问题
        is_style_issue = "文风" in fail_categories

        if is_style_issue:
            # 文风问题：提高温度
            new_temp = min(self._max_temp, current_temp + self._temp_step)
            pending_hint = ""
        else:
            # 其他问题：降低温度，添加修正提示
            new_temp = max(self._min_temp, current_temp - 0.1)
            pending_hint = self._build_correction_hint(fail_reason)

        return new_temp, pending_hint

    def _build_correction_hint(self, fail_reason: str) -> str:
        """
        构建修正提示词。

        Args:
            fail_reason: 失败原因

        Returns:
            str: 修正提示词
        """
        return f"\n\n【修正要求】上一版本存在以下问题：{fail_reason}。请保持原语境，仅修复该冲突。"

    def infer_fail_categories(
        self,
        fail_reason: str,
        failed_checks: List[str],
    ) -> List[str]:
        """
        从失败原因推断失败类型。

        Args:
            fail_reason: 失败原因描述
            failed_checks: 检查项列表

        Returns:
            List[str]: 失败类型列表
        """
        categories = set()
        reason_lower = fail_reason.lower()
        checks_lower = [c.lower() for c in failed_checks]

        # 从检查项推断
        for check in checks_lower:
            for category, keywords in self.FAIL_CATEGORY_KEYWORDS.items():
                if any(kw in check for kw in keywords):
                    categories.add(category)

        # 从失败原因推断
        for category, keywords in self.FAIL_CATEGORY_KEYWORDS.items():
            if any(kw in reason_lower for kw in keywords):
                categories.add(category)

        # 如果无法识别，归类为"其他"
        if not categories:
            categories.add("其他")

        return list(categories)

    def get_category_priority(self, category: str) -> int:
        """
        获取失败类型的优先级。

        优先级从高到低：
        1. 红线 (最高)
        2. OOC
        3. 物理幻觉
        4. 关系
        5. 文风
        6. 其他 (最低)

        Args:
            category: 失败类型

        Returns:
            int: 优先级（数字越小优先级越高）
        """
        priority_map = {
            "红线": 1,
            "OOC": 2,
            "物理幻觉": 3,
            "关系": 4,
            "文风": 5,
            "其他": 6,
        }
        return priority_map.get(category, 6)

    def should_stop_retrying(
        self,
        categories: List[str],
        attempts: int,
        max_attempts: int,
    ) -> bool:
        """
        判断是否应该停止重试。

        规则：
        - 达到最大尝试次数
        - 连续多次相同失败类型

        Args:
            categories: 失败类型列表
            attempts: 当前尝试次数
            max_attempts: 最大尝试次数

        Returns:
            bool: 是否应该停止
        """
        if attempts >= max_attempts:
            return True

        # 如果有红线问题，优先处理
        if "红线" in categories:
            return True

        return False
