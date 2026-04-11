"""
质量检查模块 - 提供生成质量验证和修复功能。

职责：
- 执行微观审阅（Micro Review）
- 检测生成文本的异常
- 提供失败原因分析

质量检查类型：
- MicroReviewer: 微观审阅，检查 OOC、物理幻觉等问题
- QuickQC: 快速质检，检测长度和结构异常
- FailAnalyzer: 失败分析，归类失败原因

使用方式：
    from backend.services.workflows.drafting_core.quality import QualityChecker

    checker = QualityChecker(config)
    is_valid, reason = await checker.check(chunk_text, context)
"""

from backend.services.workflows.drafting_core.quality.quality_checker import QualityChecker
from backend.services.workflows.drafting_core.quality.micro_reviewer import MicroReviewer
from backend.services.workflows.drafting_core.quality.fail_analyzer import FailAnalyzer

__all__ = [
    "QualityChecker",
    "MicroReviewer",
    "FailAnalyzer",
]
