# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
文风事件本地账本（data/style_events.jsonl，零上报——桌面应用隐私边界内）。

从 routes/style.py 抽出为服务层共享：幽灵洗层（ghost_wash）在 stitch 链上
落事件，不能 import 路由模块。失败静默——埋点绝不阻塞业务。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STYLE_EVENTS_FILE = "data/style_events.jsonl"


def append_style_event(book_id: str, kind: str, detail: Optional[str]) -> None:
    """追加事件到本地 JSONL（洗层命中/试听/喂养/收件箱裁决/回流先验）。"""
    try:
        path = Path(STYLE_EVENTS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "book_id": book_id,
                "kind": kind,
                "detail": detail or "",
            }, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[StyleEvent] 写入失败（静默）: {e}")
