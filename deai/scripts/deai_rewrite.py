# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""deai_rewrite.py — 去AI味改写调用封装（生产用，实现契约§6保底策略）。

保底逻辑（docs/contract.md §6）：
  - 输入超过 100 字 → 不改写，原样返回；
  - 模型输出过不了事实类闸门（数字闸/专名闸/新增事实闸，相对输入文本）→ 回退原文；
  - 输出仅触发非事实闸（如长度/套话/像人）→ 仍然返回改写，但在结果里标注警告。
调用要点（实测踩坑记录，勿改）：DashScope 原生接口 + 部署后的 deployed_model
+ enable_thinking=false。重新部署/重训后模型 ID 会变，用部署管理接口查询：
GET https://dashscope.aliyuncs.com/api/v1/deployments
用法：
  from deai_rewrite import rewrite; rewrite("你的文本")
  命令行：python scripts/deai_rewrite.py "文本"
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_pairs import check_gates, FACT_GATES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILE = ROOT / "contracts" / "forbidden_words.txt"
DEFAULT_MODEL = "qwen3-4b-instruct-2507-78a06917f4ca"  # 2026-08-31 部署的 deployed_model
API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
INPUT_MAX = 100


def _forbidden() -> list[str]:
    return [w.strip() for w in FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines() if w.strip()]


def rewrite(text: str, model: str = DEFAULT_MODEL, api_key: str | None = None,
            temperature: float = 0.3, min_diff: float = 0.10) -> dict:
    """改写一段 <=100 字的中文片段。返回 {output, fallback, reason, warnings}。"""
    text = text.strip()
    api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
    if len(text) > INPUT_MAX:
        return {"output": text, "fallback": True,
                "reason": f"输入{len(text)}字超过{INPUT_MAX}字上限，按契约不改写", "warnings": []}
    if not api_key:
        return {"output": text, "fallback": True, "reason": "未配置DASHSCOPE_API_KEY", "warnings": []}

    messages = [
        {"role": "system", "content": "你是中文润色助手，把用户给的片段改得更像人写的。"
                                      "只改语言质感，不改事实、数字、日期、专名、引文，不新增观点，输出不超过原长的120%。"},
        {"role": "user", "content": f"原文：{text}\n修改后："},
    ]
    body = json.dumps({"model": model, "input": {"messages": messages},
                       "parameters": {"temperature": temperature, "max_tokens": 256,
                                      "result_format": "message", "enable_thinking": False}}).encode()
    req = urllib.request.Request(API_URL, data=body,
                                 headers={"Authorization": f"Bearer {api_key}",
                                          "Content-Type": "application/json"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read().decode("utf-8"))
            output = resp["output"]["choices"][0]["message"]["content"].strip()
            break
        except urllib.error.HTTPError as e:
            return {"output": text, "fallback": True,
                    "reason": f"API HTTP {e.code}: {e.read().decode('utf-8')[:150]}", "warnings": []}
        except (urllib.error.URLError, KeyError, OSError) as e:
            if attempt == 2:
                return {"output": text, "fallback": True, "reason": f"网络错误: {e}", "warnings": []}

    failures, _manual, _diff = check_gates(text, output, _forbidden(), min_diff, fact=None)
    fact_fail = [(g, d) for g, d in failures if g in FACT_GATES]
    other_fail = [(g, d) for g, d in failures if g not in FACT_GATES]
    if fact_fail:
        return {"output": text, "fallback": True,
                "reason": "事实被改，回退原文: " + "；".join(f"{g}: {d}" for g, d in fact_fail),
                "warnings": [f"{g}: {d}" for g, d in other_fail]}
    return {"output": output, "fallback": False, "reason": "",
            "warnings": [f"{g}: {d}" for g, d in other_fail]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("用法: python scripts/deai_rewrite.py \"待改写文本\"")
        sys.exit(2)
    result = rewrite(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)
