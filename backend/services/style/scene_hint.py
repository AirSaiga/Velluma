# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
写作场景判定（P5 C2 · 样本场景匹配，docs/reports/foundation-hardening.md §5.2）。

职责：对当前写作上下文（stitch 装配处传 rolling_prefix 尾 300 字）跑
fingerprint 的现成对话占比统计，判出场景档位，供 retrieve_author_samples
对同型样本做检索加成——「作者正写对话时，few-shot 示范优先给对话样本」。

v1 只分两档（dialogue / general），不做抒情/动作细分——等埋点证明价值再扩
（设计稿原话）。判定口径与文风页/审计侧同源（「同一把尺子」原则）：
dialogue_ratio = count_dialogue_chars / word_count，即
compute_text_fingerprint 的 dialogue_ratio 字段（light 模式省略修辞，
对话统计不受影响）。

零变化契约：空文本/统计失败一律回落 "general"——对检索层而言 general
等价于「无 hint」，行为与现状逐一致。
"""

from typing import Optional

from backend.services.style.fingerprint import compute_text_fingerprint

# ============================================================
# 档位常量与判定口径
# ============================================================

SCENE_DIALOGUE = "dialogue"   # 对话场景（对话占比超阈值）
SCENE_GENERAL = "general"     # 一般场景（默认档，含一切兜底情形）

# 对话占比阈值（严格大于才判 dialogue）：0.35 ≈ 尾 300 字里超过三分之一
# 是引号内文字——设计稿 §5.2 拍板值，勿随手调（改判定 = 改加成触发面）
DIALOGUE_RATIO_THRESHOLD = 0.35

# 判定窗口：stitch 装配处取 rolling_prefix 尾 300 字（此刻正在写的段落，
# 不是整章——场景是「现在时」信号）。装配方切片，本模块只判给定文本。
SCENE_HINT_TAIL_CHARS = 300


def detect_scene_type(text: Optional[str]) -> str:
    """判定给定文本的场景档位（v1 两档：dialogue / general）。

    纯算法、零 I/O：直接复用 fingerprint 的对话占比统计（light 模式，
    跳过修辞密度重正则）。任何异常/空文本 → "general"（宁稳勿炸——
    判定失败绝不能阻塞样本检索）。

    Args:
        text: 待判定文本（调用方负责取尾窗，如 rolling_prefix[-300:]）

    Returns:
        "dialogue" | "general"
    """
    if not text or not text.strip():
        return SCENE_GENERAL
    try:
        fp = compute_text_fingerprint(text, light=True)
        ratio = fp.get("dialogue_ratio") or 0.0
    except Exception:  # noqa: BLE001 —— 统计失败兜底 general，不向上抛
        return SCENE_GENERAL
    return SCENE_DIALOGUE if ratio > DIALOGUE_RATIO_THRESHOLD else SCENE_GENERAL
