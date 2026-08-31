# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""阶段2检查：data/facts_seed.txt 事实卡合规 + scripts/make_bad_good_prompt.md 模板完整性。

事实卡规则（本阶段约定）：ID|类别|文本；P/N/V 各>=10 张；单条<=60字；
必含数字或拉丁字母或《》「」“”配对内容；无夸张形容词；无禁词表词；ID 唯一。
模板规则：内嵌全部10个禁词、写明120%/1.2倍长度上限、含 bad/good/id 字段说明、
批次表恰好覆盖全部卡片ID且不重复。
用法：python scripts/check_stage2.py   退出码 0=全过 1=有失败
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "facts_seed.txt"
PROMPT_MD = ROOT / "scripts" / "make_bad_good_prompt.md"
FORBIDDEN_FILE = ROOT / "contracts" / "forbidden_words.txt"

PREFIX_CAT = {"P": "产品", "N": "公告", "V": "观点"}
ID_RE = re.compile(r"^([PNV])(\d{2})$")
BLACKLIST_ADJ = ["非常", "极其", "超级", "极大", "顶级", "震撼", "炸裂", "完美", "绝佳",
                 "革命性", "颠覆性", "惊人", "史诗级", "无与伦比", "独一无二", "爆款", "全网最"]
HAS_NUM = re.compile(r"[0-9０-９]")
HAS_LATIN = re.compile(r"[A-Za-z]")
HAS_SPAN = re.compile(r"[《「“][^》」”]+[》」”]")

results = []


def check(ok, path, detail=""):
    results.append((bool(ok), str(path), detail))


sys.stdout.reconfigure(encoding="utf-8")

cards = []
if FACTS.is_file():
    for no, raw in enumerate(FACTS.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != 3:
            check(False, FACTS, f"第{no}行格式不是 ID|类别|文本: {line[:30]}")
            continue
        cid, cat, text = parts[0].strip(), parts[1].strip(), parts[2].strip()
        cards.append((no, cid, cat, text))
else:
    check(False, FACTS, "文件缺失")

seen_ids = {}
content_issues = 0
for no, cid, cat, text in cards:
    m = ID_RE.match(cid)
    if not m:
        content_issues += 1
        check(False, FACTS, f"第{no}行ID不合规: {cid}")
        continue
    if cat != PREFIX_CAT[m.group(1)]:
        content_issues += 1
        check(False, FACTS, f"{cid} 类别[{cat}]与前缀不符，应为{PREFIX_CAT[m.group(1)]}")
    if cid in seen_ids:
        content_issues += 1
        check(False, FACTS, f"{cid} 重复（第{seen_ids[cid]}行与第{no}行）")
    seen_ids[cid] = no
    if len(text) > 60:
        content_issues += 1
        check(False, FACTS, f"{cid} 长度{len(text)}>60: {text[:30]}…")
    if not (HAS_NUM.search(text) or HAS_LATIN.search(text) or HAS_SPAN.search(text)):
        content_issues += 1
        check(False, FACTS, f"{cid} 未检出数字/拉丁字母/书名引号内容（自动判据），需人工确认是否含专名: {text}")
    adj = [w for w in BLACKLIST_ADJ if w in text]
    if adj:
        content_issues += 1
        check(False, FACTS, f"{cid} 含夸张形容词: {adj}")

if cards:
    ok_cards = len(cards) - content_issues
    check(content_issues == 0, FACTS,
          f"{content_issues} 张卡片内容不合规" if content_issues else "")
    results.insert(0, (True, str(FACTS), f"逐条合规 {ok_cards}/{len(cards)}"))

for pre, cat in PREFIX_CAT.items():
    n = sum(1 for _, cid, c, _ in cards if cid.startswith(pre) and c == cat)
    check(n >= 10, FACTS, f"{cat}类仅{n}张（要求>=10）")
check(len(cards) >= 30, FACTS, f"总卡数{len(cards)}<30")

if FORBIDDEN_FILE.is_file():
    forbidden = [w.strip() for w in FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines() if w.strip()]
    for _, cid, _, text in cards:
        hits = [w for w in forbidden if w in text]
        if hits:
            check(False, FACTS, f"{cid} 含禁词: {hits}")
else:
    forbidden = []
    check(False, FORBIDDEN_FILE, "禁词表缺失")

if PROMPT_MD.is_file():
    md = PROMPT_MD.read_text(encoding="utf-8")
    for w in forbidden:
        check(w in md, PROMPT_MD, f"模板未内嵌禁词: {w}")
    check("120%" in md or "1.2" in md, PROMPT_MD, "模板未写明120%长度上限")
    for key in ('"bad"', '"good"', '"id"'):
        check(key in md, PROMPT_MD, f"模板缺少JSON字段 {key}")
    batch_ids = []
    for line in md.splitlines():
        ls = line.strip()
        if ls.startswith("批次"):
            batch_ids += re.findall(r"[PNV]\d{2}", ls)
    card_ids = {cid for _, cid, _, _ in cards}
    dup = sorted({b for b in batch_ids if batch_ids.count(b) > 1})
    missing = sorted(card_ids - set(batch_ids))
    extra = sorted(set(batch_ids) - card_ids)
    check(not dup and not missing and not extra, PROMPT_MD,
          f"批次表覆盖异常 缺失={missing} 多余={extra} 重复={dup}")
else:
    check(False, PROMPT_MD, "文件缺失")

fails = [(p, d) for ok, p, d in results if not ok]
for ok, p, d in results:
    if not ok:
        print(f"[FAIL] {p}  {d}")
print("-" * 60)
print(f"检查项: {len(results)}  通过: {len(results) - len(fails)}  失败: {len(fails)}")
print(f"事实卡: {len(cards)} 张（产品/公告/观点 = "
      f"{sum(1 for _, _, c, _ in cards if c == '产品')}/"
      f"{sum(1 for _, _, c, _ in cards if c == '公告')}/"
      f"{sum(1 for _, _, c, _ in cards if c == '观点')}）")
print("失败样例（前5条）:")
if not fails:
    print("  无")
else:
    for p, d in fails[:5]:
        print(f"  - {p}  {d}")
sys.exit(1 if fails else 0)
