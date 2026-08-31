# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""validate_pairs.py — bad/good 教师数据对的入库校验（六闸 + facts 溯源）。

契约依据: docs/contract.md §5（六闸判据）§6（失败处理）及阶段4增强规则：
  - good 的数字/日期/专名必须能回溯到同条 bad 或 facts_seed 事实卡；
  - facts 未提供的新数字/英文专名/引文书名内容判废（新增事实闸）；
  - facts 里的数字/专名必须在 good 中保留（信息不丢）；
  - 功能/评价级新增无法自动判定，进"需人工"区只报告。
输入: data/raw_teacher.jsonl，每行: {"id"?: str, "bad": str, "good": str, "meta"?: object}
      data/facts_seed.txt，行格式: ID|类别|文本（# 注释跳过），id 用于关联事实卡
输出: data/sft/clean_sft.jsonl  仅合格样本
        --format pairs（默认，阶段4规定）: 每行 {"bad":"...","good":"..."}
        --format sft  （导出用）: messages 结构 + meta 溯源
      logs/rejected_report.txt   按原因分组，每组给前5条例子；只报告，不修改数据
用法:
  python scripts/validate_pairs.py
  python scripts/validate_pairs.py --format sft --out data/sft/sft_upload.jsonl
  python scripts/validate_pairs.py --selftest
退出码: 0=流程完成（存在拒绝样本也算正常）；1=selftest 未通过；2=致命错误（输入/禁词表缺失）
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILE = ROOT / "contracts" / "forbidden_words.txt"
DEFAULT_INPUT = ROOT / "data" / "raw_teacher.jsonl"
DEFAULT_FACTS = ROOT / "data" / "facts_seed.txt"
DEFAULT_OUT = ROOT / "data" / "sft" / "clean_sft.jsonl"
DEFAULT_REPORT = ROOT / "logs" / "rejected_report.txt"

SYSTEM_PROMPT = (
    "你是中文润色助手，把用户给的片段改得更像人写的。"
    "只改语言质感，不改事实、数字、日期、专名、引文，不新增观点，输出不超过原长的120%。"
)

INPUT_MAX = 100        # 契约 C1：输入上限
RATIO_NUM, RATIO_DEN = 12, 10  # 120%，整数运算避免浮点误差
MIN_DIFF_DEFAULT = 0.10  # 像人闸最低改写幅度

GATES = ("数字闸", "专名闸", "长度闸", "套话闸", "新增事实闸", "像人闸")
FACT_GATES = {"数字闸", "专名闸", "新增事实闸"}  # 失败即"事实被改"，按契约§6回退原文

NUMBER_RE = re.compile(r"[0-9０-９]+(?:\.[0-9０-９]+)?%?")
LATIN_RE = re.compile(r"[A-Za-z]+")
SPAN_RES = (
    re.compile(r"“([^”]*)”"),
    re.compile(r"「([^」]*)」"),
    re.compile(r"『([^』]*)』"),
    re.compile(r"《([^》]*)》"),
    re.compile(r'"([^"]*)"'),
    re.compile(r"'([^']*)'"),
)
QUOTE_MARKS = (("“", "”"), ("「", "」"), ("『", "』"), ("《", "》"), ('"', '"'), ("'", "'"))


def quote_spans(text: str) -> list[str]:
    spans = []
    for rx in SPAN_RES:
        spans.extend(s for s in rx.findall(text) if s)
    return spans


def unbalanced_quotes(text: str) -> list[str]:
    return [f"{o}{c}" for o, c in QUOTE_MARKS if text.count(o) != text.count(c)]


def merge_allowed(base: Counter, extra: Counter) -> Counter:
    """溯源允许集 = bad 与 facts 两来源的逐 token 最大次数。"""
    allowed = Counter(base)
    for tok, cnt in extra.items():
        allowed[tok] = max(allowed[tok], cnt)
    return allowed


def check_gates(bad: str, good: str, forbidden: list[str], min_diff: float, fact: str | None = None):
    """返回 (失败列表[(闸名, 详情)], 需人工列表[(闸名, 原因)], 差异率)。

    fact 为该对对应的事实卡文本；None 时跳过 facts 溯源（仅 bad↔good 校验）。
    """
    bad, good = bad.strip(), good.strip()
    fact = fact.strip() if fact else None
    failures, manual = [], []
    lb, lg = len(bad), len(good)

    if lb > INPUT_MAX:
        failures.append(("长度闸", f"bad长度{lb}超过输入上限{INPUT_MAX}"))
    limit = lb * RATIO_NUM // RATIO_DEN
    if lg > limit:
        failures.append(("长度闸", f"good长度{lg}超过上限{limit}(bad {lb}×120%)"))

    num_b, num_g = Counter(NUMBER_RE.findall(bad)), Counter(NUMBER_RE.findall(good))
    num_f = Counter(NUMBER_RE.findall(fact)) if fact else Counter()
    lost_nums = dict(num_b - num_g)
    if lost_nums:
        failures.append(("数字闸", f"数字缺失或减少(相对bad): {lost_nums}"))
    lost_fact_nums = dict(num_f - num_g)
    if lost_fact_nums:
        failures.append(("数字闸", f"事实卡数字未保留: {lost_fact_nums}"))

    for src, tag in ((bad, "bad"), (good, "good")):
        ub = unbalanced_quotes(src)
        if ub:
            manual.append(("专名闸", f"{tag}引号不配对{ub}，引文校验不可靠，转人工"))

    span_b, span_g = quote_spans(bad), quote_spans(good)
    lost_spans = [s for s in span_b if s not in good]
    latin_b, latin_g = Counter(LATIN_RE.findall(bad)), Counter(LATIN_RE.findall(good))
    latin_f = Counter(LATIN_RE.findall(fact)) if fact else Counter()
    lost_latin = dict(latin_b - latin_g)
    lost_fact_latin = dict(latin_f - latin_g)
    if lost_spans or lost_latin:
        parts = []
        if lost_spans:
            parts.append(f"引文/书名内容被改: {lost_spans}")
        if lost_latin:
            parts.append(f"英文专名丢失: {lost_latin}")
        failures.append(("专名闸", "；".join(parts)))
    if lost_fact_latin:
        failures.append(("专名闸", f"事实卡英文专名未保留: {lost_fact_latin}"))
    if fact:
        lost_fact_spans = [s for s in quote_spans(fact) if s not in good]
        if lost_fact_spans:
            failures.append(("专名闸", f"事实卡引文/书名内容未保留: {lost_fact_spans}"))

    hits = [w for w in forbidden if w in good]
    if hits:
        failures.append(("套话闸", f"含禁词: {hits}"))

    allowed_nums = merge_allowed(num_b, num_f)
    new_nums = dict(num_g - allowed_nums)
    allowed_latin = merge_allowed(latin_b, latin_f)
    new_latin = dict(latin_g - allowed_latin)
    new_spans = [s for s in span_g if s not in bad and (not fact or s not in fact)]
    if new_nums or new_latin or new_spans:
        parts = []
        if new_nums:
            parts.append(f"新增数字(无法溯源bad或facts): {new_nums}")
        if new_latin:
            parts.append(f"新增英文(无法溯源): {new_latin}")
        if new_spans:
            parts.append(f"新增引文/书名(无法溯源): {new_spans}")
        failures.append(("新增事实闸", "；".join(parts)))

    diff = 1.0 - difflib.SequenceMatcher(None, bad, good, autojunk=False).ratio()
    if diff < min_diff:
        failures.append(("像人闸", f"与bad差异率{diff:.2f}低于{min_diff}，改写幅度不足"))

    return failures, manual, diff


def load_facts(path: Path) -> dict[str, str]:
    cards = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 3 and parts[0].strip():
                cards[parts[0].strip()] = parts[2].strip()
    return cards


def parse_input(path: Path):
    records, parse_errors = [], []
    with path.open(encoding="utf-8-sig") as f:
        for no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                parse_errors.append((no, "空行"))
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                parse_errors.append((no, f"非法JSON: {e.msg}"))
                continue
            if not isinstance(obj, dict):
                parse_errors.append((no, "JSON不是对象"))
                continue
            bad, good = obj.get("bad"), obj.get("good")
            if not (isinstance(bad, str) and bad.strip() and isinstance(good, str) and good.strip()):
                parse_errors.append((no, "缺bad/good字段或为空"))
                continue
            pid = obj.get("id")
            pid = pid.strip() if isinstance(pid, str) and pid.strip() else f"L{no:04d}"
            meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else None
            records.append({"line": no, "id": pid, "bad": bad.strip(), "good": good.strip(), "meta": meta})
    return records, parse_errors


def run(input_path, out_path, report_path, forbidden, min_diff, facts_cards, fmt) -> int:
    records, parse_errors = parse_input(input_path)

    passed, rejected, manual_only = [], [], []
    gate_counts = {g: 0 for g in GATES}
    for rec in records:
        fact = facts_cards.get(rec["id"])
        if fact is None:
            rec["manual_note"] = "id无法关联事实卡，facts溯源未执行"
        failures, manual, _diff = check_gates(rec["bad"], rec["good"], forbidden, min_diff, fact)
        rec["failures"], rec["manual"] = failures, manual
        if fact is None:
            manual.append(("溯源", rec.pop("manual_note")))
        for g, _ in failures:
            gate_counts[g] += 1
        if failures:
            rejected.append(rec)
        elif manual:
            manual_only.append(rec)
        else:
            passed.append(rec)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for rec in passed:
            if fmt == "sft":
                msgs = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": rec["bad"]},
                        {"role": "assistant", "content": rec["good"]}]
                meta = {"pair_id": rec["id"], "src_file": input_path.name, "src_line": rec["line"]}
                if rec["meta"]:
                    meta["teacher_meta"] = rec["meta"]
                f.write(json.dumps({"messages": msgs, "meta": meta}, ensure_ascii=False) + "\n")
            else:
                f.write(json.dumps({"bad": rec["bad"], "good": rec["good"]}, ensure_ascii=False) + "\n")

    lines = [
        f"rejected_report — {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"输入: {input_path}",
        f"统计: 读取{len(records)} 通过{len(passed)} 拒绝{len(rejected)} 需人工{len(manual_only)} 解析失败{len(parse_errors)}",
        "各闸拒绝数: " + "  ".join(f"{g}={gate_counts[g]}" for g in GATES),
        "说明: 只报告不修复；事实类失败(数字/专名/新增事实)按契约回退原文，不入库。",
        "自动闸盲区(请人工抽查): 功能/评价级新增、中文数字改动、语义偏移。",
        "",
        "== 按原因分组（每组前5条例子）==",
    ]
    for gate in GATES:
        group = [r for r in rejected if any(g == gate for g, _ in r["failures"])]
        if not group:
            continue
        is_fact = gate in FACT_GATES
        lines.append(f"[{gate}] 共{len(group)}条" + ("（事实被改→回退原文）" if is_fact else ""))
        for r in group[:5]:
            details = "；".join(d for g, d in r["failures"] if g == gate)
            lines.append(f"  - line {r['line']} id={r['id']}  {details}")
            lines.append(f"    bad : {r['bad']}")
            lines.append(f"    good: {r['good']}")
        if len(group) > 5:
            lines.append(f"  ……其余{len(group) - 5}条略（详见统计行）")
    if manual_only:
        lines.append(f"[需人工] 共{len(manual_only)}条")
        for r in manual_only[:5]:
            reasons = "；".join(d for _, d in r["manual"])
            lines.append(f"  - line {r['line']} id={r['id']}  {reasons}")
            lines.append(f"    bad : {r['bad']}")
            lines.append(f"    good: {r['good']}")
        if len(manual_only) > 5:
            lines.append(f"  ……其余{len(manual_only) - 5}条略")
    if parse_errors:
        lines.append(f"[解析失败] 共{len(parse_errors)}条")
        for no, msg in parse_errors[:5]:
            lines.append(f"  - line {no}: {msg}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"输入: {input_path}")
    if facts_cards:
        print(f"事实卡: {len(facts_cards)} 张已加载（facts溯源启用）")
    else:
        print("事实卡: 未加载（facts溯源未执行）")
    print(f"读取: {len(records)}  通过: {len(passed)}  拒绝: {len(rejected)}  "
          f"需人工: {len(manual_only)}  解析失败: {len(parse_errors)}")
    print("各闸拒绝数: " + "  ".join(f"{g}={gate_counts[g]}" for g in GATES))
    print(f"输出: {out_path} ({len(passed)} 条, 格式={fmt})")
    print(f"报告: {report_path}")
    print("失败样例（前5条）:")
    if not rejected:
        print("  无")
    for rec in rejected[:5]:
        is_fact = any(g in FACT_GATES for g, _ in rec["failures"])
        head = "事实被改→回退原文" if is_fact else "拒绝"
        g, detail = rec["failures"][0]
        more = f" 等{len(rec['failures'])}项" if len(rec["failures"]) > 1 else ""
        print(f"  line {rec['line']} id={rec['id']} [{head}] {g}: {detail}{more}")
    return 0


SELFTEST = [
    dict(name="正常通过",
         bad="综上所述，本次改版显著提升了页面加载速度，为后续增长夯实了基础。",
         good="这轮改版后，页面加载快了不少，后面的增长也有底了。",
         expect_fail=[]),
    dict(name="数字丢失",
         bad="会议定在6月3日，覆盖3个城市。",
         good="会议定在6月，覆盖三个城市。",
         expect_fail=["数字闸"]),
    dict(name="套话残留",
         bad="这个方案整体来说值得肯定。",
         good="这个方案为团队赋能，值得肯定。",
         expect_fail=["套话闸"]),
    dict(name="输出超长",
         bad="今天天气不错。",
         good="今天天气真的很不错，让人心情也跟着变好，走在路上都觉得轻快，连工作效率都提高了。",
         expect_fail=["长度闸"]),
    dict(name="新增数字",
         bad="这个项目的项目周期为两周，先做起来。",
         good="项目周期两周，预算50万，先做起来。",
         expect_fail=["新增事实闸"]),
    dict(name="未改写",
         bad="这个方案整体来说是值得肯定的。",
         good="这个方案整体来说是值得肯定的。",
         expect_fail=["像人闸"]),
    dict(name="引文被改",
         bad="他在《三体》里最喜欢的角色是“罗辑”，没有之一。",
         good="《三体》里，他最喜欢的角色叫“逻辑”，没有之一。",
         expect_fail=["专名闸", "新增事实闸"]),
    dict(name="改动过小",
         bad="我觉得这个功能很好用。",
         good="我觉得这个功能很好用啊。",
         expect_fail=["像人闸"]),
    dict(name="数字可溯源到facts",
         fact="免费版每月限50张。",
         bad="全新升级，支持按地点筛选，欢迎体验。",
         good="按地点筛选，免费版每月限50张。",
         expect_fail=[]),
    dict(name="facts数字被删",
         fact="单次续航8小时。",
         bad="耳机续航很给力，体验全新升级。",
         good="耳机续航很给力。",
         expect_fail=["数字闸"]),
    dict(name="无法溯源的新数字",
         fact="图书馆9点开门。",
         bad="关于图书馆开门时间的调整通知，敬请知悉。",
         good="图书馆9点开门，延长到21点。",
         expect_fail=["新增事实闸"]),
]


def selftest(forbidden: list[str], min_diff: float) -> int:
    print(f"selftest: {len(SELFTEST)} 个内置用例（阈值 min_diff={min_diff}）")
    bad_count = 0
    for i, case in enumerate(SELFTEST, 1):
        failures, manual, diff = check_gates(case["bad"], case["good"], forbidden, min_diff,
                                             case.get("fact"))
        actual = sorted({g for g, _ in failures})
        expect = sorted(case["expect_fail"])
        ok = actual == expect and not manual
        bad_count += 0 if ok else 1
        mark = "OK  " if ok else "FAIL"
        print(f"[{mark}] {i}.{case['name']}  期望={expect} 实际={actual} 差异率={diff:.2f}"
              + ("" if not manual else f" 需人工={manual}"))
    print(f"selftest {'全部通过' if bad_count == 0 else f'失败{bad_count}例'}")
    return 0 if bad_count == 0 else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="bad/good 数据对六闸+facts溯源校验（docs/contract.md）")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="raw_teacher.jsonl 路径")
    ap.add_argument("--facts", type=Path, default=DEFAULT_FACTS, help="facts_seed.txt 路径，传空串禁用")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="clean_sft.jsonl 输出路径")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="rejected_report.txt 输出路径")
    ap.add_argument("--format", choices=("pairs", "sft"), default="pairs",
                    help="clean 输出格式：pairs={bad,good}（默认，阶段4规定）；sft=messages+meta（导出用）")
    ap.add_argument("--min-diff", type=float, default=MIN_DIFF_DEFAULT, help="像人闸最低差异率，默认0.10")
    ap.add_argument("--selftest", action="store_true", help="跑内置用例自测，不读输入文件")
    args = ap.parse_args()

    if not FORBIDDEN_FILE.is_file():
        print(f"[致命] 禁词表缺失: {FORBIDDEN_FILE}")
        return 2
    forbidden = [w.strip() for w in FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines() if w.strip()]
    if not forbidden:
        print(f"[致命] 禁词表为空: {FORBIDDEN_FILE}")
        return 2

    if args.selftest:
        return selftest(forbidden, args.min_diff)

    if not args.input.is_file():
        print(f"[致命] 输入文件不存在: {args.input}")
        print("请先产出 bad/good 教师数据对（raw_teacher.jsonl），再运行本脚本。")
        return 2
    facts_cards = load_facts(args.facts) if str(args.facts) else {}
    return run(args.input.resolve(), args.out.resolve(), args.report.resolve(),
               forbidden, args.min_diff, facts_cards, args.format)


if __name__ == "__main__":
    sys.exit(main())
