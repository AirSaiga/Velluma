# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Reader Mirror 服务包（V4.2 路径 B 新建）。

职责：
- reader_mirror.py: 期待账本的 CRUD + 推断 + 章节规划建议

设计依据：
- 第 6 轮：期待 ≠ 伏笔；网文节奏的核心
- 第 7 轮修正：仪表盘不是方向盘（作者主权）

数据存储：Book.reader_mirror JSONB（整体存储，避免新建表）
结构：
{
  "expectations": [{...}],
  "tension_curve": [{...}],
  "information_asymmetries": [{...}]
}
"""

from backend.services.reader_mirror.reader_mirror import (
    ReaderMirrorService,
    load_mirror,
    save_mirror,
    suggest_chapter_plan,
    infer_expectations_from_chapter,
    update_expectation_after_chapter,
)

__all__ = [
    "ReaderMirrorService",
    "load_mirror",
    "save_mirror",
    "suggest_chapter_plan",
    "infer_expectations_from_chapter",
    "update_expectation_after_chapter",
]
