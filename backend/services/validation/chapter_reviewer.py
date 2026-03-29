import logging
from typing import Any, Callable, Dict, List, Optional

from backend.services.validation.review_repair_types import (
    IssueCategory,
    IssueSeverity,
    RepairStrategy,
    ReviewIssue,
    ReviewReport,
)


logger = logging.getLogger(__name__)


class ChapterReviewer:

    def __init__(self, llm_client: Callable):
        self.llm_client = llm_client

    async def review(
        self,
        chapter_text: str,
        chapter_outline: str,
        characters: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        open_hooks: List[Dict[str, Any]],
        previous_summary: Optional[str] = None,
    ) -> ReviewReport:
        report = ReviewReport()

        character_issues = self._review_character_consistency(chapter_text, characters)
        for issue in character_issues:
            report.add_issue(issue)

        relationship_issues = self._review_relationship_consistency(chapter_text, relationships)
        for issue in relationship_issues:
            report.add_issue(issue)

        plot_issues = self._review_plot_consistency(chapter_text, chapter_outline)
        for issue in plot_issues:
            report.add_issue(issue)

        foreshadowing_issues = self._review_foreshadowing(chapter_text, open_hooks)
        for issue in foreshadowing_issues:
            report.add_issue(issue)

        report.overall_score = self._calculate_score(report)
        report.passed = report.overall_score >= 70 and report.critical_count == 0
        report.determine_repair_strategy()
        report.summary = self._generate_summary(report)

        logger.info(
            f"审阅完成: 得分={report.overall_score:.1f}, "
            f"通过={report.passed}, "
            f"问题数={len(report.issues)}"
        )

        return report

    def _review_character_consistency(
        self,
        chapter_text: str,
        characters: List[Dict[str, Any]],
    ) -> List[ReviewIssue]:
        issues = []
        for char in characters:
            name = char.get("name", "")
            dynamic_state = char.get("dynamic_state", "")
            if not name or not dynamic_state:
                continue
            if "无意识" in dynamic_state or "昏迷" in dynamic_state:
                import re
                dialog_pattern = rf'{name}说[：:」』]|{name}道[：:」』]|"{name}[^"]*说"'
                if re.search(dialog_pattern, chapter_text):
                    issues.append(ReviewIssue(
                        category=IssueCategory.CHARACTER_OOC,
                        severity=IssueSeverity.MAJOR,
                        location=f"角色: {name}",
                        description=f"{name}在无意识/昏迷状态下出现对话，属于OOC",
                        original_text=dynamic_state[:200],
                        suggested_fix=f"删除或修正{name}在无意识状态下的对话",
                        auto_fixable=True,
                        fix_strategy=RepairStrategy.LOCAL_REPAIR,
                    ))
        return issues

    def _review_relationship_consistency(
        self,
        chapter_text: str,
        relationships: List[Dict[str, Any]],
    ) -> List[ReviewIssue]:
        issues = []
        for rel in relationships:
            source_name = rel.get("source_name", "")
            target_name = rel.get("target_name", "")
            affinity = rel.get("affinity_score", 0)
            if not source_name or not target_name:
                continue
            if affinity < -40:
                friendly_patterns = [
                    f"{source_name}对{target_name}微笑",
                    f"{source_name}拍了拍{target_name}",
                    f"{source_name}和{target_name}相视一笑",
                ]
                for pattern in friendly_patterns:
                    if pattern in chapter_text:
                        issues.append(ReviewIssue(
                            category=IssueCategory.RELATIONSHIP_ERROR,
                            severity=IssueSeverity.MINOR,
                            location=f"关系: {source_name} ↔ {target_name}",
                            description=f"{source_name}和{target_name}关系敌对(affinity={affinity})，但出现友好互动",
                            original_text=pattern,
                            suggested_fix=f"调整互动方式以符合敌对关系",
                            auto_fixable=False,
                            fix_strategy=RepairStrategy.LOCAL_REPAIR,
                        ))
        return issues

    def _review_plot_consistency(
        self,
        chapter_text: str,
        chapter_outline: str,
    ) -> List[ReviewIssue]:
        issues = []
        key_events = self._extract_key_events(chapter_outline)
        for event in key_events:
            if len(event) > 4 and event not in chapter_text:
                import re
                event_words = list(event)
                found = False
                for i in range(len(event_words) - 2):
                    trigram = "".join(event_words[i:i + 3])
                    if trigram in chapter_text:
                        found = True
                        break
                if not found:
                    issues.append(ReviewIssue(
                        category=IssueCategory.PLOT_HOLE,
                        severity=IssueSeverity.MAJOR,
                        location="剧情检查",
                        description=f"大纲中的关键事件未在正文中体现: {event[:50]}",
                        original_text=event[:200],
                        suggested_fix=f"在正文中补充该关键事件的描写",
                        auto_fixable=False,
                        fix_strategy=RepairStrategy.SECTION_REWRITE,
                    ))
        return issues

    def _review_foreshadowing(
        self,
        chapter_text: str,
        open_hooks: List[Dict[str, Any]],
    ) -> List[ReviewIssue]:
        issues = []
        for hook in open_hooks:
            content = hook.get("content", "")
            if not content:
                continue
            import re
            key_phrases = re.findall(r"[\u4e00-\u9fff]{2,6}", content)
            mentioned = any(phrase in chapter_text for phrase in key_phrases[:5])
            if not mentioned and len(content) > 10:
                issues.append(ReviewIssue(
                    category=IssueCategory.FORESHADOWING_MISS,
                    severity=IssueSeverity.MINOR,
                    location="伏笔检查",
                    description=f"开放伏笔未在本章中有所呼应: {content[:80]}",
                    original_text=content[:200],
                    suggested_fix="考虑在适当位置呼应此伏笔",
                    auto_fixable=False,
                    fix_strategy=RepairStrategy.MANUAL_REVIEW,
                ))
        return issues

    def _extract_key_events(self, outline: str) -> List[str]:
        import re
        events = re.split(r"[。！？\n]", outline)
        return [e.strip() for e in events if len(e.strip()) > 4]

    def _calculate_score(self, report: ReviewReport) -> float:
        score = 100.0
        score -= report.critical_count * 20
        score -= report.major_count * 10
        score -= report.minor_count * 2
        return max(0, score)

    def _generate_summary(self, report: ReviewReport) -> str:
        if report.passed:
            return f"审阅通过，得分 {report.overall_score:.1f}。共发现 {len(report.issues)} 个问题，其中 {report.critical_count} 个严重、{report.major_count} 个重要。"
        return f"审阅未通过，得分 {report.overall_score:.1f}。共发现 {len(report.issues)} 个问题，其中 {report.critical_count} 个严重、{report.major_count} 个重要。建议修复策略: {report.repair_recommendation.value}。"
