# Velluma - NLE-ADF 3.0 意图反推组件（层 2）
# AGPL-3.0
"""
从作者已写正文（+可选大纲）推断本章意图，写入世界模型层 2。

两条路径：
- from_outline：作者有大纲 → 高信度（大纲即意图，附 must_hit 校对）
- from_text：无大纲 → LLM 反推（中信度）

校对：反推结果 vs ChapterCard.must_hit_events，偏差记入 intent.deviations
（不强制修正——只标注，作者主权）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import call_llm_with_usage
from backend.services.adaptive.observing import get_adaptive_recorder
from backend.services.prompts.adaptive_prompts import build_intent_inference_prompt
from backend.services.adaptive.world_model import WorldModelRepository, ChapterIntent
from backend.services.utils.json_safe import parse_json_safe  # 复用容错解析

logger = logging.getLogger(__name__)


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 1500, **kw) -> Dict:
    """意图反推。由 orchestrator 调度。"""
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    repo = WorldModelRepository(db)

    # 正文来源：优先层 1（已沉淀事实），层 1 为空时回退章节 content_text（已落库正文）
    # 关键：作者刚开始写、还没沉淀时，层 1 是空的——但 content_text 已有正文
    facts = model_snapshot.get("facts", [])
    written_text = "\n\n".join(f.get("text", "") for f in facts if f.get("text"))
    if not written_text or len(written_text.strip()) < 100:
        # 层 1 不足，回退章节正文
        written_text = bundle.content_text or ""

    if not written_text or len(written_text.strip()) < 100:
        return {"skipped": True, "reason": "正文不足"}

    outline = bundle.outline_text or ""
    source = "author" if outline.strip() else "inferred"

    # ---- 有大纲：直接转化 + 校对（轻量，可不调 LLM）----
    if source == "author":
        intent = ChapterIntent(
            source="author",
            confidence=0.85,
            arc=_extract_arc_from_outline(outline),
            setup_points=_extract_setup_points(bundle),
            must_hits=_get_must_hits(bundle),
            foreshadows=_get_foreshadows(bundle),
            deviations=[],  # 有大纲时偏差少，省 LLM
        )
        await repo.set_intent(chapter_id, intent)
        return {"source": "author", "confidence": 0.85}

    # ---- 无大纲：LLM 反推 ----
    nutrients = bundle.nutrients()
    soft = bundle.soft_constraints()
    sys_p, usr_p = build_intent_inference_prompt(written_text, outline, nutrients, soft)
    try:
        result = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=usr_p,
            # 意图反推是归纳/判断任务（推断本章弧线、情绪曲线、标注偏差），
            # 属分析型工作，走 reasoning 槽并保留 thinking（不传 REASONING_DISABLED）。
            # 此前用 creative + 关 thinking，是「用生成配置干分析的活」。
            # 此为后台异步任务（heartbeat 触发），延迟不敏感；只在大纲为空时才调。
            model_type="reasoning",
            temperature=0.2,
            max_tokens=budget_tokens,
        )
        get_adaptive_recorder(str(chapter_id)).record_result(
            "adaptive.intent_inference", result, model_slot="reasoning")
        parsed = parse_json_safe(result.content or "") or {}
        intent = ChapterIntent(
            source="inferred",
            confidence=0.55,
            arc=parsed.get("arc", ""),
            emotion_curve=parsed.get("emotion_curve", []),
            setup_points=parsed.get("setup_points", []),
            must_hits=_get_must_hits(bundle),
            foreshadows=_get_foreshadows(bundle),
            deviations=parsed.get("deviations", []),
        )
        await repo.set_intent(chapter_id, intent)
        return {"source": "inferred", "confidence": 0.55, "arc": intent.arc}
    except Exception as e:
        logger.warning(f"[intent_inference] LLM 反推失败: {e}")
        return {"error": str(e)}


def _extract_arc_from_outline(outline: str) -> str:
    """从大纲提取一句话弧线（取首段，截断）。"""
    first = outline.strip().split("\n")[0][:120]
    return first


def _extract_setup_points(bundle) -> list:
    """铺陈要点（从章节卡或大纲提取）。"""
    cc = bundle.chapter_card
    if cc and getattr(cc, "must_hit_events", None):
        return [e.get("event", "") if isinstance(e, dict) else str(e) for e in cc.must_hit_events[:4]]
    return []


def _get_must_hits(bundle) -> list:
    cc = bundle.chapter_card
    if not cc:
        return []
    return [e.get("event", "") if isinstance(e, dict) else str(e) for e in (cc.must_hit_events or [])[:6]]


def _get_foreshadows(bundle) -> list:
    cc = bundle.chapter_card
    if not cc:
        return []
    ops = cc.foreshadow_ops or []
    return [f"{o.get('action', '')} {o.get('note', '')}".strip() if isinstance(o, dict) else str(o) for o in ops[:4]]
