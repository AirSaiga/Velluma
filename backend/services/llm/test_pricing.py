# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""成本核算单测（2026-09-11）：pricing 纯函数 + _parse_usage 缓存字段提取
+ model_config 价目表读写清洗。

计价口径对拍锚点：
- (prompt−cached)×input + cached×cached_input + (completion+thinking)×output / 1e6
- cached=None → 全价（保守）；钳位防脏数据
- 实测依据：DashScope qwen3.8-flash 返回 usage.prompt_tokens_details.cached_tokens
  （2026-09-11 活探针）；DeepSeek 文档化 prompt_cache_hit_tokens 同步兼容
"""
from types import SimpleNamespace

from backend.services.llm.client import _parse_usage
from backend.services.llm.pricing import compute_call_cost, price_for


class TestComputeCallCost:
    def test_basic_math_with_cache_discount(self):
        price = {"input": 2.0, "cached_input": 0.2, "output": 8.0}
        # 1M 输入（0.5M 命中）+ 0.25M 输出
        cost = compute_call_cost(price, 1_000_000, 200_000, 50_000, 500_000)
        assert abs(cost - 3.1) < 1e-9

    def test_cached_none_full_price(self):
        price = {"input": 2.0, "cached_input": 0.2, "output": 8.0}
        assert compute_call_cost(price, 1_000_000, 0, 0, None) == 2.0

    def test_missing_cached_price_uses_input(self):
        price = {"input": 1.0, "output": 4.0}
        assert compute_call_cost(price, 1_000_000, 0, 0, 400_000) == 1.0

    def test_clamps_dirty_cached_tokens(self):
        price = {"input": 1.0, "cached_input": 0.0, "output": 1.0}
        # 命中超 prompt → 钳到 prompt（成本不为负）
        assert compute_call_cost(price, 100, 0, 0, 500) == 0.0
        # 负命中 → 按 0
        assert compute_call_cost(price, 100, 0, 0, -3) == 100 / 1e6

    def test_none_tokens_as_zero(self):
        price = {"input": 2.0, "output": 8.0}
        assert compute_call_cost(price, None, None, None, None) == 0.0

    def test_thinking_billed_as_output(self):
        price = {"input": 0.0, "output": 4.0}
        # completion 与 thinking 同按输出价（与 token 总账 p+c+t 口径同构）
        assert compute_call_cost(price, 0, 250_000, 250_000, 0) == 2.0


class TestPriceFor:
    def test_unpriced_variants(self):
        prices = {"model-a": {"input": 1.0, "output": 2.0}}
        assert price_for(prices, "model-a") == {"input": 1.0, "output": 2.0}
        assert price_for(prices, "other") is None
        assert price_for(prices, None) is None
        assert price_for({}, "model-a") is None


def _resp(usage):
    """构造 OpenAI SDK response 形状（只用 _parse_usage 读到的字段）。"""
    return SimpleNamespace(usage=usage)


class TestParseUsageCachedTokens:
    def test_openai_compatible_shape(self):
        """DashScope/OpenAI/Kimi/GLM：prompt_tokens_details.cached_tokens。"""
        usage = SimpleNamespace(
            prompt_tokens=100, completion_tokens=50,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=10),
            prompt_tokens_details=SimpleNamespace(cached_tokens=60),
        )
        parsed = _parse_usage(_resp(usage))
        assert parsed["prompt_tokens"] == 100
        assert parsed["completion_tokens"] == 50
        assert parsed["reasoning_tokens"] == 10
        assert parsed["cached_tokens"] == 60

    def test_deepseek_shape(self):
        """DeepSeek 专有：usage.prompt_cache_hit_tokens（无 details 对象）。"""
        usage = SimpleNamespace(
            prompt_tokens=100, completion_tokens=50,
            completion_tokens_details=None,
            prompt_tokens_details=None,
            prompt_cache_hit_tokens=70,
        )
        assert _parse_usage(_resp(usage))["cached_tokens"] == 70

    def test_absent_fields_return_none(self):
        usage = SimpleNamespace(
            prompt_tokens=100, completion_tokens=50,
            completion_tokens_details=None,
        )
        parsed = _parse_usage(_resp(usage))
        assert parsed["cached_tokens"] is None
        assert parsed["reasoning_tokens"] is None

    def test_clamp_cached_over_prompt(self):
        """脏数据钳位：cached > prompt → 钳到 prompt。"""
        usage = SimpleNamespace(
            prompt_tokens=50, completion_tokens=10,
            completion_tokens_details=None,
            prompt_tokens_details=SimpleNamespace(cached_tokens=999),
        )
        assert _parse_usage(_resp(usage))["cached_tokens"] == 50

    def test_no_usage_returns_none(self):
        assert _parse_usage(_resp(None)) is None


class TestModelPricesConfig:
    """价目表读写（model_config.json prices 节）——CONFIG_PATH 打桩到临时文件。"""

    def test_roundtrip_and_cleaning(self, tmp_path, monkeypatch):
        import json

        import backend.core.model_config as mc

        cfg_path = tmp_path / "model_config.json"
        cfg_path.write_text(json.dumps({
            "llm": {"reasoning": {"model": "x"}},
            "prices": {
                "model-a": {"input": 2.0, "cached_input": 0.2, "output": 8.0},
                "model-b": {"input": 1.0, "output": 4.0},
                "bad-missing-output": {"input": 1.0},          # 缺 output → 丢弃
                "": {"input": 1.0, "output": 1.0},             # 空名 → 丢弃
                "bad-negative": {"input": -1.0, "output": 2.0},  # 负价 → 丢弃
                "bad-not-dict": "nope",                         # 形状错 → 丢弃
                "  spaced  ": {"input": 3.0, "output": 3.0},    # 名字去空白保留
                "bool-poison": {"input": True, "output": 2.0},  # bool 伪装数字 → 丢弃
            },
        }), encoding="utf-8")
        monkeypatch.setattr(mc, "CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(mc, "_config_cache", None)

        prices = mc.get_model_prices()
        assert set(prices) == {"model-a", "model-b", "spaced"}
        assert prices["model-a"]["cached_input"] == 0.2
        assert "cached_input" not in prices["model-b"]

        # 整表覆写：空表清空 prices 节
        saved = mc.update_model_prices({})
        assert saved == {}
        assert "prices" not in json.loads(cfg_path.read_text(encoding="utf-8"))

        # 写入后缓存失效、再读回一致
        saved = mc.update_model_prices({"model-c": {"input": 1.5, "output": 6.0}})
        assert saved == {"model-c": {"input": 1.5, "output": 6.0}}
        assert mc.get_model_prices() == {"model-c": {"input": 1.5, "output": 6.0}}
