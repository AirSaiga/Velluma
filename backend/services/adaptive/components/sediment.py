# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 沉淀倒灌组件
"""
段落锁死时触发：从锁死正文抽涌现实体/关系/状态变化，可选落库。

复用 extract_emergent_facts（memory_ingestion），但加冲突检测：
抽取的实体 vs 现有角色/资产设定——冲突不自动改，标记浮给作者（作者主权）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.adaptive.observing import get_adaptive_recorder
from backend.services.adaptive.emergent_facts import extract_emergent_facts

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

    # 抽涌现实体（复用既有 LLM 组件；chapter 级 recorder 记账）
    facts_data = await extract_emergent_facts(
        text,
        beat_id=f"settle_{chapter_id[:8]}",
        recorder=get_adaptive_recorder(str(chapter_id)),
    )
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
            # 矛盾判定（2026-08-29 重写，详见 _find_contradiction）
            if existing_desc:
                pair = _find_contradiction(existing_desc, desc)
                if pair:
                    conflicts.append({
                        "entity": name,
                        "existing": existing_desc[:80],
                        "new": desc[:80],
                        "type": "character_contradiction",
                        # 点名矛盾词对（前端卡片直读——作者第一眼看到「矛盾在哪」
                        # 而不是两段埋着触发词的原文互相面面相觑）
                        "pair": [pair[0], pair[1]],
                    })
    return conflicts


# 成对矛盾词（2026-08-29 重写）：旧清单 [("左手","右手"),("活","死"),("有","无"),
# ("年轻","老")] 裸子串查单字——「生活」×「死寂」、「没有」×「毫无」、「老周」×
# 「年轻」全都成对命中，矛盾卡遍地误报且作者看不出哪里矛盾（实测事故）；且
# 左手/右手这对语义是反的（设定「左手残疾」+正文「用右手」是一致不是矛盾）。
# 新纪律：
# 1. 只留**死活对**——设定已死/阵亡/牺牲 vs 正文活着行动，语义无歧义、价值
#    最高（死者开口类）；肢体侧别/年龄对退役（正确的残障矛盾判定需要语义
#    读取，词对凑不出来，硬凑就是误报）；
# 2. 全部 ≥2 字 + 分词 token 边界匹配（连续 token 拼接恰为该词），杜绝
#    「毫无」命中「无」这类嵌词误报；jieba 不可用退回子串（柔性红线）。
_CONTRA_PAIRS: List[tuple] = [
    ("活着", "已死"), ("活着", "死了"), ("活着", "阵亡"), ("活着", "牺牲"),
]


def _token_list(text: str) -> List[str] | None:
    """jieba 分词；失败返回 None（调用方回退子串匹配）。"""
    try:
        import jieba
        return jieba.lcut(text)
    except Exception:
        return None


def _term_hit(term: str, text: str, tokens: List[str] | None) -> bool:
    """词以完整分词边界出现（连续 token 拼接恰为该词）。

    tokens 不可用时退回裸子串——term 均 ≥2 字，误报面已比旧单字对小一个
    数量级，柔性红线（检测器宁可用不完美判据也不整体失明）。
    """
    if tokens is None:
        return term in text
    if term not in "".join(tokens):
        return False  # 快速预筛：拼接串里没有就不必滑窗
    for i in range(len(tokens)):
        seg = ""
        for j in range(i, len(tokens)):
            seg += tokens[j]
            if len(seg) >= len(term):
                break
        if seg == term:
            return True
    return False


def _find_contradiction(existing: str, new: str):
    """成对矛盾词检测：命中返回 (设定侧词, 正文侧词)，未命中返回 None。"""
    ex_tokens = _token_list(existing)
    new_tokens = _token_list(new)
    for a, b in _CONTRA_PAIRS:
        if _term_hit(a, existing, ex_tokens) and _term_hit(b, new, new_tokens):
            return (a, b)   # a 出现在设定、b 出现在正文
        if _term_hit(b, existing, ex_tokens) and _term_hit(a, new, new_tokens):
            return (b, a)   # 反向：b 在设定、a 在正文
    return None


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
