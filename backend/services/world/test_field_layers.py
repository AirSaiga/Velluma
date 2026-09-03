# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""字段级真相分层（2026-09-03）对拍单测。

锁定五条消费线：
1. world_bridge.static_prompt_from_world_entity 档案拆分
   （private 跳过 / partial 表顶替 / 空 layers 逐字节零变化 / secrets 通道不拆）
2. build_canon_context_for_prompt [private] 虚拟条目注入（含往返标签解析）
3. check_consistency 泄密短语源扩展（partial 表里共词豁免）
4. read_merge_reveals 字段「第几章揭」第三来源（窗内/窗外）
5. ghost_guard 3b 字段秘密快检（secret_leak + partial 豁免）

DB 用例走 db_sqlite 真实 ORM 栈（与 canon/test_context_contract.py 同模式）。
"""
import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.db_sqlite.type_compat import register_sqlite_type_compat  # noqa: F401（方言编译副作用注册）

register_sqlite_type_compat()

import backend.models as m
from backend.services.canon.consistency import (
    build_canon_context_for_prompt,
    check_consistency,
)
from backend.services.context.settings_bundle import _extract_canon_private_labels
from backend.services.context.world_bridge import static_prompt_from_world_entity
from backend.services.validation.ghost_guard import check_ghost_text
from backend.services.world.field_layers import (
    LEVEL_PARTIAL,
    LEVEL_PRIVATE,
    iter_field_layers,
    layered_profile_value,
)


def _ent(props=None, layers=None, visibility="public", name="林尘"):
    return SimpleNamespace(
        name=name, props=props or {}, field_layers=layers or {}, visibility=visibility,
    )


# ============================================================
# 1. 纯函数层 + 档案拼装拆分
# ============================================================

_PROPS = {
    "appearance": "清瘦，戴旧眼镜",
    "background": "表面是电工，实际是卧底",
    "skills": "会修老式电台",
}


def test_static_prompt_baseline_zero_change():
    """无 field_layers：输出与分层特性诞生前逐字节一致。"""
    text = static_prompt_from_world_entity(_ent(props=_PROPS))
    assert text == "外貌：清瘦，戴旧眼镜\n背景：表面是电工，实际是卧底\n技能：会修老式电台"
    # 空 layers dict 同口径
    assert static_prompt_from_world_entity(_ent(props=_PROPS, layers={})) == text


def test_static_prompt_private_field_skipped():
    layers = {"background": {"level": LEVEL_PRIVATE}}
    text = static_prompt_from_world_entity(_ent(props=_PROPS, layers=layers))
    assert "背景" not in text
    assert "卧底" not in text
    assert "外貌：清瘦，戴旧眼镜" in text  # 其余字段不动


def test_static_prompt_partial_public_text_replaces():
    layers = {"background": {"level": LEVEL_PARTIAL, "public_text": "普通电工"}}
    text = static_prompt_from_world_entity(_ent(props=_PROPS, layers=layers))
    assert "背景：普通电工" in text
    assert "卧底" not in text


def test_static_prompt_partial_empty_public_text_falls_private():
    """半露但表为空 = 安全缺省按秘密处理（字段整段隐去）。"""
    layers = {"background": {"level": LEVEL_PARTIAL, "public_text": ""}}
    text = static_prompt_from_world_entity(_ent(props=_PROPS, layers=layers))
    assert "背景" not in text


def test_static_prompt_respect_layers_false_keeps_full():
    """整人 private 走 secrets 通道时（respect_layers=False）档案不拆。"""
    layers = {"background": {"level": LEVEL_PRIVATE}}
    text = static_prompt_from_world_entity(_ent(props=_PROPS, layers=layers), respect_layers=False)
    assert "背景：表面是电工，实际是卧底" in text


def test_layered_profile_value_and_iter_defensive():
    """坏数据防御：非法 level/空全文/坏 reveal_chapter 一律安全兜底。"""
    ent = _ent(props={"background": "秘密身世"}, layers={
        "background": {"level": "nonsense"},          # 非法 level → 公开
        "skills": {"level": LEVEL_PRIVATE},            # 无此 props 字段 → 无条目
        "goal": {"level": LEVEL_PARTIAL, "reveal_chapter": "abc"},  # 无 props 值 → 无条目
    })
    assert layered_profile_value(ent, "background", "秘密身世") == "秘密身世"
    assert list(iter_field_layers(ent)) == []


# ============================================================
# DB 栈（canon 注入 / 泄密检测 / 揭示合并读）
# ============================================================

def _make_stack(tmp_path):
    engine = build_sqlite_engine(tmp_path / "field_layers.db")
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _seed(maker, *, layers, visibility="public"):
    book_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    async def run():
        async with maker() as s:
            s.add(m.Book(id=book_id, title="分层书"))
            s.add(m.WorldEntity(
                id=entity_id, book_id=book_id, name="林尘", entity_type="character",
                visibility=visibility,
                props={
                    "personality": "内向，偏软弱",
                    "background": "表面是电工，实际是卧底",
                },
                field_layers=layers,
            ))
            await s.commit()
    asyncio.run(run())
    return book_id, entity_id


def test_canon_prompt_virtual_entries(tmp_path):
    """[private] 段并入字段虚拟条目：标签「实体名·字段名」+ partial 表注 +
    往返标签解析（_extract_canon_private_labels）能取到复合标签。"""
    engine, maker = _make_stack(tmp_path)
    try:
        book_id, _ = _seed(maker, layers={
            "background": {"level": LEVEL_PARTIAL, "public_text": "普通电工", "reveal_chapter": 8},
        })

        async def run():
            async with maker() as s:
                return await build_canon_context_for_prompt(s, book_id)
        ctx = asyncio.run(run())

        assert "## 作者脑中的真相 [private]" in ctx
        assert "- 林尘·背景：表面是电工，实际是卧底（读者目前只知：普通电工）" in ctx, ctx
        assert "→ 写作时可作为角色隐藏动机" in ctx
        labels = _extract_canon_private_labels(ctx)
        assert "林尘·背景" in labels, labels
    finally:
        asyncio.run(engine.dispose())


def test_canon_prompt_zero_change_without_layers(tmp_path):
    """零变化契约：无分层的书（也无节点）输出保持原兜底文案。"""
    engine, maker = _make_stack(tmp_path)
    try:
        book_id, _ = _seed(maker, layers={})

        async def run():
            async with maker() as s:
                return await build_canon_context_for_prompt(s, book_id)
        ctx = asyncio.run(run())
        assert ctx == "（Canon 为空，无强约束）"
    finally:
        asyncio.run(engine.dispose())


def test_canon_prompt_skips_wholly_private_entity(tmp_path):
    """整人 private 实体不产虚拟条目（全档案已在 secrets 通道，防重复注入）。"""
    engine, maker = _make_stack(tmp_path)
    try:
        book_id, _ = _seed(maker, visibility="private", layers={
            "background": {"level": LEVEL_PRIVATE},
        })

        async def run():
            async with maker() as s:
                return await build_canon_context_for_prompt(s, book_id)
        ctx = asyncio.run(run())
        assert "林尘·背景" not in ctx
        assert ctx == "（Canon 为空，无强约束）"
    finally:
        asyncio.run(engine.dispose())


def test_check_consistency_field_leak_and_partial_exemption(tmp_path):
    """字段泄密命中 + partial 表里共词豁免：
    「表面是电工」在表里（读者已知）→ 不报；「实际是卧底」只在里 → 报。"""
    engine, maker = _make_stack(tmp_path)
    try:
        book_id, _ = _seed(maker, layers={
            "background": {"level": LEVEL_PARTIAL, "public_text": "表面是电工"},
        })

        async def run_check(text):
            async with maker() as s:
                return await check_consistency(s, book_id, text)
        issues_ok, _ = asyncio.run(run_check("他白天上班，表面是电工，没人怀疑。"))
        assert not [i for i in issues_ok if i.kind == "private_leak"], issues_ok

        issues_bad, stats = asyncio.run(run_check("邻居不知道他实际是卧底。"))
        leaks = [i for i in issues_bad if i.kind == "private_leak"]
        assert leaks and leaks[0].node_label == "林尘·背景", issues_bad
        assert stats["private_total"] == 1  # 字段条目计入私有总量
    finally:
        asyncio.run(engine.dispose())


def test_read_merge_reveals_field_layer_source(tmp_path):
    """字段「第几章揭」进揭示合并读：窗内（含逾期 1 章）出现、窗外缺席。"""
    from backend.repositories.intent_repository import IntentRepository

    engine, maker = _make_stack(tmp_path)
    try:
        book_id, _ = _seed(maker, layers={
            "background": {"level": LEVEL_PARTIAL, "public_text": "普通电工", "reveal_chapter": 8},
        })

        async def run(ch):
            async with maker() as s:
                return await IntentRepository(s).read_merge_reveals(book_id, chapter_number=ch)
        rows_in = asyncio.run(run(7))   # 7-1 ≤ 8 ≤ 7+2
        assert any(
            r["source"] == "field_layer" and r["label"] == "林尘·背景"
            and r["expected_reveal_chapter"] == 8
            for r in rows_in
        ), rows_in
        rows_out = asyncio.run(run(20))
        assert not [r for r in rows_out if r["source"] == "field_layer"], rows_out
    finally:
        asyncio.run(engine.dispose())


# ============================================================
# 5. ghost_guard 3b 字段秘密快检（显式参数路径，无需 DB）
# ============================================================

def test_ghost_guard_field_layer_secret_leak():
    secrets = [{
        "name": "林尘", "label": "背景", "level": LEVEL_PRIVATE,
        "text": "表面是电工，实际是卧底", "public_text": "",
    }]
    hits = check_ghost_text("没人想到，他实际是卧底。", field_layer_secrets=secrets)
    leaks = [w for w in hits if w["kind"] == "secret_leak"]
    assert leaks and "林尘·背景" in leaks[0]["message"], hits
    assert leaks[0]["span_text"] == "实际是卧底"


def test_ghost_guard_field_layer_partial_exemption():
    """partial：表文本短语被豁免（读者已知），只在里才有的短语才报。"""
    secrets = [{
        "name": "林尘", "label": "背景", "level": LEVEL_PARTIAL,
        "text": "表面是电工，实际是卧底", "public_text": "表面是电工",
    }]
    hits_ok = check_ghost_text("街坊都知道他表面是电工。", field_layer_secrets=secrets)
    assert not [w for w in hits_ok if w["kind"] == "secret_leak"], hits_ok
    hits_bad = check_ghost_text("他实际是卧底。", field_layer_secrets=secrets)
    assert [w for w in hits_bad if w["kind"] == "secret_leak"], hits_bad


def test_ghost_guard_zero_change_without_field_layers():
    """零变化契约：field_layer_secrets 缺省/空 → 行为与特性诞生前一致。"""
    assert check_ghost_text("他实际是卧底。") == []
    assert check_ghost_text("他实际是卧底。", field_layer_secrets=[]) == []
