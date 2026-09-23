# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 厂商能力档案 + 采样整形 单元测试（纯算法，不连真实 LLM）
"""
2026-08-28 五厂商调研驱动的护栏（docs/model-vendor-matrix.md 唯一事实源）：
- detect_provider 新增 GLM/Kimi/百炼新版域名识别
- match_model_rule 最长前缀优先（kimi-k3 不得被泛化 kimi-k 规则遮蔽）
- shape_sampling_params：Kimi K 系采样全删 / DeepSeek 废弃 penalty +
  思考态删 temperature / 非思考态删 top_p（2026-09-10 档案：top_p 思考态
  生效、下限 0.95 服务端抬升）/ GLM 温度钳 1.0 / MiMo 思考态删采样
- reasoning_adapter 新方言：GLM/Kimi 思考分支 + 强制思考模型（glm-5.3/
  kimi-k3/kimi-k2.7）关闭请求转不发 + effort 白名单归一
- vendor_catalog 目录结构（前端 /system/model-catalog 消费）

运行：python -m pytest backend/services/llm/test_vendor_profiles.py
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import pytest

from backend.services.llm.vendor_profiles import (
    GLM, KIMI, DEEPSEEK, MIMO, QWEN, UNKNOWN,
    VENDORS,
    detect_provider,
    match_model_rule,
    get_vendor_profile,
    shape_sampling_params,
    vendor_catalog,
)
from backend.services.llm.reasoning_adapter import adapt_reasoning_config

REASONING_DISABLED = {"reasoning": {"enabled": False}}


def _enabled(effort="medium"):
    return {"reasoning": {"enabled": True, "effort": effort, "exclude": False}}


KIMI_URL = "https://api.moonshot.cn/v1"
GLM_URL = "https://open.bigmodel.cn/api/paas/v4"
DS_URL = "https://api.deepseek.com"
MIMO_URL = "https://api.xiaomimimo.com/v1"


# ============================================================
# detect_provider：新厂商域名
# ============================================================

class TestDetectProviderNewVendors:

    @pytest.mark.parametrize("base_url,expected", [
        (GLM_URL, GLM),
        ("https://open.bigmodel.cn/api/paas/v4", GLM),
        (KIMI_URL, KIMI),
        ("https://api.moonshot.ai/v1", KIMI),          # 国际站
        ("https://{ws}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", QWEN),  # 百炼新版
        (MIMO_URL, MIMO),
        ("https://custom.example.com/v1", UNKNOWN),
    ])
    def test_domains(self, base_url, expected):
        assert detect_provider(base_url) == expected


# ============================================================
# match_model_rule：最长前缀优先
# ============================================================

class TestMatchModelRule:

    def test_kimi_k3_beats_generic(self):
        """kimi-k3 命中具体规则（强制思考+effort），不被泛化 kimi-k 遮蔽。"""
        rule = match_model_rule(VENDORS[KIMI], "kimi-k3")
        assert rule is not None
        assert rule.force_thinking is True
        assert rule.locked_sampling is True
        assert rule.effort_values == ("low", "high", "max")

    def test_kimi_k26_gets_generic(self):
        rule = match_model_rule(VENDORS[KIMI], "kimi-k2.6")
        assert rule is not None
        assert rule.locked_sampling is True
        assert rule.force_thinking is False

    def test_glm_53_flash_matches_53(self):
        rule = match_model_rule(VENDORS[GLM], "glm-5.3-flash")
        assert rule is not None and rule.force_thinking is True

    def test_no_match(self):
        assert match_model_rule(VENDORS[GLM], "glm-4.6") is None
        assert match_model_rule(None, "anything") is None


# ============================================================
# shape_sampling_params：前置整形
# ============================================================

class TestShapeSampling:

    def test_kimi_k_series_drops_all_sampling(self):
        """Kimi K 系：采样四参数全删（schema 不含，传了 400）——2026-08-28 事故根因。"""
        shaped, dropped = shape_sampling_params(
            KIMI_URL, "kimi-k2.6",
            {"model": "kimi-k2.6", "temperature": 0.7, "top_p": 1.0, "max_tokens": 800},
            thinking_enabled=False,
        )
        assert "temperature" not in shaped and "top_p" not in shaped
        assert shaped["model"] == "kimi-k2.6" and shaped["max_tokens"] == 800  # 非采样键原样
        assert set(dropped) == {"temperature", "top_p"}

    def test_deepseek_penalties_dropped_always(self):
        """DeepSeek 双 penalty 已废弃（全模式）；非思考模式 top_p 恒 1.0 被忽略（删）。"""
        shaped, dropped = shape_sampling_params(
            DS_URL, "deepseek-flash",
            {"temperature": 0.7, "top_p": 0.9, "frequency_penalty": 0.5, "presence_penalty": 0.3},
            thinking_enabled=False,
        )
        assert shaped["temperature"] == 0.7
        assert "top_p" not in shaped
        assert "frequency_penalty" not in shaped and "presence_penalty" not in shaped
        assert set(dropped) == {"top_p", "frequency_penalty", "presence_penalty"}

    def test_deepseek_thinking_drops_temperature_keeps_top_p(self):
        """思考模式（2026-09-10 档案）：temperature 无效删；top_p 生效原样透传
        （官方文档：低于 0.95 由服务端抬升，客户端不发无效参数但不替厂商抬值）。"""
        shaped, dropped = shape_sampling_params(
            DS_URL, "deepseek-flash",
            {"temperature": 1.5, "top_p": 0.9},
            thinking_enabled=True,
        )
        assert "temperature" not in shaped
        assert shaped["top_p"] == 0.9
        assert dropped == ["temperature"]

    def test_glm_temperature_clamped_to_1(self):
        shaped, dropped = shape_sampling_params(
            GLM_URL, "glm-5.2", {"temperature": 1.5, "top_p": 1.0}, thinking_enabled=False,
        )
        assert shaped["temperature"] == 1.0
        assert shaped["top_p"] == 1.0  # 1.0 在 [0.01, 1.0] 内不钳
        assert "temperature" in dropped

    def test_glm_penalties_dropped(self):
        shaped, _ = shape_sampling_params(
            GLM_URL, "glm-5.2", {"temperature": 0.7, "presence_penalty": 0.5}, thinking_enabled=False,
        )
        assert "presence_penalty" not in shaped

    def test_mimo_thinking_drops_sampling(self):
        shaped, dropped = shape_sampling_params(
            MIMO_URL, "mimo-v2.5", {"temperature": 0.7, "top_p": 0.9}, thinking_enabled=True,
        )
        assert "temperature" not in shaped and "top_p" not in shaped
        # 思考关闭：采样保留并按 [0,1.5]/[0.01,1.0] 钳制
        shaped2, _ = shape_sampling_params(
            MIMO_URL, "mimo-v2.5", {"temperature": 0.7, "top_p": 0.9}, thinking_enabled=False,
        )
        assert shaped2["temperature"] == 0.7 and shaped2["top_p"] == 0.9

    def test_qwen_passthrough_within_range(self):
        shaped, dropped = shape_sampling_params(
            "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus",
            {"temperature": 0.7, "top_p": 1.0}, thinking_enabled=True,
        )
        assert shaped == {"temperature": 0.7, "top_p": 1.0}
        assert dropped == []

    def test_unknown_vendor_passthrough(self):
        shaped, dropped = shape_sampling_params(
            "https://custom.example.com/v1", "some-model",
            {"temperature": 0.7, "top_p": 1.0, "frequency_penalty": 0.2}, thinking_enabled=True,
        )
        assert shaped == {"temperature": 0.7, "top_p": 1.0, "frequency_penalty": 0.2}
        assert dropped == []


# ============================================================
# reasoning_adapter：GLM / Kimi 新方言
# ============================================================

class TestAdaptKimi:

    def test_k26_disabled(self):
        """k2.6 思考默认开——显式关闭必须发 thinking.type=disabled（关不住就白烧思考 token）。"""
        assert adapt_reasoning_config(REASONING_DISABLED, KIMI_URL, "kimi-k2.6") == {
            "thinking": {"type": "disabled"},
        }

    def test_k26_enabled(self):
        assert adapt_reasoning_config(_enabled("high"), KIMI_URL, "kimi-k2.6") == {
            "thinking": {"type": "enabled"},
        }

    def test_k3_cannot_disable(self):
        """k3 恒思考：关闭请求转不发参数（发了也没通道，还可能 400）。"""
        assert adapt_reasoning_config(REASONING_DISABLED, KIMI_URL, "kimi-k3") is None

    def test_k3_enabled_effort_only(self):
        """k3 无 thinking 参数，只有顶层 reasoning_effort；medium 归一为 high。"""
        result = adapt_reasoning_config(_enabled("medium"), KIMI_URL, "kimi-k3")
        assert result == {"reasoning_effort": "high"}

    def test_k27_code_cannot_disable(self):
        assert adapt_reasoning_config(REASONING_DISABLED, KIMI_URL, "kimi-k2.7-code") is None

    def test_moonshot_v1_no_thinking_param(self):
        """moonshot-v1 老系非思考模型：不发思考参数。"""
        assert adapt_reasoning_config(_enabled("high"), KIMI_URL, "moonshot-v1-8k") is None


class TestAdaptGLM:

    def test_glm52_disabled(self):
        assert adapt_reasoning_config(REASONING_DISABLED, GLM_URL, "glm-5.2") == {
            "thinking": {"type": "disabled"},
        }

    def test_glm52_enabled_medium_normalized(self):
        """glm-5.2 只认 low/high/max：medium 归一为 high。"""
        result = adapt_reasoning_config(_enabled("medium"), GLM_URL, "glm-5.2")
        assert result == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}

    def test_glm53_cannot_disable(self):
        """glm-5.3 强制思考：disabled 报错（官方迁移指南），转不发参数。"""
        assert adapt_reasoning_config(REASONING_DISABLED, GLM_URL, "glm-5.3") is None

    def test_glm53_enabled_forced(self):
        result = adapt_reasoning_config(_enabled("max"), GLM_URL, "glm-5.3")
        assert result == {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}

    def test_glm47_no_reasoning_effort(self):
        """reasoning_effort 仅 5.2+：glm-4.7 开启思考也不附带。"""
        result = adapt_reasoning_config(_enabled("high"), GLM_URL, "glm-4.7")
        assert result == {"thinking": {"type": "enabled"}}
        assert "reasoning_effort" not in result


class TestEffortNormalization:

    def test_deepseek_medium_to_high(self):
        result = adapt_reasoning_config(_enabled("medium"), DS_URL, "deepseek-flash")
        assert result["reasoning_effort"] == "high"

    def test_openai_max_to_high(self):
        result = adapt_reasoning_config(_enabled("max"), "https://api.openai.com/v1", "gpt-5")
        assert result["reasoning_effort"] == "high"


# ============================================================
# vendor_catalog：前端目录
# ============================================================

class TestVendorCatalog:

    def test_structure(self):
        catalog = vendor_catalog()
        ids = {v["id"] for v in catalog}
        assert {DEEPSEEK, GLM, KIMI, QWEN, MIMO} <= ids
        for v in catalog:
            assert set(v.keys()) == {"id", "label", "base_url", "docs_url", "notes", "models"}
            for m in v["models"]:
                assert {"id", "label", "note"} <= set(m.keys())

    def test_kimi_models_listed(self):
        kimi = next(v for v in vendor_catalog() if v["id"] == KIMI)
        model_ids = {m["id"] for m in kimi["models"]}
        assert {"kimi-k2.6", "kimi-k3"} <= model_ids

    def test_deepseek_models_listed(self):
        """2026-09-10 起规范 id=deepseek-flash；v4-pro 仍在目录（带下线倒计时 note）。"""
        ds = next(v for v in vendor_catalog() if v["id"] == DEEPSEEK)
        model_ids = {m["id"] for m in ds["models"]}
        assert {"deepseek-flash", "deepseek-v4-pro"} <= model_ids
        assert "deepseek-v4-flash" not in model_ids  # 已并入 deepseek-flash（旧名暂时路由）

    def test_mimo_models_listed(self):
        """2026-09-21 V2.6 系上线（与 V2.5 同价）；v2.5 系 2026-10-21 下线前保留倒计时条目。"""
        mimo = next(v for v in vendor_catalog() if v["id"] == MIMO)
        model_ids = {m["id"] for m in mimo["models"]}
        assert {"mimo-v2.6-flash", "mimo-v2.6-pro", "mimo-v2.6-pro-ultraspeed"} <= model_ids
        assert {"mimo-v2.5", "mimo-v2.5-pro"} <= model_ids  # 10-21 下线后随目录一并移除

    def test_json_serializable(self):
        import json
        json.dumps(vendor_catalog(), ensure_ascii=False)  # 不抛即通过
