# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 容错 JSON 解析工具
"""LLM 输出常带 ```json 包裹或前后缀文本，此模块提供容错解析。"""
from __future__ import annotations

import json
from typing import Optional


def parse_json_safe(text: str) -> Optional[dict | list]:
    """容错 JSON 解析。

    尝试顺序：
    1. 直接 json.loads
    2. 剥 ```json 包裹后解析
    3. 找第一个 {/[ 到最后一个 }/] 截取后解析

    全失败返回 None。
    """
    if not text:
        return None
    text = text.strip()
    # 1. 直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2. 剥 markdown 包裹
    if text.startswith("```"):
        inner = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(inner)
        except Exception:
            pass
    # 3. 截取最外层括号
    for open_ch, close_ch in [("{", "}"), ("[", "]")]:
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start: end + 1])
            except Exception:
                continue
    return None
