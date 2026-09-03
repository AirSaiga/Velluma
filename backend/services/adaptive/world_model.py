# Velluma - NLE-ADF 3.0 世界模型 Repository
# AGPL-3.0
"""
世界模型的持久化访问层。

三层信度的章级状态容器（见 models.WorldModelORM）：
- layer1_facts：已写事实（沉淀追加，不可变）
- layer2_intent：意图推断（可变，version 递增）
- layer3_projections：未来推测（可变，懒更新）

所有组件经此读写世界模型，保证一致性与版本管理。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import WorldModelORM


# ============================================================
# 数据容器（组件间传递的快照）
# ============================================================

@dataclass
class SettledSegment:
    """层 1 单元：一段已锁死的正文 + 涌现实体。"""
    text: str
    entities: List[Dict] = field(default_factory=list)      # [{name, type, description}]
    state_changes: List[Dict] = field(default_factory=list) # [{entity, field, from, to}]
    settled_at: float = 0.0
    word_count: int = 0


@dataclass
class ChapterIntent:
    """层 2：系统对本章意图的理解。"""
    source: str = "none"  # author（大纲/打算转化）| inferred（正文反推）| none
    confidence: float = 0.0
    arc: str = ""               # 章节弧线一句话（"林尘发现真相并决定反抗"）
    emotion_curve: List[Dict] = field(default_factory=list)  # [{phase, emotion, energy}]
    setup_points: List[str] = field(default_factory=list)    # 本章应铺陈的要点
    must_hits: List[str] = field(default_factory=list)       # 必达事件（来自 ChapterCard）
    foreshadows: List[str] = field(default_factory=list)     # 伏笔操作
    deviations: List[str] = field(default_factory=list)      # 与 must_hits 的偏差（校对产出）
    # 意图加固（2026-09-03 意图入舱批次）：
    # next_direction = 窄问题「接下来这一步往哪走」——dock toward_beat 猜测兜底的
    # 素材源（arc 是章级弧线，舱要的是步级方向）；evidence = 反推依据的正文原句，
    # 组件侧代码回查（编造依据即降信度，见 intent_inference._valid_evidence）
    next_direction: str = ""
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "source": self.source, "confidence": self.confidence,
            "arc": self.arc, "emotion_curve": self.emotion_curve,
            "setup_points": self.setup_points, "must_hits": self.must_hits,
            "foreshadows": self.foreshadows, "deviations": self.deviations,
            "next_direction": self.next_direction, "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ChapterIntent":
        return cls(
            source=d.get("source", "none"),
            confidence=d.get("confidence", 0.0),
            arc=d.get("arc", ""),
            emotion_curve=d.get("emotion_curve", []),
            setup_points=d.get("setup_points", []),
            must_hits=d.get("must_hits", []),
            foreshadows=d.get("foreshadows", []),
            deviations=d.get("deviations", []),
            # 存量 layer2 无新键 → 缺省空（零迁移）
            next_direction=d.get("next_direction", ""),
            evidence=d.get("evidence", []),
        )


@dataclass
class SegmentProjection:
    """层 3 单元：对接下来可能写什么的概率推测。"""
    possible_beats: List[Dict] = field(default_factory=list)  # [{event, anchors, emotion}]
    confidence: float = 0.0
    signature: str = ""  # 内容签名（懒加载判断是否需重算）

    def to_dict(self) -> Dict:
        return {"possible_beats": self.possible_beats, "confidence": self.confidence, "signature": self.signature}


# ============================================================
# Repository
# ============================================================

class WorldModelRepository:
    """世界模型 CRUD + 三层读写 + 版本管理。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, chapter_id: str) -> WorldModelORM:
        """获取或创建章节的世界模型（每章唯一）。

        并发安全：心跳主 session 和后台 task 的独立 session 可能同时调本方法，
        两个都查到"不存在"并 INSERT → 第二个撞唯一约束。捕获 IntegrityError
        后回滚并重新 SELECT（另一个并发请求已创建好）。
        """
        result = await self.db.execute(
            select(WorldModelORM).where(WorldModelORM.chapter_id == chapter_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            try:
                model = WorldModelORM(
                    chapter_id=chapter_id,
                    layer1_facts=[],
                    layer2_intent={},
                    layer3_projections=[],
                    intent_version=0,
                    last_inference_ts=0.0,
                    last_dock_sig="",
                )
                self.db.add(model)
                await self.db.flush()
            except Exception:
                # 并发竞态：另一个 session 已插入（唯一约束冲突）→ 回滚待写，重新查
                await self.db.rollback()
                result = await self.db.execute(
                    select(WorldModelORM).where(WorldModelORM.chapter_id == chapter_id)
                )
                model = result.scalar_one()
        return model

    # ---- 层 1：已写事实（追加式，不可变）----

    async def append_fact(self, chapter_id: str, segment: SettledSegment) -> None:
        """追加一段已锁死的事实到层 1。

        精确去重：与最后一条事实规范化文本相同（连续沉淀同一段——2026-08
        事故现场 4 秒内沉淀两次）则跳过，不产生重复账。
        """
        from backend.services.adaptive.paragraph_source import normalize_for_match
        model = await self.get_or_create(chapter_id)
        facts = list(model.layer1_facts or [])
        new_norm = normalize_for_match(segment.text or "")
        if new_norm and facts:
            last = facts[-1]
            if isinstance(last, dict) and normalize_for_match(last.get("text", "") or "") == new_norm:
                return
        facts.append({
            "text": segment.text,
            "entities": segment.entities,
            "state_changes": segment.state_changes,
            "settled_at": segment.settled_at or time.time(),
            "word_count": segment.word_count or len(segment.text),
        })
        model.layer1_facts = facts

    async def get_facts(self, chapter_id: str) -> List[Dict]:
        model = await self.get_or_create(chapter_id)
        return list(model.layer1_facts or [])

    async def get_full_text(self, chapter_id: str) -> str:
        """层 1 全文（已锁段落拼接，用于后处理）。"""
        facts = await self.get_facts(chapter_id)
        return "\n\n".join(f["text"] for f in facts if f.get("text"))

    # ---- 层 2：意图推断（覆盖式，version 递增）----

    async def set_intent(self, chapter_id: str, intent: ChapterIntent) -> None:
        """覆盖层 2 意图，递增 version + 更新时间戳。"""
        model = await self.get_or_create(chapter_id)
        model.layer2_intent = intent.to_dict()
        model.intent_version = (model.intent_version or 0) + 1
        model.last_inference_ts = time.time()

    async def get_intent(self, chapter_id: str) -> ChapterIntent:
        model = await self.get_or_create(chapter_id)
        return ChapterIntent.from_dict(model.layer2_intent or {})

    async def intent_age_seconds(self, chapter_id: str) -> float:
        """距上次意图重算的秒数（调度器节流用）。"""
        model = await self.get_or_create(chapter_id)
        return time.time() - (model.last_inference_ts or 0)

    # ---- 层 3：未来推测（覆盖式）----

    async def set_projections(self, chapter_id: str, projections: List[SegmentProjection]) -> None:
        """覆写层 3 推测，保留挂件/感知带缓存标记项。

        layer3 同时是 __dock__/__canon_watch__ 缓存的载体（ORM 无专门字段）——
        整列覆盖会把缓存清掉：调度器刚判完「缓存命中复用」，路由却取不到件。
        标记项由各自组件的 _cache_* 自行更替，推测覆写不碰。
        """
        model = await self.get_or_create(chapter_id)
        kept = [
            p for p in (model.layer3_projections or [])
            if isinstance(p, dict) and (p.get("__dock__") or p.get("__canon_watch__"))
        ]
        model.layer3_projections = [p.to_dict() for p in projections] + kept

    async def get_projections(self, chapter_id: str) -> List[Dict]:
        model = await self.get_or_create(chapter_id)
        return list(model.layer3_projections or [])

    # ---- 挂件懒加载签名（projection 没变就不重算挂件）----

    async def get_dock_sig(self, chapter_id: str) -> str:
        model = await self.get_or_create(chapter_id)
        return model.last_dock_sig or ""

    async def set_dock_sig(self, chapter_id: str, sig: str) -> None:
        model = await self.get_or_create(chapter_id)
        model.last_dock_sig = sig

    # ---- 快照（组件只读，不持锁）----

    async def snapshot(self, chapter_id: str) -> Dict[str, Any]:
        """返回完整世界模型快照（组件读输入用）。

        层 1 事实带派生活性：规范化文本仍是画布全文的子串 = 活，否则过期
        （作者删改重写后事实即过期——2026-08 事故加固，活性现算不回写，
        作者把删掉的段落贴回来事实自动复活）。fact_count / total_words /
        live_facts 只计活事实；facts 原样返回全量（沉淀去重等历史语义仍用）。
        """
        model = await self.get_or_create(chapter_id)
        facts = [f for f in (model.layer1_facts or []) if isinstance(f, dict)]
        live_facts: List[Dict] = []
        stale_count = 0
        canvas_norm = ""
        try:
            from backend.models import Chapter as _Chapter
            from backend.services.adaptive.paragraph_source import (
                normalize_for_match, written_text,
            )
            ch = await self.db.get(_Chapter, chapter_id)
            canvas_norm = normalize_for_match(written_text(getattr(ch, "content_text", "") or ""))
        except Exception:
            canvas_norm = ""
        for f in facts:
            n = normalize_for_match(f.get("text", "") or "")
            if n and n not in canvas_norm:
                stale_count += 1
                continue
            live_facts.append(f)
        return {
            "facts": facts,
            "live_facts": live_facts,
            "stale_fact_count": stale_count,
            "intent": model.layer2_intent or {},
            "projections": list(model.layer3_projections or []),
            "intent_version": model.intent_version or 0,
            "fact_count": len(live_facts),
            "total_words": sum((f.get("word_count", 0) for f in live_facts), 0),
        }
