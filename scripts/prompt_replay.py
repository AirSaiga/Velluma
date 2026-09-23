# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""prompt 对拍与双跑（F2b/c · docs/next-phase/06-prompt-governance-hardening.md）。

默认模式（diff，零 LLM）：对两个快照目录（scripts/prompt_snapshot.py 产出）
逐文件比对，输出「哪条链哪个模式哪块变了」的人类可读摘要——AI 声称
「只改了 X」时，diff 会揭示它是否顺手动了 Y。

--run 模式（烧 token）：只对发生变化的场景双跑——旧 prompt（快照原文）
vs 新 prompt 各调一次 LLM（creative 槽，REASONING_DISABLED），确定性闸门
自动判分（字数 / 禁词表命中 load_prohibition_set；dock 另判 JSON 可解析），
并排报告（Markdown）落 logs/prompt_snapshots/，裁决记录追加
data/prompt_replay_log.jsonl——这是给 AI 二次修改的反馈证据。

用法：
    python scripts/prompt_replay.py --baseline          # 标记最新快照为 baseline
    python scripts/prompt_replay.py                     # baseline vs 最新（diff）
    python scripts/prompt_replay.py --old D1 --new D2   # 指定两目录（diff）
    python scripts/prompt_replay.py --run               # 对变化场景双跑（需 LLM 配置）
    python scripts/prompt_replay.py --verbose           # diff 附完整 unified diff

退出码：0=无差异 / 1=有差异（diff 模式）或双跑完成 / 2=错误（目录缺失、LLM 未配置等）。
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:  # Windows 控制台 GBK 防御
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

SNAPSHOT_ROOT = REPO_ROOT / "logs" / "prompt_snapshots"
BASELINE_FILE = SNAPSHOT_ROOT / "baseline.json"
REPLAY_LEDGER = REPO_ROOT / "data" / "prompt_replay_log.jsonl"
TS_DIR_RE = re.compile(r"^\d{8}-\d{6}$")

STITCH_MODES = ("stitch", "continue", "burst", "open", "outline")


# ============================================================
# 快照目录解析
# ============================================================

def _require_snapshot_dir(arg: str) -> Path:
    """把参数（目录名或绝对路径）解析成含 manifest.json 的快照目录。"""
    p = Path(arg)
    if not p.is_absolute():
        p = SNAPSHOT_ROOT / arg
    if not (p / "manifest.json").exists():
        raise SystemExit(f"[prompt_replay] 不是有效快照目录（缺 manifest.json）: {arg}")
    return p


def list_snapshots() -> list:
    """logs/prompt_snapshots/ 下全部合法快照目录名（时间戳名），按时间序。"""
    if not SNAPSHOT_ROOT.exists():
        return []
    return [
        d.name for d in sorted(SNAPSHOT_ROOT.iterdir())
        if d.is_dir() and TS_DIR_RE.match(d.name) and (d / "manifest.json").exists()
    ]


def load_manifest(dir_path: Path) -> dict:
    return json.loads((dir_path / "manifest.json").read_text(encoding="utf-8"))


def mark_baseline() -> int:
    snaps = list_snapshots()
    if not snaps:
        print("[prompt_replay] 没有任何快照——先跑 scripts/prompt_snapshot.py")
        return 2
    latest = snaps[-1]
    mf = load_manifest(SNAPSHOT_ROOT / latest)
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(
            {
                "dir": latest,
                "prompt_version": mf.get("prompt_version", ""),
                "marked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8", newline="\n",
    )
    print(f"[prompt_replay] baseline 已标记 → {latest}（PROMPT_VERSION={mf.get('prompt_version', '?')}）")
    print("    之后改完 prompt 再跑一次快照，直接运行本脚本即为对拍")
    return 0


def resolve_dirs(old_arg: str, new_arg: str) -> tuple:
    """解析待比对的两目录：显式参数（--old/--new）> baseline vs 最新。"""
    if bool(old_arg) != bool(new_arg):
        print("[prompt_replay] --old 与 --new 要么都给，要么都不给")
        raise SystemExit(2)
    if old_arg and new_arg:
        return _require_snapshot_dir(old_arg), _require_snapshot_dir(new_arg)

    snaps = list_snapshots()
    if not snaps:
        print("[prompt_replay] 没有任何快照——先跑 scripts/prompt_snapshot.py")
        raise SystemExit(2)
    if not BASELINE_FILE.exists():
        print("[prompt_replay] 未设 baseline：先跑 --baseline，或用 --old/--new 显式指定")
        raise SystemExit(2)
    base = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    old_name = base.get("dir", "")
    if old_name not in snaps:
        print(f"[prompt_replay] baseline 目录不存在: {old_name}")
        raise SystemExit(2)
    newer = [s for s in snaps if s > old_name]
    if not newer:
        print(f"[prompt_replay] baseline（{old_name}）之后没有新快照——"
              f"先改 prompt 再跑一次 scripts/prompt_snapshot.py")
        raise SystemExit(2)
    return SNAPSHOT_ROOT / old_name, SNAPSHOT_ROOT / newer[-1]


# ============================================================
# diff：哪条链哪个模式哪块变了
# ============================================================

def parse_prompt_filename(name: str):
    """stitch_continue.system.txt → (stitch, continue, system)；dock.user.txt → (dock, -, user)。"""
    stem, plane, _ext = name.rsplit(".", 2)
    if stem.startswith("stitch_"):
        return "stitch", stem[len("stitch_"):], plane
    if stem == "dock":
        return "dock", "-", plane
    return stem, "-", plane


def _heading_of(line: str) -> str:
    """prompt 块标题识别：system/user 的 # 标题、dock 的【…】节与「硬性要求：」式短标签行。"""
    s = line.strip()
    if s.startswith("#"):
        return s.lstrip("# ").strip() or s
    if s.startswith("【"):
        return s
    if s.endswith(("：", ":")) and len(s) <= 20:
        return s
    return ""


def _block_map(lines: list) -> list:
    """逐行的块归属坐标轴（[(行号→所属块标题)]，无标题区=“(文件头)”）。"""
    out, cur = [], "(文件头)"
    for l in lines:
        h = _heading_of(l)
        if h:
            cur = h
        out.append(cur)
    return out


def diff_file(old_text: str, new_text: str) -> dict:
    """单文件 diff 摘要：增删行数 + 命中的块标题集合 + unified diff 文本。"""
    old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
    blocks = _block_map(old_lines)
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    added = removed = 0
    hit_blocks, has_hunks = [], False
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        has_hunks = True
        added += j2 - j1
        removed += i2 - i1
        anchor = min(i1 if i1 < len(blocks) else len(blocks) - 1, len(blocks) - 1)
        hit_blocks.append(blocks[max(anchor, 0)])
    unified = ""
    if has_hunks:
        unified = "\n".join(difflib.unified_diff(
            old_lines, new_lines, fromfile="old", tofile="new", lineterm=""))
    return {"added": added, "removed": removed,
            "blocks": list(dict.fromkeys(hit_blocks)), "unified": unified}


def collect_diff(old_dir: Path, new_dir: Path) -> dict:
    """比对两快照目录全部 prompt 文件（文件名单侧存在也计入）。"""
    names = sorted(
        {p.name for p in old_dir.glob("*.txt")} | {p.name for p in new_dir.glob("*.txt")}
    )
    results: dict = {}
    for name in names:
        o, n = old_dir / name, new_dir / name
        old_text = o.read_text(encoding="utf-8") if o.exists() else None
        new_text = n.read_text(encoding="utf-8") if n.exists() else None
        chain, mode, plane = parse_prompt_filename(name)
        if old_text is None or new_text is None:
            results[name] = {
                "chain": chain, "mode": mode, "plane": plane, "added": 0, "removed": 0,
                "blocks": ["（文件单侧缺席）"],
                "unified": f"文件缺席：old={'有' if old_text is not None else '无'} / new={'有' if new_text is not None else '无'}",
            }
            continue
        if old_text == new_text:
            continue
        results[name] = {"chain": chain, "mode": mode, "plane": plane, **diff_file(old_text, new_text)}
    return results


def changed_scenarios(results: dict) -> list:
    """受影响场景（去重，固定序）：[(chain, mode, planes)]。"""
    by_sc: dict = {}
    for d in results.values():
        by_sc.setdefault((d["chain"], d["mode"]), []).append(d["plane"])
    order = [("stitch", m) for m in STITCH_MODES] + [("dock", "-")]
    return [(c, m, sorted(by_sc[(c, m)])) for c, m in order if (c, m) in by_sc]


def print_diff_report(old_dir: Path, new_dir: Path, results: dict, verbose: bool) -> None:
    old_mf, new_mf = load_manifest(old_dir), load_manifest(new_dir)
    print("=" * 64)
    print(f"旧：{old_dir.name}  PROMPT_VERSION={old_mf.get('prompt_version', '?')}  "
          f"第{old_mf.get('chapter_number', '?')}章")
    print(f"新：{new_dir.name}  PROMPT_VERSION={new_mf.get('prompt_version', '?')}  "
          f"第{new_mf.get('chapter_number', '?')}章")
    if old_mf.get("chapter_id") != new_mf.get("chapter_id"):
        print("⚠ 两次快照章节不同——diff 可能混入上下文变化（非 prompt 措辞变化）")
    print("=" * 64)
    if not results:
        print("无差异：两条链五个模式 + dock 的 prompt 逐字节一致。")
        return
    for name in sorted(results):
        d = results[name]
        blocks = "、".join(d["blocks"]) if d["blocks"] else ""
        print(f"[{d['chain']} / {d['mode']} / {d['plane']}]  +{d['added']}/-{d['removed']} 行"
              f"  块：{blocks}")
    sc = changed_scenarios(results)
    print("-" * 64)
    print(f"共 {len(results)} 个文件变化，涉及 {len(sc)} 个场景："
          + "、".join(f"{c}/{m}" for c, m, _ in sc))
    if old_mf.get("prompt_version") != new_mf.get("prompt_version"):
        print(f"prompt_version: {old_mf.get('prompt_version', '?')} → {new_mf.get('prompt_version', '?')}")
    else:
        print(f"⚠ prompt_version 未递增（{new_mf.get('prompt_version', '?')}）——"
              f"按纪律动措辞的提交必须递增 backend/services/prompts/prompt_version.py")
    if verbose:
        print("=" * 64)
        for name in sorted(results):
            print(f"\n----- {name} -----")
            print(results[name]["unified"])


# ============================================================
# --run：双跑 + 确定性闸门判分
# ============================================================

def _llm_configured() -> tuple:
    from backend.core.model_config import get_model_profile

    profile = get_model_profile("creative")
    return bool(profile.get("model") and profile.get("api_key")), profile.get("model", "")


async def _load_prohibitions(book_id: str):
    """四源合并禁忌面（load_prohibition_set 唯一权威；书级数据来自新快照）。"""
    from backend.database import AsyncSessionLocal
    from backend.models import Book
    from backend.services.style.prohibitions import load_prohibition_set

    try:
        async with AsyncSessionLocal() as db:
            book = await db.get(Book, str(book_id)) if book_id else None
            return await load_prohibition_set(db, book=book)
    except Exception as e:
        print(f"[prompt_replay] 禁忌面书级加载失败（降级种子库）: {e}")
        return await load_prohibition_set(None)


def _hit_patterns(pros, text: str) -> list:
    return sorted({entry.pattern for _m, entry in pros.finditer(text or "")})


def _score_text(text: str, pros, target: int, expect_json: bool) -> dict:
    """确定性闸门：字数 / 目标窗 / 禁词命中；dock 另判 JSON 可解析与 parts 数。"""
    patterns = _hit_patterns(pros, text)
    gates = {
        "chars": len(text),
        "prohibition_hits": len(patterns),
        "prohibition_patterns": patterns[:10],
    }
    if target > 0:
        gates["in_target_window"] = 0.4 * target <= len(text) <= 1.6 * target
    if expect_json:
        try:
            parsed = json.loads(text)
            parts = parsed.get("parts", []) if isinstance(parsed, dict) else []
            gates["json_ok"] = True
            gates["parts_count"] = len(parts) if isinstance(parts, list) else 0
        except Exception:
            gates["json_ok"] = False
            gates["parts_count"] = 0
    return gates


def _verdict(old_g: dict, new_g: dict) -> str:
    """自动裁决：禁词命中（主）> 目标窗 / JSON 可解析（次）；全平=作者裁决。"""
    if old_g.get("prohibition_hits", 0) != new_g.get("prohibition_hits", 0):
        return "新优" if new_g.get("prohibition_hits", 0) < old_g.get("prohibition_hits", 0) else "旧优"
    if old_g.get("in_target_window") != new_g.get("in_target_window"):
        return "新优" if new_g.get("in_target_window") else "旧优"
    if old_g.get("json_ok") != new_g.get("json_ok"):
        return "新优" if new_g.get("json_ok") else "旧优"
    return "平（作者裁决）"


async def run_double(old_dir: Path, new_dir: Path, results: dict) -> int:
    from backend.services.adaptive.stitch_gates import STITCH_MAX_TOKENS_FLOOR
    from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage

    ok, model_name = _llm_configured()
    if not ok:
        print("[prompt_replay] LLM 未配置（model_config.json 的 llm.creative 缺 api_key/model）——"
              "--run 不可用；diff 模式不受影响")
        return 2

    scenarios = changed_scenarios(results)
    if not scenarios:
        print("无差异，无需双跑")
        return 0

    new_mf = load_manifest(new_dir)
    pros = await _load_prohibitions(new_mf.get("book_id", ""))

    runs: list = []
    for chain, mode, planes in scenarios:
        stem = f"{chain}_{mode}" if chain == "stitch" else "dock"
        target = int(new_mf.get("context", {}).get("target_chars", {}).get(mode, 0)) \
            if chain == "stitch" else 0
        max_tokens = max(STITCH_MAX_TOKENS_FLOOR, target * 2 + 1000) if chain == "stitch" else 1600
        entry = {"chain": chain, "mode": mode, "planes": planes, "target": target,
                 "old": {}, "new": {}, "error": ""}
        for side, d in (("old", old_dir), ("new", new_dir)):
            try:
                system = (d / f"{stem}.system.txt").read_text(encoding="utf-8")
                user = (d / f"{stem}.user.txt").read_text(encoding="utf-8")
                result = await call_llm_with_usage(
                    system_prompt=system,
                    user_prompt=user,
                    model_type="creative",
                    temperature=0.7,
                    max_tokens=max_tokens,
                    reasoning_config=REASONING_DISABLED,
                )
                entry[side] = {
                    "text": (result.content or "").strip(),
                    "model": result.model_name,
                    "latency_ms": result.latency_ms,
                    "usage": result.usage,
                }
            except Exception as e:
                entry["error"] = f"{side}: {type(e).__name__}: {str(e)[:200]}"
        for side in ("old", "new"):
            if "text" in entry[side]:
                entry[side]["gates"] = _score_text(
                    entry[side]["text"], pros, target, expect_json=(chain == "dock"))
        if entry["old"].get("gates") and entry["new"].get("gates"):
            entry["verdict"] = _verdict(entry["old"]["gates"], entry["new"]["gates"])
        runs.append(entry)

    report_path = _write_report(old_dir, new_dir, model_name, runs)
    _append_ledger(old_dir, new_dir, runs, report_path)
    print(f"[prompt_replay] 双跑完成 → 报告 {report_path}；裁决已追加 {REPLAY_LEDGER}")
    return 1


def _write_report(old_dir: Path, new_dir: Path, model_name: str, runs: list) -> str:
    old_mf, new_mf = load_manifest(old_dir), load_manifest(new_dir)
    path = SNAPSHOT_ROOT / f"replay_{time.strftime('%Y%m%d-%H%M%S')}.md"
    lines = [
        "# prompt 双跑对照（replay）",
        "",
        f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模型：{model_name}（creative 槽，REASONING_DISABLED，temperature=0.7）",
        f"- 旧：{old_dir.name}（PROMPT_VERSION={old_mf.get('prompt_version', '?')}）",
        f"- 新：{new_dir.name}（PROMPT_VERSION={new_mf.get('prompt_version', '?')}）",
        f"- 章节：第{new_mf.get('chapter_number', '?')}章「{new_mf.get('chapter_name', '')}」",
        "",
        "> 同模型同参数下生成仍具随机性——闸门判分是客观信号，最终裁决在作者。",
        "",
    ]
    for r in runs:
        lines.append(f"## {r['chain']} / {r['mode']}（{'+'.join(r['planes'])} 变）")
        lines.append("")
        if r["error"]:
            lines.append(f"⚠ 双跑出错：{r['error']}")
            lines.append("")
            continue
        g_old, g_new = r["old"].get("gates", {}), r["new"].get("gates", {})
        target_note = f"（目标 {r['target']} 字）" if r["target"] else ""

        def _hit_cell(g):
            n = g.get("prohibition_hits", 0)
            pats = "、".join(g.get("prohibition_patterns", [])[:5])
            return f"{n}{('：' + pats) if pats else ''}"

        lines.append(f"| 闸门 | 旧{target_note} | 新{target_note} |")
        lines.append("|---|---|---|")
        lines.append(f"| 字数 | {g_old.get('chars', '-')} | {g_new.get('chars', '-')} |")
        if r["target"]:
            lines.append(f"| 目标窗 [0.4×, 1.6×] | {'在' if g_old.get('in_target_window') else '出'} "
                         f"| {'在' if g_new.get('in_target_window') else '出'} |")
        lines.append(f"| 禁词命中 | {_hit_cell(g_old)} | {_hit_cell(g_new)} |")
        if "json_ok" in g_old:
            lines.append(f"| JSON 可解析 / parts 数 | {g_old.get('json_ok')} / {g_old.get('parts_count')} "
                         f"| {g_new.get('json_ok')} / {g_new.get('parts_count')} |")
        lines.append("")
        lines.append(f"**自动裁决：{r.get('verdict', '（判分缺失）')}**")
        lines.append("")
        for side, label in (("old", "旧稿"), ("new", "新稿")):
            text = r[side].get("text", "")
            lines.append(f"### {label}（{r[side].get('model', '?')}，{r[side].get('latency_ms', 0)}ms）")
            lines.append("")
            for ln in (text or "（空产出）").splitlines():
                lines.append(f"> {ln}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return str(path)


def _append_ledger(old_dir: Path, new_dir: Path, runs: list, report_path: str) -> None:
    old_mf, new_mf = load_manifest(old_dir), load_manifest(new_dir)
    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "old": {"dir": old_dir.name, "prompt_version": old_mf.get("prompt_version", "")},
        "new": {"dir": new_dir.name, "prompt_version": new_mf.get("prompt_version", "")},
        "chapter_id": new_mf.get("chapter_id", ""),
        "scenarios": [
            {
                "chain": r["chain"], "mode": r["mode"], "planes": r["planes"],
                "target_chars": r["target"],
                "gates_old": r["old"].get("gates"),
                "gates_new": r["new"].get("gates"),
                "verdict": r.get("verdict", ""),
                "error": r.get("error", ""),
            }
            for r in runs
        ],
        "report": report_path,
    }
    REPLAY_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(REPLAY_LEDGER, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ============================================================
# main
# ============================================================

def main() -> int:
    ap = argparse.ArgumentParser(
        description="prompt 对拍（diff）与双跑对照（--run）——快照见 scripts/prompt_snapshot.py",
    )
    ap.add_argument("--baseline", action="store_true",
                    help="把最新快照标记为 baseline（此后默认对拍 baseline vs 最新）")
    ap.add_argument("--old", default="", help="旧快照目录（logs/prompt_snapshots/ 下的目录名或路径）")
    ap.add_argument("--new", default="", help="新快照目录")
    ap.add_argument("--run", action="store_true", help="对变化场景双跑 LLM 并出判分报告（烧 token）")
    ap.add_argument("--verbose", action="store_true", help="diff 附完整 unified diff")
    args = ap.parse_args()

    if args.baseline:
        return mark_baseline()

    old_dir, new_dir = resolve_dirs(args.old, args.new)
    results = collect_diff(old_dir, new_dir)
    print_diff_report(old_dir, new_dir, results, args.verbose)

    if args.run:
        return asyncio.run(run_double(old_dir, new_dir, results))
    return 1 if results else 0


if __name__ == "__main__":
    sys.exit(main())
