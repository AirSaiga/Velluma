# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""全局 prompt 版本号（prompt 治理加固 F2d · docs/next-phase/06-prompt-governance-hardening.md）。

纪律（改 prompt 措辞的提交必须遵守）：
- 任何动了两条生成链（stitch 五模式 / dock 卡片舱）prompt 措辞的提交，
  必须递增本版本号（日期式递增：同日第 N 次改版 → "YYYY-MM-DD.N"）。
- 版本号进 trace 事件（adaptive_stitch_complete.prompt_version）与快照
  manifest（scripts/prompt_snapshot.py）——历史生成记录由此可归因到
  prompt 版本，跨时间对比（scripts/prompt_replay.py 对拍）才有意义。
- dock 侧另有 DOCK_PIPELINE_VERSION 缓存盐（dock_generator.py，管缓存
  失效语义），与本常量职责不同，互不替代。
"""
from __future__ import annotations

PROMPT_VERSION = "2026-09-24.1"
