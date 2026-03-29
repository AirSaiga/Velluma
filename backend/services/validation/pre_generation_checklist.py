# Velluma - AI Novel Writing Assistant
# 生成前检查清单模块

"""
生成前检查清单 - 章节生成前的预检查。

职责：
- 在章节生成前检查必要条件
- 验证世界观、角色、关系等设置
- 确保生成环境就绪

业务场景：
- 章节生成前的基本检查
- 发现可能导致生成失败的问题
- 提供明确的错误提示

主要功能：
- 设定完整性检查
- 角色有效性检查
- 上下文准备检查
- 伏笔状态检查

依赖项：
- backend.models: 数据模型
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class CheckSeverity(str, Enum):
    """检查结果严重程度"""
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    OK = "ok"


class CheckCategory(str, Enum):
    """检查类别"""
    SETTING = "setting"
    CHARACTER = "character"
    RELATIONSHIP = "relationship"
    CHAPTER = "chapter"
    FORESHADOWING = "foreshadowing"
    WORLD_STATE = "world_state"
    CONTEXT = "context"


@dataclass
class CheckResult:
    """单项检查结果"""
    category: CheckCategory
    check_name: str
    severity: CheckSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    auto_fixable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "check_name": self.check_name,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
        }


class PreGenerationReport(BaseModel):
    """生成前检查报告"""
    chapter_id: str = ""
    passed: bool = True
    results: List[Dict[str, Any]] = Field(default_factory=list)
    fatal_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    blocking_issues: List[str] = Field(default_factory=list)

    def add_result(self, result: CheckResult) -> None:
        self.results.append(result.to_dict())
        if result.severity == CheckSeverity.FATAL:
            self.fatal_count += 1
            self.blocking_issues.append(result.message)
        elif result.severity == CheckSeverity.ERROR:
            self.error_count += 1
        elif result.severity == CheckSeverity.WARNING:
            self.warning_count += 1

    def can_proceed(self) -> bool:
        return self.fatal_count == 0


class PreGenerationChecklist:
    """生成前检查清单执行器"""

    def run_all_checks(self, context: Dict[str, Any]) -> PreGenerationReport:
        report = PreGenerationReport()
        
        # 检查书籍
        book = context.get("book")
        if not book:
            report.add_result(CheckResult(
                category=CheckCategory.SETTING,
                check_name="book_exists",
                severity=CheckSeverity.FATAL,
                message="书籍信息不存在",
            ))
            report.passed = False
            return report

        # 检查章节
        chapter = context.get("chapter")
        if chapter:
            outline = getattr(chapter, "outline_text", "") or ""
            if not outline:
                report.add_result(CheckResult(
                    category=CheckCategory.CHAPTER,
                    check_name="outline_exists",
                    severity=CheckSeverity.ERROR,
                    message="章节大纲为空",
                ))
            else:
                report.add_result(CheckResult(
                    category=CheckCategory.CHAPTER,
                    check_name="outline_exists",
                    severity=CheckSeverity.OK,
                    message=f"章节大纲存在 ({len(outline)} 字)",
                ))

        # 检查角色
        entities = context.get("entities", [])
        if not entities:
            report.add_result(CheckResult(
                category=CheckCategory.CHARACTER,
                check_name="characters_exist",
                severity=CheckSeverity.WARNING,
                message="未指定出场角色",
            ))
        else:
            # 检查角色状态
            for entity in entities:
                char = getattr(entity, "character", None)
                if char:
                    dynamic_state = getattr(char, "dynamic_state", "") or ""
                    if "无意识" in dynamic_state or "昏迷" in dynamic_state:
                        report.add_result(CheckResult(
                            category=CheckCategory.CHARACTER,
                            check_name="character_state",
                            severity=CheckSeverity.WARNING,
                            message=f"角色【{getattr(char, 'name', '')}】处于无意识状态",
                        ))

        # 检查伏笔
        open_hooks = context.get("open_hooks", [])
        if len(open_hooks) > 10:
            report.add_result(CheckResult(
                category=CheckCategory.FORESHADOWING,
                check_name="hook_count",
                severity=CheckSeverity.WARNING,
                message=f"开放伏笔过多 ({len(open_hooks)})",
            ))

        # 检查上一章状态
        previous_snapshot = context.get("previous_world_snapshot")
        if not previous_snapshot:
            chapter_num = getattr(chapter, "chapter_number", 1) if chapter else 1
            if chapter_num > 1:
                report.add_result(CheckResult(
                    category=CheckCategory.WORLD_STATE,
                    check_name="previous_snapshot",
                    severity=CheckSeverity.WARNING,
                    message="上一章世界状态快照不存在",
                ))

        report.passed = report.can_proceed()
        return report


def run_pre_generation_checks(context: Dict[str, Any]) -> PreGenerationReport:
    """便捷函数：执行生成前检查"""
    checklist = PreGenerationChecklist()
    return checklist.run_all_checks(context)