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

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from dataclasses import dataclass


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    SUGGESTION = "suggestion"


class IssueCategory(str, Enum):
    PLOT_HOLE = "plot_hole"
    CHARACTER_OOC = "character_ooc"
    RELATIONSHIP_ERROR = "relationship_error"
    CONTINUITY_ERROR = "continuity_error"
    PACING_ISSUE = "pacing_issue"
    STYLE_ISSUE = "style_issue"
    FORESHADOWING_MISS = "foreshadowing_miss"
    WORLD_BUILDING_ERROR = "world_building_error"


class RepairStrategy(str, Enum):
    LOCAL_REPAIR = "local_repair"
    SECTION_REWRITE = "section_rewrite"
    FULL_CHAPTER_REWRITE = "full_chapter_rewrite"
    MANUAL_REVIEW = "manual_review"


@dataclass
class ReviewIssue:
    category: IssueCategory
    severity: IssueSeverity
    location: str
    description: str
    original_text: str
    suggested_fix: Optional[str] = None
    auto_fixable: bool = False
    fix_strategy: RepairStrategy = RepairStrategy.LOCAL_REPAIR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "location": self.location,
            "description": self.description,
            "original_text": self.original_text[:200],
            "suggested_fix": self.suggested_fix,
            "auto_fixable": self.auto_fixable,
            "fix_strategy": self.fix_strategy.value,
        }


class ReviewReport(BaseModel):
    chapter_id: str = ""
    overall_score: float = 0.0
    passed: bool = False
    issues: List[Dict[str, Any]] = []
    critical_count: int = 0
    major_count: int = 0
    minor_count: int = 0
    repair_recommendation: RepairStrategy = RepairStrategy.LOCAL_REPAIR
    summary: str = ""

    def add_issue(self, issue: ReviewIssue) -> None:
        self.issues.append(issue.to_dict())
        if issue.severity == IssueSeverity.CRITICAL:
            self.critical_count += 1
        elif issue.severity == IssueSeverity.MAJOR:
            self.major_count += 1
        elif issue.severity == IssueSeverity.MINOR:
            self.minor_count += 1

    def determine_repair_strategy(self) -> None:
        if self.critical_count >= 3:
            self.repair_recommendation = RepairStrategy.FULL_CHAPTER_REWRITE
        elif self.critical_count >= 1 or self.major_count >= 5:
            self.repair_recommendation = RepairStrategy.SECTION_REWRITE
        elif self.major_count >= 2:
            self.repair_recommendation = RepairStrategy.LOCAL_REPAIR
        else:
            self.repair_recommendation = RepairStrategy.MANUAL_REVIEW
