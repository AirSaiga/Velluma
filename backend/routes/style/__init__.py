# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""文风体系路由包（S1 落地，docs/style-module-redesign.md）。

原单文件 routes/style.py（1255 行）按资源族拆六子模块（2026-09-11 架构
优化批，行为零变化）：
- card.py:        /style-card CRUD + 提炼 + 章级覆盖删除
- samples.py:     /samples 全家（手动/章节收编/黄金导入/检索/局部更新）
- fingerprint.py: /style-fingerprint（测量层，纯 code）
- feedback.py:    收件箱/试听/禁词扫描/可逆学习/采纳池（作者反馈环）
- cliches.py:     /system/cliches + 本书豁免
- events.py:      /style/events 埋点与汇总
- _deps.py:       仓储依赖提供者

剥 HTML 规范实现：services/utils/html_text.html_to_plain（路由侧原
_plain_text 与 rag/memory_indexing._html_to_plain 双实现已收敛委托）。
"""
from fastapi import APIRouter

from .card import router as card_router
from .cliches import router as cliches_router
from .events import router as events_router
from .feedback import router as feedback_router
from .fingerprint import router as fingerprint_router
from .samples import router as samples_router

# 合并路由（子模块各自 prefix="/api"，路径与拆分前逐条一致）
router = APIRouter()
router.include_router(card_router)
router.include_router(samples_router)
router.include_router(fingerprint_router)
router.include_router(feedback_router)
router.include_router(cliches_router)
router.include_router(events_router)

__all__ = ["router"]
