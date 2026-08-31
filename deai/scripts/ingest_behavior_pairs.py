# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""ingest_behavior_pairs.py — 写作台手动配对（行为数据）六闸入库。

数据源：宿主应用写作台「记改前/记改后」收集账本（默认
../data/deai_pairs.jsonl，格式与本仓库 validate_pairs.py 的输入契约兼容：
每行 {"id","bad","good","meta"}）。

与 validate_pairs.py 的分工：行为配对没有 facts 事实卡（bad 本身就是事实
源），走 check_gates 的 fact=None 路径执行六闸判据；validate_pairs.run()
的 facts 溯源层不适用（其缺失 facts 会把全部样本转「需人工」），故本脚本
独立成篇但**判据零私货**——check_gates 直接 import 自 validate_pairs，
改判据仍以那边为唯一权威。

六闸之外的额外防线：
  - 去重：完全相同的 (bad, good) 只入库一次（作者重复标记/撤销重标常态）；
  - bad > 100 字（契约 C1）：宿主收集侧已拒，这里再拦一道（手工编辑文件场景）。

用法：
  python scripts/ingest_behavior_pairs.py
  python scripts/ingest_behavior_pairs.py --input /path/deai_pairs.jsonl --min-diff 0.10
输出：
  data/sft/behavior_sft.jsonl   合格对（{"bad","good"}，与 clean_sft 同构，
                                 合并进正式训练集由人工确认后执行）
  logs/behavior_rejected.txt    按闸门分组的拒收报告（只报告不修复）
退出码：0=完成；2=致命（输入/禁词表缺失）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_pairs import check_gates, GATES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILE = ROOT / "contracts" / "forbidden_words.txt"
DEFAULT_INPUT = ROOT.parent / "data" / "deai_pairs.jsonl"
DEFAULT_OUT = ROOT / "data" / "sft" / "behavior_sft.jsonl"
DEFAULT_REPORT = ROOT / "logs" / "behavior_rejected.txt"


def load_forbidden() -> list[str]:
    if not FORBIDDEN_FILE.is_file():
        print(f"[致命] 禁词表缺失: {FORBIDDEN_FILE}")
        sys.exit(2)
    words = [w.strip() for w in FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines() if w.strip()]
    if not words:
        print(f"[致命] 禁词表为空: {FORBIDDEN_FILE}")
        sys.exit(2)
    return words


def load_pairs(path: Path) -> list[dict]:
    if not path.is_file():
        print(f"[致命] 收集账本不存在: {path}")
        print("先在写作台用「记改前/记改后」标记配对，或用 --input 指定路径。")
        sys.exit(2)
    records = []
    for no, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[警告] 第 {no} 行非法 JSON，跳过: {e.msg}")
            continue
        bad, good = obj.get("bad"), obj.get("good")
        if not (isinstance(bad, str) and bad.strip() and isinstance(good, str) and good.strip()):
            print(f"[警告] 第 {no} 行缺 bad/good 或为空，跳过")
            continue
        pid = obj.get("id")
        records.append({
            "line": no,
            "id": pid.strip() if isinstance(pid, str) and pid.strip() else f"L{no:04d}",
            "bad": bad.strip(),
            "good": good.strip(),
        })
    return records


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="写作台手动配对六闸入库（判据唯一权威 validate_pairs.check_gates）")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="宿主收集账本 deai_pairs.jsonl 路径")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="合格对输出（behavior_sft.jsonl）")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="拒收报告路径")
    ap.add_argument("--min-diff", type=float, default=0.10, help="像人闸最低差异率，默认0.10")
    args = ap.parse_args()

    forbidden = load_forbidden()
    records = load_pairs(args.input)
    if not records:
        print(f"账本为空: {args.input}")
        return 0

    seen: set[tuple[str, str]] = set()
    passed, rejected, manual_only, dupes = [], [], [], 0
    gate_counts = {g: 0 for g in GATES}
    gate_counts["C1超长"] = 0
    for rec in records:
        key = (rec["bad"], rec["good"])
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        if len(rec["bad"]) > 100:  # 契约 C1：宿主已拒，手工编辑文件兜底
            gate_counts["C1超长"] += 1
            rec["failures"] = [("C1超长", f"bad长度{len(rec['bad'])}超过100字输入上限")]
            rec["manual"] = []
            rejected.append(rec)
            continue
        failures, manual, _diff = check_gates(rec["bad"], rec["good"], forbidden, args.min_diff, fact=None)
        rec["failures"], rec["manual"] = failures, manual
        for g, _ in failures:
            gate_counts[g] += 1
        if failures:
            rejected.append(rec)
        elif manual:
            manual_only.append(rec)
        else:
            passed.append(rec)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        for rec in passed:
            f.write(json.dumps({"bad": rec["bad"], "good": rec["good"]}, ensure_ascii=False) + "\n")

    lines = [
        f"behavior_rejected — {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"输入: {args.input}",
        f"统计: 读取{len(records)} 去重跳过{dupes} 通过{len(passed)} 拒绝{len(rejected)} 需人工{len(manual_only)}",
        "各闸拒绝数: " + "  ".join(f"{g}={n}" for g, n in gate_counts.items() if n),
        "说明: 只报告不修复；拒收对子留在宿主账本里，可改后重跑。合并 behavior_sft.jsonl",
        "      进正式训练集（clean_sft.jsonl）前请人工过目（契约「宁可少入库」）。",
        "",
        "== 按原因分组（每组前5条例子）==",
    ]
    for gate in list(GATES) + ["C1超长"]:
        group = [r for r in rejected if any(g == gate for g, _ in r["failures"])]
        if not group:
            continue
        lines.append(f"[{gate}] 共{len(group)}条")
        for r in group[:5]:
            details = "；".join(d for g, d in r["failures"] if g == gate)
            lines.append(f"  - line {r['line']} id={r['id']}  {details}")
            lines.append(f"    bad : {r['bad']}")
            lines.append(f"    good: {r['good']}")
        if len(group) > 5:
            lines.append(f"  ……其余{len(group) - 5}条略")
    if manual_only:
        lines.append(f"[需人工] 共{len(manual_only)}条（引号不配对，引文校验不可靠）")
        for r in manual_only[:5]:
            reasons = "；".join(d for _, d in r["manual"])
            lines.append(f"  - line {r['line']} id={r['id']}  {reasons}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"读取: {len(records)}  去重: {dupes}  通过: {len(passed)}  "
          f"拒绝: {len(rejected)}  需人工: {len(manual_only)}")
    print("各闸拒绝数: " + "  ".join(f"{g}={n}" for g, n in gate_counts.items() if n))
    print(f"输出: {args.out} ({len(passed)} 条)")
    print(f"报告: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
