"""
DDE 剧情分叉控制器（章节级 DecisionSet 生成器）。

职责：对全章做一次"剧情走向级真实岔路"判断（1×creative LLM），输出
     ChapterDecisionSet，并做 Python 侧代码闸门校验。

业务场景：BS-ADF Phase 4b 之后（槽位卡已 enrich，分支判断更准），
         Track A 静默应用默认分支，Track B 随 BEAT_SLOTS_BUILT 一起给作者。
主要功能：
- generate_chapter_decision_set：全章一次 LLM 调用 + 代码闸门

设计要点：
- 全章一次调用（不再逐卡循环）——岔路判断需要全章视角，逐卡提问正是旧版
  "每段一张微观物理题"的病根。
- 无岔路放行是特性不是失败：LLM 判 has_story_branch=false 或输出被闸门
  滤空时，返回空 ChapterDecisionSet，主流程照常继续（已删除旧版的
  _generate_fallback_decision 保底出题——它会在无岔路时捏造题目，并把
  选项文本污染进 coverage 强制词）。
- 代码闸门（不信任 prompt 约束）：节点数 >2 截断；选项数 2~3、id 唯一、
  label 非空；beat_id 必须命中本章槽位卡；default_option 缺失/非法时
  兜底 options[0]。
- LLM 调用失败/超时/乱码 → 空 DecisionSet（不阻塞主流程）。

依赖项：LLM 客户端、dde/types、BeatSlotCard
"""
# Velluma - DDE decision_card_generator
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import json
import logging
from typing import Any, List, Optional

from backend.services.observability.run_recorder import RunRecorder
from backend.services.llm import call_llm_with_usage
from backend.services.llm.client import REASONING_DISABLED
from backend.services.prompts.dde_prompts import build_chapter_decision_prompt
from backend.services.workflows.bsadf.dde.types import (
    BranchOption,
    ChapterDecisionSet,
    StoryBranch,
)
from backend.services.workflows.bsadf.types import BeatSlotCard

logger = logging.getLogger(__name__)


# ============================================================
# 常量与闸门规则
# ============================================================

MAX_DECISION_NODES = 2      # 全章分支节点硬上限
MIN_OPTIONS = 2
MAX_OPTIONS = 3
MAX_LABEL_LEN = 30          # prompt 约束 ≤20 字，代码侧留富余防误杀
MAX_TITLE_LEN = 60


def _validate_option(opt: BranchOption, seen_ids: set) -> bool:
    """校验单个选项：id 非空唯一、label 非空且不过长。"""
    if not opt.option_id or not opt.label:
        return False
    if len(opt.label) > MAX_LABEL_LEN:
        return False
    if opt.option_id in seen_ids:
        return False
    seen_ids.add(opt.option_id)
    return True


def _parse_chapter_decision_json(
    raw: str,
    valid_beat_ids: set,
) -> ChapterDecisionSet:
    """解析 LLM 返回的 JSON 为 ChapterDecisionSet，应用代码闸门。

    闸门规则：
    - 节点数 > MAX_DECISION_NODES 截断
    - 节点 beat_id 必须命中本章槽位卡（防 LLM 漂移出无效挂载点）
    - 选项 2~3 个、id 唯一、label 非空
    - default_option 缺失/非法时兜底 options[0].option_id
    - has_story_branch 以解析后的实际节点数为准（不信 LLM 自报旗帜）

    解析失败/全部节点不合规时返回空 ChapterDecisionSet（不抛异常）。
    """
    if not raw or not raw.strip():
        return ChapterDecisionSet()
    try:
        data = json.loads(raw.strip())
    except Exception:
        # 容错：尝试抽取第一个 {...} 块（DeepSeek 常见带解释文字/围栏输出）
        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            try:
                data = json.loads(raw[first:last + 1])
            except Exception:
                return ChapterDecisionSet()
        else:
            return ChapterDecisionSet()

    nodes: List[StoryBranch] = []
    for n_raw in (data.get("decision_nodes") or []):
        if len(nodes) >= MAX_DECISION_NODES:
            break  # 节点数硬上限截断
        try:
            beat_id = str(n_raw.get("beat_id", "")).strip()
            node_title = str(n_raw.get("node_title", "")).strip()[:MAX_TITLE_LEN]
            if not beat_id or beat_id not in valid_beat_ids or not node_title:
                continue
            seen_ids: set = set()
            options = [
                o for o in (
                    BranchOption(
                        option_id=str(o_raw.get("option_id", "")).strip(),
                        label=str(o_raw.get("label", "")).strip(),
                        plot_impact=str(o_raw.get("plot_impact", "")).strip(),
                    )
                    for o_raw in (n_raw.get("options") or [])
                )
                if _validate_option(o, seen_ids)
            ]
            if not (MIN_OPTIONS <= len(options) <= MAX_OPTIONS):
                continue
            default_option = str(n_raw.get("default_option", "")).strip()
            # default_option 缺失/非法 → 兜底 options[0]（最顺大纲的默认主路径）
            if default_option not in {o.option_id for o in options}:
                default_option = options[0].option_id
            nodes.append(StoryBranch(
                beat_id=beat_id,
                node_title=node_title,
                options=options,
                default_option=default_option,
            ))
        except Exception:
            continue

    return ChapterDecisionSet(
        has_story_branch=bool(nodes),
        decision_nodes=nodes,
    )


async def generate_chapter_decision_set(
    chapter: Any,
    anchor: Any,
    spine: Any,
    cards: List[BeatSlotCard],
    recorder: Optional[RunRecorder] = None,
    force_branch_gaps: Optional[List[dict]] = None,
) -> ChapterDecisionSet:
    """对全章做一次剧情分叉判断（1×creative LLM + 代码闸门）。

    Args:
        chapter: chapter ORM 对象（读 outline_text）
        anchor: Phase 2 产出的 ChapterClimax（高潮设计 + preconditions）
        spine: Phase 1 产出的 StoryContext（卷位/节奏）
        cards: 本章全部槽位卡（enrich 之后；提供 beat_id 清单与 outline_beat）
        recorder: RunRecorder（计量用，可选）
        force_branch_gaps: Loop 1 大纲自检产出的 macro 缺口列表（可选）。
            非空时，把每个缺口包装成 StoryBranch 追加到 decision_set，并在
            LLM 判无岔路时仍把缺口分支暴露给作者（覆盖 has_story_branch=True）。

    Returns:
        ChapterDecisionSet（has_story_branch=False 表示全章无岔路，自动放行；
        LLM 失败/乱码同样返回空集——无岔路放行是特性不是失败）
    """
    outline_text = getattr(chapter, "outline_text", "") or ""
    climax_description = getattr(getattr(anchor, "climax", None), "description", "") or ""
    precondition_descriptions = [
        getattr(pc, "description", "") or ""
        for pc in (getattr(anchor, "preconditions", None) or [])
    ]
    # spine 卷位信息（供 LLM 判断"此时该不该出现走向级岔路"）
    volume_position_text = ""
    chapter_position = getattr(spine, "chapter_position", None)
    if chapter_position is not None:
        offset = getattr(chapter_position, "offset_from_volume_climax", None)
        tempo = getattr(chapter_position, "pacing_tempo", "") or ""
        if offset is not None:
            volume_position_text = f"距卷高潮还有 {offset} 章，节奏：{tempo or '常规'}"
    beat_outlines = [
        {"beat_id": c.beat_id, "outline_beat": c.outline_beat or ""}
        for c in cards
    ]

    system_prompt, user_prompt = build_chapter_decision_prompt(
        outline_text=outline_text,
        climax_description=climax_description,
        precondition_descriptions=precondition_descriptions,
        volume_position_text=volume_position_text,
        beat_outlines=beat_outlines,
    )

    # 调 LLM（creative 槽，沿用旧决策卡的调用惯例；关 thinking 防小预算被吃光）
    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="dde.chapter_decision",
                model_slot="creative",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.5,
                    max_tokens=2048,
                    reasoning_config=REASONING_DISABLED,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.5,
                max_tokens=2048,
                reasoning_config=REASONING_DISABLED,
            )
        raw = result.content or ""
    except Exception as e:
        logger.warning(f"[dde] 章节分叉判断 LLM 调用失败（降级无岔路放行）: {e}")
        return ChapterDecisionSet()

    decision_set = _parse_chapter_decision_json(
        raw, valid_beat_ids={c.beat_id for c in cards},
    )
    logger.info(
        f"[dde] 章节分叉判断完成：has_story_branch={decision_set.has_story_branch}，"
        f"节点数={len(decision_set.decision_nodes)}"
    )

    # Loop 1 宏观缺口联动：把 NLE-ADF 大纲自检的 macro 缺口包装成 StoryBranch
    # 追加进 decision_set，使缺口在 DDE 层暴露为可被作者/Track A 处置的走向节点。
    if force_branch_gaps:
        for gap in force_branch_gaps:
            # 选目标卡（用第一张卡，简单策略）
            target_beat_id = cards[0].beat_id if cards else ""
            branch = StoryBranch(
                beat_id=target_beat_id,
                node_title=str(gap.get("description", "Loop1 缺口"))[:40],
                options=[BranchOption(
                    option_id="A",
                    label=str(gap.get("suggested_fill", "默认走向"))[:20],
                    plot_impact=str(gap.get("suggested_fill", "")),
                )],
                default_option="A",
            )
            decision_set.decision_nodes.append(branch)
        decision_set.has_story_branch = True
        logger.info(
            f"[dde] 注入 Loop1 macro 缺口分支 {len(force_branch_gaps)} 个，"
            f"节点数={len(decision_set.decision_nodes)}"
        )

    return decision_set
