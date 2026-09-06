# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 自动阅读预算闸与幂等锚（「系统自己去读」的成本护栏）
"""
2026-08-25 战略定稿「系统自己去读」：观察触发权交给系统后，必须回答
「系统自己读 = 系统自己花 token」——本模块是这道闸。

三层防护（全部宁错放勿错杀的反直觉面：宁可不读，也不多花钱）：
1. 幂等锚：chapters.auto_read_state 内容哈希——正文没变就不重读
   （切章随处发枪、全书通读刷新重跑，都安全幂等）。实体抽取用独立键
   entities_hash（阶段 A 与阶段 B 互不封锁）。
2. 章级最小间隔：同章**同阶段**两次自动阅读 ≥300s（防开关章抖动连发）。
   间隔时间戳同样按阶段分键——事件读 last_run_at、实体读 entities_last_run_at
   （2026-08-26 修复：共享 last_run_at 时阶段 A 跑完 300s 内阶段 B 全部
   too_soon 静默空跑，与「互不封锁」的文档承诺相悖；旧数据里阶段 A 写过的
   last_run_at 只影响事件侧 ≤300s，过期自然失效，无需迁移）。
3. 每书每日上限：滚动 24h 窗口内自动观察类 LLM 调用 ≤30（口径：
   event_scout.auto_read + loop3.emergent_facts——后者与手动沉淀的涌现
   抽取共用 stage，故手动沉淀也占用本池；沉淀是低频手动动作，可接受，
   注释留证）。计数走 generation_runs 既有台账（经 chapters 归书），零新表。

decide_auto_read 是纯函数（单测锚点）；async 装配层负责取数。
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chapter, GenerationRun

logger = logging.getLogger(__name__)

AUTO_READ_MIN_TEXT = 100        # 正文太短不值得花一次 LLM
AUTO_READ_MIN_INTERVAL_S = 300  # 同章两次自动阅读最小间隔（秒）
AUTO_READ_DAILY_CAP = 30        # 每书滚动 24h 自动观察类调用上限

# 自动观察口径的 stage 集合（usage 拆账同源；新增自动观察组件时同步补这里）
_AUTO_STAGES = ("adaptive.event_scout.auto_read", "loop3.emergent_facts")

# 跳过短码 → 人话（作者语言；上屏原文可用）
AUTO_READ_SKIP_REASONS = {
    "short_text": "这章正文还太短，没什么好读的",
    "unchanged": "内容没变化，不用重读",
    "too_soon": "刚读过这章，歇一会儿再来",
    "daily_cap": "今天的自动阅读额度用完了，明天再来",
    "no_entities": "世界页还没有角色——先认人，AI 才能从正文发现世界变化",
}

_WS_RE = re.compile(r"\s+")


def content_fingerprint(text: str) -> str:
    """正文指纹：折叠空白后取 sha1——任何实义编辑都重新武装阅读闸。"""
    return hashlib.sha1(_WS_RE.sub("", text or "").encode("utf-8")).hexdigest()


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def decide_auto_read(
    *,
    text_len: int,
    state: Optional[Dict[str, Any]],
    fingerprint: str,
    hash_key: str = "hash",
    ts_key: str = "last_run_at",
    now: Optional[datetime] = None,
    daily_used: int = 0,
    force: bool = False,
) -> Tuple[bool, Optional[str]]:
    """纯判定：该章此刻该不该自动读。返回 (该不该, 跳过短码)。

    判定序有语义：unchanged 先于 too_soon/daily_cap——「没变」是最常见静默出口，
    避免无事时也暴露预算信息；间隔闸只对「确实要读」的情况生效。
    hash_key / ts_key 成对使用（事件="hash"+"last_run_at"、实体="entities_hash"+
    "entities_last_run_at"）——幂等锚与间隔闸都按阶段独立，A/B 互不封锁。
    force=True（全书通读「重新认人」补救：刷新丢 review 状态后哈希全跳过的死局）
    只豁免 unchanged/too_soon 两道幂等闸；short_text 与 daily_cap 永远生效
    （防爆冲红线不因作者主动重跑而松动）。
    """
    if text_len < AUTO_READ_MIN_TEXT:
        return False, "short_text"
    if not force and state:
        if state.get(hash_key) == fingerprint:
            return False, "unchanged"
        last = _parse_ts(state.get(ts_key))
        now = now or datetime.now(timezone.utc)
        if last is not None and (now - last).total_seconds() < AUTO_READ_MIN_INTERVAL_S:
            return False, "too_soon"
    if daily_used >= AUTO_READ_DAILY_CAP:
        return False, "daily_cap"
    return True, None


async def count_auto_reads_24h(db: AsyncSession, book_id: str) -> int:
    """滚动 24h 窗口内该书自动观察类调用数（generation_runs 经 chapters 归书）。"""
    window_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    stmt = (
        select(func.count(GenerationRun.id))
        .join(Chapter, GenerationRun.chapter_id == Chapter.id)
        .where(
            Chapter.book_id == book_id,
            GenerationRun.created_at >= window_start,
            or_(*[GenerationRun.stage == s for s in _AUTO_STAGES]),
        )
    )
    return int((await db.execute(stmt)).scalar() or 0)
