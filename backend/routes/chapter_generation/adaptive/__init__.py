# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""NLE-ADF 3.0 自适应辅助路由包（前端默认写作路径）。

原单文件 adaptive.py（3105 行）按端点族拆为八个子模块（2026-09-11 架构
优化批，行为零变化——函数体逐字节搬运）；确定性闸门/后处理下沉
services/adaptive/stitch_gates.py。

核心协议：心跳模式。前端双档防抖发 heartbeat（活跃 3s / 停顿 4s+光标段尾），
后端调度器决定激活哪些组件，异步跑、写回世界模型。

子模块（路径省略前缀 /api/chapters/{chapter_id}）：
- heartbeat.py:    POST /adaptive/heartbeat（快照 + 挂件/走向卡/感知带/谋篇进度）
- settle_finish.py: POST /adaptive/settle | /adaptive/finish | /adaptive/fix-sentence;
                    GET /adaptive/model
- stitch.py:       POST /adaptive/stitch-ghost（SSE 五模式）
- preview.py:      GET  /adaptive/context-preview
- spine.py:        GET/PATCH /adaptive/spine + POST /adaptive/spine-suggest;
                    GET /api/books/{id}/adaptive/spines（书级批量，大纲板用）
- world_read.py:   POST /adaptive/auto-read | /adaptive/read-entities
- events.py:       POST /adaptive/event + GET /adaptive/constraints/summary
                   （GET /adaptive/events/summary 已随 05 埋点瘦身拆除）
- opening_card.py: GET /adaptive/opening-card + POST /adaptive/opening-card/touch
                   （01 开章卡：空章镜子 + 专用计数，零 LLM）
- ask_book.py:     POST /adaptive/ask-book（04 问书：六类纯代码直答 +
                   M2 意图笼 + M3 材料内合成，逐条出处零创作）
- schemas.py:      请求/响应模型

设定数据来源：services.context.settings_bundle（分级访问 hard/soft/nutrients）。
"""
from fastapi import APIRouter

from .ask_book import router as ask_book_router
from .events import router as events_router
from .heartbeat import router as heartbeat_router
from .opening_card import router as opening_card_router
from .preview import router as preview_router
from .settle_finish import router as settle_finish_router
from .spine import book_router as spine_book_router
from .spine import router as spine_router
from .stitch import router as stitch_router
from .world_read import router as world_read_router

# 合并路由（子模块各自 prefix="/api/chapters"，路径与拆分前逐条一致；
# spine 另带书级批量路由 prefix="/api/books"）
router = APIRouter()
router.include_router(heartbeat_router)
router.include_router(settle_finish_router)
router.include_router(stitch_router)
router.include_router(preview_router)
router.include_router(spine_router)
router.include_router(spine_book_router)
router.include_router(world_read_router)
router.include_router(events_router)
router.include_router(opening_card_router)
router.include_router(ask_book_router)

__all__ = ["router"]
