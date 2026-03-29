import logging
from typing import Any, Callable, Dict, Optional

from backend.services.validation.review_repair_types import (
    IssueCategory,
    IssueSeverity,
    RepairStrategy,
    ReviewIssue,
    ReviewReport,
)


logger = logging.getLogger(__name__)


class ChapterRepairer:

    def __init__(self, llm_client: Callable):
        self.llm_client = llm_client

    async def repair(
        self,
        chapter_text: str,
        report: ReviewReport,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        current_text = chapter_text
        repaired_count = 0

        for issue_dict in report.issues:
            if not issue_dict.get("auto_fixable", False):
                continue
            severity = issue_dict.get("severity", "")
            if severity not in ("critical", "major"):
                continue

            issue = self._dict_to_issue(issue_dict)
            try:
                current_text = await self._repair_single_issue(current_text, issue)
                repaired_count += 1
            except Exception as e:
                logger.error(f"修复失败: {e}")

        logger.info(f"修复完成，共修复 {repaired_count} 个问题")
        return current_text

    async def _repair_single_issue(
        self,
        text: str,
        issue: ReviewIssue,
    ) -> str:
        if issue.category == IssueCategory.CHARACTER_OOC:
            return self._repair_ooc(text, issue)
        elif issue.category == IssueCategory.RELATIONSHIP_ERROR:
            return self._repair_relationship(text, issue)
        else:
            logger.warning(f"不支持自动修复的问题类型: {issue.category}")
            return text

    def _repair_ooc(self, text: str, issue: ReviewIssue) -> str:
        original = issue.original_text[:100]
        if original and original in text:
            return text.replace(original, "……")
        return text

    def _repair_relationship(self, text: str, issue: ReviewIssue) -> str:
        return text

    def _dict_to_issue(self, issue_dict: Dict[str, Any]) -> ReviewIssue:
        return ReviewIssue(
            category=IssueCategory(issue_dict.get("category", "plot_hole")),
            severity=IssueSeverity(issue_dict.get("severity", "minor")),
            location=issue_dict.get("location", ""),
            description=issue_dict.get("description", ""),
            original_text=issue_dict.get("original_text", ""),
            suggested_fix=issue_dict.get("suggested_fix"),
            auto_fixable=issue_dict.get("auto_fixable", False),
            fix_strategy=RepairStrategy(issue_dict.get("fix_strategy", "local_repair")),
        )
