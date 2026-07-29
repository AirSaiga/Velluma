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


def diagnose_gaps(hard_facts: List[dict], total_segments: int) -> List[dict]:
    """Pass 2：缺口诊断（纯算法）。"""
    gaps: List[dict] = []
    # 风险9修复：类型校验——LLM 返回的 hard_facts 元素可能非 dict（str/None）
    safe_facts = [f for f in (hard_facts or []) if isinstance(f, dict)]
    fact_contents = " ".join(f.get("content", "") for f in safe_facts)

    has_motivation = any(kw in fact_contents for kw in _MOTIVATION_KEYWORDS)
    if not has_motivation and safe_facts:
        gaps.append({
            "type": "macro", "impact": "high",
            "description": "大纲未明确角色动机，可能影响剧情说服力",
            "suggested_fill": "建议补充：主角为何采取此行动",
            "for_dde": True,
        })

    has_relation = any(kw in fact_contents for kw in _RELATION_KEYWORDS)
    if not has_relation and total_segments >= 4:
        gaps.append({
            "type": "macro", "impact": "high",
            "description": "本章无明确关系转折，若涉及多方角色建议明确",
            "suggested_fill": "建议补充：角色间关系的演变方向",
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
