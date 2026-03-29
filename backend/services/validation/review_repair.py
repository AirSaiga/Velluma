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
审阅-修复循环模块。

职责：协调章节审阅与修复的迭代循环。

子模块：
- review_repair_types: 枚举和数据类型定义
- chapter_reviewer: 章节审阅器
- chapter_repairer: 章节修复器
"""

import logging
from typing import Callable, Optional, Tuple

from backend.services.validation.review_repair_types import (
    IssueSeverity,
    IssueCategory,
    RepairStrategy,
    ReviewIssue,
    ReviewReport,
)
from backend.services.validation.chapter_reviewer import ChapterReviewer
from backend.services.validation.chapter_repairer import ChapterRepairer


logger = logging.getLogger(__name__)


class ReviewRepairCycle:
    MAX_ITERATIONS = 3
    PASS_THRESHOLD = 70.0

    def __init__(self, llm_client: Callable):
        self.reviewer = ChapterReviewer(llm_client)
        self.repairer = ChapterRepairer(llm_client)

    async def execute(
        self,
        chapter_text: str,
        chapter_outline: str,
        characters: list,
        relationships: list,
        open_hooks: list,
        previous_summary: Optional[str] = None,
    ) -> Tuple[str, ReviewReport]:
        current_text = chapter_text
        report = None

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            logger.info(f"审阅-修复循环 第 {iteration} 轮")

            report = await self.reviewer.review(
                chapter_text=current_text,
                chapter_outline=chapter_outline,
                characters=characters,
                relationships=relationships,
                open_hooks=open_hooks,
                previous_summary=previous_summary,
            )

            if report.passed or report.overall_score >= self.PASS_THRESHOLD:
                logger.info(
                    f"审阅通过或得分达标: "
                    f"passed={report.passed}, "
                    f"score={report.overall_score:.1f}"
                )
                break

            if report.repair_recommendation == RepairStrategy.FULL_CHAPTER_REWRITE:
                logger.info("建议整章重写，终止修复循环")
                break

            try:
                current_text = await self.repairer.repair(
                    chapter_text=current_text,
                    report=report,
                )
            except Exception as e:
                logger.error(f"修复失败: {e}")
                break

        return current_text, report
