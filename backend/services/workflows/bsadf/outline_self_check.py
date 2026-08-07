# Velluma - NLE-ADF Loop 1: Outline Self-Check
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""
Loop 1：大纲层 3-pass 自检。

职责：在 Phase 4b（enrich）之前，对大纲做硬事实提取→缺口诊断→Critique 校验。

流程：
- Pass 1 硬事实提取（1× reasoning LLM）
- Pass 2 缺口诊断（0 LLM，纯算法）
- Pass 3 Critique 校验（1× reasoning LLM）
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.nle_prompts import (
    build_outline_hard_facts_prompt, build_outline_critique_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class OutlineCheckResult:
    """Loop 1 自检结果。"""
    pass_: bool = True
    violations: List[dict] = field(default_factory=list)
    hard_facts: List[dict] = field(default_factory=list)
    gaps: List[dict] = field(default_factory=list)
    macro_gaps_for_dde: List[dict] = field(default_factory=list)
    degraded_reason: Optional[str] = None


_MOTIVATION_KEYWORDS = ["动机", "为什么", "原因", "目的", "为了"]
_RELATION_KEYWORDS = ["关系", "背叛", "结盟", "冲突", "信任"]

# 用于从 hard_facts 中提取行为/动作片段的辅助正则
import re as _re
_ACTION_PATTERN = _re.compile(
    r"(?:林尘|他|她|他们|流光|白霆)\S{0,8}(?:了|着|向|在|把|被|去|来|走|看|说|站|坐|躺|躲|逃|冲|跑|追|挡|拦|攻|杀|砍|刺|打|踢|摔|撞|砸|劈|轰|炸|烧|冻|射|扔|抛|甩|挥|握|拿|取|放|推|拉|拽|拖|搬|抬|举|按|压|踩|踏|蹬|扒|撬|拧|捏|掐|搓|揉|撕|扯|拔|剥|削|切|割|剪|锯|钻|磨|刮|蹭|蹭|挠|抓|揪|拧|摇|晃|抖|颤|缩|弓|弯|蹲|跪|趴|伏|仰|俯|侧|转|旋|滚|翻|蹦|跳|跃|扑|窜|闪|避|退|进|靠|凑|凑|凑|挨|贴|挤|塞|夹|夹|夹)",
    _re.UNICODE,
)


def _extract_action_snippets(facts: List[dict], max_snippets: int = 3) -> List[str]:
    """从 hard_facts 的 content 中提取行为/动作片段，用于缺口描述的具体化。"""
    snippets: List[str] = []
    for f in facts:
        content = f.get("content", "")
        if not content:
            continue
        # 优先找含动词的短句（分号/逗号分割后取 ≤15 字片段）
        parts = _re.split(r"[；;，,。.]", content)
        for part in parts:
            part = part.strip()
            if 5 <= len(part) <= 20 and _ACTION_PATTERN.search(part):
                snippets.append(part)
                if len(snippets) >= max_snippets:
                    return snippets
    return snippets


def diagnose_gaps(hard_facts: List[dict], total_segments: int) -> List[dict]:
    """Pass 2：缺口诊断（纯算法）。

    改进：基于 hard_facts 的实际内容生成具体化的缺口描述和补充建议，
    而非笼统地说"大纲未明确角色动机"。
    """
    gaps: List[dict] = []
    # 风险9修复：类型校验——LLM 返回的 hard_facts 元素可能非 dict（str/None）
    safe_facts = [f for f in (hard_facts or []) if isinstance(f, dict)]
    fact_contents = " ".join(f.get("content", "") for f in safe_facts)

    # ---- 缺口1：角色动机缺失 ----
    has_motivation = any(kw in fact_contents for kw in _MOTIVATION_KEYWORDS)
    if not has_motivation and safe_facts:
        # 具体化：从 hard_facts 中提取行为片段，告诉作者"哪些行为缺少动机"
        action_snippets = _extract_action_snippets(safe_facts)
        if action_snippets:
            actions_text = "、".join(action_snippets)
            description = (
                f"大纲提到「{actions_text}」等行为，"
                f"但未说明角色为何这样做——缺少动机/原因/目的"
            )
            suggested_fill = (
                f"请补充：角色做这些事的内在动机"
                f"（如{action_snippets[0]}的前因/心理状态/被迫原因）"
            )
        else:
            description = "大纲未明确角色动机，可能影响剧情说服力"
            suggested_fill = "请补充：角色行为的内在动机（为何这样做？受什么驱使？）"
        gaps.append({
            "type": "macro", "impact": "high",
            "description": description,
            "suggested_fill": suggested_fill,
            "for_dde": True,
        })

    # ---- 缺口2：关系转折缺失 ----
    has_relation = any(kw in fact_contents for kw in _RELATION_KEYWORDS)
    if not has_relation and total_segments >= 4:
        # 具体化：从 hard_facts 中提取出现的角色名，告诉作者"哪些角色关系未定义"
        # 简单的中文人名提取（2-4 字连续汉字，排除常见非人名词）
        _NON_PERSON = {"一个", "两个", "三个", "所有", "他们", "这里", "哪里", "什么", "这个", "那个", "基地", "仓库", "走廊", "大厅", "反抗", "统合"}
        char_pattern = _re.compile(r"[\u4e00-\u9fff]{2,4}")
        char_names = set()
        for m in char_pattern.finditer(fact_contents):
            w = m.group()
            if w not in _NON_PERSON and not any(kw in w for kw in _MOTIVATION_KEYWORDS + _RELATION_KEYWORDS):
                char_names.add(w)
        char_list = sorted(char_names)[:4]  # 取最多 4 个角色名

        if char_list:
            names_text = "、".join(char_list)
            description = (
                f"大纲涉及{names_text}等角色，"
                f"但未明确他们之间的关系走向（联盟/对抗/背叛/信任变化）"
            )
            suggested_fill = (
                f"请补充：本章中{names_text}之间关系的演变方向"
                f"（谁和谁产生冲突/结盟/信任变化？）"
            )
        else:
            description = "本章涉及多方角色，但未明确关系转折"
            suggested_fill = "请补充：角色间关系的演变方向（联盟/对抗/背叛/信任变化）"
        gaps.append({
            "type": "macro", "impact": "high",
            "description": description,
            "suggested_fill": suggested_fill,
            "for_dde": True,
        })

    if total_segments >= 3:
        gaps.append({
            "type": "micro", "impact": "low",
            "description": "具体场景细节（打断方式/道具交互）可由渲染器自由发挥",
            "suggested_fill": "渲染期 LLM 自由补全",
            "for_dde": False,
        })

    return gaps


def _parse_json_safe(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


async def run_outline_self_check(
    outline_text: str,
    chapter_title: str,
    beat_slots: List[dict],
    recorder: Optional[RunRecorder] = None,
) -> OutlineCheckResult:
    """执行 Loop 1 完整 3-pass 自检。"""
    result = OutlineCheckResult()

    # Pass 1
    try:
        sys_p, user_p = build_outline_hard_facts_prompt(outline_text, chapter_title)
        llm_res = await call_llm_with_usage(
            system_prompt=sys_p, user_prompt=user_p, model_type="reasoning",
            temperature=0.0, max_tokens=2000,
        )
        parsed = _parse_json_safe(llm_res.content or "") or {}
        result.hard_facts = parsed.get("hard_facts", [])
    except Exception as e:
        logger.warning("Loop1 Pass1 硬事实提取失败: %s", e)
        result.degraded_reason = "loop1_pass1_failed"
        return result

    # Pass 2
    result.gaps = diagnose_gaps(result.hard_facts, total_segments=len(beat_slots))
    result.macro_gaps_for_dde = [g for g in result.gaps if g.get("for_dde")]

    # Pass 3
    try:
        sys_p, user_p = build_outline_critique_prompt(outline_text, result.hard_facts, beat_slots)
        llm_res = await call_llm_with_usage(
            system_prompt=sys_p, user_prompt=user_p, model_type="reasoning",
            temperature=0.0, max_tokens=2000,
        )
        parsed = _parse_json_safe(llm_res.content or "") or {}
        result.pass_ = bool(parsed.get("pass", True))
        result.violations = parsed.get("violations", [])
    except Exception as e:
        logger.warning("Loop1 Pass3 Critique 失败: %s", e)
        result.pass_ = True

    return result
