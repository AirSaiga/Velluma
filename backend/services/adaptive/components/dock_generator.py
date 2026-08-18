# Velluma - NLE-ADF 3.0 挂件生发组件
# AGPL-3.0
"""
基于层 3 推测 + 设定养料，LLM 生发 3-4 个镜头特写挂件。

挂件是 6-12 字的物理画面碎片（"老烟用残手砸灭油灯"），不是角色名罗列、
不是抽象建议。作者吸附挂件 + Space 微缝合。

校对：挂件 vs 禁词/canon private/character static_prompt——违规挂件丢弃。
懒加载：projection 签名没变就不重算（orchestrator 据此判断）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.adaptive.observing import get_adaptive_recorder
from backend.services.prompts.adaptive_prompts import build_dock_generator_prompt
from backend.services.utils.json_safe import parse_json_safe

logger = logging.getLogger(__name__)


async def _spine_intent(chapter_id: str, db) -> str:
    """章级谋篇意图一行（P1.4 M2；chapters 主键单行取，开销可忽略）。

    只在意图存在时返回；无脉络/查询失败返回空串（prompt 零变化）。
    """
    try:
        from backend.models import Chapter as _Chapter
        ch = await db.get(_Chapter, chapter_id)
        if ch is not None and isinstance(ch.spine, dict):
            return (ch.spine.get("intent") or {}).get("text", "") or ""
    except Exception:
        pass
    return ""


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 1500, **kw) -> Dict:
    """挂件生发。由 orchestrator 调度，产出写回世界模型缓存。

    kw 可带 direction_weights（5 叙事方向权重），碎片按此分布生成并自标 direction。
    """
    direction_weights = kw.get("direction_weights") or None
    bundle = await load_chapter_settings_bundle(chapter_id, db)

    # 取作者当前段落（从 content_text 尾部，或最近事实）
    recent_text = (bundle.content_text or "")[-500:]
    facts = model_snapshot.get("facts", [])
    if facts:
        recent_text = facts[-1].get("text", "")[-500:] or recent_text
    if not recent_text or len(recent_text) < 30:
        return {"skipped": True, "reason": "正文不足"}

    projections = model_snapshot.get("projections", [])
    nutrients = bundle.nutrients()
    hard = bundle.hard_constraints()
    soft = bundle.soft_constraints()

    # 前情召回（记忆倒灌）：让「呼应前情细节」类零件有素材；失败降级为空不阻塞
    from backend.services.rag.recall import recall_memories
    memory_echoes = await recall_memories(
        db,
        book_id=bundle.book_id or "",
        chapter_id=chapter_id,
        chapter_number=bundle.chapter_number,
        query_text=recent_text[-300:],
        k=2,
    )

    sys_p, usr_p = build_dock_generator_prompt(
        recent_text, projections, nutrients, hard,
        direction_weights=direction_weights,
        reader_expectations=soft.get("reader_expectations") or None,
        memory_echoes=memory_echoes or None,
        spine_intent=await _spine_intent(chapter_id, db),
    )

    try:
        result = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=usr_p,
            model_type="creative",
            temperature=0.75,
            max_tokens=budget_tokens,
            reasoning_config=REASONING_DISABLED,
        )
        get_adaptive_recorder(str(chapter_id)).record_result(
            "adaptive.dock_generator", result, model_slot="creative")
        parsed = parse_json_safe(result.content or "") or {}
        raw_parts = parsed.get("parts", [])

        # ---- 校对：丢弃违规挂件 + direction 合法性 ----
        valid_parts: List[Dict] = []
        icon_map = {"action": "👤", "scene": "⚙️", "line": "💬"}
        for p in raw_parts[:4]:
            if not isinstance(p, dict):
                continue
            text = (p.get("text", "") or "").strip()
            if not text or len(text) < 2:
                continue
            # 禁词 / canon private 拦截
            if _violates(text, hard):
                continue
            kind = p.get("type", "action")
            # direction 校验：必须是 5 方向之一，否则回退到"环境"
            direction = p.get("direction", "环境")
            if direction not in ("主线", "伏笔", "刻画", "环境", "关系"):
                direction = "环境"
            # 截断到 16 字（prompt 允许 8-14 字，留余量防超长产出被生生截断）
            safe_text = text[:16]
            valid_parts.append({
                "key": f"{kind}:{safe_text[:12]}",
                "kind": kind,
                "icon": icon_map.get(kind, "✨"),
                "text": safe_text,
                "direction": direction,
                # 期待账本衍生件标记（前端 Dock 显示「期待」tag）；
                # LLM 未标 from_expectation 则无此键——优雅降级为普通零件
                **({"origin": "expectation"} if p.get("from_expectation") else {}),
            })

        # 挂件产出缓存到世界模型（前端 heartbeat 响应里取）
        from backend.services.adaptive.world_model import WorldModelRepository
        repo = WorldModelRepository(db)
        sig = "|".join(p["key"] for p in valid_parts)
        await repo.set_dock_sig(chapter_id, sig)

        # 临时缓存挂件（写到一个临时字段供心跳读取——复用 layer3 的 metadata 思路）
        # 这里直接通过 db session 写一个内存 dict 给路由层取（路由层会重新拉一次）
        # 实际上前端拿挂件是通过 heartbeat 响应，我们把挂件存进 ORM 的临时字段
        await _cache_dock_parts(db, chapter_id, valid_parts)

        return {"count": len(valid_parts)}
    except Exception as e:
        logger.warning(f"[dock_generator] 失败: {e}")
        return {"error": str(e)}


def _violates(text: str, hard: Dict) -> bool:
    """校对挂件是否违规（禁词 / canon private）。"""
    for label in hard.get("canon_private_labels", []):
        if label and len(label) >= 2 and label in text:
            return True
    for word in hard.get("banned_words", []):
        if word and len(word) >= 2 and word in text:
            return True
    return False


async def _cache_dock_parts(db, chapter_id: str, parts: List[Dict]):
    """把挂件缓存到世界模型（存 layer3_projections 的伴生字段）。

    由于 WorldModelORM 没有专门的 dock_parts 字段，复用 layer3_projections
    的最后一项作为缓存载体（带 __dock__ 标记，前端/路由据此识别）。
    """
    from sqlalchemy import select
    from backend.models import WorldModelORM
    result = await db.execute(select(WorldModelORM).where(WorldModelORM.chapter_id == chapter_id))
    model = result.scalar_one_or_none()
    if model is None:
        return
    # 挂件缓存放进 layer3_projections 末尾的特殊项
    projections = list(model.layer3_projections or [])
    # 移除旧 dock 缓存
    projections = [p for p in projections if not (isinstance(p, dict) and p.get("__dock__"))]
    projections.append({"__dock__": True, "parts": parts, "ts": __import__("time").time()})
    model.layer3_projections = projections
