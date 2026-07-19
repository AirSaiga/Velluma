# Velluma - AI Novel Writing Assistant
# 验证模块导出

"""
章节验证模块 - 统一导出入口。

职责：
- 统一导出章节审阅和修复相关类
- 提供审阅-修复循环能力

子模块：
- pre_generation_checklist: 生成前检查清单
- chapter_reviewer: 章节审阅器
- chapter_repairer: 章节修复器
- review_repair: 审阅修复类型定义

业务场景：
- 章节生成后的质量检查
- 审阅-修复循环
- 生成前预检查

依赖项：
- backend.services.llm: LLM 调用接口
"""

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

# CP3.1b 新增：代码级审计层
from backend.services.validation.code_auditors import (
    CodeAuditResult,
    CodeAuditPipeline,
    BaseAuditor,
    ClichéAuditor,
    RhythmAuditor,
    DialogueAuditor,
    EntityAuditor,
    RedLineAuditor,
    ContinuityAuditor,
    WordCountAuditor,
)

# CP3.1c 新增：LLM 级审计层
from backend.services.validation.llm_auditor import (
    LLMAuditResult,
    LLMAuditor,
    merge_audit_results,
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

    # CP3.1b 代码级审计层
    "CodeAuditResult",
    "CodeAuditPipeline",
    "BaseAuditor",
    "ClichéAuditor",
    "RhythmAuditor",
    "DialogueAuditor",
    "EntityAuditor",
    "RedLineAuditor",
    "ContinuityAuditor",
    "WordCountAuditor",

    # CP3.1c LLM 级审计层
    "LLMAuditResult",
    "LLMAuditor",
    "merge_audit_results",
]
