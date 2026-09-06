# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 学着闭嘴（被拒学习）：辅助层提醒/候选的静音派生与宽恕复位
"""
作者拒绝历史 → 静音集合的唯一权威（2026-08-25 战略定稿「学着闭嘴」）。

设计立场：
- 静音状态永远从行为数据**派生**（候选裁决史 + collab 埋点拒收史），不落库——
  杜绝「静音态与行为历史漂移」。books.assist_mutes 只存**宽恕时间戳**：
  作者点「恢复」→ 该时刻前的拒绝记录一笔勾销，重新计数。
- 宁错放勿错杀（宁漏勿误的反向应用）：任一通道只要有 1 次采纳即不静音
  （一次肯定胜过三次否定）；裁决样本 <3 次永不静音。
- 安全类提醒（canon 泄露 leak / 矛盾 contradiction）**永不静音**——它们保护的
  是作者自己的秘密与一致性，作者主权不包括「让我看不见穿帮」。

通道与静音键：
- wevt:<event_type>  世界事件候选（event_scout 生成侧：prompt 排除 + 落池过滤）
- hint:<kind>        心跳感知带提醒（白名单 appearance/callback/style_drift/world_inbox；
                     未识别类别一律不可静音——保守方向）

数据来源：
- 世界候选裁决史：world_event_candidates.status（rejected 留痕不删除，天然教材）
- 提醒拒收史：data/collab_events.jsonl 的 hint_dismiss 事件（30 天窗口，过期原谅——
  收起是轻动作，不应终身监禁；事件候选的 ✗ 是重裁决，不适用时间窗）

缓存：心跳每 ~4s 进一次，静音集合按书缓存 60s（裁决行为变化最迟 60s 生效，
作者可接受）；宽恕/端点读取走 use_cache=False 即时生效。hint_dismiss 埋点
文件扫描按书缓存 30s（文件有 5MB 轮转上限，全扫有界）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Book, WorldEventCandidate

logger = logging.getLogger(__name__)

MUTE_PREFIX_EVENT = "wevt:"
MUTE_PREFIX_HINT = "hint:"

# 可静音的提醒类别白名单（未识别类别一律不可静音——保守方向；
# 与前端 features/workspace/presentation/PerceptionBand.vue 的 MUTEABLE_KINDS 同步，改任一侧先对拍）
HINT_MUTEABLE_KINDS = frozenset({"appearance", "callback", "style_drift", "world_inbox"})
# 安全类永不静音（泄露/矛盾是作者自己的秘密与一致性护栏）——仅作文档化标注，
# 代码闸是上面的白名单（不在白名单即不可静音）
HINT_NEVER_MUTE_KINDS = frozenset({"leak", "contradiction"})

_EVENT_MIN_DECIDED = 3   # 裁决样本下限（少于此次数永不静音）
_EVENT_MIN_REJECTS = 3   # 且零采纳才静音
_HINT_MIN_DISMISSES = 3  # 30 天窗口内收起 ≥3 次
_HINT_WINDOW_DAYS = 30

_MUTES_CACHE_TTL = 60.0
_HINT_SCAN_TTL = 30.0

# 事件类型 → 作者语言标签（与前端 world/engine/eventTemplates.ts 同词表，改任一侧先对拍）
_EVENT_TYPE_LABELS = {
    "birth": "出生",
    "move": "移动",
    "death": "死亡",
    "battle": "战役",
    "territory_change": "疆域变更",
    "found": "建立",
    "destroy": "毁灭",
    "alliance": "结盟",
    "war_declare": "宣战",
    "coronation": "即位",
    "custom": "自定义",
}
_HINT_KIND_LABELS = {
    "appearance": "角色出场提醒",
    "callback": "伏笔回收提醒",
    "style_drift": "文风偏离提醒",
    "world_inbox": "收件箱积压提醒",
}

_mutes_cache: Dict[str, Tuple[float, Set[str]]] = {}
_hint_scan_cache: Dict[str, Tuple[float, List[Tuple[datetime, str]]]] = {}


def event_mute_key(event_type: str) -> str:
    return MUTE_PREFIX_EVENT + str(event_type)


def hint_mute_key(kind: str) -> str:
    return MUTE_PREFIX_HINT + str(kind)


def muted_event_types(keys: Iterable[str]) -> Set[str]:
    """从静音键集合提取事件类型集合（event_scout 消费侧）。"""
    return {k[len(MUTE_PREFIX_EVENT):] for k in keys if k.startswith(MUTE_PREFIX_EVENT)}


# ============================================================
# 纯决策（单测锚点；宁错放勿错杀）
# ============================================================

def decide_event_type_mutes(counts: Mapping[str, Mapping[str, int]]) -> Set[str]:
    """事件类型静音判定：裁决样本 ≥3 且 ✗ ≥3 且 ✓ == 0 才静音。"""
    muted: Set[str] = set()
    for etype, c in counts.items():
        if not etype:
            continue
        rejected = int(c.get("rejected", 0) or 0)
        accepted = int(c.get("accepted", 0) or 0)
        if rejected + accepted < _EVENT_MIN_DECIDED:
            continue
        if rejected >= _EVENT_MIN_REJECTS and accepted == 0:
            muted.add(etype)
    return muted


def decide_hint_mutes(
    dismiss_counts: Mapping[str, int],
    *,
    muteable: Iterable[str] = HINT_MUTEABLE_KINDS,
) -> Set[str]:
    """提醒类别静音判定：窗口内收起 ≥3 次且类别在白名单内。"""
    allow = set(muteable)
    return {
        k for k, n in dismiss_counts.items()
        if k in allow and int(n or 0) >= _HINT_MIN_DISMISSES
    }


def describe_mute_keys(keys: Iterable[str]) -> List[Dict[str, str]]:
    """静音键 → 端点/上屏描述（作者语言标签）。"""
    out: List[Dict[str, str]] = []
    for key in sorted(set(keys)):
        if key.startswith(MUTE_PREFIX_EVENT):
            etype = key[len(MUTE_PREFIX_EVENT):]
            out.append({
                "key": key,
                "label": "世界候选·" + _EVENT_TYPE_LABELS.get(etype, etype),
                "channel": "inbox",
            })
        elif key.startswith(MUTE_PREFIX_HINT):
            kind = key[len(MUTE_PREFIX_HINT):]
            out.append({
                "key": key,
                "label": _HINT_KIND_LABELS.get(kind, kind),
                "channel": "hint",
            })
        else:
            out.append({"key": key, "label": key, "channel": "unknown"})
    return out


# ============================================================
# 数据加载（派生层）
# ============================================================

def _parse_ts(raw: Any) -> Optional[datetime]:
    """解析 ISO 时间戳为 aware datetime；naive 一律按 UTC（SQLite DateTime 无时区）。"""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _collab_paths() -> List[Path]:
    """collab 埋点文件路径（轮转份 + 当前份）。

    ⚠ 与 routes/chapter_generation/adaptive.py 的 _collab_events_path 同款推导，
    有意复制：services 层不反向 import routes 层。锚定项目根不随 CWD 漂移，
    尊重 VELLUMA_DATA_DIR 运行时覆盖。
    """
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    base = data_dir / "collab_events.jsonl"
    return [base.with_name(base.name + ".1"), base]


def _hint_dismiss_events(book_id: str) -> List[Tuple[datetime, str]]:
    """扫描 collab 埋点取该书的 hint_dismiss 事件 [(ts, kind)]（按书 30s 缓存）。"""
    now = time.monotonic()
    ent = _hint_scan_cache.get(book_id)
    if ent and now - ent[0] < _HINT_SCAN_TTL:
        return ent[1]
    events: List[Tuple[datetime, str]] = []
    for path in _collab_paths():
        try:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"hint_dismiss"' not in line:  # 快速预筛，减少 json 解析量
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") != "hint_dismiss":
                        continue
                    if str(e.get("book_id") or "") != str(book_id):
                        continue
                    kind = str((e.get("detail") or {}).get("kind") or "")
                    ts = _parse_ts(e.get("ts"))
                    if kind and ts is not None:
                        events.append((ts, kind))
        except Exception as e:
            logger.debug(f"[quiet_learning] 埋点扫描跳过损坏文件 {path}: {e}")
    _hint_scan_cache[book_id] = (now, events)
    return events


async def load_muted_keys(
    db: AsyncSession,
    book_id: str,
    *,
    use_cache: bool = True,
) -> Set[str]:
    """派生该书当前生效的静音键集合（60s 缓存；宽恕后 invalidate 即时生效）。

    失败静默降级为空集——学习链路故障绝不阻塞心跳/候选生产主流程。
    """
    book_id = str(book_id)
    now = time.monotonic()
    if use_cache:
        ent = _mutes_cache.get(book_id)
        if ent and now - ent[0] < _MUTES_CACHE_TTL:
            return ent[1]
    try:
        muted = await _compute_muted_keys(db, book_id)
    except Exception as e:
        logger.warning(f"[quiet_learning] 静音集派生失败（按无静音继续）: {e}")
        muted = set()
    _mutes_cache[book_id] = (now, muted)
    return muted


async def _compute_muted_keys(db: AsyncSession, book_id: str) -> Set[str]:
    book = await db.get(Book, book_id)
    forgiven: Dict[str, Any] = dict(getattr(book, "assist_mutes", None) or {}) if book else {}

    muted: Set[str] = set()

    # --- 通道一：世界候选裁决史（无时间窗——✗ 是重裁决；恢复走宽恕复位）
    rows = (
        await db.execute(
            select(
                WorldEventCandidate.status,
                WorldEventCandidate.draft,
                WorldEventCandidate.updated_at,
            ).where(
                WorldEventCandidate.book_id == book_id,
                WorldEventCandidate.status.in_(["accepted", "rejected"]),
            )
        )
    ).all()
    counts: Dict[str, Dict[str, int]] = {}
    for status, draft, updated_at in rows:
        etype = str((draft or {}).get("event_type") or "")
        if not etype:
            continue
        if (draft or {}).get("auto_reject"):
            continue  # 系统判重跳过的假拒绝（重复转正闸留痕）不是作者态度，不计入学习
        f = _parse_ts(forgiven.get(event_mute_key(etype)))
        decided_at = _parse_ts(updated_at)
        if f is not None and decided_at is not None and decided_at <= f:
            continue  # 宽恕时刻之前的裁决一笔勾销
        bucket = counts.setdefault(etype, {"accepted": 0, "rejected": 0})
        if status in bucket:
            bucket[status] += 1
    muted |= {event_mute_key(t) for t in decide_event_type_mutes(counts)}

    # --- 通道二：感知带提醒拒收史（30 天窗口，过期原谅）
    window_start = datetime.now(timezone.utc) - timedelta(days=_HINT_WINDOW_DAYS)
    dismiss_counts: Dict[str, int] = {}
    for ts, kind in _hint_dismiss_events(book_id):
        if kind not in HINT_MUTEABLE_KINDS:
            continue
        if ts < window_start:
            continue
        f = _parse_ts(forgiven.get(hint_mute_key(kind)))
        if f is not None and ts <= f:
            continue
        dismiss_counts[kind] = dismiss_counts.get(kind, 0) + 1
    muted |= {hint_mute_key(k) for k in decide_hint_mutes(dismiss_counts)}

    return muted


def invalidate_mutes_cache(book_id: str) -> None:
    """宽恕/端点写操作后调用，下次派生即时反映（不坐等 TTL）。"""
    book_id = str(book_id)
    _mutes_cache.pop(book_id, None)
    _hint_scan_cache.pop(book_id, None)


async def forgive_mute(db: AsyncSession, book_id: str, key: str) -> Set[str]:
    """宽恕复位：该键此前的拒绝记录一笔勾销。返回复位后的静音集合。"""
    book = await db.get(Book, str(book_id))
    if book is None:
        return set()
    mutes = dict(book.assist_mutes or {})
    # 重新赋值而非原地改——SQLAlchemy 对 JSONB 原地突变不追踪 dirty
    mutes[key] = datetime.now(timezone.utc).isoformat()
    book.assist_mutes = mutes
    await db.commit()
    invalidate_mutes_cache(str(book_id))
    return await load_muted_keys(db, str(book_id), use_cache=False)
