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

"""
成本核算纯函数（2026-09-11）——token × 价目表 → 元。

价目表唯一权威：backend/core/model_config.py 的 get_model_prices()
（model_config.json 顶层 "prices" 节，元/百万 token，按模型名键控）。

计价口径：
- 单次调用成本 = (prompt − cached) × input + cached × cached_input
  + (completion + thinking) × output，全部除以 1e6
- 输出侧把 thinking 计入输出价——与用量面板既有 token 总账口径
  （total = prompt + completion + thinking）同构，两视图可互相对账
- cached_tokens 为 None（厂商未回报/历史行）→ 按全价计（保守：宁可
  高估不低估）；钳位防脏数据（负数/超 prompt）
- 模型未配价 → 该行不计成本（cost 累加 0），token 计入 unpriced——
  面板如实显示「另有 N token 未计价」，不冒充零成本

本模块不落库不读文件（价目获取经 get_model_prices 注入），单测直接打纯函数。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

PriceTable = Dict[str, Dict[str, float]]


def compute_call_cost(
    price: Dict[str, float],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    thinking_tokens: Optional[int],
    cached_tokens: Optional[int],
) -> float:
    """单次调用成本（元）。price 必含 input/output（cached_input 可缺省回退 input）。

    token 缺失按 0 计（与 usage 聚合的 None→0 口径一致）。
    """
    p = max(prompt_tokens or 0, 0)
    out = max(completion_tokens or 0, 0) + max(thinking_tokens or 0, 0)
    cached = cached_tokens or 0
    if cached < 0:
        cached = 0
    if cached > p:
        cached = p
    input_price = price.get("input") or 0.0
    cached_price = price.get("cached_input")
    if cached_price is None:
        cached_price = input_price
    output_price = price.get("output") or 0.0
    uncached = p - cached
    return (
        uncached * input_price / 1e6
        + cached * cached_price / 1e6
        + out * output_price / 1e6
    )


def price_for(prices: PriceTable, model_name: Optional[str]) -> Optional[Dict[str, float]]:
    """取模型价目；未配价/无名 → None（调用方把 token 计入 unpriced）。"""
    if not model_name:
        return None
    return prices.get(model_name)


def new_cost_bucket() -> Dict[str, Any]:
    """成本累加桶（usage 聚合侧逐行累入）。"""
    return {"cost": 0.0, "unpriced_tokens": 0}


def accumulate_cost(
    bucket: Dict[str, Any],
    prices: PriceTable,
    run: Any,
) -> None:
    """单行 generation_runs 的成本累入桶（鸭子类型读 5 字段）。

    已计价行 → cost 累加；未计价行 → unpriced_tokens 累加该行 token 总量
    （p+c+t，与 totals 同口径）。降级行（token 全 None）两边都不动。
    """
    price = price_for(prices, getattr(run, "model_name", None))
    total = (
        (getattr(run, "prompt_tokens", None) or 0)
        + (getattr(run, "completion_tokens", None) or 0)
        + (getattr(run, "thinking_tokens", None) or 0)
    )
    if total <= 0:
        return
    if price is None:
        bucket["unpriced_tokens"] += total
        return
    bucket["cost"] += compute_call_cost(
        price,
        getattr(run, "prompt_tokens", None),
        getattr(run, "completion_tokens", None),
        getattr(run, "thinking_tokens", None),
        getattr(run, "cached_tokens", None),
    )
