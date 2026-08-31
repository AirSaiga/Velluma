# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""check_jsonl.py — 校验 SFT 训练文件与评测提示文件（阶段5产物）。

校验对象（默认两个）：
  data/sft/train30.jsonl  每行 messages = system/user/assistant
  data/eval/eval15.jsonl  每行 messages = system/user（无 assistant）
user 统一格式："原文：{bad}\\n修改后："

打印：条数、平均bad长度、平均good长度、禁词命中数（assistant 侧必为 0，
bad 输入侧命中仅作信息展示——bad 本来就是AI腔，允许含禁词）。
退出码: 0=全部合规 1=结构非法或 assistant 含禁词 2=文件缺失
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILE = ROOT / "contracts" / "forbidden_words.txt"
DEFAULT_FILES = [ROOT / "data" / "sft" / "train30.jsonl", ROOT / "data" / "eval" / "eval15.jsonl"]
USER_PREFIX, USER_SUFFIX = "原文：", "\n修改后："


def extract_bad(user_content: str) -> str | None:
    if user_content.startswith(USER_PREFIX) and user_content.endswith(USER_SUFFIX):
        return user_content[len(USER_PREFIX):-len(USER_SUFFIX)]
    return None


def check_file(path: Path, forbidden: list[str]) -> tuple[bool, list[str], dict]:
    stats = {"n": 0, "bad_len": [], "good_len": [], "fw_assistant": 0, "fw_bad": 0, "has_assistant": False}
    problems = []
    with path.open(encoding="utf-8-sig") as f:
        for no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                problems.append(f"line {no}: 空行")
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"line {no}: 非法JSON({e.msg})")
                continue
            msgs = obj.get("messages") if isinstance(obj, dict) else None
            if not isinstance(msgs, list) or not msgs:
                problems.append(f"line {no}: 无messages数组")
                continue
            roles = [m.get("role") for m in msgs if isinstance(m, dict)]
            if roles and roles[0] != "system":
                problems.append(f"line {no}: 首个role不是system")
            if roles[:2] != ["system", "user"]:
                problems.append(f"line {no}: roles={roles}，应为system,user[,assistant]")
                continue
            user_content = msgs[1].get("content", "")
            bad = extract_bad(user_content) if isinstance(user_content, str) else None
            if bad is None or not bad.strip():
                problems.append(f"line {no}: user格式不是 原文：{{bad}}\\n修改后：")
                continue
            stats["n"] += 1
            stats["bad_len"].append(len(bad))
            stats["fw_bad"] += sum(bad.count(w) for w in forbidden)
            if len(roles) >= 3 and roles[2] == "assistant":
                stats["has_assistant"] = True
                good = msgs[2].get("content", "")
                if not isinstance(good, str) or not good.strip():
                    problems.append(f"line {no}: assistant内容为空")
                    continue
                stats["good_len"].append(len(good))
                hits = [w for w in forbidden if w in good]
                if hits:
                    stats["fw_assistant"] += sum(good.count(w) for w in hits)
                    problems.append(f"line {no}: assistant含禁词{hits}")
            elif len(roles) > 2:
                problems.append(f"line {no}: 多余role {roles[2:]}")
    ok = not problems
    return ok, problems, stats


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="校验 train/eval JSONL 结构与统计")
    ap.add_argument("files", type=Path, nargs="*", default=DEFAULT_FILES)
    args = ap.parse_args()

    if not FORBIDDEN_FILE.is_file():
        print(f"[致命] 禁词表缺失: {FORBIDDEN_FILE}")
        return 2
    forbidden = [w.strip() for w in FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines() if w.strip()]

    all_ok = True
    for path in args.files:
        if not path.is_file():
            print(f"[缺失] {path}")
            all_ok = False
            continue
        ok, problems, s = check_file(path, forbidden)
        all_ok = all_ok and ok
        avg_bad = sum(s["bad_len"]) / len(s["bad_len"]) if s["bad_len"] else 0
        avg_good = (sum(s["good_len"]) / len(s["good_len"])) if s["good_len"] else None
        good_disp = f"{avg_good:.1f}" if avg_good is not None else "-（无assistant）"
        print(f"文件: {path}")
        print(f"  条数={s['n']}  平均bad长度={avg_bad:.1f}  平均good长度={good_disp}  "
              f"禁词命中数(assistant)={s['fw_assistant']}  禁词命中数(bad输入,仅信息)={s['fw_bad']}")
        if problems:
            print(f"  问题（前5条）:")
            for p in problems[:5]:
                print(f"    - {p}")
    print("结论: " + ("全部合规" if all_ok else "存在问题，见上"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
