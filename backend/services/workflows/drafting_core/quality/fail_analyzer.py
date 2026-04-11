"""
失败分析器 - 分析失败原因并提供修复建议。

职责：
- 根据失败类型推断修复方向
- 生成针对性的修复建议
- 辅助重试决策

失败类型及建议：
- 红线: 重新生成，避免特定内容
- 物理幻觉: 修正空间/位置描述
- OOC: 强调角色设定
- 关系: 调整关系状态表达
- 文风: 改进文笔风格

使用方式：
    analyzer = FailAnalyzer()
    suggestions = analyzer.suggest_fixes(
        fail_categories=["文风"],
        fail_reason="文本过于平淡",
    )
"""

from typing import Dict, List


class FailAnalyzer:
    """
    失败分析器。

    职责：
    - 分析失败原因推断问题本质
    - 根据失败类型生成修复建议
    - 提供失败归因用于统计

    设计决策：
    - 使用规则映射而非 LLM 进行快速分析
    - 失败建议与提示词模板配合使用
    - 支持多类别失败的综合建议
    """

    # 失败类型 → 失败原因关键词映射
    FAIL_REASON_PATTERNS: Dict[str, List[str]] = {
        "红线": [
            "禁忌", "禁止", "红线", "违规", "不允许",
            "red line", "taboo", "forbidden",
        ],
        "物理幻觉": [
            "物理", "空间", "位置", "幻觉", "瞬移", "矛盾",
            "physical", "spatial", "inconsistent", "teleport",
        ],
        "OOC": [
            "ooc", "角色", "设定", "性格", "行为", "偏离",
            "out of character", "personality", "behavior",
        ],
        "关系": [
            "关系", "态度", "信任", "敌对", "友好", "情感",
            "relation", "attitude", "trust", "affection",
        ],
        "文风": [
            "文风", "白开水", "ai味", "平淡", "机械", "套路", "模板",
            "style", "boring", "robotic", "generic", "template",
        ],
    }

    # 失败类型 → 修复建议模板
    FIX_SUGGESTION_TEMPLATES: Dict[str, str] = {
        "红线": "请严格遵守内容禁区，重新生成符合规范的内容。",
        "物理幻觉": "请检查并修正空间位置描述，确保物理状态逻辑连贯。",
        "OOC": "请严格遵循角色设定，保持角色行为和语言风格一致。",
        "关系": "请调整关系状态表达，确保符合当前关系动态。",
        "文风": "请改进文笔表达，增加情感色彩和叙事张力。",
        "其他": "请优化内容质量，提升叙事表现力。",
    }

    def __init__(self):
        """初始化失败分析器"""
        pass

    def analyze(self, fail_reason: str, failed_checks: List[str]) -> Dict[str, any]:
        """
        分析失败原因。

        Args:
            fail_reason: 失败原因描述
            failed_checks: 检查项列表

        Returns:
            Dict: 分析结果，包含：
                - primary_category: 主要失败类型
                - all_categories: 所有失败类型
                - severity: 严重程度 (high/medium/low)
                - suggestion: 修复建议
        """
        # 推断失败类型
        categories = self._infer_categories(fail_reason, failed_checks)

        # 获取主要类别
        primary_category = categories[0] if categories else "其他"

        # 评估严重程度
        severity = self._assess_severity(primary_category, fail_reason)

        # 生成修复建议
        suggestion = self.suggest_fixes(categories, fail_reason)

        return {
            "primary_category": primary_category,
            "all_categories": categories,
            "severity": severity,
            "suggestion": suggestion,
            "fail_reason": fail_reason,
        }

    def suggest_fixes(
        self,
        fail_categories: List[str],
        fail_reason: str,
    ) -> List[str]:
        """
        生成修复建议列表。

        Args:
            fail_categories: 失败类型列表
            fail_reason: 失败原因

        Returns:
            List[str]: 修复建议列表
        """
        suggestions = []

        for category in fail_categories:
            if category in self.FIX_SUGGESTION_TEMPLATES:
                suggestions.append(self.FIX_SUGGESTION_TEMPLATES[category])

        # 如果没有匹配的建议，使用通用建议
        if not suggestions:
            suggestions.append(self.FIX_SUGGESTION_TEMPLATES["其他"])

        return suggestions

    def _infer_categories(
        self,
        fail_reason: str,
        failed_checks: List[str],
    ) -> List[str]:
        """
        从失败原因推断失败类型。

        Args:
            fail_reason: 失败原因
            failed_checks: 检查项列表

        Returns:
            List[str]: 失败类型列表（按优先级排序）
        """
        categories = set()
        reason_lower = fail_reason.lower()
        checks_lower = [c.lower() for c in failed_checks]

        # 从检查项推断
        for check in checks_lower:
            for category, keywords in self.FAIL_REASON_PATTERNS.items():
                if any(kw in check for kw in keywords):
                    categories.add(category)

        # 从失败原因推断
        for category, keywords in self.FAIL_REASON_PATTERNS.items():
            if any(kw in reason_lower for kw in keywords):
                categories.add(category)

        # 按优先级排序
        priority_order = ["红线", "OOC", "物理幻觉", "关系", "文风", "其他"]
        sorted_categories = sorted(
            categories,
            key=lambda c: priority_order.index(c) if c in priority_order else len(priority_order)
        )

        return sorted_categories

    def _assess_severity(
        self,
        primary_category: str,
        fail_reason: str,
    ) -> str:
        """
        评估失败严重程度。

        Args:
            primary_category: 主要失败类型
            fail_reason: 失败原因

        Returns:
            str: 严重程度 (high/medium/low)
        """
        severity_map = {
            "红线": "high",
            "OOC": "high",
            "物理幻觉": "medium",
            "关系": "medium",
            "文风": "low",
            "其他": "low",
        }

        # 检查失败原因中是否有强化的词
        severity_boost = False
        intensify_words = ["严重", "完全", "彻底", "明显", "严重", "serious", "completely"]
        if any(word in fail_reason for word in intensify_words):
            severity_boost = True

        base_severity = severity_map.get(primary_category, "low")

        if severity_boost and base_severity == "low":
            return "medium"
        elif severity_boost and base_severity == "medium":
            return "high"

        return base_severity

    def get_category_priority(self, category: str) -> int:
        """
        获取失败类型的优先级。

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
