# Velluma - NLE-ADF 3.0 未来推测组件（层 3）
# AGPL-3.0
"""
基于层 1（已写事实）+ 层 2（意图），LLM 推测接下来的画面方向。

校对：推测 vs Canon public/static_prompt——违规推测丢弃（不写入层 3）。
懒加载：orchestrator 只在挂件需要且 projection 过期时激活本组件。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.prompts.adaptive_prompts import build_future_projection_prompt
from backend.services.adaptive.world_model import WorldModelRepository, SegmentProjection
from backend.services.utils.json_safe import parse_json_safe

logger = logging.getLogger(__name__)


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 600, **kw) -> Dict:
    """未来推测。由 orchestrator 调度。"""
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    repo = WorldModelRepository(db)

    # 层 1 正文尾部（最近写的）
    facts = model_snapshot.get("facts", [])
    written_text = "\n\n".join(f.get("text", "") for f in facts if f.get("text"))
    if not written_text:
        return {"skipped": True, "reason": "无已写正文"}

    intent = model_snapshot.get("intent", {})
    if intent.get("source", "none") == "none":
        return {"skipped": True, "reason": "无意图（层 2 空）"}

    nutrients = bundle.nutrients()
    soft = bundle.soft_constraints()
    sys_p, usr_p = build_future_projection_prompt(written_text, intent, nutrients, soft)

    try:
        result = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=usr_p,
            model_type="creative",
            temperature=0.6,
            max_tokens=budget_tokens,
            reasoning_config=REASONING_DISABLED,
        )
        parsed = parse_json_safe(result.content or "") or {}
        raw_projections = parsed.get("projections", [])

        # ---- 校对：丢弃违规推测 ----
        hard = bundle.hard_constraints()
        valid: List[SegmentProjection] = []
        for proj in raw_projections[:3]:
            if not isinstance(proj, dict):
                continue
            # 检查 event/anchors 是否触碰 canon private 或违背 public
            text_to_check = proj.get("event", "") + " " + " ".join(proj.get("anchors", []))
            if _violates_constraints(text_to_check, hard):
                continue
            sig = _signature(proj)
            valid.append(SegmentProjection(
                possible_beats=[proj],
                confidence=0.5,
                signature=sig,
            ))

        await repo.set_projections(chapter_id, valid)
        return {"count": len(valid)}
    except Exception as e:
        logger.warning(f"[future_projection] 失败: {e}")
        return {"error": str(e)}


def _violates_constraints(text: str, hard: Dict) -> bool:
    """校对：文本是否触碰 canon private 或含禁词。"""
    # private 标签词出现在文本里 = 泄密
    for label in hard.get("canon_private_labels", []):
        if label and len(label) >= 2 and label in text:
            return True
    # 禁词
    for word in hard.get("banned_words", []):
        if word and len(word) >= 2 and word in text:
            return True
    return False


def _signature(proj: Dict) -> str:
    """推测内容签名（懒加载判断）。"""
    raw = proj.get("event", "") + str(proj.get("anchors", []))
    return hashlib.md5(raw.encode()).hexdigest()[:8]
