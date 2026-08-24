# Velluma - 章级文风特例卡消费接通（Phase 4）单测
# AGPL-3.0
"""章级 StyleCard 整卡覆盖语义单测。

语义定档（2026-08-24 拍板）：章级特例卡存在 → 该章完整文风定义（负面清单
/正面画像/旋钮/对话目标/段落节奏整卡生效，书级不再参与）；不存在 → 回退书级
卡 → 无卡 → 零变化。统一入口 StyleCardRepository.get_effective_card。

覆盖两层：
1. repository 三态：章级优先 / 回退书级 / 双无 None（+ chapter_id=None 直取书级）。
2. bundle 真实栈：书级+章级并存 → bundle.style_card 为章级（画像渲染与
   prohibitions 负面清单同步换源）；仅书级 → 回退（Phase 4 前行为显式锁定）；
   无卡 → style_card=None、style_positive=""（零变化契约）。

配方：临时文件 SQLite + 真实 repo 栈（同 test_stitch_context.py）；每个异步
场景独立 asyncio.run 事件循环（AGENTS.md 测试节防污染约定）；UUID 带字母。

运行：python -m pytest backend/services/context/test_chapter_style_override.py -v
"""

import asyncio
import uuid

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories import StyleCardRepository
from backend.services.context.settings_bundle import (
    load_chapter_settings_bundle,
    render_style_positive,
)

BOOK_ID = uuid.UUID("dd440000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("dd440000-0000-4000-8000-0000000000b1")

# 书级与章级卡用互斥标记词，断言谁的生效一目了然
# （BOOK_BAN_WORD 必须避开系统陈词库种子——「眼底闪过」之类真实禁忌词
# 在层① SystemCliche 恒在，与卡来源无关，不能用来区分卡覆盖）
BOOK_PROFILE_TEXT = "书级画像：绵密抒情"
CHAPTER_PROFILE_TEXT = "章级画像：冷峻短句"
BOOK_BAN_WORD = "书级禁词甲乙丙"
CHAPTER_BAN_WORD = "章级禁词丁戊己"


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed_book_chapter(session) -> None:
    """一本书 + 一章（Book/Chapter 先 flush 再加子表——SQLite FK 分层配方）。"""
    session.add(m.Book(id=BOOK_ID, title="章级特例测试书"))
    session.add(m.Chapter(
        id=CH_ID, book_id=BOOK_ID, chapter_number=1,
        title="第一章", outline_text="林尘回到旧灯塔。",
    ))
    await session.flush()


def _book_card(**overrides):
    fields = dict(
        book_id=BOOK_ID, chapter_id=None,
        positive_profile={"sentence_rhythm": BOOK_PROFILE_TEXT},
        negative_list=[{"word": BOOK_BAN_WORD, "alternative": "", "severity": "warning"}],
        dialogue_ratio_target=0.3,
    )
    fields.update(overrides)
    return m.StyleCard(**fields)


def _chapter_card(**overrides):
    fields = dict(
        book_id=BOOK_ID, chapter_id=CH_ID,
        positive_profile={"sentence_rhythm": CHAPTER_PROFILE_TEXT},
        negative_list=[{"word": CHAPTER_BAN_WORD, "alternative": "笑了笑", "severity": "blocker"}],
        dialogue_ratio_target=0.6,
    )
    fields.update(overrides)
    return m.StyleCard(**fields)


# ============================================================
# 1. repository 层：get_effective_card 三态
# ============================================================

class TestGetEffectiveCard:
    def test_chapter_override_wins(self, tmp_path):
        """书级+章级并存 → 章级卡生效。"""
        engine, maker = _make_stack(tmp_path, "repo_win.db")
        try:
            async def run():
                async with maker() as s:
                    await _seed_book_chapter(s)
                    s.add(_book_card())
                    s.add(_chapter_card())
                    await s.commit()
                    return await StyleCardRepository(s).get_effective_card(BOOK_ID, CH_ID)

            card = asyncio.run(run())
            assert card is not None
            assert str(card.chapter_id) == str(CH_ID)
            assert card.positive_profile["sentence_rhythm"] == CHAPTER_PROFILE_TEXT
        finally:
            asyncio.run(engine.dispose())

    def test_fallback_to_book_card(self, tmp_path):
        """无章级覆盖 → 回退书级卡。"""
        engine, maker = _make_stack(tmp_path, "repo_fallback.db")
        try:
            async def run():
                async with maker() as s:
                    await _seed_book_chapter(s)
                    s.add(_book_card())
                    await s.commit()
                    return await StyleCardRepository(s).get_effective_card(BOOK_ID, CH_ID)

            card = asyncio.run(run())
            assert card is not None
            assert card.chapter_id is None
            assert card.positive_profile["sentence_rhythm"] == BOOK_PROFILE_TEXT
        finally:
            asyncio.run(engine.dispose())

    def test_none_when_no_cards(self, tmp_path):
        engine, maker = _make_stack(tmp_path, "repo_none.db")
        try:
            async def run():
                async with maker() as s:
                    await _seed_book_chapter(s)
                    await s.commit()
                    return await StyleCardRepository(s).get_effective_card(BOOK_ID, CH_ID)

            assert asyncio.run(run()) is None
        finally:
            asyncio.run(engine.dispose())

    def test_none_chapter_id_returns_book_card(self, tmp_path):
        """chapter_id=None（书级调用方）→ 直取书级卡，不碰章级。"""
        engine, maker = _make_stack(tmp_path, "repo_bookonly.db")
        try:
            async def run():
                async with maker() as s:
                    await _seed_book_chapter(s)
                    s.add(_book_card())
                    s.add(_chapter_card())
                    await s.commit()
                    return await StyleCardRepository(s).get_effective_card(BOOK_ID, None)

            card = asyncio.run(run())
            assert card is not None and card.chapter_id is None
        finally:
            asyncio.run(engine.dispose())


# ============================================================
# 2. bundle 真实栈：整卡覆盖 / 回退 / 零变化
# ============================================================

class TestBundleChapterOverride:
    def test_bundle_uses_chapter_card(self, tmp_path):
        """并存时 bundle.style_card 为章级卡：画像渲染与禁忌面同步换源。"""
        engine, maker = _make_stack(tmp_path, "bundle_win.db")
        try:
            async def run():
                async with maker() as s:
                    await _seed_book_chapter(s)
                    s.add(_book_card())
                    s.add(_chapter_card())
                    await s.commit()
                    return await load_chapter_settings_bundle(str(CH_ID), s)

            bundle = asyncio.run(run())
            assert bundle.style_card is not None
            assert str(bundle.style_card.chapter_id) == str(CH_ID)

            positive = render_style_positive(bundle.style_card)
            assert CHAPTER_PROFILE_TEXT in positive
            assert BOOK_PROFILE_TEXT not in positive
            # to_prompt_context 暴露键同步走章级
            assert CHAPTER_PROFILE_TEXT in bundle.to_prompt_context()["style_positive"]
            # 对话目标整卡覆盖（章级 0.6，非书级 0.3）
            assert "60%" in positive

            ps = bundle.prohibitions
            assert ps is not None
            # 章级负面清单生效（severity 透传 blocker）
            hits = [(m_.group(0), e.severity) for m_, e in ps.finditer(f"他{CHAPTER_BAN_WORD}了一下。")]
            assert hits == [(CHAPTER_BAN_WORD, "blocker")]
            # 整卡覆盖：书级负面清单不参与本章
            assert not list(ps.finditer(f"她{BOOK_BAN_WORD}。"))
        finally:
            asyncio.run(engine.dispose())

    def test_bundle_falls_back_to_book_card(self, tmp_path):
        """仅书级卡 → 回退语义锁定（与 Phase 4 前行为一致）。"""
        engine, maker = _make_stack(tmp_path, "bundle_fallback.db")
        try:
            async def run():
                async with maker() as s:
                    await _seed_book_chapter(s)
                    s.add(_book_card())
                    await s.commit()
                    return await load_chapter_settings_bundle(str(CH_ID), s)

            bundle = asyncio.run(run())
            assert bundle.style_card is not None
            assert bundle.style_card.chapter_id is None
            positive = render_style_positive(bundle.style_card)
            assert BOOK_PROFILE_TEXT in positive
            assert "30%" in positive
            assert bundle.prohibitions is not None
            assert list(bundle.prohibitions.finditer(f"她{BOOK_BAN_WORD}。"))
        finally:
            asyncio.run(engine.dispose())

    def test_bundle_no_card_zero_change(self, tmp_path):
        """无任何卡 → style_card=None、style_positive=""（零变化契约）。"""
        engine, maker = _make_stack(tmp_path, "bundle_none.db")
        try:
            async def run():
                async with maker() as s:
                    await _seed_book_chapter(s)
                    await s.commit()
                    return await load_chapter_settings_bundle(str(CH_ID), s)

            bundle = asyncio.run(run())
            assert bundle.style_card is None
            assert render_style_positive(bundle.style_card) == ""
            assert bundle.to_prompt_context()["style_positive"] == ""
        finally:
            asyncio.run(engine.dispose())
