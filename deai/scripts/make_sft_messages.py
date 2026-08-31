# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""make_sft_messages.py — 把 clean_sft.jsonl（{"bad","good"} 对）转成千问/百炼风格 SFT JSONL。

输出每行：
{"messages":[{"role":"system","content":"<任务契约>"},
             {"role":"user","content":"原文：{bad}\\n修改后："},
             {"role":"assistant","content":"{good}"}]}

system 固定为任务契约提示词（与 validate_pairs.SYSTEM_PROMPT 同源，单一事实来源）。
用法: python scripts/make_sft_messages.py
      python scripts/make_sft_messages.py --in X --out Y
退出码: 0=成功 2=输入缺失
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_pairs import SYSTEM_PROMPT  # noqa: E402  任务契约提示词单一来源

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "data" / "sft" / "clean_sft.jsonl"
DEFAULT_OUT = ROOT / "data" / "sft" / "train30.jsonl"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="bad/good 对 → 千问/百炼 messages 格式")
    ap.add_argument("--in", dest="inp", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.inp.is_file():
        print(f"[致命] 输入文件不存在: {args.inp}")
        return 2

    n, bad_lines = 0, 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.inp.open(encoding="utf-8-sig") as f, args.out.open("w", encoding="utf-8", newline="\n") as out:
        for no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                bad_lines += 1
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            bad, good = obj.get("bad"), obj.get("good")
            if not (isinstance(bad, str) and bad.strip() and isinstance(good, str) and good.strip()):
                bad_lines += 1
                continue
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"原文：{bad.strip()}\n修改后："},
                {"role": "assistant", "content": good.strip()},
            ]
            out.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
            n += 1

    print(f"输入: {args.inp}")
    print(f"输出: {args.out} ({n} 条, system=任务契约, user=原文：{{bad}}\\n修改后：)")
    if bad_lines:
        print(f"[警告] 跳过无效行 {bad_lines} 行（空行/非法JSON/缺bad、good）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
