# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""阶段1检查：目录结构 + 任务契约文件完整性。

用法：python scripts/check_stage1.py
退出码：0 = 全部通过；1 = 存在失败项。
报告同时落盘到 logs/stage1_report.txt。
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "logs" / "stage1_report.txt"

REQUIRED_DIRS = [
    "contracts",
    "data/sft",
    "data/dpo",
    "data/eval",
    "docs",
    "scripts",
    "logs",
]

REQUIRED_FILES = [
    "README.md",
    "contracts/task_contract.md",
    "contracts/data_format.md",
    "contracts/forbidden_words.txt",
    "docs/roadmap.md",
    "docs/open_questions.md",
    "scripts/check_stage1.py",
]

# 契约的权威违禁词表（与用户需求逐字对应），用于核对 forbidden_words.txt
FORBIDDEN = [
    "综上所述", "值得注意的是", "赋能", "闭环", "抓手",
    "全链路", "多维度", "显著提升", "夯实基础", "生态化反",
]

CONTRACT_KEYWORDS = {
    "contracts/task_contract.md": ["C1", "C2", "C3", "C4", "C5", "C6",
                                   "120%", "forbidden_words.txt"],
    "contracts/data_format.md": ['"messages"', '"prompt"', '"chosen"', '"rejected"', "jsonl"],
}

results = []  # (ok, path, detail)


def check(ok, path, detail=""):
    results.append((bool(ok), str(path), detail))


for d in REQUIRED_DIRS:
    p = ROOT / d
    check(p.is_dir(), p, "目录不存在")

for f in REQUIRED_FILES:
    p = ROOT / f
    check(p.is_file() and p.stat().st_size > 0, p, "文件缺失或为空")

fw_path = ROOT / "contracts" / "forbidden_words.txt"
if fw_path.is_file():
    raw = fw_path.read_text(encoding="utf-8")
    words = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    missing = [w for w in FORBIDDEN if w not in words]
    extra = [w for w in words if w not in FORBIDDEN]
    dupes = sorted({w for w in words if words.count(w) > 1})
    detail = ""
    if missing or extra or dupes:
        detail = f"缺失={missing} 多余={extra} 重复={dupes}"
    check(not detail, fw_path, detail)

for rel, kws in CONTRACT_KEYWORDS.items():
    p = ROOT / rel
    if p.is_file():
        text = p.read_text(encoding="utf-8")
        for kw in kws:
            check(kw in text, p, f"缺少关键词: {kw}")

lines = []
for ok, p, d in results:
    mark = "[OK]  " if ok else "[FAIL]"
    suffix = f"  -- {d}" if (d and not ok) else ""
    lines.append(f"{mark} {p}{suffix}")

fails = [(p, d) for ok, p, d in results if not ok]
lines.append("-" * 60)
lines.append(f"检查项: {len(results)}  通过: {len(results) - len(fails)}  失败: {len(fails)}")
lines.append(f"违禁词表条数: {len(FORBIDDEN)}")
if fails:
    lines.append("失败样例（前5条）:")
    for p, d in fails[:5]:
        lines.append(f"  - {p}  {d}")
else:
    lines.append("失败样例（前5条）: 无")

report = "\n".join(lines)
print(report)
if REPORT.parent.is_dir():
    REPORT.write_text(report + "\n", encoding="utf-8")
    print(f"\n报告已写入: {REPORT}")

sys.exit(1 if fails else 0)
