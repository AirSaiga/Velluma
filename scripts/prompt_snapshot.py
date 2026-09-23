# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""prompt 快照（F2a · docs/next-phase/06-prompt-governance-hardening.md）。

对指定书/章，把两条生成链的最终 prompt **纯渲染**成文件（零 LLM 生成调用）：
- stitch 五模式（stitch/continue/burst/open/outline）：system + user 全文，
  装配走 services/context/stitch_context.assemble_stitch_context（与
  /adaptive/context-preview 同一函数，预览与注入同源红线）；
- dock 卡片舱：system 编译产物（_dock_system_sections + render_sections，
  上下文键从 DB 现状推导，与 dock_generator.run 同判据）+ user 全文
  （build_dock_generator_prompt 真实调用，离线无世界模型快照 → projections 空）。

输出 logs/prompt_snapshots/{timestamp}/：每链每模式 system/user 各一文件 +
manifest.json（PROMPT_VERSION、章节、时间、sha256、上下文摘要）。

对拍工作流（F2b）：改 prompt 前跑一次 → AI 改措辞 → 再跑一次 →
scripts/prompt_replay.py diff 出「哪条链哪个模式哪块变了」。

注意：
- DB 只读（bundle 加载 / 召回 / 文风检索全走既有只读路径）；embedding 已
  配置时装配层的向量召回会发 embedding 只读请求（与 context-preview 同
  路径），LLM 生成调用为零。
- 快照的对比前提是两次快照间**书章内容与设定未变**——正文一变 diff 会
  显示上下文变化（非措辞变化），manifest 记录章节 id 供核对。
- 无实时光标：fragment/rolling_prefix 从画布正文尾部推导（见 _FEED_*
  常量），target_chars 用五模式代表值——这些是快照的固定口径，两次快照
  间自身恒定，diff 只反映 prompt 措辞/设定数据的变化。

用法：
    python scripts/prompt_snapshot.py                       # 最近有内容的章
    python scripts/prompt_snapshot.py --chapter-id UUID
    python scripts/prompt_snapshot.py --book-id UUID        # 该书最近有内容的章
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:  # Windows 控制台 GBK 防御
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from sqlalchemy import select  # noqa: E402

from backend.database import AsyncSessionLocal, engine  # noqa: E402
from backend.models import Book, Chapter  # noqa: E402
from backend.services.adaptive.components.dock_generator import (  # noqa: E402
    onstage_projection,
    pick_shot_template,
)
from backend.services.adaptive.outline_nearby import outline_nearby  # noqa: E402
from backend.services.adaptive.paragraph_source import (  # noqa: E402
    resolve_current_paragraph,
    sentence_clean_tail,
    written_text,
)
from backend.services.adaptive.texture_contract import pick_contract  # noqa: E402
from backend.services.context.budget import (  # noqa: E402
    ECHOES_K_DOCK,
    STITCH_OUTLINE_MAX_CHARS,
    STITCH_ROLLING_LONG_MAX_CHARS,
    STITCH_ROLLING_SHORT_MAX_CHARS,
)
from backend.services.context.knowledge_plane import kg_block_kwargs  # noqa: E402
from backend.services.context.settings_bundle import (  # noqa: E402
    load_chapter_settings_bundle,
)
from backend.services.context.stitch_context import (  # noqa: E402
    _layer2_intent_fallback,
    assemble_stitch_context,
)
from backend.services.prompts.adaptive_prompts import (  # noqa: E402
    _dock_system_sections,
    build_burst_prompt,
    build_continue_prompt,
    build_dock_generator_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
)
from backend.services.prompts.prompt_version import PROMPT_VERSION  # noqa: E402
from backend.services.rag.recall import bundle_mask_names, recall_memories  # noqa: E402
from backend.services.utils.html_text import html_to_plain  # noqa: E402
from backend.services.world.active_scene import (  # noqa: E402
    pre_cursor_window,
    resolve_active_scene,
)
from backend.routes.chapter_generation.adaptive.spine import (  # noqa: E402
    _spine_anchor_rows_for_prompt,
)

SNAPSHOT_ROOT = REPO_ROOT / "logs" / "prompt_snapshots"

# ---- 快照固定口径（两次快照间恒定，diff 只反映 prompt 措辞/设定变化）----
STITCH_MODES = ("stitch", "continue", "burst", "open", "outline")
TARGET_CHARS = {"stitch": 120, "continue": 200, "burst": 700, "outline": 400, "open": 700}
ROLLING_FEED_CHARS = 600        # 上送 rolling_prefix 的代表窗（前端惯例上送正文尾部）
FRAGMENT_TAIL_CHARS = {"stitch": 48, "continue": 96, "burst": 120}
OUTLINE_NOTE_PLACEHOLDER = "（快照占位细纲：主角清点随身的物件，动身前往约定地点）"


# ============================================================
# 章节选择
# ============================================================

async def resolve_chapter(db, book_id: str = "", chapter_id: str = "") -> Chapter:
    """按参数/默认规则选出快照章节（最近有内容的章；全空书回退最新章）。"""
    if chapter_id:
        ch = await db.get(Chapter, str(chapter_id))
        if ch is None:
            raise SystemExit(f"[prompt_snapshot] 章节不存在: {chapter_id}")
        return ch

    # func.length 对 SQLite/PG 均可用；content 非空即「有内容」
    from sqlalchemy import func

    stmt = select(Chapter).where(
        Chapter.content_text.isnot(None), func.length(Chapter.content_text) > 0
    )
    if book_id:
        book = await db.get(Book, str(book_id))
        if book is None:
            raise SystemExit(f"[prompt_snapshot] 书不存在: {book_id}")
        stmt = stmt.where(Chapter.book_id == str(book_id))
    stmt = stmt.order_by(Chapter.created_at.desc(), Chapter.chapter_number.desc()).limit(1)
    ch = (await db.execute(stmt)).scalar_one_or_none()
    if ch is not None:
        return ch
    if book_id:
        raise SystemExit(f"[prompt_snapshot] 书 {book_id} 下没有带正文的章节")
    # 全库无正文章：回退最新章（open 模式的快照仍可渲染）
    stmt = select(Chapter).order_by(Chapter.created_at.desc()).limit(1)
    ch = (await db.execute(stmt)).scalar_one_or_none()
    if ch is None:
        raise SystemExit("[prompt_snapshot] 库里没有任何章节")
    print(f"[prompt_snapshot] 注意：全书无带正文章节，回退最新章 第{ch.chapter_number}章「{ch.chapter_name or ch.title or ''}」")
    return ch


# ============================================================
# stitch 五模式（与 stitch.py 路由同参同源）
# ============================================================

async def render_stitch_mode(db, chapter: Chapter, mode: str, outline_note: str, outline_note_source: str):
    """渲染一个 stitch 模式的 (system, user)——复刻路由侧 builder 调用参数。"""
    plain = written_text(chapter.content_text or "")
    if mode == "open":
        fragment, rolling_prefix = "", ""
    elif mode == "outline":
        fragment, rolling_prefix = outline_note, plain[-ROLLING_FEED_CHARS:]
    else:
        fragment = plain[-FRAGMENT_TAIL_CHARS[mode]:]
        rolling_prefix = plain[-ROLLING_FEED_CHARS:]

    ctx = await assemble_stitch_context(
        chapter_id=str(chapter.id),
        mode=mode,
        fragment=fragment,
        rolling_prefix=rolling_prefix,
        db=db,
    )
    bundle = ctx.bundle
    kg = ctx.kg
    kg_kwargs = kg_block_kwargs(kg)

    # 滚动窗（路由同款分档截窗）
    rolling_cap = (
        0 if mode == "open"
        else STITCH_ROLLING_LONG_MAX_CHARS if mode in ("outline", "burst")
        else STITCH_ROLLING_SHORT_MAX_CHARS
    )
    rolling_windowed = (
        sentence_clean_tail(rolling_prefix, rolling_cap).strip() if rolling_cap else ""
    )
    target = TARGET_CHARS[mode]

    if mode == "open":
        # 点火剂量闸（路由同款）：空章就近=开头一两拍，短大纲回退原文截断
        open_beats = outline_nearby(bundle.outline_text or "", "")
        open_outline = (
            "\n".join(open_beats) if open_beats
            else bundle.outline_text[:STITCH_OUTLINE_MAX_CHARS]
        )
        system, user = build_opening_prompt(
            outline_text=open_outline,
            previous_summary=bundle.previous_summary or "",
            proper_nouns=ctx.proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=target,
            memory_echoes=ctx.memory_echoes,
            style_positive=ctx.style_positive,
            author_samples=ctx.author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            recency_pin=kg.recency_pin,
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )
    elif mode == "outline":
        spine_anchor_rows = await _spine_anchor_rows_for_prompt(str(chapter.id), db)
        system, user = build_outline_expand_prompt(
            outline_note=fragment,
            rolling_prefix=rolling_windowed,
            after_text="",
            proper_nouns=ctx.proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=target,
            chapter_intent=ctx.chapter_intent,
            memory_echoes=ctx.memory_echoes,
            style_positive=ctx.style_positive,
            author_samples=ctx.author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            spine_anchors=spine_anchor_rows,
            previous_summary=kg.previous_summary,
            recency_pin=kg.recency_pin,
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )
    elif mode == "burst":
        system, user = build_burst_prompt(
            fragment=fragment,
            rolling_prefix=rolling_windowed,
            beat_guidance="",
            proper_nouns=ctx.proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=target,
            chapter_intent=ctx.chapter_intent,
            memory_echoes=ctx.memory_echoes,
            style_positive=ctx.style_positive,
            author_samples=ctx.author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            previous_summary=kg.previous_summary,
            recency_pin=kg.recency_pin,
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )
    else:  # stitch / continue
        system, user = build_continue_prompt(
            fragment=fragment,
            rolling_prefix=rolling_windowed,
            mode=mode,
            picked_parts=[],
            proper_nouns=ctx.proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=target,
            chapter_intent=ctx.chapter_intent,
            memory_echoes=ctx.memory_echoes,
            style_positive=ctx.style_positive,
            author_samples=ctx.author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            previous_summary=kg.previous_summary,
            recency_pin=kg.recency_pin,
            contract=pick_contract(mode, [], rolling_windowed),
            intent_source=getattr(ctx, "intent_source", "") or "",
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )
    return {
        "system": system,
        "user": user,
        "intent_source": ctx.intent_source,
        "outline_note_source": outline_note_source if mode == "outline" else "",
    }


def _pick_outline_note(chapter: Chapter, bundle) -> tuple:
    """outline 模式的细纲速记代表文本（真实数据优先：spine 锚点 → 大纲节拍 → 占位）。"""
    spine = chapter.spine if isinstance(chapter.spine, dict) else {}
    for a in spine.get("anchors") or []:
        if isinstance(a, dict) and str(a.get("text") or "").strip() and a.get("status") != "dropped":
            return str(a["text"]).strip(), "spine_anchor"
    beats = outline_nearby(bundle.outline_text or "", written_text(chapter.content_text or ""))
    if beats:
        return str(beats[0]), "outline_beat"
    return OUTLINE_NOTE_PLACEHOLDER, "placeholder"


# ============================================================
# dock 卡片舱（system 编译产物 + user）
# ============================================================

async def render_dock(db, chapter: Chapter):
    """dock system 编译产物（ctx 键从 DB 现状推导，判据同 dock_generator.run）。"""
    bundle = await load_chapter_settings_bundle(str(chapter.id), db)
    recent_text = resolve_current_paragraph("", bundle.content_text or "")

    beats = outline_nearby(bundle.outline_text or "", written_text(bundle.content_text or ""))
    memory_echoes = await recall_memories(
        db,
        book_id=bundle.book_id or "",
        chapter_id=str(chapter.id),
        chapter_number=bundle.chapter_number,
        query_text=recent_text[-300:],
        k=ECHOES_K_DOCK,
        mask_names=bundle_mask_names(bundle),
    )
    reader_expectations = bundle.soft_constraints().get("reader_expectations") or None
    spine_intent = ""
    if isinstance(chapter.spine, dict):
        spine_intent = (chapter.spine.get("intent") or {}).get("text", "") or ""

    # 层 2 意图兜底（无节拍时 toward_beat 的猜测供料；stitch_context 同款
    # 只读 SELECT + 信度闸。离线快照无实时 word_count → 意图衰老闸不可判）
    intent_guess, intent_source = await _layer2_intent_fallback(str(chapter.id), db)
    if intent_source != "inferred":
        intent_guess = ""

    # 场景取景框（dock_generator.run 同款：光标前扫描窗 → 派生取景，回退本章钉）
    base_pin = str(getattr(chapter, "scene_location_id", "") or "")
    pre_cursor = pre_cursor_window(html_to_plain(bundle.content_text or ""), "")
    active_scene = resolve_active_scene(pre_cursor, getattr(bundle, "locations", None) or [], base_pin)
    scene_loc_id = active_scene.loc_id
    mention_window = pre_cursor or recent_text
    onstage = onstage_projection(bundle, scene_loc_id, mention_window)
    if onstage is not None:
        template = pick_shot_template(recent_text, (onstage or {}).get("scene_line", ""))
    else:
        template = "default"

    guess_only = not beats and bool(intent_guess)
    dock_ctx = {
        "has_nearby": bool(beats),
        "has_guess": guess_only,
        "has_onstage": bool(onstage),
        "template": template,
        "has_echo_mat": bool(memory_echoes or reader_expectations),
    }
    banned = "、".join((bundle.hard_constraints().get("banned_words") or [])[:30])
    system = render_dock_system(dock_ctx, banned)
    _, user = build_dock_generator_prompt(
        recent_text, [], bundle.nutrients(), bundle.hard_constraints(),
        reader_expectations=reader_expectations,
        memory_echoes=memory_echoes or None,
        spine_intent=spine_intent,
        outline_nearby=beats,
        intent_guess=intent_guess,
        onstage=onstage,
        template=template,
        suffix_anchor="",
    )
    return {
        "system": system,
        "user": user,
        "ctx": dock_ctx,
        "recent_chars": len(recent_text),
        "min_chars_gate_passed": len(recent_text) >= 30,
        "note": "projections 缺席（离线渲染无世界模型快照）——user 侧推测块为兜底文案",
    }


def render_dock_system(dock_ctx: dict, banned: str) -> str:
    """dock system 分节编译（_dock_system_sections + render_sections 唯一权威）。"""
    from backend.services.constraints.prompt_sections import render_sections

    return render_sections(_dock_system_sections(), dock_ctx).replace(
        "«BANNED_WORDS»", banned or "（无）"
    )


# ============================================================
# 落盘
# ============================================================

def _write(dir_path: Path, name: str, text: str, files_meta: dict) -> None:
    path = dir_path / name
    path.write_text(text, encoding="utf-8", newline="\n")
    files_meta[name] = {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "chars": len(text),
    }


async def run(book_id: str, chapter_id: str) -> int:
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = SNAPSHOT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionLocal() as db:
        chapter = await resolve_chapter(db, book_id=book_id, chapter_id=chapter_id)
        bundle0 = await load_chapter_settings_bundle(str(chapter.id), db)
        outline_note, outline_note_source = _pick_outline_note(chapter, bundle0)

        files_meta: dict = {}
        context_meta: dict = {"intent_source": {}, "target_chars": dict(TARGET_CHARS)}

        for mode in STITCH_MODES:
            rendered = await render_stitch_mode(db, chapter, mode, outline_note, outline_note_source)
            _write(out_dir, f"stitch_{mode}.system.txt", rendered["system"], files_meta)
            _write(out_dir, f"stitch_{mode}.user.txt", rendered["user"], files_meta)
            context_meta["intent_source"][mode] = rendered["intent_source"]
            if mode == "outline":
                context_meta["outline_note_source"] = rendered["outline_note_source"]

        dock = await render_dock(db, chapter)
        _write(out_dir, "dock.system.txt", dock["system"], files_meta)
        _write(out_dir, "dock.user.txt", dock["user"], files_meta)
        context_meta["dock_ctx"] = dock["ctx"]
        context_meta["dock_min_chars_gate_passed"] = dock["min_chars_gate_passed"]
        context_meta["dock_note"] = dock["note"]

        manifest = {
            "prompt_version": PROMPT_VERSION,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "chapter_id": str(chapter.id),
            "chapter_number": chapter.chapter_number,
            "chapter_name": chapter.chapter_name or chapter.title or "",
            "book_id": str(chapter.book_id),
            "outline_note_source": outline_note_source,
            "context": context_meta,
            "files": files_meta,
        }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    await engine.dispose()

    print(f"[prompt_snapshot] PROMPT_VERSION={PROMPT_VERSION}")
    print(
        f"[prompt_snapshot] 章节：第{chapter.chapter_number}章「{chapter.chapter_name or chapter.title or ''}」"
        f"（book={str(chapter.book_id)[:8]}… chapter={str(chapter.id)[:8]}…）"
    )
    print(f"[prompt_snapshot] 输出目录：{out_dir}")
    for name in sorted(files_meta):
        print(f"    {name:<32} {files_meta[name]['chars']:>6} 字")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="prompt 快照：两条生成链最终 prompt 纯渲染落盘（零 LLM 调用）",
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--book-id", default="", help="指定书（取该书最近有正文的章）")
    g.add_argument("--chapter-id", default="", help="指定章节 id")
    args = ap.parse_args()
    return asyncio.run(run(args.book_id, args.chapter_id))


if __name__ == "__main__":
    sys.exit(main())
