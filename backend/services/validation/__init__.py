# Velluma - AI Novel Writing Assistant
# 验证模块导出

from backend.services.validation.pre_generation_checklist import (
    PreGenerationChecklist,
    PreGenerationReport,
    CheckResult,
    CheckSeverity,
    CheckCategory,
    run_pre_generation_checks,
)

from backend.services.validation.review_repair import (
    ChapterReviewer,
    ChapterRepairer,
    ReviewRepairCycle,
    ReviewReport,
    ReviewIssue,
    IssueSeverity,
    IssueCategory,
    RepairStrategy,
)

__all__ = [
    # 生成前检查
    "PreGenerationChecklist",
    "PreGenerationReport",
    "CheckResult",
    "CheckSeverity",
    "CheckCategory",
    "run_pre_generation_checks",
    
    # 审阅修复
    "ChapterReviewer",
    "ChapterRepairer",
    "ReviewRepairCycle",
    "ReviewReport",
    "ReviewIssue",
    "IssueSeverity",
    "IssueCategory",
    "RepairStrategy",
]
