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
NLG（自然语言生成）质量保障包。

职责：在 ADF 引擎（V3.2）的多个触点拦截"AI 味/机械感"，包括病态微操、
套路比喻、匀速句式、上下文风格污染。

子模块分层（依赖单向向下）：
- anti_ai_rules       纯数据契约：禁令词表/正则/阈值（零依赖、零 I/O）
- ai_taste_meter      纯算法：AI 味密度评估（输入文本→DensityReport）
- text_sanitizer      纯正则裁剪：删黑名单词、修微操、rolling 去毒（确定性、可测）
- local_preprocessor  0 Token 本地预处理：jieba 词性抽脂 + 硬断句（Tier 2）
- de_ai_washer        LLM 编排：超阈值时调 creative 槽单段重洗（唯一含 LLM I/O）

依赖方向：washer → {meter, sanitizer, rules}；sanitizer → rules；meter → rules；
         local_preprocessor → jieba（独立，平行于 sanitizer）
"""

from backend.services.nlg.anti_ai_rules import (
    AntiAIBanList,
    DensityThresholds,
    DEFAULT_BAN_LIST,
    DEFAULT_THRESHOLDS,
)
from backend.services.nlg.ai_taste_meter import (
    DensityReport,
    measure_ai_taste,
)
from backend.services.nlg.text_sanitizer import (
    sanitize_segment,
    sanitize_rolling_prefix,
)
from backend.services.nlg.local_preprocessor import (
    LocalPreprocessor,
    preprocess_segment,
)
from backend.services.nlg.de_ai_washer import (
    WashResult,
    wash_segment_if_too_ai,
)

__all__ = [
    "AntiAIBanList",
    "DensityThresholds",
    "DEFAULT_BAN_LIST",
    "DEFAULT_THRESHOLDS",
    "DensityReport",
    "measure_ai_taste",
    "sanitize_segment",
    "sanitize_rolling_prefix",
    "LocalPreprocessor",
    "preprocess_segment",
    "WashResult",
    "wash_segment_if_too_ai",
]
