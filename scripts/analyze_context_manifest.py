# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - context_manifest 观测分析（B0.2 · docs/world-kernel-construction-plan.md §1）
"""解析 logs/trace_adaptive_*.jsonl 的 context_manifest 事件，产出观测指标：

1. 注入未消费率：context_manifest.selected 的实体条目 × 同次生成文本的提及重叠
   （注入了但模型没用的比例——B8 冷层 digest 的第一道开工许可依据：
   若冷知识注入多而消费少，压缩成 digest 的论证成立）；
2. 前缀稳定性：同章连续生成的 prefix_sha1 相等率（WCA 前缀纪律的效果观测）；
3. 块体积分布：各知识块字符量的分布（p50/p90）。

用法：python scripts/analyze_context_manifest.py [logs 目录，默认 logs/]
纯本地分析，零上报。配对规则：context_manifest → 其后最近一次 llm_call
（creative）→ adaptive_stitch_complete（按文件内时间序）。
"""
import collections
import glob
import json
import sys


def _percentile(values, p):
    if not values:
        return 0
    vals = sorted(values)
    idx = min(int(len(vals) * p / 100), len(vals) - 1)
    return vals[idx]


def main(logs_dir="logs/"):
    manifests = []  # (chapter, ts, data, generated_text)
    for f in sorted(glob.glob(f"{logs_dir}trace_adaptive_*.jsonl")):
        chapter = f.split("trace_adaptive_")[-1].split(".jsonl")[0][:8]
        pending = None
        pending_text = ""
        for line in open(f, encoding="utf-8"):
            try:
                ev = json.loads(line)
            except Exception:
                continue
            e = ev.get("event")
            if e == "context_manifest":
                pending = ev.get("data", {}) or {}
                pending_text = ""
            elif e == "llm_call" and pending is not None:
                pending_text = (ev.get("data", {}).get("content") or "")
            elif e == "adaptive_stitch_complete" and pending is not None:
                manifests.append((chapter, ev.get("ts", ""), pending, pending_text))
                pending = None

    if not manifests:
        print("无 context_manifest 记录（需要新代码跑过真实生成后重试）")
        return

    # 1. 注入未消费率（实体条目口径）
    consumed_total, injected_total = 0, 0
    per_item = []
    for chapter, ts, m, text in manifests:
        ent = [k.split(":", 1)[1] for k in (m.get("selected") or [])
               if k.startswith(("entity:", "asset:"))]
        if not ent:
            continue
        hit = [n for n in ent if n and n in (text or "")]
        injected_total += len(ent)
        consumed_total += len(hit)
        per_item.append((chapter, ts[:16], len(ent), len(hit), ent, hit))
    rate = (consumption := consumed_total / injected_total * 100) if injected_total else 0.0
    print(f"== 注入未消费率（实体条目） ==")
    print(f"  注入 {injected_total} 条次，生成文本提及 {consumed_total} 条次，消费率 {rate:.0f}%")
    for chapter, ts, n, h, ent, hit in per_item[-12:]:
        missed = [n_ for n_ in ent if n_ not in hit]
        print(f"  {ts} {chapter}: 注入 {n} 用 {h}｜未用：{'、'.join(missed) or '无'}")

    # 2. 前缀稳定性（同章连续 prefix_sha1 相等率）
    print(f"\n== 前缀稳定性 ==")
    by_ch = collections.defaultdict(list)
    for chapter, ts, m, _ in manifests:
        if m.get("prefix_sha1"):
            by_ch[chapter].append(m["prefix_sha1"])
    for chapter, shas in by_ch.items():
        same = sum(1 for a, b in zip(shas, shas[1:]) if a == b)
        pairs = max(len(shas) - 1, 0)
        print(f"  {chapter}: {len(shas)} 次生成，相邻相等 {same}/{pairs}"
              + (f"（{same / pairs * 100:.0f}%）" if pairs else ""))

    # 3. 块体积分布
    print(f"\n== 块体积分布（字符） ==")
    by_key = collections.defaultdict(list)
    for _, _, m, _ in manifests:
        for b in m.get("blocks") or []:
            by_key[b["key"]].append(b["chars"])
    for key in sorted(by_key, key=lambda k: -sum(by_key[k])):
        v = by_key[key]
        print(f"  {key}: n={len(v)} p50={_percentile(v, 50)} p90={_percentile(v, 90)} max={max(v)}")

    print(f"\n样本：{len(manifests)} 次生成（{len(by_ch)} 章）")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "logs/")
