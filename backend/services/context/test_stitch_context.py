# Velluma - stitch_context 单测（P5 B2 · AI 所见预览）
# AGPL-3.0
"""
stitch-ghost 上下文装配共享器单测（docs/foundation-hardening.md §2.1）。

覆盖四层：
1. 同源红线（纯函数）：预览块拼接 + 基座 == 四个 stitch builder 的真实
   system prompt，逐字节一致；空上下文 → 全空块、builder prompt 零残留。
2. 预览载荷契约：块序 = 注入序（画像→样本→专名→canon→私有→回响→空间）、
   total_chars/world 字段透传、来源徽标分流（世界实体 vs 章级绑定、
   真相层含私有 vs 公开、私有设定）。
3. 装配口径（mock bundle）：open/非 open 的召回 query 构造、chapter_intent
   兜底、无 book_id 不检索样本——与旧 stitch 路由内联段逐条对齐。
4. 端点级（真实 SQLite 栈）：种子书跑通 context_preview 全程（含 HTML 剥离），
   预览块与同一装配结果再喂 builder 的 system prompt 逐字节一致；
   空设定书（章节不存在）七块全空不抛错；非法 mode 422。

配方：临时文件 SQLite + 真实 repo 栈（同 test_world_bridge_presence.py）；
embedding 一律 monkeypatch 为未配置（防本地 model_config.json 触发真实
embedding HTTP 调用——兜底流已覆盖装配路径）；每个异步场景独立
asyncio.run 事件循环（AGENTS.md 测试节防污染约定）；测试 UUID 带字母。

运行：python -m pytest backend/services/context/test_stitch_context.py -v
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.routes.chapter_generation.adaptive import context_preview
from backend.services.context.settings_bundle import SettingsBundle
from backend.services.context.stitch_context import (
    StitchContext,
    assemble_stitch_context,
    build_context_preview,
)
from backend.services.prompts.adaptive_prompts import (
    _base_system,
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
)
from backend.services.rag import recall as recall_mod
from backend.services.style import retrieval as retrieval_mod

BOOK_ID = uuid.UUID("cc330000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("cc330000-0000-4000-8000-0000000000b1")
ENT_ID = uuid.UUID("cc330000-0000-4000-8000-0000000000e1")

# 知识检索平面 v3.1（2026-08-27）：注入序=事实层前于文风层；空 kg 时专名兜底位在 entities 后
BLOCK_ORDER = ["scene", "warm", "entities", "proper_nouns", "canon", "secrets", "worldview",
               "relations", "negative", "echoes", "spatial", "style_positive", "author_samples"]

# 固定装配值（六块全非空，逼出完整块渲染）
FIXED = dict(
    style_positive="- 句长节奏：短句为主\n- 语域偏好：冷峻克制",
    author_samples=["他走到窗前。雨在下，一声一声，像谁在数着什么。"],
    proper_nouns=["林尘", "扳手"],
    canon_context="[public]\n- 林尘：灯塔守夜人\n\n[private]\n- 怀表：藏有旧主遗书",
    memory_echoes=["第三章：林尘捡到一枚锈蚀的怀表。"],
    spatial_brief="北岸要塞到灯塔约 3 日路程。",
)


def _fixed_ctx() -> StitchContext:
    return StitchContext(
        bundle=SettingsBundle(canon_context=FIXED["canon_context"], spatial_brief=FIXED["spatial_brief"]),
        proper_nouns=FIXED["proper_nouns"],
        memory_echoes=FIXED["memory_echoes"],
        style_positive=FIXED["style_positive"],
        author_samples=FIXED["author_samples"],
    )


# ============================================================
# 1. 同源红线：预览块拼接 == 真实 builder system prompt
# ============================================================

class TestPreviewBlocksMatchRealPrompt:
    """预览块（拼接在基座后）与四 builder 的 system prompt 逐字节一致。"""

    def test_blocks_concat_equals_all_four_builders(self):
        """各 builder 的 system prompt == 基座 + 同模式装配块的拼接（逐字节）。

        C3 起分模式差异化注入（continue 档画像压缩）——对拍时 ctx 与 builder
        必须同 mode：同源红线的模式维度。
        """
        six = dict(
            style_positive=FIXED["style_positive"],
            author_samples=FIXED["author_samples"],
            proper_nouns=FIXED["proper_nouns"],
            canon_context=FIXED["canon_context"],
            memory_echoes=FIXED["memory_echoes"],
            spatial_brief=FIXED["spatial_brief"],
        )
        cases = [
            (build_continue_prompt, dict(fragment="他攥紧扳手", rolling_prefix="灯下。", mode="stitch"), "stitch"),
            (build_burst_prompt, dict(fragment="风更大了。", rolling_prefix="退潮在即。"), "burst"),
            (build_outline_expand_prompt, dict(outline_note="约300字：阿晚说出真相", rolling_prefix="灯下。"), "outline"),
            (build_opening_prompt, dict(outline_text="第一章：暴风雨夜，灯塔失电。"), "open"),
        ]
        for builder, extra, mode in cases:
            ctx = _fixed_ctx()
            ctx.mode = mode
            block_text = "".join(content for _key, content in ctx.system_blocks())
            sys_prompt, _ = builder(**six, **extra)
            assert sys_prompt == _base_system() + block_text, f"{builder.__name__} 与预览块不同源"

    def test_block_order_is_injection_order(self):
        ctx = _fixed_ctx()
        assert [key for key, _ in ctx.system_blocks()] == BLOCK_ORDER

    def test_empty_context_all_blocks_empty(self):
        ctx = StitchContext()
        for key, content in ctx.system_blocks():
            assert content == "", f"{key} 空上下文应为空块"
        # 空块拼接 → builder prompt 无任何块头（零变化契约）
        sys_prompt, _ = build_continue_prompt(fragment="他攥紧扳手", rolling_prefix="灯下。")
        for header in ("作者文风画像", "作者笔迹示范", "在场实体专名", "作者脑中世界图谱", "作者私有设定", "前情回响", "空间常识"):
            assert header not in sys_prompt


# ============================================================
# 2. 预览载荷契约
# ============================================================

class TestBuildContextPreview:
    def test_payload_contract_full(self):
        ctx = _fixed_ctx()
        ctx.bundle.world_time = 1240
        ctx.bundle.world_time_source = "chapter_anchor"
        ctx.bundle.world_sourced = True
        payload = build_context_preview(ctx, "continue")

        assert payload["mode"] == "continue"
        assert [b["key"] for b in payload["blocks"]] == BLOCK_ORDER
        assert payload["total_chars"] == sum(b["chars"] for b in payload["blocks"])
        assert all(b["chars"] == len(b["content"]) for b in payload["blocks"])
        # 世界字段透传
        assert payload["world_time"] == 1240
        assert payload["world_time_source"] == "chapter_anchor"
        assert payload["world_sourced"] is True
        # 来源徽标：world 桥接书 + 含私有 canon
        by_key = {b["key"]: b for b in payload["blocks"]}
        assert by_key["proper_nouns"]["source"] == "世界实体"
        assert by_key["canon"]["source"] == "真相层（含私有）"
        # A1 私有通道徽标（块内容为空但来源档位恒在——空块走「未配置」提示）
        assert by_key["secrets"]["source"] == "世界实体 · 私有设定"
        assert by_key["style_positive"]["source"] == "文风卡"
        assert by_key["author_samples"]["source"] == "文风样本库"
        assert by_key["echoes"]["source"] == "记忆召回"
        assert by_key["spatial"]["source"] == "世界比例尺"
        # 每块都有中文标题（前端折叠区展示）
        assert all(b["title"] for b in payload["blocks"])

    def test_source_badges_legacy_book(self):
        ctx = StitchContext()  # world_sourced=False、canon 无 [private]
        payload = build_context_preview(ctx, "stitch")
        by_key = {b["key"]: b for b in payload["blocks"]}
        assert by_key["proper_nouns"]["source"] == "章级绑定"
        assert by_key["canon"]["source"] == "真相层"
        assert payload["world_time_source"] == "zero"
        assert payload["world_sourced"] is False

    def test_empty_bundle_all_blocks_empty_kept(self):
        """空块原样返回（content=""），不删块——前端「未配置」提示的入口流量。"""
        payload = build_context_preview(StitchContext(), "open")
        assert len(payload["blocks"]) == len(BLOCK_ORDER)
        assert all(b["content"] == "" and b["chars"] == 0 for b in payload["blocks"])
        assert payload["total_chars"] == 0

    def test_author_samples_badge_shows_dialogue_scene(self):
        """C2 判定可见性：dialogue 加成激活时样本块徽标注明；general 时与旧版逐一致。"""
        ctx = _fixed_ctx()
        ctx.scene_hint = "dialogue"
        by_key = {b["key"]: b for b in build_context_preview(ctx, "continue")["blocks"]}
        assert by_key["author_samples"]["source"] == "文风样本库 · 对话场景优先"
        ctx.scene_hint = "general"
        by_key = {b["key"]: b for b in build_context_preview(ctx, "continue")["blocks"]}
        assert by_key["author_samples"]["source"] == "文风样本库"


# ============================================================
# 3. 装配口径（mock bundle，与旧路由内联段逐条对齐）
# ============================================================

class _Capture:
    """捕获 recall/样本检索调用的假件（存储与方法异名，防属性遮蔽方法）。"""

    def __init__(self, echoes=None, samples=None):
        self.calls = []
        self.sample_hints = []  # C2：样本检索收到的 scene_hint 序列
        self._echoes = echoes or []
        self._samples = samples or []

    async def recall(self, db, **kw):
        self.calls.append(("recall", kw))
        return self._echoes

    async def samples_meta(self, db, book_id, query, k=2, scene_hint=None,
                           style_card=None, drift_anchor=False):
        self.calls.append(("samples", book_id, query, k))
        self.sample_hints.append(scene_hint)
        # P5 meta 契约：[(sample_id, text)]；样本 id 用序号占位（埋点测试用）
        return [(f"sid-{i}", t) for i, t in enumerate(self._samples)]


def _mock_bundle(monkeypatch, capture, **bundle_kw) -> SettingsBundle:
    defaults = dict(chapter_id="ch-1", book_id="bk-1", chapter_number=3)
    defaults.update(bundle_kw)
    bundle = SettingsBundle(**defaults)
    async def _load(chapter_id, db):
        return bundle
    monkeypatch.setattr("backend.services.context.stitch_context.load_chapter_settings_bundle", _load)
    monkeypatch.setattr("backend.services.context.stitch_context.recall_memories", capture.recall)
    monkeypatch.setattr("backend.services.context.stitch_context.retrieve_author_samples_with_meta", capture.samples_meta)
    return bundle


class TestAssembleQueryContract:
    def test_continue_mode_query(self, monkeypatch):
        capture = _Capture()
        outline = "第" * 300  # 大纲长于 200，验证 open 截断用
        _mock_bundle(monkeypatch, capture, outline_text=outline)
        rolling = "旧" * 300
        ctx = asyncio.run(assemble_stitch_context(
            "ch-1", "continue", fragment="他攥紧扳手", rolling_prefix=rolling, db=None,
        ))
        # query = rolling[-150:] + " " + fragment（旧路由同口径）
        assert ctx.recall_query == rolling[-150:] + " " + "他攥紧扳手"
        recall_kw = capture.calls[0][1]
        assert recall_kw["book_id"] == "bk-1"
        assert recall_kw["chapter_id"] == "ch-1"
        assert recall_kw["chapter_number"] == 3
        assert recall_kw["k"] == 3
        # 样本检索同锚（query 相同、k=2）
        assert capture.calls[1] == ("samples", "bk-1", ctx.recall_query, 2)
        # C2 场景判定接线：rolling_prefix 尾 300 字纯叙述 → general（透传）
        assert ctx.scene_hint == "general"
        assert capture.sample_hints == ["general"]

    def test_burst_mode_samples_k3(self, monkeypatch):
        """C3 burst 样本加量：burst 档样本检索 k=3（走向卡连写段落级生成，
        范例权重最高）；continue 等其余模式维持 k=2（零变化，见上测）。"""
        capture = _Capture()
        _mock_bundle(monkeypatch, capture, outline_text="大纲：走向卡连写。")
        ctx = asyncio.run(assemble_stitch_context(
            "ch-1", "burst", fragment="风更大了。", rolling_prefix="退潮在即。", db=None,
        ))
        assert capture.calls[1] == ("samples", "bk-1", ctx.recall_query, 3)
        assert ctx.scene_hint == "general"   # scene_hint 仍照常透传（C2 不回退）

    def test_open_mode_query_uses_outline(self, monkeypatch):
        capture = _Capture()
        outline = "第" * 300
        _mock_bundle(monkeypatch, capture, outline_text=outline)
        ctx = asyncio.run(assemble_stitch_context(
            "ch-1", "open", fragment="", rolling_prefix="正文尾部", db=None,
        ))
        assert ctx.recall_query == outline[:200]

    def test_chapter_intent_fallback_and_passthrough(self, monkeypatch):
        capture = _Capture()
        _mock_bundle(monkeypatch, capture, outline_text="大纲：林尘发现假信。")
        ctx = asyncio.run(assemble_stitch_context(
            "ch-1", "continue", fragment="他", rolling_prefix="", db=None,
        ))
        assert ctx.chapter_intent == "大纲：林尘发现假信。"[:200]
        ctx2 = asyncio.run(assemble_stitch_context(
            "ch-1", "continue", fragment="他", rolling_prefix="", db=None,
            chapter_intent="作者亲笔意图",
        ))
        assert ctx2.chapter_intent == "作者亲笔意图"

    def test_no_book_id_skips_sample_retrieval(self, monkeypatch):
        capture = _Capture()
        _mock_bundle(monkeypatch, capture, book_id=None, outline_text="有大纲防 query 过短")
        ctx = asyncio.run(assemble_stitch_context(
            "ch-1", "continue", fragment="他攥紧扳手", rolling_prefix="", db=None,
        ))
        # recall 收到空 book_id 兜底；样本检索被跳过（bundle.book_id 为空）
        assert capture.calls[0][1]["book_id"] == ""
        assert all(c[0] != "samples" for c in capture.calls)
        assert ctx.author_samples == []
        # style_card 为 None → 画像空串（零变化契约）
        assert ctx.style_positive == ""

    def test_scene_hint_from_rolling_prefix_tail(self, monkeypatch):
        """C2 接线：rolling_prefix 尾 300 字对话占比 >0.35 → scene_hint="dialogue"
        透传给样本检索（头 300 字纯叙述不影响判定——只看尾窗）。"""
        capture = _Capture()
        _mock_bundle(monkeypatch, capture, outline_text="大纲：对话场景。")
        head = "他沿着江岸走了很远，看着潮水一层一层地漫上来。" * 10   # 300+ 字纯叙述
        tail = "“走吧。”“再等等。”" * 40                              # 尾窗对话密集
        ctx = asyncio.run(assemble_stitch_context(
            "ch-1", "continue", fragment="他", rolling_prefix=head + tail, db=None,
        ))
        assert ctx.scene_hint == "dialogue"
        assert capture.sample_hints == ["dialogue"]

    def test_scene_hint_empty_prefix_general(self, monkeypatch):
        """C2 兜底：空 rolling_prefix（新章/预览 open 档常见）→ general。"""
        capture = _Capture()
        _mock_bundle(monkeypatch, capture, outline_text="大纲。")
        ctx = asyncio.run(assemble_stitch_context(
            "ch-1", "open", fragment="", rolling_prefix="", db=None,
        ))
        assert ctx.scene_hint == "general"
        assert capture.sample_hints == ["general"]


# ============================================================
# 4. 端点级（真实 SQLite 栈 + 真实装配管线）
# ============================================================

CHAPTER_HTML = "<p>林尘在灯下擦拭扳手。</p>" * 20  # 落库 HTML（编辑器 getHTML 形态）


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed(session) -> None:
    """一本书 + 一章（HTML 正文 + 叙事锚）+ 书级文风卡 + 2 条样本 + 1 个世界实体 + 出生事件。

    Book/Chapter 先落（flush）再加子表——SQLite FK 下同批混插偶发乱序
    （同 test_world_bridge_presence 的分层 flush 配方）。
    """
    session.add(m.Book(id=BOOK_ID, title="预览测试书"))
    session.add(m.Chapter(
        id=CH_ID, book_id=BOOK_ID, chapter_number=1,
        title="第一章", outline_text="林尘发现怀表的秘密。",
        content_text=CHAPTER_HTML, narrative_time=100,
    ))
    await session.flush()
    session.add(m.StyleCard(
        book_id=BOOK_ID, chapter_id=None,
        positive_profile={"sentence_rhythm": "短句为主，偶尔长句", "register": "冷峻"},
        dialogue_ratio_target=0.3,
    ))
    session.add_all([
        m.AuthorSample(book_id=BOOK_ID, content="他把扳手放回工具箱。灯芯结了花。", word_count=16),
        m.AuthorSample(book_id=BOOK_ID, content="风从窗缝里进来。他没有抬头。", word_count=14),
    ])
    session.add(m.WorldEntity(
        id=ENT_ID, book_id=BOOK_ID, entity_type="character",
        name="林尘", importance=8, props={},
    ))
    await session.flush()
    # 事件走 repo.create（sequence_num 由 repo 分配，直插会违反非空约束）
    from backend.repositories.world_repository import WorldRepository

    await WorldRepository(session).events.create(
        book_id=BOOK_ID, event_type="birth", time_start=5, time_end=5,
        participant_ids=[str(ENT_ID)], payload={}, note="林尘出生",
    )
    await session.commit()


def _disable_embedding(monkeypatch):
    """测试一律未配置 embedding（防本地 model_config 触发真实 HTTP 调用）。"""
    monkeypatch.setattr(retrieval_mod, "is_embedding_configured", lambda: False)
    monkeypatch.setattr(recall_mod, "is_embedding_configured", lambda: False)


def test_endpoint_preview_through_real_pipeline(tmp_path, monkeypatch):
    """种子书端到端：预览各块 == 基座+块拼接的 builder system prompt（真实管线同源）。"""
    _disable_embedding(monkeypatch)
    engine, maker = _make_stack(tmp_path, "preview.db")
    try:
        async def run():
            async with maker() as s:
                await _seed(s)
                resp = await context_preview(str(CH_ID), "continue", s)
                # 同一 session 再装配一次，喂 builder 对拍（预览 vs 真实注入）
                from backend.services.rag.memory_indexing import _html_to_plain
                ctx = await assemble_stitch_context(
                    str(CH_ID), "continue", fragment="",
                    rolling_prefix=_html_to_plain(CHAPTER_HTML)[-500:], db=s,
                )
                sys_prompt, _ = build_continue_prompt(
                    fragment="", rolling_prefix="", mode="continue",
                    proper_nouns=ctx.proper_nouns, canon_context=ctx.bundle.canon_context,
                    chapter_intent=ctx.chapter_intent, memory_echoes=ctx.memory_echoes,
                    style_positive=ctx.style_positive, author_samples=ctx.author_samples,
                    spatial_brief=ctx.bundle.spatial_brief,
                    previous_summary=ctx.kg.previous_summary,
                    recency_pin=ctx.kg.recency_pin,
                    **ctx._kg_kwargs(),
                )
                return resp, ctx, sys_prompt

        resp, ctx, sys_prompt = asyncio.run(run())
        block_text = "".join(c for _k, c in ctx.system_blocks())
        assert sys_prompt == _base_system() + block_text
        # 端点返回块与装配函数输出逐项一致
        # B6：种子书无场景钉=无在场集 → 实体块空、专名兜底位在（13 键全序）
        assert [b.key for b in resp.blocks] == BLOCK_ORDER
        assert [b.content for b in resp.blocks] == [c for _k, c in ctx.system_blocks()]
        assert [b.chars for b in resp.blocks] == [len(c) for _k, c in ctx.system_blocks()]
        assert resp.total_chars == sum(b.chars for b in resp.blocks)

        by_key = {b.key: b for b in resp.blocks}
        # 种子数据断言：画像/样本/专名/回响非空；canon/空间未配置 → 空块
        assert by_key["style_positive"].chars > 0
        assert by_key["author_samples"].chars > 0
        # B6：提及逐出前缀——种子书无在场集，实体块空；「林尘」改由专名兜底块携带
        assert "林尘" in by_key["proper_nouns"].content
        assert by_key["echoes"].chars > 0            # 世界事件结构化前情
        assert by_key["canon"].content == ""
        assert by_key["spatial"].content == ""
        # 世界字段：章锚 t=100、world 桥接生效
        assert resp.world_time == 100
        assert resp.world_time_source == "chapter_anchor"
        assert resp.world_sourced is True
        assert by_key["entities"].source == "知识平面 · 世界实体"  # v3.1：专名块被实体块取代
    finally:
        asyncio.run(engine.dispose())


def test_endpoint_empty_book_no_500(tmp_path, monkeypatch):
    """空设定书（章节不存在）：七块全空、不抛 500——「未配置」提示的入口流量。"""
    _disable_embedding(monkeypatch)
    engine, maker = _make_stack(tmp_path, "empty.db")
    try:
        async def run():
            async with maker() as s:
                return await context_preview("cc330000-0000-4000-8000-00000000dead", "continue", s)

        resp = asyncio.run(run())
        assert len(resp.blocks) == len(BLOCK_ORDER)
        assert all(b.content == "" and b.chars == 0 for b in resp.blocks)
        assert resp.total_chars == 0
        assert resp.world_sourced is False
        assert resp.world_time == 0
        assert resp.world_time_source == "zero"
    finally:
        asyncio.run(engine.dispose())


def test_endpoint_rejects_invalid_mode(tmp_path):
    engine, maker = _make_stack(tmp_path, "badmode.db")
    try:
        async def run():
            async with maker() as s:
                await context_preview(str(CH_ID), "fast", s)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run())
        assert exc_info.value.status_code == 422
    finally:
        asyncio.run(engine.dispose())


def test_endpoint_open_mode_query_from_outline(tmp_path, monkeypatch):
    """open 档预览：召回锚走大纲（同 stitch 口径），五档 mode 全部可跑通。"""
    _disable_embedding(monkeypatch)
    engine, maker = _make_stack(tmp_path, "modes.db")
    try:
        async def run():
            async with maker() as s:
                await _seed(s)
                return [
                    await context_preview(str(CH_ID), mode, s)
                    for mode in ("stitch", "continue", "burst", "outline", "open")
                ]

        resps = asyncio.run(run())
        assert all(r.mode in ("stitch", "continue", "burst", "outline", "open") for r in resps)
        # open 与其他档的检索锚不同 → 样本块可能不同；但专名/画像/canon 块与模式无关
        for r in resps:
            by_key = {b.key: b for b in r.blocks}
            assert "entities" in by_key  # B6：无在场者时实体块空（提及走后缀）
            assert by_key["style_positive"].chars > 0
    finally:
        asyncio.run(engine.dispose())
