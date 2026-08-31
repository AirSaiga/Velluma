# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""eval_model.py — 调用百炼自定义模型，对 holdout 评测集跑六闸评测（阶段8）。

流程：
  1. 读 data/facts_holdout.jsonl（id/cat/fact/bad），构造与训练一致的
     messages（system=任务契约，user="原文：{bad}\\n修改后："）；
  2. 逐条调用模型（OpenAI 兼容 chat/completions，默认百炼 compatible-mode 地址，
     以控制台模型详情页"调用示例"为准，可用 --base-url 覆盖）；
  3. 模型输出过六闸（复用 validate_pairs.check_gates，facts 溯源）；
  4. 报告落盘：logs/model_eval_report.txt + logs/model_outputs.jsonl，控制台打印
     统计与失败样例前5条。

用法：
  python scripts/eval_model.py --model qwen3-4b-instruct-2507-ft-xxxx   # 需 DASHSCOPE_API_KEY
  python scripts/eval_model.py --model mock --mock                      # 无API管线自测
退出码: 0=评测完成（有失败样本也算正常）2=致命错误（数据/密钥缺失、API全挂）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_pairs import SYSTEM_PROMPT, check_gates  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "facts_holdout.jsonl"
DEFAULT_FORBIDDEN = ROOT / "contracts" / "forbidden_words.txt"
DEFAULT_REPORT = ROOT / "logs" / "model_eval_report.txt"
DEFAULT_OUTPUTS = ROOT / "logs" / "model_outputs.jsonl"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
GATES = ("数字闸", "专名闸", "长度闸", "套话闸", "新增事实闸", "像人闸")


def call_api(base_url: str, api_key: str, model: str, messages: list, temperature: float, api: str) -> str:
    if api == "dashscope":
        body = json.dumps({
            "model": model,
            "input": {"messages": messages},
            "parameters": {"temperature": temperature, "max_tokens": 256,
                           "result_format": "message", "enable_thinking": False},
        }).encode("utf-8")
    else:  # openai 兼容入口（百炼调优模型官方声明不支持，仅留作通用回退）
        body = json.dumps({
            "model": model, "messages": messages,
            "temperature": temperature, "max_tokens": 256,
        }).encode("utf-8")
    req = urllib.request.Request(
        base_url, data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode("utf-8"))
    if api == "dashscope":
        return resp["output"]["choices"][0]["message"]["content"]
    return resp["choices"][0]["message"]["content"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="百炼自定义模型六闸评测")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--model", required=True, help="自定义模型ID（控制台模型列表可复制）")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API地址，以控制台调用示例为准")
    ap.add_argument("--api", choices=("dashscope", "openai"), default="dashscope",
                    help="调用协议：dashscope=原生（调优模型官方仅支持此方式）；openai=兼容模式回退")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=0, help="只评前N条（0=全部）")
    ap.add_argument("--mock", action="store_true", help="不调API，用事实卡文本模拟输出，自测管线")
    ap.add_argument("--min-diff", type=float, default=0.10)
    args = ap.parse_args()

    if not args.data.is_file():
        print(f"[致命] 评测数据缺失: {args.data}")
        return 2
    forbidden = [w.strip() for w in DEFAULT_FORBIDDEN.read_text(encoding="utf-8").splitlines() if w.strip()]

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not args.mock and not api_key:
        print("[致命] 未设置 DASHSCOPE_API_KEY 环境变量（或用 --mock 自测管线）")
        return 2

    items = []
    with args.data.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if args.limit > 0:
        items = items[:args.limit]

    gate_counts = {g: 0 for g in GATES}
    records, api_errors = [], 0
    for it in items:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"原文：{it['bad']}\n修改后："},
        ]
        if args.mock:
            output = it["fact"]  # 模拟一个"保真但没怎么改"的输出，用于管线自测
        else:
            output = None
            last_err = None
            for attempt in (1, 2):  # 偶发SSL断连重试一次
                try:
                    output = call_api(args.base_url, api_key, args.model, messages,
                                      args.temperature, args.api).strip()
                    last_err = None
                    break
                except urllib.error.HTTPError as e:
                    detail = ""
                    try:
                        detail = e.read().decode("utf-8")[:200]
                    except Exception:
                        pass
                    last_err = ("API", f"HTTP {e.code}: {detail}")
                    break  # 参数/权限类错误重试无意义
                except (urllib.error.URLError, KeyError, TimeoutError, OSError) as e:
                    last_err = ("API", f"调用失败(第{attempt}次): {e}")
            if output is None:
                api_errors += 1
                records.append({"id": it["id"], "bad": it["bad"], "fact": it["fact"],
                                "output": None, "failures": [last_err], "diff": None})
                continue
        failures, _manual, diff = check_gates(it["bad"], output, forbidden, args.min_diff, it["fact"])
        for g, _ in failures:
            gate_counts[g] += 1
        records.append({"id": it["id"], "bad": it["bad"], "fact": it["fact"],
                        "output": output, "failures": failures, "diff": round(diff, 3)})

    n = len(records)
    passed = sum(1 for r in records if not r["failures"])
    outs = [r["output"] for r in records if r["output"] is not None]
    avg_out = sum(len(o) for o in outs) / len(outs) if outs else 0

    lines = [
        f"model_eval_report — {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"模型: {args.model}  温度: {args.temperature}  模式: {'mock' if args.mock else 'API'}",
        f"评测集: {args.data}  条数: {n}",
        f"结果: 六闸全过 {passed}/{n}（通过率 {passed / n * 100:.0f}%）"
        + (f"  API失败: {api_errors}" if api_errors else ""),
        "各闸拦截数: " + "  ".join(f"{g}={gate_counts[g]}" for g in GATES),
        f"平均输出长度: {avg_out:.1f} 字",
        "",
    ]
    fails = [r for r in records if r["failures"]]
    for r in fails[:5]:
        lines.append(f"[{r['id']}] " + "；".join(f"{g}: {d}" for g, d in r["failures"]))
        lines.append(f"  bad   : {r['bad']}")
        lines.append(f"  output: {r['output']}")
    if len(fails) > 5:
        lines.append(f"……其余{len(fails) - 5}条见 model_outputs.jsonl")
    DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with DEFAULT_OUTPUTS.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n".join(lines))
    print(f"报告: {DEFAULT_REPORT}")
    print(f"明细: {DEFAULT_OUTPUTS}")
    return 0 if api_errors < n else 2


if __name__ == "__main__":
    sys.exit(main())
