# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
deai 小模型调用客户端（去AI味改写，deai/ 子项目的宿主侧接口）。

设计唯一权威：docs/deai-integration.md。任务：把 ≤100 字的中文片段改写得
像人写的——只改语言质感，不动事实/数字/日期/专名/引文（模型契约见
deai/docs/contract.md）。

调用要点（deai/docs/usage.md §2 实测踩坑，勿改）：
1. 接口用 DashScope **原生** text-generation 端点——百炼调优模型不支持
   OpenAI 兼容入口（model_not_found）；
2. model 填部署后的 deployed_model（不是训练任务 ft-… ID），重训/重部署
   后会变；
3. parameters 必须带 enable_thinking=false（Qwen3 非流式调用要求）。

保底策略（契约§6 运行时规则，移植自 deai/scripts/deai_rewrite.py）：
- 输入 >100 字 / 未配置 Key / 网络/HTTP 失败 → 原样返回（skipped 或回退）；
- 模型输出过不了事实闸（数字/专名/新增事实）→ 回退原文；
- 仅非事实闸失败（长度/套话/像人）→ 仍返回改写，携带 warnings。

零变化契约：未配置（model_config.json 无 deai 节或 enabled=false 且无
覆盖 Key）时 ghost 链路对其零调用、文本逐字节不变——调用方
（stitch-ghost）以 is_deai_configured() 守门。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

from backend.core.model_config import get_deai_config
from backend.services.deai.gates import INPUT_MAX, runtime_gates

logger = logging.getLogger(__name__)

# 与训练数据同形的 system 提示（deai_rewrite.py 逐字一致——SFT 模型对
# 训练分布外的 system 措辞不保证行为，勿随手润色）
SYSTEM_PROMPT = (
    "你是中文润色助手，把用户给的片段改得更像人写的。"
    "只改语言质感，不改事实、数字、日期、专名、引文，不新增观点，输出不超过原长的120%。"
)

# 4B 模型、≤100 字输入、256 max_tokens、非思考态——常态 1-3s、p99 约 3-5s。
# 等待发生在主生成完成之后、GHOST_START 之前，用户读作「生成完了却卡住」；
# 超时即保底回退（代价极小），故取 8s 挂死上限而非网络宽容值。
REQUEST_TIMEOUT_S = 8.0


@dataclass
class DeaiResult:
    """polish_fragment 的返回。text 恒为「最终应采用的文本」（保底时=原文）。"""
    text: str
    applied: bool = False        # True=采用了模型改写
    skipped: bool = False        # True=根本没发起调用（未配置/超长/空文本）
    reason: str = ""             # skipped/未采纳的原因（人读）
    warnings: List[str] = field(default_factory=list)  # 非事实闸告警
    tokens_in: int = 0           # DashScope usage.input_tokens（0=无调用/未返回）
    tokens_out: int = 0          # DashScope usage.output_tokens


def is_deai_configured() -> bool:
    """deai 是否已配置并启用（enabled 且 api_key 且 model 齐备）。

    ghost 链路的唯一守门判据——False 时逐字节零变化。
    """
    cfg = get_deai_config()
    return bool(cfg["enabled"] and cfg["api_key"] and cfg["model"])


def _build_payload(text: str, model: str) -> Dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"原文：{text}\n修改后："},
    ]
    return {
        "model": model,
        "input": {"messages": messages},
        "parameters": {
            "temperature": 0.3,
            "max_tokens": 256,
            "result_format": "message",
            "enable_thinking": False,
        },
    }


def _parse_response(resp: Dict) -> Tuple[str, Dict]:
    """返回 (content, usage)——usage 取 DashScope 原生 usage 节（缺失给空）。"""
    usage = resp.get("usage") or {}
    return (resp["output"]["choices"][0]["message"]["content"] or "").strip(), usage


async def _call_dashscope(
    text: str, model: str, api_key: str, base_url: str
) -> Tuple[str, Dict]:
    """发起 DashScope 原生调用，返回 (模型输出文本, usage)；失败抛异常由上层保底。

    代理：跟随 model_config.json 的 proxy 节（与 LLM 调用同一出口策略）。
    备注：此 await 不受客户端断连取消（作者关 SSE 后调用仍跑完）——预留期
    可接受，最坏多烧一次小模型调用（Tokens 后付费，单次厘级）。
    """
    from backend.services.llm.proxy import get_active_proxy

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_S, proxy=get_active_proxy()
    ) as client:
        resp = await client.post(
            base_url,
            json=_build_payload(text, model),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        return _parse_response(resp.json())


async def polish_fragment(
    text: str,
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    protected_names: Sequence[str] = (),
) -> DeaiResult:
    """对 ≤100 字中文片段做「只改质感」的去AI味改写（预留接口的公共入口）。

    不检查 enabled——那是调用方的策略开关（ghost 链路用 is_deai_configured
    守门；设置面板的「试一试」直传表单值，未启用也能测）。

    覆盖参数（model/api_key/base_url）非空时优先生效，其余取
    model_config.json 的 deai 节。

    protected_names：宿主侧**保名闸**（超出模型契约的加护，非移植闸门——
    契约的专名闸只护引文/书名内容与拉丁 token，中文名不在其内）。原文中
    出现的每个保护名必须在改写稿中逐字保留，否则按事实失败回退原文。
    小说场景人名地名是最重要的事实，deai v1 又未训练叙事文本，这道闸
    补的就是这个窗口。names 来自调用方的场景上下文（如 kg 在场/死者名单）。
    """
    original = text.strip()
    cfg = get_deai_config()
    model = (model or "").strip() or cfg["model"]
    api_key = (api_key or "").strip() or cfg["api_key"]
    base_url = (base_url or "").strip() or cfg["base_url"]

    if not original:
        return DeaiResult(text=text, skipped=True, reason="空文本")
    if not api_key or not model:
        return DeaiResult(text=text, skipped=True, reason="未配置 DashScope Key 或模型名")
    if len(original) > INPUT_MAX:
        return DeaiResult(
            text=text, skipped=True,
            reason=f"输入{len(original)}字超过{INPUT_MAX}字上限，按契约不改写",
        )

    try:
        # _parse_response 已 strip；此处再 strip 一次防传输层契约漂移
        raw, usage = await _call_dashscope(original, model, api_key, base_url)
        output = raw.strip()
    except httpx.HTTPStatusError as e:
        snippet = ""
        try:
            snippet = e.response.text[:150]
        except Exception:
            pass
        logger.warning(f"[deai] API HTTP {e.response.status_code}: {snippet}")
        return DeaiResult(
            text=text, reason=f"API HTTP {e.response.status_code}: {snippet}",
        )
    except Exception as e:
        logger.warning(f"[deai] 调用失败（保底回退原文）: {e}")
        return DeaiResult(text=text, reason=f"网络错误: {e}")

    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)

    if not output:
        return DeaiResult(
            text=text, reason="模型空输出", tokens_in=tokens_in, tokens_out=tokens_out,
        )

    fact_failures, warnings = runtime_gates(original, output)
    # 宿主侧保名闸（见 docstring）：与契约事实闸同处置——失败即回退原文
    lost_names = [n for n in protected_names if n and n in original and n not in output]
    if lost_names:
        fact_failures.append(("保名闸", f"实体名被改: {lost_names}"))
    if fact_failures:
        detail = "；".join(f"{g}: {d}" for g, d in fact_failures)
        logger.info(f"[deai] 事实被改，回退原文: {detail}")
        return DeaiResult(
            text=text, reason="事实被改，回退原文: " + detail, warnings=warnings,
            tokens_in=tokens_in, tokens_out=tokens_out,
        )
    return DeaiResult(
        text=output, applied=True, warnings=warnings,
        tokens_in=tokens_in, tokens_out=tokens_out,
    )
