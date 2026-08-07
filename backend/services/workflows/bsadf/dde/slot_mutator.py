"""
DDE 槽位突变器（SlotMutator，章节级剧情分叉版）。

职责：将选定的剧情分支走向，写入目标 BeatSlotCard.branch_directive 字段
     （渲染 prompt 的"本段剧情走向约束"注入源）。

业务场景：
- Track A：DDE 判出有分支后，立即用 default_option 静默突变（本模块，
  skipped=True 路径），全程不暂停。
- Track B：作者在分镜面板选定分支（或跳过）后，/confirm-beats 先调本模块
  突变，再 resume_from_slots 渲染。
主要功能：
- mutate_slot_cards：批量突变（接收 branch_choices + decision_set，返回突变后的 cards）

设计要点：
- 只写 branch_directive，**绝不触碰** core_plot_event / key_anchors /
  text_carrier——硬契约字段是 coverage 校验的锚，走向约束不是（旧版把
  选项文本覆盖进 anchor_actions 导致 coverage 污染的事故由此根治）。
- 走向文本格式：f"{label}。{plot_impact}"；自定义输入（"custom:" 前缀）
  直接取前缀后文本。
- 跳过/未作答一律走 default_option——默认选项是主路径，不是兜底交互。
- 纯函数（无 LLM、无 IO），便于单测。

依赖项：BeatSlotCard、ChapterDecisionSet、UserChoices
"""
# Velluma - DDE slot_mutator
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import logging
from typing import List, Optional

from backend.services.workflows.bsadf.dde.types import (
    BranchOption,
    ChapterDecisionSet,
    StoryBranch,
    UserChoices,
)
from backend.services.workflows.bsadf.types import BeatSlotCard

logger = logging.getLogger(__name__)

_CUSTOM_PREFIX = "custom:"


def _resolve_option(
    node: StoryBranch, chosen_id: Optional[str],
) -> Optional[BranchOption]:
    """根据 option_id 解析选定选项；空/非法一律回退 default_option。

    - 普通选项：按 option_id 匹配 node.options
    - 自定义输入（"custom:" 前缀）：返回一个以自定义文本为 label 的临时选项
    - 兜底链：chosen → default_option → options[0]
    """
    if chosen_id and chosen_id.startswith(_CUSTOM_PREFIX):
        custom_text = chosen_id[len(_CUSTOM_PREFIX):].strip()
        if custom_text:
            return BranchOption(
                option_id=chosen_id, label=custom_text, plot_impact="",
            )
        # 自定义文本为空 → 落回默认
    if chosen_id:
        for opt in node.options:
            if opt.option_id == chosen_id:
                return opt
    # 未作答 / 非法 id / 跳过 → default_option（缺失时再兜底 options[0]）
    for opt in node.options:
        if opt.option_id == node.default_option:
            return opt
    return node.options[0] if node.options else None


def _apply_branch(card: BeatSlotCard, node: StoryBranch, option: BranchOption) -> None:
    """把选定走向写入 card.branch_directive（in-place）。

    警示：本函数只允许写 branch_directive / edited / edit_count，
    严禁触碰 core_plot_event / key_anchors / text_carrier 等硬契约字段。
    """
    directive = option.label
    if option.plot_impact:
        directive = f"{option.label}。{option.plot_impact}"
    card.branch_directive = directive
    card.edited = True
    card.edit_count += 1


def mutate_slot_cards(
    cards: List[BeatSlotCard],
    decision_set: ChapterDecisionSet,
    branch_choices: Optional[UserChoices] = None,
    skipped: bool = False,
) -> List[BeatSlotCard]:
    """批量突变槽位卡（SlotMutator 主入口，纯函数）。

    Args:
        cards: 原始槽位卡列表（按 beat_id 与 decision_nodes 对应）
        decision_set: DDE 产出的章节级决策集
        branch_choices: { beat_id: option_id }（"custom:" 前缀 = 自定义走向）
        skipped: True 表示作者跳过/Track A 静默应用，全部走 default_option

    Returns:
        突变后的 cards 列表（同一批对象，已 in-place 突变）
    """
    if not decision_set or not decision_set.decision_nodes:
        return cards
    choices = branch_choices or {}
    card_map = {c.beat_id: c for c in cards}

    for node in decision_set.decision_nodes:
        card = card_map.get(node.beat_id)
        if card is None:
            logger.warning(
                f"[dde.slot_mutator] 分支节点挂载点 {node.beat_id} 不在槽位卡中，跳过"
            )
            continue
        chosen_id = None if skipped else choices.get(node.beat_id)
        # Loop1 缺口提示节点：唯一选项是"建议补充：..."提示语而非走向，
        # 只有作者显式 custom: 补充文本才写 directive；默认/跳过一律不注入
        # （否则 Track A 静默应用 / Track B 默认确认会把提示语污染进渲染 prompt）
        if node.source == "loop1_gap":
            custom_text = (
                chosen_id[len(_CUSTOM_PREFIX):].strip()
                if chosen_id and chosen_id.startswith(_CUSTOM_PREFIX)
                else ""
            )
            if custom_text:
                option = _resolve_option(node, chosen_id)
                if option is not None:
                    try:
                        _apply_branch(card, node, option)
                    except Exception as e:
                        logger.warning(
                            f"[dde.slot_mutator] 缺口补充突变失败（{node.beat_id}，保留原卡）: {e}"
                        )
            continue
        option = _resolve_option(node, chosen_id)
        if option is None:
            continue
        try:
            _apply_branch(card, node, option)
        except Exception as e:
            logger.warning(
                f"[dde.slot_mutator] 突变失败（{node.beat_id}，保留原卡）: {e}"
            )

    return cards
