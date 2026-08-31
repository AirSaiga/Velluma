# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""make_eval_prompts.py — 由 data/facts_eval.jsonl 生成评测提示文件 eval15.jsonl。

输出每行只含 system+user（不给 assistant，评测时由被测模型生成）：
{"messages":[{"role":"system","content":"<任务契约>"},
             {"role":"user","content":"原文：{bad}\\n修改后："}]}

溯源说明（C6 评测隔离）：eval15.jsonl 本身不带 meta（保持纯提示格式），
事实/模板溯源在 data/facts_eval.jsonl（id/cat/fact/bad/template）。

本脚本内置隔离校验，不过则拒绝生成：
  1) 事实隔离：评测事实与 facts_seed.txt 训练事实不得相同，文本相似度>0.6 判重；
  2) 模板隔离：评测 bad 模板不得与训练用过的 5 种风格重名；
  3) 卡片规则：fact ≤60 字、必含数字/拉丁/书名引号内容、bad ≤100 字。
用法: python scripts/make_eval_prompts.py
退出码: 0=成功 1=隔离或规则校验失败 2=输入缺失
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_pairs import SYSTEM_PROMPT, NUMBER_RE, LATIN_RE, quote_spans  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL = ROOT / "data" / "facts_eval.jsonl"
DEFAULT_SEED = ROOT / "data" / "facts_seed.txt"
DEFAULT_OUT = ROOT / "data" / "eval" / "eval15.jsonl"

TRAIN_TEMPLATES = {"基准", "工作汇报体", "营销文案体", "客服通知体", "百科说明体", "总结陈词体"}
SIM_THRESHOLD = 0.6
FACT_MAX, BAD_MAX = 60, 100


def load_seed_facts(path: Path) -> dict[str, str]:
    cards = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                cards[parts[0].strip()] = parts[2].strip()
    return cards


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="评测提示文件生成（含 C6 隔离校验）")
    ap.add_argument("--eval", type=Path, default=DEFAULT_EVAL, help="facts_eval.jsonl")
    ap.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="facts_seed.txt")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="eval15.jsonl 输出")
    args = ap.parse_args()

    if not args.eval.is_file():
        print(f"[致命] 评测事实源不存在: {args.eval}")
        return 2

    items, errors = [], []
    with args.eval.open(encoding="utf-8-sig") as f:
        for no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"line {no}: 非法JSON({e.msg})")
                continue
            for k in ("id", "cat", "template", "fact", "bad"):
                if not isinstance(obj.get(k), str) or not obj[k].strip():
                    errors.append(f"line {no}: 缺字段或为空 {k}")
            if errors and errors[-1].startswith(f"line {no}:"):
                continue
            items.append({k: obj[k].strip() for k in ("id", "cat", "template", "fact", "bad")})

    seed = load_seed_facts(args.seed)

    # 卡片规则
    for it in items:
        if len(it["fact"]) > FACT_MAX:
            errors.append(f"{it['id']}: fact长度{len(it['fact'])}>{FACT_MAX}")
        if not (NUMBER_RE.search(it["fact"]) or LATIN_RE.search(it["fact"]) or quote_spans(it["fact"])):
            errors.append(f"{it['id']}: fact未检出数字/拉丁/书名引号内容")
        if len(it["bad"]) > BAD_MAX:
            errors.append(f"{it['id']}: bad长度{len(it['bad'])}>{BAD_MAX}")
        if it["template"] in TRAIN_TEMPLATES:
            errors.append(f"{it['id']}: 模板[{it['template']}]与训练集重名，违反C6模板隔离")

    # 事实隔离：与训练事实逐条比对相似度
    for it in items:
        for sid, stext in seed.items():
            ratio = difflib.SequenceMatcher(None, it["fact"], stext).ratio()
            if it["fact"] == stext or ratio > SIM_THRESHOLD:
                errors.append(f"{it['id']}: 与训练卡{sid}事实重复(相似度{ratio:.2f})，违反C6事实隔离")
                break

    if errors:
        print(f"[拒绝生成] 校验失败 {len(errors)} 项：")
        for e in errors[:5]:
            print(f"  - {e}")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for it in items:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"原文：{it['bad']}\n修改后："},
            ]
            out.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")

    cats = {}
    for it in items:
        cats[it["cat"]] = cats.get(it["cat"], 0) + 1
    templates = sorted({it["template"] for it in items})
    print(f"输入: {args.eval}")
    print(f"输出: {args.out} ({len(items)} 条, 仅system+user, 无assistant)")
    print(f"类别: {cats}")
    print(f"bad模板: {templates}（与训练模板无交集）")
    print(f"隔离校验: 与{len(seed)}张训练卡零重复（阈值{SIM_THRESHOLD}），通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
