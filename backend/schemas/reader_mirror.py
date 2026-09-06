# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Reader Mirror（读者状态镜像）数据模型（V4.2 路径 B 新建）。

职责：推断"读者现在脑子里在想什么"——期待、张力、信息差。

设计依据：
- 第 6 轮讨论：期待 ≠ 伏笔，期待是动态张力
- 第 7 轮修正：期待账本是仪表盘，不是方向盘（作者主权至上）
- 双层设计：显性作者声明层 + 推断读者状态层

核心约束：
- 所有字段都是"建议"，作者可无视
- 推断失败空值填充，不阻塞生成
- 与 Canon HOOK 节点双向同步（HOOK 是事实层，Expectation 是动态层）
"""

from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field


# ============================================================
# 枚举
# ============================================================

class ExpectationType(str, Enum):
    """期待类型（网文五大类）。"""
    POWER_REVEAL = "power_reveal"     # 主角实力揭示（如：兰星什么时候展露弦月巅峰）
    REVENGE = "revenge"               # 复仇/打脸（如：贵族什么时候被打脸）
    ROMANCE = "romance"               # 感情（如：男女主什么时候相认）
    MYSTERY = "mystery"               # 悬念（如：老人到底是谁）
    GROWTH = "growth"                 # 成长（如：主角什么时候升级）


class ExpectationStatus(str, Enum):
    """期待状态（动态）。"""
    SETUP = "setup"             # 刚埋下
    ACCUMULATING = "accumulating"  # 累积中（每章加张力）
    PAYOFF = "payoff"           # 已释放（爽点）
    SUBVERTED = "subverted"     # 被反转（作者故意不打脸）
    DROPPED = "dropped"         # 放弃


class ExpectationSource(str, Enum):
    """期待来源（双层账本的关键）。"""
    AUTHOR_DECLARED = "author_declared"      # 作者显式声明（最高权威）
    AUTO_INFERRED = "auto_inferred"          # 从已发布文本推断（建议）


# ============================================================
# 期待节点
# ============================================================

class Expectation(BaseModel):
    """单个期待（双层账本的一行）。"""
    id: str = Field(..., description="期待 ID，如 EXP_LANSTAR_POWER")
    book_id: str
    type: str = Field(..., description="ExpectationType 值")
    description: str = Field(..., description="期待描述（读者视角，如'读者想看兰星打脸贵族'）")

    # 双层来源
    source: str = Field(..., description="author_declared | auto_inferred")

    # 状态
    status: str = Field("setup", description="ExpectationStatus 值")
    current_tension: int = Field(5, ge=1, le=10, description="当前张力 1-10")
    expected_payoff_chapter: Optional[int] = Field(None, description="预期释放章节")

    # 累积历史
    tension_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="[{chapter, tension, event}] 每章张力变化",
    )

    # 关联
    related_hook_ids: List[str] = Field(default_factory=list, description="关联的 Canon HOOK 节点 id")
    related_character_ids: List[str] = Field(default_factory=list)

    # 作者意图（来自第 7 轮修正）
    author_override: Optional[str] = Field(
        None,
        description="作者对该期待的处理意图（如'再压 3 章才释放'），覆盖任何自动决策",
    )


# ============================================================
# 张力曲线（章节级，全书）
# ============================================================

class ChapterTensionSample(BaseModel):
    """单章张力采样。"""
    chapter_number: int
    overall_tension: int = Field(..., ge=1, le=10, description="全章综合张力")
    active_expectations: int = Field(0, description="该章活跃期待数")
    is_payoff_chapter: bool = Field(False, description="是否爽点章（释放了某期待）")
    note: str = ""


# ============================================================
# 信息差条目
# ============================================================

class InformationAsymmetry(BaseModel):
    """信息差（谁知道什么）。"""
    id: str
    book_id: str
    fact: str = Field(..., description="事实描述（如'兰星是暗月转世'）")
    reader_knows: bool = Field(False, description="读者是否知道")
    characters_know: Dict[str, bool] = Field(
        default_factory=dict,
        description="{角色名: 是否知道}",
    )
    source_chapter: Optional[int] = Field(None, description="在哪章建立")
    reveal_plan: str = ""


# ============================================================
# 章节规划建议（给介入点 1 用）
# ============================================================

class ChapterPlanSuggestion(BaseModel):
    """系统对本章的规划建议（仪表盘输出）。"""
    chapter_number: int

    # 期待处理建议
    expectations_to_setup: List[str] = Field(default_factory=list, description="建议新埋的期待 id")
    expectations_to_accumulate: List[str] = Field(default_factory=list, description="建议累积的期待 id")
    expectations_to_payoff: List[str] = Field(default_factory=list, description="建议释放的期待 id")

    # 张力建议
    suggested_tension: int = Field(5, ge=1, le=10, description="建议本章张力")
    is_payoff_chapter_recommended: bool = Field(False, description="是否建议释放爽点")

    # 理由（透明化）
    rationale: str = Field("", description="规划理由（透明化给作者）")

    # 作者可调
    author_override: Optional[str] = Field(None, description="作者覆盖意图")


class ExpectationUpdate(BaseModel):
    """期待更新请求。"""
    tension_delta: int = Field(0, ge=-10, le=10, description="张力变化（+1 累积 / -5 释放等）")
    new_status: Optional[str] = Field(None, description="新状态")
    tension_event: str = Field("", description="本章张力变化事件描述")
    chapter_number: int


# ============================================================
# 全书 Reader Mirror 快照
# ============================================================

class ReaderMirrorSnapshot(BaseModel):
    """全书读者状态快照。"""
    expectations: List[Expectation] = Field(default_factory=list)
    tension_curve: List[ChapterTensionSample] = Field(default_factory=list)
    information_asymmetries: List[InformationAsymmetry] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)
