# Velluma - NLE-ADF 3.0 沉淀倒灌组件
# AGPL-3.0
"""
段落锁死时触发：从锁死正文抽涌现实体/关系/状态变化，可选落库。

复用 extract_emergent_facts（memory_ingestion），但加冲突检测：
抽取的实体 vs 现有角色/资产设定——冲突不自动改，标记浮给作者（作者主权）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.workflows.bsadf.memory_ingestion import extract_emergent_facts

logger = logging.getLogger(__name__)


async def run(
    chapter_id: str,
    db,
    model_snapshot: Dict,
    budget_tokens: int = 1500,
    commit: bool = False,
    **kw,
) -> Dict:
    """沉淀倒灌。由 orchestrator.on_settle 调度。

    Args:
        commit: 是否落库涌现实体（作者确认后 true）。默认 false——只抽取标记，不写设定库。
    """
    # 取最新锁死的事实
    facts = model_snapshot.get("facts", [])
    if not facts:
        return {"skipped": True}
    latest = facts[-1]
    text = latest.get("text", "")
    if not text:
        return {"skipped": True}

    # 抽涌现实体（复用既有 LLM 组件）
    facts_data = await extract_emergent_facts(text, beat_id=f"settle_{chapter_id[:8]}")
    facts_dict = facts_data.to_dict()

    # ---- 冲突检测：抽取实体 vs 现有设定 ----
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    conflicts = _detect_conflicts(facts_dict, bundle)

    # ---- 可选落库 ----
    committed = None
    if commit and not conflicts and bundle.book_id:
        try:
            committed = await _commit(db, bundle, text, facts_dict)
        except Exception as e:
            logger.warning(f"[sediment] 落库失败（不影响抽取结果返回）: {e}")

    return {
        "emergent_facts": facts_dict,
        "conflicts": conflicts,
        "committed": committed,
    }


def _detect_conflicts(facts_dict: Dict, bundle) -> List[Dict]:
    """检测抽取实体与现有设定的冲突（不自动改，标记浮给作者）。"""
    conflicts: List[Dict] = []
    existing_chars = {}
    for ent in bundle.entities:
        name = getattr(getattr(ent, "character", None), "name", "") or ""
        static = getattr(getattr(ent, "character", None), "static_prompt", "") or ""
        if name:
            existing_chars[name] = static

    for new_ent in (facts_dict.get("new_entities") or [])[:5]:
        if not isinstance(new_ent, dict):
            continue
        name = new_ent.get("name", "")
        desc = new_ent.get("description", "")
        if name in existing_chars:
            existing_desc = existing_chars[name]
            # 简单冲突检测：描述里有明显矛盾词（如已有"右手残疾"，新提"右手"动作）
            if existing_desc and _has_contradiction(existing_desc, desc):
                conflicts.append({
                    "entity": name,
                    "existing": existing_desc[:80],
                    "new": desc[:80],
                    "type": "character_contradiction",
                })
    return conflicts


def _has_contradiction(existing: str, new: str) -> bool:
    """简单矛盾检测：左右手/死活/有无 等成对矛盾词。"""
    pairs = [("左手", "右手"), ("活", "死"), ("有", "无"), ("年轻", "老")]
    for a, b in pairs:
        if (a in existing and b in new) or (b in existing and a in new):
            return True
    return False


async def _commit(db, bundle, raw_text: str, facts_dict: Dict) -> Dict:
    """落库（复用 content_extractor.commit_extraction 轻量子集）。

    关系键名与 commit_extraction 对齐（source_name/target_name/relation_type/
    description）——历史上这里曾发 {source,target,type}，旧实现读不到键名，
    沉淀路径的关系被静默丢弃（已修，两侧统一）。
    """
    from backend.services.extraction.content_extractor import commit_extraction, ExtractionResult
    from uuid import UUID
    confirmed = ExtractionResult(
        characters=facts_dict.get("new_entities", []),
        relationships=[
            {
                "source_name": r.get("from", ""),
                "target_name": r.get("to", ""),
                "relation_type": "custom",
                "description": r.get("change", ""),
            }
            for r in (facts_dict.get("relationship_changes") or [])
        ],
        locations=facts_dict.get("new_locations", []),
        assets=[],
        foreshadows=[],
    )
    return await commit_extraction(
        db=db,
        book_id=UUID(bundle.book_id),
        chapter_id=UUID(bundle.chapter_id),
        chapter_number=bundle.chapter_number or 1,
        confirmed=confirmed,
        raw_text=raw_text,
    )
