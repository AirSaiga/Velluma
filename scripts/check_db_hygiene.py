# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""数据库卫生检测与修复（历史遗留数据 × 生成链一致性）。

用法：
    python scripts/check_db_hygiene.py            # 只检测，输出报告（退出码 0=干净 / 1=有脏项）
    python scripts/check_db_hygiene.py --fix      # 自动备份到 data/backups/ 后执行修复
    python scripts/check_db_hygiene.py --db PATH  # 指定 SQLite 库（默认 data/velluma.db）

检测/修复项（全部幂等，重复跑第二遍应全绿）：
    R1  world_events / world_event_candidates 的 id 引用格式归一
        —— 早期写入路径把 hex32（无连字符）存进 JSONB 引用（participant_ids /
        payload.character_ids / location_id 等），而全部读侧（fold /
        world_bridge / 前端 engine）用带连字符 str(UUID) 匹配 → 静默失配，
        推演状态挂不上实体。修复 = strip 后命中实体/地点表的引用改写为标准
        带连字符格式；命中不了的（真孤儿）只报告不动。
    R2  memory_chunks 卫生
        —— 摘要型 chunk（旧引擎遗产，现行索引只写「片段N」型）→ 删；
        片段型但剥前缀/HTML 后不是当前正文子串（章节重写过）→ 删；
        章节孤儿（指向已删除章节）→ 删；同书同章同文本完全重复 → 去重。
        --fix 后对删过块的章节走 index_chapter_memories（章级替换正规通道）
        按当前正文重建。
    R3  plot_ledgers 重复伏笔 —— 同书同 content 且 ledger_key 呈 X / X-N
        模式的复本 → 保留原 key，删 -N 复本（重复伏笔会在「开放伏笔」素材
        块双份注入 prompt）。
    R4  chapters.summary 旧引擎格式噪声 —— LLM 寒暄开头（「这是一份…」「以下
        是…」）或 **【情节摘要】** 类标记 → 置 NULL（summary 经
        previous_summary 接力棒注入下一章 prompt，旧版摘要=假前情）。
    R5  只报告不修 —— 场景钉悬空 / 候选池积压 / RAG 零覆盖章节（提示补完稿）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent

UUID_DASH_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
CHUNK_PREFIX_RE = re.compile(r"^【[^】]*片段\d+】")
HTML_TAG_RE = re.compile(r"<[^>]+>")

# R4：旧引擎落库的 summary 带 LLM 寒暄/格式噪声（现行章节摘要不落此格式）
_SUMMARY_NOISE_HEADS = ("这是一份", "以下是", "这是一篇", "这是一段", "（以下")
_SUMMARY_NOISE_MARKS = (
    "**【情节摘要】**", "**【剧情摘要】**", "**【情节概括】**",
    "**【内容摘要】**", "**【摘要】**", "**【剧情概括】**",
)


def html_unescape(s: str) -> str:
    import html
    return html.unescape(s)


def plain(text: str) -> str:
    """HTML → 纯文本。

    正文比对用项目唯一权威 backend.services.utils.html_text.html_to_plain
    （标签→换行的折叠规则与 memory_indexing 建块侧逐字节一致——自写剥标签
    曾把重建块误判为陈旧）。旧库存量 chunk 的标签残留走宽松回退（unescape
    后再剥一遍），兼容「<p> 混进文本」的历史格式。
    """
    from backend.services.utils.html_text import html_to_plain
    return html_to_plain(text)


def strip_dash(u: str) -> str:
    return str(u).replace("-", "").lower()


def to_dashed(hex_or_uuid: str) -> str:
    s = str(hex_or_uuid)
    if HEX32_RE.match(s):
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}".lower()
    return s.lower() if UUID_DASH_RE.match(s) else s


class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.dirty = 0

    def ok(self, name: str, detail: str = ""):
        self.lines.append(f"  [OK]    {name}{(' — ' + detail) if detail else ''}")

    def dirty_(self, name: str, n: int, detail: str):
        self.dirty += 1
        self.lines.append(f"  [DIRTY] {name} ×{n} — {detail}")

    def fixed(self, name: str, n: int, detail: str = ""):
        self.lines.append(f"  [FIXED] {name} ×{n}{(' — ' + detail) if detail else ''}")

    def info(self, name: str, detail: str):
        self.lines.append(f"  [INFO]  {name} — {detail}")

    def dump(self):
        print("\n".join(self.lines))


# ============================================================
# R1：id 引用格式归一（world_events + world_event_candidates）
# ============================================================

def _iter_id_strings(obj):
    """递归产出 (容器, key, 原值)——容器为 dict/list，值为 id 样式字符串。"""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str) and (HEX32_RE.match(v) or UUID_DASH_RE.match(v)):
                yield obj, k, v
            else:
                yield from _iter_id_strings(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and (HEX32_RE.match(v) or UUID_DASH_RE.match(v)):
                yield obj, i, v
            else:
                yield from _iter_id_strings(v)


def check_r1(con: sqlite3.Connection, rep: Report, fix: bool) -> list[str]:
    """返回归一涉及的 (table, row_id) 事件清单（供 trace 打印）。"""
    ent_ids = {strip_dash(r[0]) for r in con.execute("SELECT id FROM world_entities")}
    loc_ids = {strip_dash(r[0]) for r in con.execute("SELECT id FROM world_locations")}
    evt_ids = {strip_dash(r[0]) for r in con.execute("SELECT id FROM world_events")}
    known = {"entity": ent_ids, "location": loc_ids, "event": evt_ids}
    # 命中不了实体/地点/事件的 id 无法归一（真孤儿）——不知道目标格式
    all_known = ent_ids | loc_ids | evt_ids

    touched = []
    orphans = []

    def normalize_container(container, key, value, kind_hint) -> str | None:
        """返回改写后的值；已是标准格式或无法归一返回 None。"""
        sd = strip_dash(value)
        if sd not in all_known:
            orphans.append((kind_hint, value))
            return None
        target = to_dashed(value)
        if target == value:
            return None  # 已是标准格式
        container[key] = target
        return target

    # ---- world_events ----
    rows = con.execute(
        "SELECT id, participant_ids, faction_ids, causes, location_id, payload FROM world_events"
    ).fetchall()
    n_fixed_evt = 0
    for rid, pids, fids, causes, loc_id, payload in rows:
        changed = False
        for col, raw in (("participant_ids", pids), ("faction_ids", fids), ("causes", causes)):
            if not raw:
                continue
            data = json.loads(raw)
            if not isinstance(data, list):
                continue
            col_changed = False
            for holder in (data,):
                for i, v in enumerate(holder):
                    if isinstance(v, str) and (HEX32_RE.match(v) or UUID_DASH_RE.match(v)):
                        new = normalize_container(holder, i, v, f"events.{col}")
                        if new is not None:
                            col_changed = True
            if col_changed:
                con.execute(f"UPDATE world_events SET {col}=? WHERE id=?", (json.dumps(data, ensure_ascii=False), rid))
                changed = True
        if loc_id and (HEX32_RE.match(loc_id) or UUID_DASH_RE.match(loc_id)):
            sd = strip_dash(loc_id)
            if sd not in all_known:
                orphans.append(("events.location_id", loc_id))
            else:
                new = to_dashed(loc_id)
                if new != loc_id:
                    con.execute("UPDATE world_events SET location_id=? WHERE id=?", (new, rid))
                    changed = True
        if payload:
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                data = None
            if data is not None:
                before = json.dumps(data, ensure_ascii=False, sort_keys=True)
                for holder, key, v in _iter_id_strings(data):
                    normalize_container(holder, key, v, "events.payload")
                if json.dumps(data, ensure_ascii=False, sort_keys=True) != before:
                    con.execute("UPDATE world_events SET payload=? WHERE id=?",
                                (json.dumps(data, ensure_ascii=False), rid))
                    changed = True
        if changed:
            n_fixed_evt += 1
            touched.append(f"world_events:{str(rid)[:8]}")

    # ---- world_event_candidates.draft（转正后原样进库，必须同口径归一） ----
    n_fixed_cand = 0
    for rid, draft in con.execute("SELECT id, draft FROM world_event_candidates WHERE draft IS NOT NULL").fetchall():
        try:
            data = json.loads(draft)
        except (json.JSONDecodeError, TypeError):
            continue
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        for holder, key, v in _iter_id_strings(data):
            normalize_container(holder, key, v, "candidates.draft")
        if json.dumps(data, ensure_ascii=False, sort_keys=True) != before:
            con.execute("UPDATE world_event_candidates SET draft=? WHERE id=?",
                        (json.dumps(data, ensure_ascii=False), rid))
            n_fixed_cand += 1
            touched.append(f"candidate:{str(rid)[:8]}")

    total_evt = len(rows)
    if fix:
        if n_fixed_evt:
            rep.fixed("R1 events id 归一", n_fixed_evt, f"/ {total_evt} 条中")
        if n_fixed_cand:
            rep.fixed("R1 candidates.draft id 归一", n_fixed_cand)
        if not n_fixed_evt and not n_fixed_cand:
            rep.ok("R1 id 引用格式", "全部标准带连字符")
        if orphans:
            rep.info("R1 真孤儿引用（不自动处理）", "；".join(f"{k}={v[:13]}…" for k, v in orphans[:6]) + ("…" if len(orphans) > 6 else ""))
    else:
        # 检测模式：统计非标准格式引用数（不改库）
        n_hex = 0
        for _rid, pids, fids, causes, loc_id, payload in rows:
            blobs = [pids, fids, causes]
            for b in blobs:
                if b:
                    try:
                        for v in json.loads(b):
                            if isinstance(v, str) and HEX32_RE.match(v):
                                n_hex += 1
                    except json.JSONDecodeError:
                        pass
            if loc_id and HEX32_RE.match(loc_id):
                n_hex += 1
            if payload:
                try:
                    for _h, _k, v in _iter_id_strings(json.loads(payload)):
                        if HEX32_RE.match(v):
                            n_hex += 1
                except json.JSONDecodeError:
                    pass
        for _rid, draft in con.execute("SELECT id, draft FROM world_event_candidates WHERE draft IS NOT NULL").fetchall():
            try:
                for _h, _k, v in _iter_id_strings(json.loads(draft)):
                    if HEX32_RE.match(v):
                        n_hex += 1
            except json.JSONDecodeError:
                pass
        if n_hex:
            rep.dirty_("R1 hex32 格式 id 引用", n_hex, "读侧带连字符匹配 → 推演断链；--fix 归一")
        else:
            rep.ok("R1 id 引用格式", "全部标准带连字符")
    return touched


# ============================================================
# R2：memory_chunks 卫生
# ============================================================

def check_r2(con: sqlite3.Connection, rep: Report, fix: bool) -> set[str]:
    """返回需要重建索引的 chapter_id 集合（删过块的章）。"""
    chapters = {
        r[0]: {"number": r[1], "body": plain(r[2] or r[3] or "")}
        for r in con.execute("SELECT id, chapter_number, content_text, draft_text FROM chapters")
    }
    chunks = con.execute(
        "SELECT id, book_id, chapter_id, chunk_text FROM memory_chunks ORDER BY created_at"
    ).fetchall()

    to_delete: list[str] = []
    seen_texts: dict[tuple, str] = {}  # (book, chapter, canonical_text) -> kept chunk id
    n_stale = n_summary = n_orphan = n_dup = n_dirty_html = 0

    for cid_, book_id, chapter_id, text in chunks:
        text = text or ""
        ch = chapters.get(chapter_id)
        if not ch:
            to_delete.append(cid_)
            n_orphan += 1
            continue
        m = CHUNK_PREFIX_RE.match(text)
        if not m:
            # 摘要型 / 无前缀块：现行索引器只写「片段N」型，其余为旧引擎遗产
            to_delete.append(cid_)
            n_summary += 1
            continue
        body = plain(text[m.end():]).strip()
        if body and body not in ch["body"]:
            to_delete.append(cid_)
            n_stale += 1
            continue
        # 活块：登记去重（同书同章同文本只留最早——created_at 排序保证首见为最早）
        key = (book_id, chapter_id, body)
        if key in seen_texts:
            to_delete.append(cid_)
            n_dup += 1
            continue
        seen_texts[key] = cid_
        # 格式卫生：库存文本仍含 HTML 标签（S5 剥标签收敛之前的遗产）
        if HTML_TAG_RE.search(text):
            n_dirty_html += 1
            # 不就地改写（embedding 若存在会失配）——删掉走重建
            to_delete.append(cid_)
            del seen_texts[key]

    if fix:
        if to_delete:
            rebuild = set()
            for cid_, book_id, chapter_id, text in chunks:
                if cid_ in to_delete and chapter_id:
                    rebuild.add(chapter_id)
            con.executemany("DELETE FROM memory_chunks WHERE id=?", [(x,) for x in to_delete])
            rep.fixed("R2 记忆块清理", len(to_delete),
                      f"陈旧{n_stale}/摘要型{n_summary}/孤儿{n_orphan}/重复{n_dup}/带HTML{n_dirty_html}")
            return rebuild
        rep.ok("R2 memory_chunks", "全部为当前正文切片")
        return set()
    else:
        total_dirty = len(to_delete)
        if total_dirty:
            rep.dirty_("R2 脏记忆块", total_dirty,
                       f"陈旧{n_stale}/摘要型{n_summary}/孤儿{n_orphan}/重复{n_dup}/带HTML{n_dirty_html}；--fix 清理+按正文重建")
        else:
            rep.ok("R2 memory_chunks", "全部为当前正文切片")
        # R5 提示：RAG 零覆盖
        live_books = {r[0] for r in con.execute(
            "SELECT DISTINCT book_id FROM chapters WHERE content_text IS NOT NULL AND length(content_text)>10")}
        covered = {r[0] for r in con.execute("SELECT DISTINCT chapter_id FROM memory_chunks WHERE chapter_id IS NOT NULL")}
        zero = [c for c in chapters if chapters[c]["body"].strip() and c not in covered and _book_of(con, c) in live_books]
        if zero:
            rep.info("R5 RAG 零覆盖章节", f"{len(zero)} 章有正文但无记忆块（完稿/发布时自动重索引，或 runpy 触发）")
        return set()


def _book_of(con: sqlite3.Connection, chapter_id: str) -> str:
    row = con.execute("SELECT book_id FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    return row[0] if row else ""


# ============================================================
# R3：plot_ledgers 重复伏笔
# ============================================================

def check_r3(con: sqlite3.Connection, rep: Report, fix: bool):
    rows = con.execute(
        "SELECT id, book_id, ledger_key, content, created_at FROM plot_ledgers ORDER BY created_at"
    ).fetchall()
    groups: dict[tuple, list] = {}
    for rid, book_id, key, content, created in rows:
        groups.setdefault((book_id, content), []).append((rid, key, created))

    to_delete: list[str] = []
    n_groups = 0
    for (book_id, content), items in groups.items():
        if len(items) < 2:
            continue
        # X / X-N 模式：去掉尾部 -N 后 key 相同才算复本（防误删语义独立的同名伏笔）
        bases: dict[str, list] = {}
        for rid, key, created in items:
            base = re.sub(r"-\d+$", "", key or "")
            bases.setdefault(base, []).append((rid, key, created))
        for base, lst in bases.items():
            if len(lst) < 2:
                continue
            plain_keys = [x for x in lst if x[1] == base]
            keep = plain_keys[0] if plain_keys else sorted(lst, key=lambda x: x[2])[0]
            for rid, key, _c in lst:
                if rid != keep[0]:
                    to_delete.append(rid)
            n_groups += 1

    if fix:
        if to_delete:
            con.executemany("DELETE FROM plot_ledgers WHERE id=?", [(x,) for x in to_delete])
            rep.fixed("R3 重复伏笔复本", len(to_delete), f"涉及 {n_groups} 组（保留原 key，删 -N 复本）")
        else:
            rep.ok("R3 plot_ledgers", "无同内容复本")
    else:
        if to_delete:
            rep.dirty_("R3 重复伏笔复本", len(to_delete), f"涉及 {n_groups} 组；--fix 删 -N 复本")
        else:
            rep.ok("R3 plot_ledgers", "无同内容复本")


# ============================================================
# R4：chapters.summary 旧引擎噪声
# ============================================================

def _summary_is_noise(s: str) -> bool:
    if not s:
        return False
    head = s.lstrip()[:8]
    if any(head.startswith(h) for h in _SUMMARY_NOISE_HEADS):
        return True
    return any(m in s for m in _SUMMARY_NOISE_MARKS)


def check_r4(con: sqlite3.Connection, rep: Report, fix: bool):
    rows = con.execute(
        "SELECT id, chapter_number, summary FROM chapters WHERE summary IS NOT NULL AND summary != ''"
    ).fetchall()
    noise = [(r[0], r[1]) for r in rows if _summary_is_noise(r[2] or "")]
    if fix:
        if noise:
            con.executemany("UPDATE chapters SET summary=NULL WHERE id=?", [(x[0],) for x in noise])
            rep.fixed("R4 summary 噪声清除", len(noise), f"章号 {[x[1] for x in noise]}（previous_summary 接力棒将不再注入假前情）")
        else:
            rep.ok("R4 chapters.summary", "无旧引擎格式噪声")
    else:
        if noise:
            rep.dirty_("R4 summary 噪声", len(noise), f"章号 {[x[1] for x in noise]}；--fix 置 NULL")
        else:
            rep.ok("R4 chapters.summary", "无旧引擎格式噪声")


# ============================================================
# R5：报告项
# ============================================================

def check_r5(con: sqlite3.Connection, rep: Report):
    loc_ids = {r[0] for r in con.execute("SELECT id FROM world_locations")}
    for ch_id, num, loc in con.execute(
        "SELECT id, chapter_number, scene_location_id FROM chapters WHERE scene_location_id IS NOT NULL"
    ).fetchall():
        if loc not in loc_ids:
            rep.info("R5 场景钉悬空", f"第{num}章 scene_location_id 指向不存在的地点（世界页重新钉定即可）")
    n_pending = con.execute(
        "SELECT COUNT(*) FROM world_event_candidates WHERE status='pending'"
    ).fetchone()[0]
    if n_pending:
        rep.info("R5 待确认候选", f"{n_pending} 条 pending（切片条收件箱 / 世界页待确认分区处理）")


# ============================================================
# RAG 重建（async 段：index_chapter_memories 正规通道）
# ============================================================

async def rebuild_memory(chapter_ids: set[str]) -> int:
    from backend.database import AsyncSessionLocal
    from backend.models import Chapter
    from backend.services.rag.memory_indexing import index_chapter_memories
    from sqlalchemy import select

    total = 0
    async with AsyncSessionLocal() as db:
        for cid in chapter_ids:
            ch = (await db.execute(select(Chapter).where(Chapter.id == cid))).scalar_one_or_none()
            if not ch or not (ch.content_text or "").strip():
                continue
            n = await index_chapter_memories(
                db,
                book_id=str(ch.book_id),
                chapter_id=str(ch.id),
                chapter_number=ch.chapter_number,
                text=ch.content_text,
            )
            total += n
            print(f"    重索引 第{ch.chapter_number}章 → {n} 块（当前正文切片）")
    return total


# ============================================================
# main
# ============================================================

def backup_db(db_path: Path) -> Path:
    bak_dir = db_path.parent / "backups"
    bak_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = bak_dir / f"{db_path.stem}.pre-hygiene-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, bak)
    return bak


def main() -> int:
    ap = argparse.ArgumentParser(description="数据库卫生检测与修复")
    ap.add_argument("--fix", action="store_true", help="执行修复（自动先备份）")
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "velluma.db"), help="SQLite 库路径")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"库不存在: {db_path}")
        return 2

    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    rep = Report()

    print(f"{'修复模式' if args.fix else '检测模式（--fix 执行修复）'} — {db_path}")

    rebuild: set[str] = set()
    try:
        if args.fix:
            bak = backup_db(db_path)
            print(f"已备份 → {bak}")

        print("\n[R1] world 事件 id 引用格式")
        check_r1(con, rep, fix=args.fix)
        print("\n[R2] memory_chunks 卫生")
        rebuild = check_r2(con, rep, fix=args.fix)
        print("\n[R3] plot_ledgers 重复伏笔")
        check_r3(con, rep, fix=args.fix)
        print("\n[R4] chapters.summary 噪声")
        check_r4(con, rep, fix=args.fix)
        print("\n[R5] 报告项（不自动处理）")
        check_r5(con, rep)

        if args.fix:
            con.commit()
            if rebuild:
                print("\n[R2+] 按当前正文重建记忆索引（index_chapter_memories 章级替换）")
                total = asyncio.run(rebuild_memory(rebuild))
                print(f"    重建完成，共写入 {total} 块")
        else:
            con.rollback()
    finally:
        con.close()

    print()
    rep.dump()
    print()
    if args.fix:
        print("修复完成。建议再跑一次检测模式验证全绿：")
        print(f"    python scripts/check_db_hygiene.py")
        return 0
    return 1 if rep.dirty else 0


if __name__ == "__main__":
    sys.exit(main())
