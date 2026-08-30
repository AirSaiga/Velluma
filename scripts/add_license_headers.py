# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""==== 批量补齐 AGPL-3.0 SPDX 许可证头（幂等维护工具） ====

用法（仓库根目录）：
    python scripts/add_license_headers.py             # 实际写入
    python scripts/add_license_headers.py --dry-run   # 只报告不写入

规则（2026-08-30 文件规范化施工定稿，AGENTS.md「代码规范」节同步）：
- 范围：git 追踪的全部 .py（backend/ + scripts/ 等），排除 *_deprecated* 整树
        （归档引擎不参与 import 链，动它只会制造「还在维护」的假信号）
- 幂等：前 5 行已含 SPDX-License-Identifier 或 AGPL 字样即跳过——
        新文件漏头随时重跑本脚本补齐
- 空文件跳过（保留空 __init__.py 的「空包标记」语义）
- shebang（#!）与 PEP 263 coding 声明必须留在头注释之前（PEP 263 要求
  coding 声明在第 1/2 行，插错位置会把它挤到第 3 行失效）
- 纯插入施工：只在精确偏移处插入头注释块，其余字节逐字不动
  （按文件自身主导行尾定头的行尾，UTF-8 读写、BOM 保真）
"""

import re
import subprocess
import sys
from pathlib import Path

HEADER_LINES = [
    "# SPDX-License-Identifier: AGPL-3.0-or-later",
    "# Copyright (C) 2026 Velluma Contributors",
]

# PEP 263 编码声明正则（官方文档定义的形态）
CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-_.a-zA-Z0-9]+")


def tracked_py_files():
    """git ls-files 取追踪 .py，排除 _deprecated 与磁盘上已不存在的路径。"""
    out = subprocess.run(
        ["git", "ls-files", "*.py"], capture_output=True, text=True, check=True
    )
    files = []
    for line in out.stdout.splitlines():
        p = Path(line.strip())
        if "_deprecated" in p.parts or not p.exists():
            continue
        files.append(p)
    return files


def detect_eol(text):
    """取文件前 200 字符内出现的主导行尾；无换行默认 LF。"""
    return "\r\n" if "\r\n" in text[:200] else "\n"


def insert_offset(lines):
    """头注释的落点（行号）：依次让位给 shebang 与 coding 声明；
    返回 (行号, 字节偏移)——偏移=前各行长度+各自行分隔符。"""
    i = 0
    if i < len(lines) and lines[i].startswith("#!"):
        i += 1
    if i < len(lines) and CODING_RE.match(lines[i]):
        i += 1
    offset = sum(len(ln) + 1 for ln in lines[:i])
    return i, offset


def main():
    dry_run = "--dry-run" in sys.argv
    counts = {"inserted": 0, "has_header": 0, "empty": 0}
    for path in tracked_py_files():
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        lines = text.split("\n")

        if not text.strip():
            counts["empty"] += 1
            continue
        if any("SPDX-License-Identifier" in ln or "AGPL" in ln for ln in lines[:5]):
            counts["has_header"] += 1
            continue

        eol = detect_eol(text)
        _, offset = insert_offset(lines)
        header_block = eol.join(HEADER_LINES) + eol
        if dry_run:
            print(f"[dry-run] 将插入: {path}")
        else:
            new_text = text[:offset] + header_block + text[offset:]
            data = new_text.encode("utf-8")
            if has_bom:
                data = b"\xef\xbb\xbf" + data
            path.write_bytes(data)
        counts["inserted"] += 1

    label = "dry-run " if dry_run else ""
    print(
        f"\n{label}完成：插入 {counts['inserted']} / 已有头跳过 {counts['has_header']}"
        f" / 空文件跳过 {counts['empty']}"
    )


if __name__ == "__main__":
    main()
