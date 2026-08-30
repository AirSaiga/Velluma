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
文风模块补全批次单测（完整落地，纯算法——不连 LLM/DB）。

覆盖（docs/style-module-redesign.md §5/§6.4/§7.1 补全项）：
- 负面清单台账化：count_negative_hits（含 0 计数——反向提醒）
- 心跳漂移提示：compute_style_drift_hint 的门槛/两类偏离/健康静默
- 检索兜底排序：收藏优先 → 近期 → 早期
- 系统陈词本书豁免：StyleClicheValidator 层 1 剔除被豁免 pattern（种子降级路径）
"""

import asyncio
import re

from backend.services.style.fingerprint import (
    compute_style_drift_hint,
    count_negative_hits,
)
from backend.services.style.retrieval import order_samples_for_fallback


# ============================================================
# 负面清单台账化
# ============================================================

class TestCountNegativeHits:
    def test_counts_and_zeros(self):
        counts = count_negative_hits(
            ["他不禁感到愤怒。她也不禁叹气。", "没有禁词的一章。"],
            ["不禁", "涌上心头", "无人问津"],
        )
        assert counts == {"不禁": 2, "涌上心头": 0, "无人问津": 0}

    def test_empty_inputs(self):
        assert count_negative_hits([], []) == {}
        assert count_negative_hits(["正文"], []) == {}


# ============================================================
# 心跳漂移提示
# ============================================================

class TestStyleDriftHint:
    def _dialogue_heavy(self) -> str:
        # 高对话占比 + 短句（句长 CV 低）——制造两类偏离（≥400 字才过测量门槛）
        return "“走？”“走。”" * 60

    def test_short_text_silent(self):
        assert compute_style_drift_hint("太短。", 0.2, 0.35, 0.8) is None

    def test_dialogue_above_target(self):
        hint = compute_style_drift_hint(self._dialogue_heavy(), 0.2, 0.35, 0.8)
        assert hint is not None
        assert "高于目标" in hint

    def test_dialogue_below_target(self):
        # 纯叙述长文（无引号）+ 高目标 → 低于目标（≥400 字）
        text = "他沿着江岸走了很远，看着潮水一层一层地漫上来，又一层一层地退下去。" * 16
        hint = compute_style_drift_hint(text, 0.5, 0.35, 0.8)
        assert hint is not None
        assert "低于目标" in hint

    def test_healthy_silent(self):
        # 参差句长 + 中等对话占比，贴目标 → 静默
        text = (
            "雨停了。\n"
            + "他站在渡口，看着江水在暮色里翻涌，想起十年前也是这样的天。\n"
            + "“走了？”艄公问。\n" * 6
            + "船离岸的时候，他忽然想问一句什么，最终没有问。\n" * 4
        )
        assert compute_style_drift_hint(text, 0.3, 0.35, 0.8) is None


# ============================================================
# 检索兜底排序（era + favorite）
# ============================================================

class _FakeSample:
    def __init__(self, name: str, favorite=False, era="recent"):
        self.name = name
        self.favorite = favorite
        self.era = era


class TestOrderSamplesForFallback:
    def test_favorite_first_early_last(self):
        samples = [
            _FakeSample("旧早期", era="early"),
            _FakeSample("普通近期"),
            _FakeSample("收藏", favorite=True),
            _FakeSample("早期收藏", favorite=True, era="early"),
        ]
        ordered = order_samples_for_fallback(samples)
        names = [s.name for s in ordered]
        # 收藏优先于一切；非收藏内近期先于早期
        assert names.index("收藏") < names.index("普通近期")
        assert names.index("早期收藏") < names.index("普通近期")
        assert names.index("普通近期") < names.index("旧早期")

    def test_missing_attrs_default_recent(self):
        # 旧数据无 era/favorite 属性 → 按 recent/非收藏处理（不炸）
        s = type("S", (), {"name": "旧样本"})()
        assert [x.name for x in order_samples_for_fallback([s])] == ["旧样本"]


# ============================================================
# 系统陈词本书豁免（种子降级路径，无 DB）
# ============================================================

class TestClicheExemptions:
    def test_exempted_pattern_removed_from_layer1(self):
        from backend.services.workflows.validators import StyleClicheValidator

        async def run() -> list:
            v = StyleClicheValidator()
            await v._ensure_loaded({
                "cliche_exemptions": ["眼底闪过一丝"],
            })
            return v._compiled_patterns

        compiled = asyncio.run(run())
        patterns = {p.pattern for p, _alt, _sev in compiled}
        assert re.escape("眼底闪过一丝") not in patterns  # 被豁免剔除
        # 未豁免的系统种子仍在（层 1 未被整体清空）
        assert len(patterns) > 5

    def test_without_exemptions_pattern_present(self):
        from backend.services.style.cliche_provider import invalidate_cache
        from backend.services.workflows.validators import StyleClicheValidator

        async def run() -> list:
            invalidate_cache()
            v = StyleClicheValidator()
            await v._ensure_loaded({})
            return v._compiled_patterns

        compiled = asyncio.run(run())
        patterns = {p.pattern for p, _alt, _sev in compiled}
        assert re.escape("眼底闪过一丝") in patterns  # 未豁免时正常在列
