# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
A1「私有」语义统一单测（docs/foundation-hardening.md §3.1，D5 拍板：
私有 = AI 知晓但绝不能直接写出，对齐 canon [private]，而非从上下文删除）。

双轨纪律（§9 红线）锁定四件套：
1. 私有实体档案只进 secrets 通道（bundle.character_secrets → prompt 私有块），
   不进 characters/assets 文本、不进 hard_constraints()["character_statics"]；
2. 公开实体各装配口不变；
3. 零变化契约：无私有实体的书 prompt 逐字节不变（render_system_blocks 空
   secrets → 空块；四 builder 默认 None 与显式传空逐字节一致）；
4. 内部算法消费方（sediment 冲突检测的 ent.character.static_prompt 鸭子链）
   仍吃适配器全量——过滤只发生在文本装配层。

另覆盖：私有 asset/faction 同通道、_secrets_block 条数/截断常量、
预览块序含 secrets（stitch_context 同源）。

配方（同 test_world_bridge_presence.py）：临时文件 SQLite + 真实 repo 栈
（db_sqlite 引擎 + init_db_sqlite；:memory: 不适用见 engine.py 模块注释），
每测试独立 asyncio.run 事件循环（AGENTS.md 测试节），测试 UUID 一律带字母
（SQLite NUMERIC 亲和性坑，db_sqlite/type_compat.py）。

运行：python -m pytest backend/services/context/test_private_channel.py -v
"""

import asyncio
import uuid

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.world_repository import WorldRepository
from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.context.world_bridge import load_world_overlay
from backend.services.prompts.adaptive_prompts import (
    SECRETS_BLOCK_HEADER,
    SECRETS_BLOCK_MAX_ENTRIES,
    SECRETS_ENTRY_MAX_CHARS,
    _base_system,
    _secrets_block,
    build_continue_prompt,
    render_system_blocks,
)

BOOK_ID = uuid.UUID("ad410000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("ad410000-0000-4000-8000-0000000000b1")

SECRET_DOSSIER = "背景：其实是敌国公主\n目标：复仇"


def _make_stack(tmp_path, name: str):
    """建引擎+会话工厂+初始化 schema，返回 (engine, sessionmaker)。"""
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed_book(session, with_private: bool) -> None:
    """一章 + 世界实体：甲（公开，档案豪爽）+ 可选 叶姑娘（私有，敌国公主）。

    with_private=False 的种子同时充当零变化基线（同一书结构、无私有实体）。
    """
    session.add(m.Book(id=BOOK_ID, title="私有通道测试书"))
    session.add(m.Chapter(
        id=CH_ID, book_id=BOOK_ID, chapter_number=1,
        title="第一章", narrative_time=10,
    ))
    await session.flush()
    repo = WorldRepository(session)
    await repo.entities.create(
        book_id=BOOK_ID, entity_type="character", name="甲", importance=5,
        props={"personality": "豪爽"},
    )
    if with_private:
        await repo.entities.create(
            book_id=BOOK_ID, entity_type="character", name="叶姑娘",
            importance=9, visibility="private",
            props={"background": "其实是敌国公主", "goal": "复仇"},
        )
    await session.flush()


def _load_bundle(maker, with_private: bool):
    async def run():
        async with maker() as s:
            await _seed_book(s, with_private)
            return await load_chapter_settings_bundle(str(CH_ID), s)

    return asyncio.run(run())


# ============================================================
# 1. 私有实体内容只进 secrets 通道，不进 prompt 文本装配
# ============================================================

def test_private_dossier_only_in_secrets_channel(tmp_path):
    """私有角色：档案进 character_secrets；characters 文本 / nutrients /
    character_statics / assets 文本均无其内容。"""
    engine, maker = _make_stack(tmp_path, "private.db")
    try:
        bundle = _load_bundle(maker, with_private=True)

        assert bundle.world_sourced is True
        # secrets 通道：结构化拼接文本（键序 = _STRUCTURED_FIELDS 拼接序）
        assert bundle.character_secrets == [
            {"name": "叶姑娘", "text": SECRET_DOSSIER},
        ]

        ctx = bundle.to_prompt_context()
        assert "叶姑娘" not in ctx["characters"]
        assert "敌国公主" not in ctx["characters"]
        assert "复仇" not in ctx["characters"]
        assert "- 甲：性格：豪爽" in ctx["characters"]  # 公开实体照常在场
        assert ctx["character_secrets"] == bundle.character_secrets

        # nutrients（dock/intent/future 组件的 prompt 养料）同过滤
        assert "叶姑娘" not in bundle.nutrients()["characters"]
        # character_statics（dock 生发 prompt 的防 OOC 块）同过滤
        assert "叶姑娘" not in bundle.hard_constraints()["character_statics"]
        assert "甲" in bundle.hard_constraints()["character_statics"]
    finally:
        asyncio.run(engine.dispose())


def test_private_asset_goes_to_secrets_not_assets_text(tmp_path):
    """私有资产：intro 走 secrets（与 WorldAssetAdapter.static_description
    同口径），_assets_text 不再出现。"""
    engine, maker = _make_stack(tmp_path, "asset.db")
    try:
        async def run():
            async with maker() as s:
                session = s
                await _seed_book(session, with_private=False)
                repo = WorldRepository(session)
                await repo.entities.create(
                    book_id=BOOK_ID, entity_type="asset", name="断剑",
                    importance=7, visibility="private",
                    intro="剑柄里藏着密信",
                )
                await repo.entities.create(
                    book_id=BOOK_ID, entity_type="asset", name="油灯",
                    importance=3, intro="普通的油灯",
                )
                await session.flush()
                return await load_chapter_settings_bundle(str(CH_ID), session)

        bundle = asyncio.run(run())
        assert {"name": "断剑", "text": "剑柄里藏着密信"} in bundle.character_secrets
        assets_text = bundle.to_prompt_context()["assets"]
        assert "断剑" not in assets_text
        assert "密信" not in assets_text
        assert "油灯" in assets_text
    finally:
        asyncio.run(engine.dispose())


def test_private_entity_without_text_skipped(tmp_path):
    """空档案的私有实体不进 secrets（无秘密可保，不占 prompt 行）。"""
    engine, maker = _make_stack(tmp_path, "notext.db")
    try:
        async def run():
            async with maker() as s:
                await _seed_book(s, with_private=False)
                repo = WorldRepository(s)
                await repo.entities.create(
                    book_id=BOOK_ID, entity_type="character", name="哑谜",
                    importance=5, visibility="private", props={},
                )
                await s.flush()
                return await load_chapter_settings_bundle(str(CH_ID), s)

        bundle = asyncio.run(run())
        assert bundle.character_secrets == []
    finally:
        asyncio.run(engine.dispose())


# ============================================================
# 2. 公开实体不变 + 零变化契约（无私有实体的书 prompt 逐字节不变）
# ============================================================

def test_public_entities_unchanged(tmp_path):
    """公开书：characters/assets/character_statics 与 secrets 空载——
    全部装配口与 A1 之前的行为一致。"""
    engine, maker = _make_stack(tmp_path, "public.db")
    try:
        bundle = _load_bundle(maker, with_private=False)
        assert bundle.character_secrets == []
        assert bundle.to_prompt_context()["characters"] == "- 甲：性格：豪爽"
        assert "甲" in bundle.hard_constraints()["character_statics"]
    finally:
        asyncio.run(engine.dispose())


def test_zero_change_prompt_without_private(tmp_path):
    """零变化契约：secrets 空载时四 builder 的 prompt 与不传该参逐字节一致，
    且 render_system_blocks 无私有块头残留。"""
    engine, maker = _make_stack(tmp_path, "zerochange.db")
    try:
        bundle = _load_bundle(maker, with_private=False)
        base = dict(
            proper_nouns=bundle.proper_nouns(),
            canon_context=bundle.canon_context,
        )
        for secrets_value in (None, []):
            sys_new, usr_new = build_continue_prompt(
                fragment="他抬头。", rolling_prefix="灯下。",
                character_secrets=secrets_value, **base,
            )
            sys_old, usr_old = build_continue_prompt(
                fragment="他抬头。", rolling_prefix="灯下。", **base,
            )
            assert sys_new == sys_old
            assert usr_new == usr_old
            assert SECRETS_BLOCK_HEADER not in sys_new
    finally:
        asyncio.run(engine.dispose())


def test_secrets_block_injected_after_canon():
    """私有书：块头+条目出现在 system prompt，且紧随 canon 块（注入序权威）。"""
    secrets = [{"name": "叶姑娘", "text": SECRET_DOSSIER}]
    sys_prompt, _ = build_continue_prompt(
        fragment="他抬头。", rolling_prefix="灯下。",
        proper_nouns=["甲"], canon_context="[public]\n- 甲：老兵",
        character_secrets=secrets,
    )
    assert f"# {SECRETS_BLOCK_HEADER}" in sys_prompt
    assert "- 叶姑娘：背景：其实是敌国公主\n目标：复仇" in sys_prompt
    # 注入序：canon 块 → secrets 块 →（无回响/空间）
    assert sys_prompt.index("作者脑中世界图谱") < sys_prompt.index(SECRETS_BLOCK_HEADER)
    # 块清单（预览同源）：secrets 在 canon 之后、echoes 之前
    keys = [k for k, _ in render_system_blocks(
        canon_context="[public]\n- 甲：老兵",
        character_secrets=secrets,
        memory_echoes=["旧章片段。"],
    )]
    assert keys.index("canon") < keys.index("secrets") < keys.index("echoes")


def test_secrets_block_caps_and_truncation():
    """条数上限 8 / 每条截 150 字（常量集中书写，A3a 收编点）。"""
    long_text = "密" * (SECRETS_ENTRY_MAX_CHARS + 50)
    many = [{"name": f"密探{i:02d}", "text": long_text} for i in range(SECRETS_BLOCK_MAX_ENTRIES + 3)]
    block = _secrets_block(many)
    lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(lines) == SECRETS_BLOCK_MAX_ENTRIES
    for ln in lines:
        # 「- 名字：」前缀 + 截断文本（名字 3 字 + 分隔符），体长 ≤ 150
        body = ln.split("：", 1)[1]
        assert len(body) == SECRETS_ENTRY_MAX_CHARS
    # 空载形态
    assert _secrets_block(None) == ""
    assert _secrets_block([]) == ""
    assert _secrets_block([{"name": "", "text": "有文无名"}]) == ""
    assert _secrets_block([{"name": "有名", "text": ""}]) == ""


# ============================================================
# 3. 算法轨吃全量（双轨纪律另一侧）
# ============================================================

def test_algorithm_consumers_still_get_full_dossier(tmp_path):
    """适配器 static_prompt 仍是全量：sediment 冲突检测的
    ent.character.static_prompt 鸭子链读得到私有档案（过滤只在文本装配层）。"""
    engine, maker = _make_stack(tmp_path, "full.db")
    try:
        async def run():
            async with maker() as s:
                await _seed_book(s, with_private=True)
                chapter = await s.get(m.Chapter, CH_ID)
                return await load_world_overlay(str(BOOK_ID), s, chapter)

        overlay = asyncio.run(run())
        # 私有实体仍在 entities 适配器名单里（16 席不因 private 被逐出）
        by_name = {a.character.name: a for a in overlay["entities"]}
        assert "叶姑娘" in by_name
        # 鸭子链直读 = 全量档案（与 secrets 通道同一份文本，但未经条数/截断）
        static = by_name["叶姑娘"].character.static_prompt
        assert static == SECRET_DOSSIER
        # overlay 的 secrets 通道与适配器全量同源（world_bridge 侧一致性）
        assert overlay["secrets"] == [{"name": "叶姑娘", "text": static}]
    finally:
        asyncio.run(engine.dispose())


def test_legacy_entities_have_no_visibility_concept(tmp_path):
    """旧表回退路径零影响：world 为空 → overlay=None → 旧表实体（Character
    模型无 visibility 列）恒公开，character_secrets 恒空。"""
    engine, maker = _make_stack(tmp_path, "legacy.db")
    try:
        async def run():
            async with maker() as s:
                s.add(m.Book(id=BOOK_ID, title="旧表书"))
                s.add(m.Chapter(
                    id=CH_ID, book_id=BOOK_ID, chapter_number=1,
                    title="第一章", narrative_time=10,
                ))
                await s.flush()
                overlay = await load_world_overlay(str(BOOK_ID), s, None)
                bundle = await load_chapter_settings_bundle(str(CH_ID), s)
                return overlay, bundle

        overlay, bundle = asyncio.run(run())
        assert overlay is None
        assert bundle.character_secrets == []
        assert bundle.world_sourced is False
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    import unittest

    unittest.main()
