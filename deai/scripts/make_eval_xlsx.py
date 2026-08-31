# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""make_eval_xlsx.py — 按百炼评测集官方模板生成 eval15_bailian.xlsx。

模板（data/eval/bailian_eval_template.xlsx，2026-08-31 从百炼控制台下载）：
  Sheet1，A1=Prompt、B1=Completion 表头，第2行起为示例数据。
做法（Preserve First）：
  克隆模板 → 删除示例行 → 写入 15 行：
    Prompt     = "原文：{bad}\\n修改后："（与训练 user 格式逐字一致）
    Completion = 参考答案 good（已过六闸+facts溯源，见 data/facts_eval.jsonl）
  不改表头、不加样式/工作表，保持平台可解析结构。
用法: python scripts/make_eval_xlsx.py
退出码: 0=成功并读回校验通过 1=数据校验失败 2=模板/数据缺失
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "facts_eval.jsonl"
DEFAULT_TEMPLATE = ROOT / "data" / "eval" / "bailian_eval_template.xlsx"
DEFAULT_OUT = ROOT / "data" / "eval" / "eval15_bailian.xlsx"
EXPECTED_HEADERS = ("Prompt", "Completion")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="按百炼模板生成评测集 xlsx")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    for p, tag in ((args.template, "模板"), (args.data, "数据")):
        if not p.is_file():
            print(f"[致命] {tag}缺失: {p}")
            return 2

    items = []
    with args.data.open(encoding="utf-8-sig") as f:
        for no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            bad, good = obj.get("bad"), obj.get("good")
            if not (isinstance(bad, str) and bad.strip() and isinstance(good, str) and good.strip()):
                print(f"[失败] line {no} id={obj.get('id')} 缺bad/good")
                return 1
            items.append((obj["id"], bad.strip(), good.strip()))
    print(f"数据: {args.data} -> {len(items)} 对（参考答案已过六闸）")

    wb = load_workbook(args.template)
    ws = wb.worksheets[0]
    headers = tuple(ws.cell(row=1, column=c).value for c in (1, 2))
    if headers != EXPECTED_HEADERS:
        print(f"[失败] 模板表头 {headers} 与预期 {EXPECTED_HEADERS} 不符")
        return 1
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)  # 清掉模板示例行

    wrap = Alignment(wrap_text=True, vertical="top")
    for i, (_pid, bad, good) in enumerate(items, start=2):
        a = ws.cell(row=i, column=1, value=f"原文：{bad}\n修改后：")
        b = ws.cell(row=i, column=2, value=good)
        a.alignment, b.alignment = wrap, wrap
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 45

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)

    # 读回语义校验：行数、列数、非空、表头、抽查内容
    chk = load_workbook(args.out).worksheets[0]
    n = chk.max_row - 1
    problems = []
    if tuple(chk.cell(row=1, column=c).value for c in (1, 2)) != EXPECTED_HEADERS:
        problems.append("表头被改动")
    if n != len(items):
        problems.append(f"数据行数{n}≠{len(items)}")
    for r in range(2, chk.max_row + 1):
        for c in (1, 2):
            v = chk.cell(row=r, column=c).value
            if not isinstance(v, str) or not v.strip():
                problems.append(f"{chr(64+c)}{r} 为空")
    if chk.max_column != 2:
        problems.append(f"列数{chk.max_column}≠2")
    if problems:
        print(f"[失败] 读回校验: {problems[:5]}")
        return 1

    print(f"输出: {args.out}")
    print(f"读回校验: 表头OK，数据 {n} 行×2 列，无空单元格")
    print("样例预览（第1行）:")
    print(f"  Prompt     = {chk.cell(row=2, column=1).value!r}")
    print(f"  Completion = {chk.cell(row=2, column=2).value!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
