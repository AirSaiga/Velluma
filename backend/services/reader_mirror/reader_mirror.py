# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Reader Mirror 核心服务（V4.2 路径 B）。

职责：
- load_mirror / save_mirror：读写 Book.reader_mirror JSONB
- suggest_chapter_plan：基于当前期待状态生成本章规划建议（仪表盘输出）
- infer_expectations_from_chapter：从已发布章节自动推断期待（auto_inferred 层）
- update_expectation_after_chapter：章节生成后更新期待张力/状态

设计要点（第 7 轮修正）：
- 所有输出都是"建议"，不强制
- 显性作者声明永远优先于自动推断
- 推断失败空值填充，不阻塞生成
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Book
from backend.repositories import BookRepository
from backend.schemas.reader_mirror import (
    Expectation,
    ExpectationStatus,
    ExpectationSource,
    ChapterTensionSample,
    ChapterPlanSuggestion,
    ExpectationUpdate,
    ReaderMirrorSnapshot,
)

logger = logging.getLogger(__name__)


# ============================================================
# 加载 / 保存
# ============================================================

async def load_mirror(db: AsyncSession, book_id: UUID) -> Dict[str, Any]:
    """读取 Book.reader_mirror JSONB，返回 dict（空时返回默认结构）。"""
    repo = BookRepository(db)
    book = await repo.get_by_id(str(book_id))
    if not book:
        return _empty_mirror()
    raw = getattr(book, "reader_mirror", None) or {}
    if not isinstance(raw, dict):
        return _empty_mirror()
    # 保证三个 key 存在
    return {
        "expectations": raw.get("expectations") or [],
        "tension_curve": raw.get("tension_curve") or [],
        "information_asymmetries": raw.get("information_asymmetries") or [],
    }


async def save_mirror(db: AsyncSession, book_id: UUID, mirror: Dict[str, Any]) -> None:
    """保存 mirror 到 Book.reader_mirror JSONB。

    警示：JSONB mutable 必须重新赋值整个 dict 才能触发 SQLAlchemy dirty tracking。
    """
    repo = BookRepository(db)
    book = await repo.get_by_id(str(book_id))
    if not book:
        logger.warning(f"[ReaderMirror] 保存失败：book {book_id} 不存在")
        return
    # 关键：必须重新赋值整个 dict（不能 in-place 修改）
    book.reader_mirror = {
        "expectations": mirror.get("expectations") or [],
        "tension_curve": mirror.get("tension_curve") or [],
        "information_asymmetries": mirror.get("information_asymmetries") or [],
    }
    await db.commit()


def _empty_mirror() -> Dict[str, Any]:
    return {"expectations": [], "tension_curve": [], "information_asymmetries": []}


# ============================================================
# 章节规划建议（仪表盘输出）
# ============================================================

def suggest_chapter_plan(
    mirror: Dict[str, Any],
    chapter_number: int,
    volume_size: int = 12,
) -> ChapterPlanSuggestion:
    """基于当前期待状态生成本章规划建议。

    设计要点：
    - 纯算法（不调 LLM），快速
    - 输出是"建议"，作者可无视
    - 基于：期待张力 + 章节位置（爽点周期）+ 上次爽点距离

    Args:
        mirror: 全书 mirror dict
        chapter_number: 本章序号
        volume_size: 卷大小（默认 12 章/卷）

    Returns:
        ChapterPlanSuggestion
    """
    expectations = mirror.get("expectations") or []
    tension_curve = mirror.get("tension_curve") or []

    # 活跃期待（status in setup/accumulating）
    active = [
        e for e in expectations
        if e.get("status") in ("setup", "accumulating")
    ]

    # 高张力期待（tension >= 8，建议释放）
    high_tension = [e for e in active if e.get("current_tension", 5) >= 8]
    # 中张力期待（5-7，建议累积）
    mid_tension = [e for e in active if 5 <= e.get("current_tension", 5) < 8]
    # 低张力期待（< 5，建议 setup 阶段持续）
    low_tension = [e for e in active if e.get("current_tension", 5) < 5]

    # 爽点周期判断：距上次爽点章的距离
    payoff_chapters = [
        s.get("chapter_number") for s in tension_curve
        if s.get("is_payoff_chapter")
    ]
    last_payoff = max(payoff_chapters) if payoff_chapters else 0
    distance_since_payoff = chapter_number - last_payoff

    # 卷内位置（每 volume_size 章一卷，卷末前 1-2 章是 climax 区）
    offset_in_volume = (chapter_number - 1) % volume_size
    is_near_volume_end = offset_in_volume >= volume_size - 2

    # 决策逻辑（透明化）
    rationale_parts = []
    expectations_to_payoff = []
    expectations_to_accumulate = []
    expectations_to_setup = []
    suggested_tension = 5
    is_payoff_recommended = False

    if high_tension and (distance_since_payoff >= 5 or is_near_volume_end):
        # 高张力 + 距上次爽点 >= 5 章 或 卷末 → 建议释放
        expectations_to_payoff = [e["id"] for e in high_tension[:2]]
        suggested_tension = 9
        is_payoff_recommended = True
        rationale_parts.append(
            f"{len(high_tension)} 个期待张力 >= 8（已到临界），"
            f"距上次爽点 {distance_since_payoff} 章"
        )
    elif high_tension:
        # 高张力但时机未到 → 继续累积（卡爽点）
        expectations_to_accumulate = [e["id"] for e in high_tension]
        suggested_tension = 7
        rationale_parts.append(
            f"{len(high_tension)} 个高张力期待，但距上次爽点仅 {distance_since_payoff} 章，"
            f"建议继续累积（卡爽点）"
        )
    elif mid_tension:
        # 中张力 → 累积
        expectations_to_accumulate = [e["id"] for e in mid_tension]
        suggested_tension = 5
        rationale_parts.append(f"{len(mid_tension)} 个中张力期待，建议继续累积")
    else:
        # 无活跃或全低张力 → 建议新埋
        suggested_tension = 3
        rationale_parts.append("无高张力期待，建议本章埋新期待或推进低张力的")

    # 低张力的建议继续 setup
    expectations_to_setup = [e["id"] for e in low_tension]

    # 卷末特殊建议
    if is_near_volume_end and not is_payoff_recommended:
        rationale_parts.append("⚠ 卷末位置，强烈建议释放爽点")
        is_payoff_recommended = True
        suggested_tension = max(suggested_tension, 8)

    return ChapterPlanSuggestion(
        chapter_number=chapter_number,
        expectations_to_setup=expectations_to_setup,
        expectations_to_accumulate=expectations_to_accumulate,
        expectations_to_payoff=expectations_to_payoff,
        suggested_tension=suggested_tension,
        is_payoff_chapter_recommended=is_payoff_recommended,
        rationale="；".join(rationale_parts) if rationale_parts else "无特殊建议",
        author_override=None,
    )


# ============================================================
# 章节后更新（推断 + 应用作者声明）
# ============================================================

def update_expectation_after_chapter(
    mirror: Dict[str, Any],
    expectation_id: str,
    update: ExpectationUpdate,
) -> Dict[str, Any]:
    """章节生成后更新某个期待（累积/释放/反转）。

    Args:
        mirror: 全书 mirror（会被原地修改）
        expectation_id: 期待 id
        update: 更新请求

    Returns:
        更新后的 expectation dict
    """
    expectations = mirror.setdefault("expectations", [])
    for e in expectations:
        if e.get("id") == expectation_id:
            # 应用张力变化
            old_tension = e.get("current_tension", 5)
            new_tension = max(1, min(10, old_tension + update.tension_delta))
            e["current_tension"] = new_tension

            # 应用状态变化
            if update.new_status:
                e["status"] = update.new_status
                # 释放时张力归位
                if update.new_status == "payoff":
                    e["current_tension"] = max(1, new_tension - 5)

            # 记录历史
            history = e.setdefault("tension_history", [])
            history.append({
                "chapter": update.chapter_number,
                "tension": new_tension,
                "event": update.tension_event or f"tension {old_tension}→{new_tension}",
            })
            return e
    return {}


def infer_expectations_from_chapter(
    chapter_text: str,
    chapter_number: int,
    existing_expectations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """从章节正文启发式推断期待变化（v1 纯算法，无 LLM）。

    v1 策略（保守）：
    - 检测"打脸/羞辱/挑衅"等关键词 → revenge 类型期待 +1 张力
    - 检测"展露/爆发/真相"等关键词 → 满足相应期待
    - 不新建期待（避免误判），只更新已有的

    Returns:
        更新后的 expectations 列表（与 existing 同结构）
    """
    if not chapter_text or not existing_expectations:
        return existing_expectations

    # 关键词组（启发式，v1）
    accumulate_keywords = ["挑衅", "羞辱", "嘲讽", "蔑视", "压迫", "陷阱", "危机", "威胁"]
    payoff_keywords = ["打脸", "爆发", "展露", "真相", "反杀", "逆袭", "觉醒"]

    text_lower = chapter_text.lower()
    accumulate_hit = sum(1 for k in accumulate_keywords if k in chapter_text)
    payoff_hit = sum(1 for k in payoff_keywords if k in chapter_text)

    result = []
    for e in existing_expectations:
        e = dict(e)
        if e.get("status") in ("setup", "accumulating"):
            old_tension = e.get("current_tension", 5)
            # 简单线性推断
            delta = 0
            if accumulate_hit > 0 and e.get("type") in ("revenge", "power_reveal"):
                delta = min(2, accumulate_hit)
            if payoff_hit > 0 and e.get("type") in ("revenge", "power_reveal", "growth"):
                # 关键词命中 → 可能释放
                if old_tension >= 7:
                    e["status"] = "payoff"
                    e["current_tension"] = max(1, old_tension - 4)
                    e.setdefault("tension_history", []).append({
                        "chapter": chapter_number,
                        "tension": e["current_tension"],
                        "event": f"自动推断：释放（命中关键词 {payoff_hit}）",
                    })
                    result.append(e)
                    continue
            if delta:
                e["current_tension"] = max(1, min(10, old_tension + delta))
                e.setdefault("tension_history", []).append({
                    "chapter": chapter_number,
                    "tension": e["current_tension"],
                    "event": f"自动推断：累积 +{delta}（命中关键词 {accumulate_hit}）",
                })
        result.append(e)
    return result


# ============================================================
# 综合服务类
# ============================================================

class ReaderMirrorService:
    """Reader Mirror 综合服务（封装 db 操作）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_snapshot(self, book_id: UUID) -> Dict[str, Any]:
        """获取全书 mirror 快照。"""
        return await load_mirror(self.db, book_id)

    async def add_expectation(
        self,
        book_id: UUID,
        expectation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """添加期待（作者声明）。"""
        mirror = await load_mirror(self.db, book_id)
        expectations = mirror.setdefault("expectations", [])
        # 同 id 不重复
        if not any(e.get("id") == expectation.get("id") for e in expectations):
            expectations.append(expectation)
        await save_mirror(self.db, book_id, mirror)
        return expectation

    async def update_expectation(
        self,
        book_id: UUID,
        expectation_id: str,
        update: ExpectationUpdate,
    ) -> Dict[str, Any]:
        """更新期待。"""
        mirror = await load_mirror(self.db, book_id)
        updated = update_expectation_after_chapter(mirror, expectation_id, update)
        await save_mirror(self.db, book_id, mirror)
        return updated

    async def delete_expectation(self, book_id: UUID, expectation_id: str) -> bool:
        """删除期待。"""
        mirror = await load_mirror(self.db, book_id)
        before = len(mirror.get("expectations", []))
        mirror["expectations"] = [
            e for e in mirror.get("expectations", [])
            if e.get("id") != expectation_id
        ]
        await save_mirror(self.db, book_id, mirror)
        return len(mirror["expectations"]) < before

    async def get_chapter_plan(
        self,
        book_id: UUID,
        chapter_number: int,
    ) -> ChapterPlanSuggestion:
        """获取本章规划建议（仪表盘）。"""
        mirror = await load_mirror(self.db, book_id)
        return suggest_chapter_plan(mirror, chapter_number)

    async def record_chapter_tension(
        self,
        book_id: UUID,
        chapter_number: int,
        overall_tension: int,
        is_payoff: bool = False,
        note: str = "",
    ) -> None:
        """记录章节张力采样（章节生成后调用）。"""
        mirror = await load_mirror(self.db, book_id)
        curve = mirror.setdefault("tension_curve", [])
        # 移除同章号的旧采样
        curve = [s for s in curve if s.get("chapter_number") != chapter_number]
        active_count = sum(
            1 for e in mirror.get("expectations", [])
            if e.get("status") in ("setup", "accumulating")
        )
        curve.append({
            "chapter_number": chapter_number,
            "overall_tension": max(1, min(10, overall_tension)),
            "active_expectations": active_count,
            "is_payoff_chapter": is_payoff,
            "note": note,
        })
        curve.sort(key=lambda s: s.get("chapter_number", 0))
        mirror["tension_curve"] = curve
        await save_mirror(self.db, book_id, mirror)

    async def update_after_chapter_published(
        self,
        book_id: UUID,
        chapter_number: int,
        chapter_text: str,
    ) -> Dict[str, Any]:
        """章节发布后：自动推断期待变化 + 记录张力。

        Returns:
            更新后的 mirror
        """
        mirror = await load_mirror(self.db, book_id)
        # 推断期待变化
        updated_exp = infer_expectations_from_chapter(
            chapter_text, chapter_number, mirror.get("expectations", []),
        )
        mirror["expectations"] = updated_exp
        await save_mirror(self.db, book_id, mirror)
        return mirror
