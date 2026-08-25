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
from backend.services.adaptive.observing import get_adaptive_recorder
from backend.services.prompts.adaptive_prompts import build_future_projection_prompt
from backend.services.adaptive.world_model import WorldModelRepository, SegmentProjection
from backend.services.utils.json_safe import parse_json_safe

logger = logging.getLogger(__name__)


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 1500, **kw) -> Dict:
    """未来推测。由 orchestrator 调度。"""
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    repo = WorldModelRepository(db)

    # 已写正文：画布全文（剥 HTML）尾部——画布即事实源，写到画布即已写
    # （无论是否沉淀）。层 1 事实是沉淀审计账，作者删改后即过期，
    # 不得代替正文（曾致推测锚定已删除文本）
    from backend.services.adaptive.paragraph_source import written_text
    written = written_text(bundle.content_text or "")[-2000:]
    if not written:
        return {"skipped": True, "reason": "无已写正文"}

    intent = model_snapshot.get("intent", {})
    if intent.get("source", "none") == "none":
        return {"skipped": True, "reason": "无意图（层 2 空）"}

    nutrients = bundle.nutrients()
    soft = bundle.soft_constraints()

    # 章级软脉络（P1.4 M2）：pending 锚点注入推测 prompt——走向卡挂脉络。
    # 无脉络/无 pending 锚点 → spine_anchors=None，prompt 与旧版逐字节一致
    spine_anchors = None
    try:
        from backend.models import Chapter as _Chapter
        ch = await db.get(_Chapter, chapter_id)
        if ch is not None and isinstance(ch.spine, dict):
            pending = [
                {"id": a.get("id", ""), "text": a.get("text", "")}
                for a in ch.spine.get("anchors", [])
                if isinstance(a, dict) and a.get("status") == "pending" and a.get("text")
            ]
            if pending:
                spine_anchors = pending
    except Exception as e:
        logger.debug(f"[future_projection] 读 spine 失败（跳过注入）: {e}")

    # W5 桥：地图相遇机会（此刻同地角色组，纯推演零 LLM）注入推测——
    # 世界沙盘开始喂养走向卡（roadmap §3.2，验证指标=from_encounter 卡的采纳率）
    _encounter_lines: List[str] = []
    try:
        from backend.models import Chapter as _Chapter
        from backend.services.world.scene_slice import build_scene_slice

        ch = await db.get(_Chapter, chapter_id)
        if ch is not None and bundle.book_id:
            slice_data = await build_scene_slice(db, str(bundle.book_id), ch)
            _encounter_lines = [
                f"{'与'.join(e.get('names', [])[:3])}（{e.get('location_name') or '某处'}）"
                for e in (slice_data.get("encounters") or [])
            ]
    except Exception as e:
        logger.debug(f"[future_projection] 相遇机会读取失败（跳过注入）: {e}")

    sys_p, usr_p = build_future_projection_prompt(written, intent, nutrients, soft, spine_anchors=spine_anchors, encounters=_encounter_lines)

    try:
        result = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=usr_p,
            model_type="creative",
            temperature=0.6,
            max_tokens=budget_tokens,
            reasoning_config=REASONING_DISABLED,
        )
        get_adaptive_recorder(str(chapter_id)).record_result(
            "adaptive.future_projection", result, model_slot="creative")
        parsed = parse_json_safe(result.content or "") or {}
        raw_projections = parsed.get("projections", [])

        # ---- 校对：丢弃违规推测 ----
        hard = bundle.hard_constraints()
        valid_ids = {a["id"] for a in (spine_anchors or [])}
        valid: List[SegmentProjection] = []
        for proj in raw_projections[:3]:
            if not isinstance(proj, dict):
                continue
            # 检查 event/anchors 是否触碰 canon private 或违背 public
            text_to_check = proj.get("event", "") + " " + " ".join(proj.get("anchors", []))
            if _violates_constraints(text_to_check, hard):
                continue
            # serves_anchor 代码闸门（不信任 prompt 约束，DDE 同思想）：
            # 非命中本章 pending 锚点 id → 剥除（推测保留，挂载关系不保留）
            sa = proj.get("serves_anchor")
            if sa is not None and sa not in valid_ids:
                proj = {k: v for k, v in proj.items() if k != "serves_anchor"}
            # W5 桥：from_encounter 闸（必须严格布尔 true，其余剥除——防 LLM 乱标字符串）
            if proj.get("from_encounter") is not True:
                proj = {k: v for k, v in proj.items() if k != "from_encounter"}
            # 打上生成时的意图版本：调度器据此判「意图重算后旧推测过期」
            # （缺键=修复前的旧推测，心跳侧视为过期刷新一次）
            proj = {**proj, "intent_version": model_snapshot.get("intent_version", 0)}
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
    """校对：文本是否触碰 canon private 或含 blocker 级硬禁词。

    severity 分级同 dock_generator._violates：提醒级词不拦生成侧。
    """
    # private 标签词出现在文本里 = 泄密
    for label in hard.get("canon_private_labels", []):
        if label and len(label) >= 2 and label in text:
            return True
    # 硬禁词（提醒级只进 prompt/审计，不在此拦）
    if "banned_words_blocker" in hard:
        banned = hard.get("banned_words_blocker") or []
    else:
        banned = hard.get("banned_words", [])
    for word in banned:
        if word and len(word) >= 2 and word in text:
            return True
    return False


def _signature(proj: Dict) -> str:
    """推测内容签名（懒加载判断）。"""
    raw = proj.get("event", "") + str(proj.get("anchors", []))
    return hashlib.md5(raw.encode()).hexdigest()[:8]
