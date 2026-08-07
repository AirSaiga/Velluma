"""
DDE（Director Decision Engine，导演决策引擎）核心数据结构（章节级剧情分叉版）。

职责：定义 BranchOption / StoryBranch / ChapterDecisionSet 等章节级剧情分叉
     决策的数据结构。
业务场景：BS-ADF Phase 4b 之后，DDE 对全章做一次"剧情走向级岔路"判断，
         产出 ChapterDecisionSet；作者（或 Track A 静默默认）选定分支后，
         SlotMutator 把选定走向写入目标 BeatSlotCard.branch_directive。
主要功能：结构化"剧情分叉控制器"的输入输出契约。
依赖项：dataclasses、typing

设计要点：
- 决策粒度是宏观/中观剧情走向（忍辱 vs 反抗），不是微观物理动作（藏哪儿）。
- 无岔路是常态：has_story_branch=False 表示全章无真实岔路，自动放行。
- 每个 StoryBranch 带 default_option（最顺大纲的走向）——Track A 静默应用、
  作者跳过时的兜底都走它，默认选项是主路径而非兜底交互。
- 与 schemas/bsadf.py 的 StoryBranchSchema 平行（dataclass 供内部流转，
  Pydantic 供 API 边界），字段一一对应。
"""
# Velluma - DDE (Director Decision Engine) Types
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class BranchOption:
    """单个剧情分支选项（走向级，非物理动作级）。"""
    option_id: str          # "A" | "B" | "C"
    label: str              # 走向标签（≤20字），如 "忍辱负重并暗中破坏设备"
    plot_impact: str = ""   # 剧情后果说明（给作者看 + 注入渲染走向约束）


@dataclass
class StoryBranch:
    """单个剧情分叉节点（挂在某个 beat 上的一道走向选择题）。"""
    beat_id: str                            # 目标 BeatSlotCard.beat_id
    node_title: str                         # 如 "面对工头恶意挑衅，林尘的应对分支"
    options: List[BranchOption] = field(default_factory=list)  # 2~3 个
    default_option: str = ""                # LLM 指定的默认 option_id（最顺大纲的）
    # 节点来源："dde"=LLM 判出的真实走向岔路；"loop1_gap"=Loop1 大纲自检
    # macro 缺口注入（单选项提示节点，只有作者 custom: 补充文本才应写 directive，
    # 否则提示语会被当走向污染渲染 prompt）
    source: str = "dde"


@dataclass
class ChapterDecisionSet:
    """全章剧情分叉决策集（DDE 单次 LLM 调用的产出）。"""
    has_story_branch: bool = False                     # False = 全章无岔路，自动放行
    decision_nodes: List[StoryBranch] = field(default_factory=list)  # 硬上限 2 个


# ============================================================
# 序列化（SSE 事件 / pending 暂存 / 内部 dict 流转用）
# ============================================================

def branch_option_to_dict(o: BranchOption) -> dict:
    return {
        "option_id": o.option_id,
        "label": o.label,
        "plot_impact": o.plot_impact,
    }


def branch_option_from_dict(d: dict) -> BranchOption:
    return BranchOption(
        option_id=str(d.get("option_id", "")),
        label=str(d.get("label", "")),
        plot_impact=str(d.get("plot_impact", "")),
    )


def story_branch_to_dict(n: StoryBranch) -> dict:
    return {
        "beat_id": n.beat_id,
        "node_title": n.node_title,
        "options": [branch_option_to_dict(o) for o in n.options],
        "default_option": n.default_option,
        "source": n.source,
    }


def story_branch_from_dict(d: dict) -> StoryBranch:
    return StoryBranch(
        beat_id=str(d.get("beat_id", "")),
        node_title=str(d.get("node_title", "")),
        options=[branch_option_from_dict(o) for o in d.get("options", [])],
        default_option=str(d.get("default_option", "")),
        # 旧 pending 载荷无 source 字段 → 按 "dde"（维持旧行为）
        source=str(d.get("source", "dde") or "dde"),
    )


def chapter_decision_set_to_dict(s: ChapterDecisionSet) -> dict:
    return {
        "has_story_branch": s.has_story_branch,
        "decision_nodes": [story_branch_to_dict(n) for n in s.decision_nodes],
    }


def chapter_decision_set_from_dict(d: dict) -> ChapterDecisionSet:
    return ChapterDecisionSet(
        has_story_branch=bool(d.get("has_story_branch", False)),
        decision_nodes=[story_branch_from_dict(n) for n in d.get("decision_nodes", [])],
    )


# ============================================================
# 用户选择载荷
# ============================================================

# branch_choices 结构：{ beat_id: option_id }
# option_id 为 "custom:xxx" 前缀时表示作者自定义走向文本
UserChoices = Dict[str, str]
