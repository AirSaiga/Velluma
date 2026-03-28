# Velluma - AI Novel Writing Assistant
# 审阅与修复闭环系统

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
import logging
import json
import re

logger = logging.getLogger(__name__)


class IssueSeverity(str, Enum):
    """问题严重程度"""
    CRITICAL = "critical"  # 致命问题，必须修复
    MAJOR = "major"        # 重要问题，建议修复
    MINOR = "minor"        # 次要问题，可选修复
    SUGGESTION = "suggestion"  # 建议改进


class IssueCategory(str, Enum):
    """问题类别"""
    PLOT_HOLE = "plot_hole"           # 剧情漏洞
    CHARACTER_OOC = "character_ooc"   # 角色OOC
    RELATIONSHIP_ERROR = "relationship_error"  # 关系错误
    CONTINUITY_ERROR = "continuity_error"  # 连续性错误
    PACING_ISSUE = "pacing_issue"     # 节奏问题
    STYLE_ISSUE = "style_issue"       # 风格问题
    FORESHADOWING_MISS = "foreshadowing_miss"  # 伏笔遗漏
    WORLD_BUILDING_ERROR = "world_building_error"  # 世界观错误


class RepairStrategy(str, Enum):
    """修复策略"""
    LOCAL_REPAIR = "local_repair"      # 局部修复
    SECTION_REWRITE = "section_rewrite"  # 段落重写
    FULL_CHAPTER_REWRITE = "full_chapter_rewrite"  # 整章重写
    MANUAL_REVIEW = "manual_review"    # 人工审核


@dataclass
class ReviewIssue:
    """审阅问题"""
    category: IssueCategory
    severity: IssueSeverity
    location: str  # 问题位置（段落/句子引用）
    description: str  # 问题描述
    original_text: str  # 原文
    suggested_fix: Optional[str] = None  # 建议修复
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
    """审阅报告"""
    chapter_id: str = ""
    overall_score: float = 0.0
    passed: bool = False
    issues: List[Dict[str, Any]] = Field(default_factory=list)
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

    def determine_repair_strategy(self) -> RepairStrategy:
        """确定修复策略"""
        if self.critical_count >= 3:
            return RepairStrategy.FULL_CHAPTER_REWRITE
        elif self.critical_count >= 1 or self.major_count >= 5:
            return RepairStrategy.SECTION_REWRITE
        elif self.major_count >= 2:
            return RepairStrategy.LOCAL_REPAIR
        else:
            return RepairStrategy.MANUAL_REVIEW


class ChapterReviewer:
    """
    章节审阅器
    
    职责：
    - 对生成的章节进行多维度审阅
    - 识别问题并分级
    - 提供修复建议
    """
    
    def __init__(self, llm_client: Callable):
        self.llm_client = llm_client
    
    async def review(
        self,
        chapter_text: str,
        chapter_outline: str,
        characters: List[Dict],
        relationships: List[Dict],
        open_hooks: List[Dict],
        previous_summary: Optional[str] = None,
    ) -> ReviewReport:
        """
        执行章节审阅
        
        Args:
            chapter_text: 章节正文
            chapter_outline: 章节大纲
            characters: 出场角色列表
            relationships: 关系列表
            open_hooks: 开放伏笔列表
            previous_summary: 上一章摘要
        
        Returns:
            ReviewReport: 审阅报告
        """
        report = ReviewReport()
        
        # 1. 角色一致性审阅
        await self._review_character_consistency(
            chapter_text, characters, report
        )
        
        # 2. 关系一致性审阅
        await self._review_relationship_consistency(
            chapter_text, relationships, report
        )
        
        # 3. 剧情连贯性审阅
        await self._review_plot_consistency(
            chapter_text, chapter_outline, previous_summary, report
        )
        
        # 4. 伏笔处理审阅
        await self._review_foreshadowing(
            chapter_text, open_hooks, report
        )
        
        # 计算总体得分
        report.overall_score = self._calculate_score(report)
        report.passed = report.critical_count == 0 and report.major_count < 3
        report.repair_recommendation = report.determine_repair_strategy()
        report.summary = self._generate_summary(report)
        
        return report
    
    async def _review_character_consistency(
        self,
        text: str,
        characters: List[Dict],
        report: ReviewReport,
    ) -> None:
        """审阅角色一致性"""
        for char in characters:
            name = char.get("name", "")
            if not name:
                continue
            
            # 检查角色是否在文本中出现
            if name not in text:
                continue
            
            # 检查角色状态是否被尊重
            dynamic_state = char.get("dynamic_state", "") or ""
            
            # 检查无意识角色是否有主动行为
            if "无意识" in dynamic_state or "昏迷" in dynamic_state:
                # 简化检测：检查是否有该角色的对话
                dialog_pattern = rf"[「「\"]([^\"]*{name}[^\"]*)[」」\"]"
                matches = re.findall(dialog_pattern, text)
                if matches:
                    report.add_issue(ReviewIssue(
                        category=IssueCategory.CHARACTER_OOC,
                        severity=IssueSeverity.CRITICAL,
                        location=f"角色【{name}】对话",
                        description=f"无意识角色【{name}】有对话，违反角色状态",
                        original_text=matches[0][:100],
                        auto_fixable=True,
                        fix_strategy=RepairStrategy.LOCAL_REPAIR,
                    ))
    
    async def _review_relationship_consistency(
        self,
        text: str,
        relationships: List[Dict],
        report: ReviewReport,
    ) -> None:
        """审阅关系一致性"""
        for rel in relationships:
            source = rel.get("source_name", "")
            target = rel.get("target_name", "")
            affinity = rel.get("affinity_score", 0) or 0
            
            if not source or not target:
                continue
            
            # 检查敌对关系的处理
            if affinity < -40:
                # 检查是否有不符合敌对关系的友好互动
                friendly_patterns = [
                    rf"{source}.*微笑.*{target}",
                    rf"{source}.*拥抱.*{target}",
                    rf"{source}.*信任.*{target}",
                ]
                for pattern in friendly_patterns:
                    if re.search(pattern, text):
                        report.add_issue(ReviewIssue(
                            category=IssueCategory.RELATIONSHIP_ERROR,
                            severity=IssueSeverity.MAJOR,
                            location=f"{source}与{target}互动",
                            description=f"敌对关系({affinity})出现友好互动",
                            original_text="",
                            auto_fixable=True,
                            fix_strategy=RepairStrategy.LOCAL_REPAIR,
                        ))
    
    async def _review_plot_consistency(
        self,
        text: str,
        outline: str,
        previous_summary: Optional[str],
        report: ReviewReport,
    ) -> None:
        """审阅剧情连贯性"""
        # 检查大纲核心事件是否被覆盖
        if outline:
            # 提取大纲关键事件
            outline_events = self._extract_key_events(outline)
            
            for event in outline_events:
                # 简化检测：检查关键词是否出现
                keywords = event.split()[:5]  # 取前5个词
                found = any(kw in text for kw in keywords if len(kw) > 2)
                
                if not found:
                    report.add_issue(ReviewIssue(
                        category=IssueCategory.PLOT_HOLE,
                        severity=IssueSeverity.MAJOR,
                        location="大纲事件",
                        description=f"大纲事件未体现：{event[:50]}",
                        original_text="",
                        auto_fixable=False,
                        fix_strategy=RepairStrategy.SECTION_REWRITE,
                    ))
    
    async def _review_foreshadowing(
        self,
        text: str,
        open_hooks: List[Dict],
        report: ReviewReport,
    ) -> None:
        """审阅伏笔处理"""
        for hook in open_hooks:
            content = hook.get("content", "") or ""
            hook_id = hook.get("hook_id", "")
            
            if not content:
                continue
            
            # 检查伏笔是否被提及
            keywords = content.split()[:3]
            mentioned = any(kw in text for kw in keywords if len(kw) > 2)
            
            # 这里只是提示，不作为问题
            if not mentioned:
                report.add_issue(ReviewIssue(
                    category=IssueCategory.FORESHADOWING_MISS,
                    severity=IssueSeverity.MINOR,
                    location=f"伏笔【{hook_id}】",
                    description=f"开放伏笔未被提及：{content[:30]}",
                    original_text="",
                    auto_fixable=False,
                    fix_strategy=RepairStrategy.LOCAL_REPAIR,
                ))
    
    def _extract_key_events(self, outline: str) -> List[str]:
        """提取大纲关键事件"""
        # 简化实现：按句子分割
        sentences = re.split(r'[。！？\n]', outline)
        return [s.strip() for s in sentences if len(s.strip()) > 10]
    
    def _calculate_score(self, report: ReviewReport) -> float:
        """计算总体得分"""
        base_score = 100.0
        base_score -= report.critical_count * 20
        base_score -= report.major_count * 10
        base_score -= report.minor_count * 2
        return max(0, base_score)
    
    def _generate_summary(self, report: ReviewReport) -> str:
        """生成摘要"""
        if report.passed:
            return f"审阅通过，得分 {report.overall_score:.1f}，{report.major_count} 个需关注问题"
        return f"审阅未通过，{report.critical_count} 个致命问题，{report.major_count} 个重要问题"


class ChapterRepairer:
    """
    章节修复器
    
    职责：
    - 根据审阅报告执行修复
    - 支持局部修复、段落重写
    - 判断是否需要整章重写
    """
    
    def __init__(self, llm_client: Callable):
        self.llm_client = llm_client
    
    async def repair(
        self,
        chapter_text: str,
        report: ReviewReport,
        max_attempts: int = 2,
    ) -> Tuple[str, bool]:
        """
        执行修复
        
        Args:
            chapter_text: 原始章节文本
            report: 审阅报告
            max_attempts: 最大修复尝试次数
        
        Returns:
            Tuple[str, bool]: (修复后文本, 是否成功)
        """
        strategy = report.repair_recommendation
        
        if strategy == RepairStrategy.FULL_CHAPTER_REWRITE:
            # 整章重写需要外部处理
            logger.warning(
                f"[ChapterRepairer] 建议整章重写 "
                f"({report.critical_count} critical issues)"
            )
            return chapter_text, False
        
        if strategy == RepairStrategy.MANUAL_REVIEW:
            # 无需自动修复
            return chapter_text, True
        
        # 执行局部修复
        repaired_text = chapter_text
        successful_repairs = 0
        
        for issue_data in report.issues:
            issue = self._dict_to_issue(issue_data)
            
            if not issue.auto_fixable:
                continue
            
            if issue.severity not in [IssueSeverity.CRITICAL, IssueSeverity.MAJOR]:
                continue
            
            # 尝试修复
            try:
                repaired_text = await self._repair_single_issue(
                    repaired_text, issue
                )
                successful_repairs += 1
            except Exception as e:
                logger.error(f"[ChapterRepairer] 修复失败: {e}")
        
        logger.info(
            f"[ChapterRepairer] 修复完成: "
            f"{successful_repairs}/{len(report.issues)} 个问题已处理"
        )
        
        return repaired_text, successful_repairs > 0
    
    async def _repair_single_issue(
        self,
        text: str,
        issue: ReviewIssue,
    ) -> str:
        """修复单个问题"""
        # 根据问题类别执行不同的修复策略
        if issue.category == IssueCategory.CHARACTER_OOC:
            return await self._repair_ooc(text, issue)
        elif issue.category == IssueCategory.RELATIONSHIP_ERROR:
            return await self._repair_relationship(text, issue)
        else:
            return text
    
    async def _repair_ooc(self, text: str, issue: ReviewIssue) -> str:
        """修复角色 OOC 问题"""
        # 简化实现：移除有问题的对话
        original = issue.original_text
        if original and original in text:
            # 用省略号或描述替代
            text = text.replace(original, "……")
        return text
    
    async def _repair_relationship(self, text: str, issue: ReviewIssue) -> str:
        """修复关系错误问题"""
        # 简化实现：这里需要更复杂的逻辑
        return text
    
    def _dict_to_issue(self, data: Dict[str, Any]) -> ReviewIssue:
        """将字典转换为 Issue 对象"""
        return ReviewIssue(
            category=IssueCategory(data.get("category", "plot_hole")),
            severity=IssueSeverity(data.get("severity", "minor")),
            location=data.get("location", ""),
            description=data.get("description", ""),
            original_text=data.get("original_text", ""),
            suggested_fix=data.get("suggested_fix"),
            auto_fixable=data.get("auto_fixable", False),
            fix_strategy=RepairStrategy(data.get("fix_strategy", "local_repair")),
        )


class ReviewRepairCycle:
    """
    审阅-修复闭环
    
    职责：
    - 协调审阅与修复的迭代
    - 控制最大迭代次数
    - 判断何时终止
    """
    
    MAX_ITERATIONS = 3
    PASS_THRESHOLD = 70.0
    
    def __init__(self, llm_client: Callable):
        self.reviewer = ChapterReviewer(llm_client)
        self.repairer = ChapterRepairer(llm_client)
    
    async def execute(
        self,
        chapter_text: str,
        chapter_outline: str,
        characters: List[Dict],
        relationships: List[Dict],
        open_hooks: List[Dict],
        previous_summary: Optional[str] = None,
        on_progress: Optional[Callable] = None,
    ) -> Tuple[str, ReviewReport]:
        """
        执行审阅-修复循环
        
        Args:
            chapter_text: 章节文本
            chapter_outline: 章节大纲
            characters: 角色列表
            relationships: 关系列表
            open_hooks: 开放伏笔
            previous_summary: 上一章摘要
            on_progress: 进度回调
        
        Returns:
            Tuple[str, ReviewReport]: (最终文本, 最终报告)
        """
        current_text = chapter_text
        final_report = None
        
        for iteration in range(1, self.MAX_ITERATIONS + 1):
            logger.info(f"[ReviewRepairCycle] 第 {iteration} 次审阅")
            
            # 审阅
            report = await self.reviewer.review(
                current_text,
                chapter_outline,
                characters,
                relationships,
                open_hooks,
                previous_summary,
            )
            
            if on_progress:
                await on_progress("REVIEWING", iteration, {
                    "score": report.overall_score,
                    "critical": report.critical_count,
                    "major": report.major_count,
                })
            
            # 检查是否通过
            if report.passed or report.overall_score >= self.PASS_THRESHOLD:
                logger.info(
                    f"[ReviewRepairCycle] 审阅通过 "
                    f"(score={report.overall_score:.1f})"
                )
                final_report = report
                break
            
            # 检查是否需要整章重写
            if report.repair_recommendation == RepairStrategy.FULL_CHAPTER_REWRITE:
                logger.warning(
                    "[ReviewRepairCycle] 建议整章重写，终止修复循环"
                )
                final_report = report
                break
            
            # 尝试修复
            repaired_text, success = await self.repairer.repair(
                current_text, report
            )
            
            if not success:
                logger.warning(
                    "[ReviewRepairCycle] 修复失败，终止循环"
                )
                final_report = report
                break
            
            current_text = repaired_text
            final_report = report
        
        if final_report is None:
            final_report = ReviewReport(
                passed=False,
                summary="审阅循环异常终止",
            )
        
        return current_text, final_report
