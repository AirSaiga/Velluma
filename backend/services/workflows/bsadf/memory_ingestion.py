# Velluma - NLE-ADF Loop 3: Memory Ingestion
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""
Loop 3：记忆倒灌。

职责：每段 BEAT_LOCKED 后，从正文抽取涌现实体/关系/地点/大纲补遗，
保守回写（emergent 标记 + 建议而非破坏性改写）。
"""

import json
import logging
from typing import Any, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.llm.client import REASONING_DISABLED
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.nle_prompts import build_emergent_facts_prompt
from backend.services.workflows.bsadf.types import EmergentFacts

logger = logging.getLogger(__name__)


def _parse_json_safe(text: str) -> Optional[dict]:
    """容错解析 LLM 输出的 JSON（支持 ```json 代码块与外层噪音）。"""
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


def _unwrap_llm_response(resp: Any) -> str:
    """从 call_llm_with_usage 返回值里取出正文文本。

    生产实现返回 LLMResult（.content）；单元测试常以 (text, usage) 二元组 mock，
    两种形态都兼容。
    """
    if resp is None:
        return ""
    # 测试 mock 形态：(text, usage)
    if isinstance(resp, tuple):
        return str(resp[0]) if resp[0] is not None else ""
    # 生产形态：LLMResult
    return getattr(resp, "content", "") or ""


async def extract_emergent_facts(
    segment_text: str,
    beat_id: str,
    prev_state_summary: str = "",
    recorder: Optional[RunRecorder] = None,
) -> EmergentFacts:
    """从一段定稿正文抽取涌现实体（1× creative LLM）。

    失败时返回空 EmergentFacts（不抛异常）—— Loop 3 不阻塞步进主流程。
    """
    if not segment_text or not segment_text.strip():
        return EmergentFacts()
    try:
        sys_p, user_p = build_emergent_facts_prompt(segment_text, beat_id, prev_state_summary)
        resp = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=user_p,
            model_type="creative",
            temperature=0.1,
            max_tokens=1500,
            reasoning_config=REASONING_DISABLED,
        )
        text = _unwrap_llm_response(resp)
        parsed = _parse_json_safe(text) or {}
        return EmergentFacts(
            new_entities=parsed.get("new_entities", []),
            relationship_changes=parsed.get("relationship_changes", []),
            new_locations=parsed.get("new_locations", []),
            outline_addenda=parsed.get("outline_addenda", []),
        )
    except Exception as e:
        logger.warning("Loop3 extract_emergent_facts 失败 (beat=%s): %s", beat_id, e)
        return EmergentFacts()
