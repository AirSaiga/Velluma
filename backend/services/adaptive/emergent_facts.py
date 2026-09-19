# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 涌现实体抽取（Loop 3 思想迁入 adaptive）
"""
从一段定稿正文抽取涌现实体/关系/地点/大纲补遗（1× creative LLM）。

迁移动机（roadmap P3.2，BS-ADF 整体归档）：本模块前身是
`workflows/bsadf/memory_ingestion.py`（Loop 3 记忆倒灌）。adaptive 的 sediment
与 canon_watch 一直复用它——归档前把它连同 EmergentFacts 数据类一起迁出，
adaptive 链路自此不依赖步进流任何设施（与 stitch 的字数闸门同策略：
复制/迁移而非 import，防归档反噬）。

行为契约与原实现逐字节一致（含 P0-2 观测钩子 recorder 参数、
失败返回空 EmergentFacts 不抛异常、_unwrap_llm_response 的 mock 兼容形态）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.llm.client import REASONING_DISABLED
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.nle_prompts import build_emergent_facts_prompt

logger = logging.getLogger(__name__)


@dataclass
class EmergentFacts:
    """涌现实体抽取结果（单段）。

    failed=True（02 候选回流修缮 P6）：LLM 调用异常/返回不可解析——与「无涌现」
    （failed=False 且全空列表）显式区分，调用方可据此保留重试资格（不写幂等锚）。
    """

    new_entities: List[dict] = field(default_factory=list)
    relationship_changes: List[dict] = field(default_factory=list)
    new_locations: List[dict] = field(default_factory=list)
    outline_addenda: List[dict] = field(default_factory=list)
    failed: bool = False

    def is_empty(self) -> bool:
        return (
            not self.new_entities
            and not self.relationship_changes
            and not self.new_locations
            and not self.outline_addenda
        )

    def to_dict(self) -> dict:
        return {
            "new_entities": self.new_entities,
            "relationship_changes": self.relationship_changes,
            "new_locations": self.new_locations,
            "outline_addenda": self.outline_addenda,
        }


def _parse_json_safe(text: str) -> Optional[dict]:
    """容错解析 LLM 输出的 JSON（支持 ```json 代码块与外层噪音）。"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
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
    stage: str = "loop3.emergent_facts",
) -> EmergentFacts:
    """从一段定稿正文抽取涌现实体（1× creative LLM）。

    stage：记账标识（用量面板拆账用）——手动沉淀走默认 loop3.emergent_facts；
    自动认人（read-entities）传 adaptive.read_entities，两条链路在
    用量视图与自动阅读预算闸（read_budget._AUTO_STAGES）各自可见。

    失败时返回空 EmergentFacts（不抛异常）——不阻塞调用方主流程。
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
        # 观测钩子：调用方传 recorder 则记账（P0-2；纯观测非功能）
        if recorder is not None:
            recorder.record_result(stage, resp, model_slot="creative")
        parsed = _parse_json_safe(text)
        # 空响应/不可解析 = 抽取失败（02 修缮 P6）：与「无涌现」区分——调用方
        # （read-entities）据此不写幂等锚保留重试资格。无涌现的合法形态是
        # 可解析 JSON 的全空列表，走到 None 只有失败一条路。
        if parsed is None:
            logger.warning("extract_emergent_facts 输出不可解析 (beat=%s)", beat_id)
            return EmergentFacts(failed=True)
        # 类型校验——LLM 返回的列表字段可能是 str/dict/None
        def _safe_list(v):
            return v if isinstance(v, list) else []
        return EmergentFacts(
            new_entities=_safe_list(parsed.get("new_entities")),
            relationship_changes=_safe_list(parsed.get("relationship_changes")),
            new_locations=_safe_list(parsed.get("new_locations")),
            outline_addenda=_safe_list(parsed.get("outline_addenda")),
        )
    except Exception as e:
        logger.warning("extract_emergent_facts 失败 (beat=%s): %s", beat_id, e)
        return EmergentFacts(failed=True)
