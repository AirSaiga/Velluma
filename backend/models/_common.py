# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""模型层共享底座：UUID/时间默认值函数、状态 Enum、章档 TIER 常量。

被各模型子模块与外部消费方共同引用，独立成底层模块避免相互依赖。
"""
import uuid
from datetime import datetime, timezone
from enum import Enum


def generate_uuid() -> uuid.UUID:
    """生成 UUID 主键"""
    return uuid.uuid4()


def utc_now() -> datetime:
    """返回当前 UTC 时间（naive datetime，与 TIMESTAMP WITHOUT TIME ZONE 列兼容）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlotLedgerStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    DROPPED = "dropped"


class TaskStatus(str, Enum):
    """生成任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================
# V3.1 统一引擎：章节定档 tier（docs/generation-v3.1-unified.md §2.1）
# ============================================================
# 四档定义：高潮章 / 转折章 / 推进章 / 过渡章
# auto 表示由定档器自主决策（规格 §2.2 决策函数，宁低勿高）
TIER_CLIMAX = "climax"        # 高潮章：大高潮/揭盅/决裂/卷尾
TIER_TURN = "turn"            # 转折章：中等转折、重要推进
TIER_PROGRESS = "progress"    # 推进章：小转折、日常推进
TIER_TRANSITION = "transition"  # 过渡章：纯过渡、衔接
TIER_AUTO = "auto"            # 自动定档（默认）

# 有效档位集合（auto 不在其中，auto 是请求参数表示"由定档器决策"）
VALID_TIERS = {TIER_CLIMAX, TIER_TURN, TIER_PROGRESS, TIER_TRANSITION}

# 档位 → 铺垫结构深度上限（规格 §2.1 表）
TIER_MAX_DEPTH = {
    TIER_CLIMAX: 6,
    TIER_TURN: 4,
    TIER_PROGRESS: 2,
    TIER_TRANSITION: 1,
}

# 档位 → 铺陈段（development 区）占比目标（规格 §2.1 表，铺陈段占全章比例）
TIER_DEVELOPMENT_RATIO = {
    TIER_CLIMAX: 0.30,
    TIER_TURN: 0.50,
    TIER_PROGRESS: 0.70,
    TIER_TRANSITION: 0.90,
}
