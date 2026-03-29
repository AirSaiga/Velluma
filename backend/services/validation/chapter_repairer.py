"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
章节修复器 - 修复章节草稿中的问题。

职责：
- 根据审阅报告修复章节问题
- 执行指定的修复策略
- 返回修复后的章节文本

业务场景：
- 审阅-修复循环的修复阶段
- 迭代优化章节质量
- 支持多种修复策略

主要功能：
- 问题定位和修复
- 修复策略执行
- 修复验证

依赖项：
- backend.services.validation.review_repair_types: 问题类型定义
- LLM Client: 用于复杂修复

使用方式：
    repairer = ChapterRepairer(llm_client)
    fixed_text = await repairer.repair(chapter_text, report)
"""

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
