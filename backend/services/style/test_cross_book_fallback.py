# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - B4 跨书文风冷启动兜底对拍（2026-09-13 深水区批）
"""检索层样本兜底 + 卡层隔离红线（docs 红队报告 Q5 拍板口径）：

1. 本书零样本（新书第一章）→ 兜底流第三级吃到其它书 favorite/golden 样本；
2. adopted_ghost 一律不进跨书池（AI 学 AI 不跨书传播——即便标了 favorite）；
3. manual/published_chapter 未认证样本不跨书（题材未过滤，只吃认证好样本）；
4. 本书有自己的样本 → 绝不跨书；
5. **卡层隔离红线**：get_effective_card 零改动——旧书的画像/负面清单绝不
   出现在新书的生效卡（get_effective_card(B)=None、render_style_positive 空）。

运行：python -m pytest backend/services/style/test_cross_book_fallback.py -v
"""
import asyncio
import uuid

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.style_card_repository import StyleCardRepository
from backend.services.context.settings_bundle import render_style_positive
from backend.services.style.retrieval import retrieve_author_samples_with_meta

BOOK_A = uuid.UUID("dd450000-0000-4000-8000-00000000000a")   # 旧书（黄金池）
BOOK_B = uuid.UUID("dd450000-0000-4000-8000-00000000000b")   # 新书（零样本）

_OLD_BAN_WORD = "旧书禁词庚辛壬"


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed_books(session, *, with_b_sample=False):
    session.add(m.Book(id=BOOK_A, title="旧书"))
    session.add(m.Book(id=BOOK_B, title="新书"))
    await session.flush()
    # 旧书四类样本：golden / manual+favorite / manual 普通 / adopted（favorite 也排除）
    session.add(m.AuthorSample(
        book_id=BOOK_A, content="旧书黄金片段：海风把盐粒吹进灯罩。",
        source="golden_snippet", favorite=False,
    ))
    session.add(m.AuthorSample(
        book_id=BOOK_A, content="旧书收藏片段：他把烟按灭在铁皮沿上。",
        source="manual", favorite=True,
    ))
    session.add(m.AuthorSample(
        book_id=BOOK_A, content="旧书普通手贴占位文本，不该跨书。",
        source="manual", favorite=False,
    ))
    session.add(m.AuthorSample(
        book_id=BOOK_A, content="旧书AI采纳片段：机甲转动关节。",
        source="adopted_ghost", favorite=True,
    ))
    # 旧书文风卡（画像+负面清单——隔离红线的对照组）
    session.add(m.StyleCard(
        book_id=BOOK_A, chapter_id=None,
        positive_profile={"sentence_rhythm": "旧书画像：绵密抒情"},
        negative_list=[{"word": _OLD_BAN_WORD, "alternative": "", "severity": "warning"}],
    ))
    if with_b_sample:
        session.add(m.AuthorSample(
            book_id=BOOK_B, content="新书自己的样本：他抬头看了看塔尖。",
            source="manual", favorite=False,
        ))
    await session.commit()


def test_new_book_gets_cross_book_golden(tmp_path):
    """新书零样本 → few-shot 吃到旧书 favorite/golden；adopted/普通手贴不进。"""
    engine, maker = _make_stack(tmp_path, "cross_golden.db")

    async def run():
        async with maker() as session:
            await _seed_books(session)
            pairs = await retrieve_author_samples_with_meta(
                session, str(BOOK_B), query_text="海边灯塔的风很大", k=2,
            )
        return pairs

    pairs = asyncio.run(run())
    assert len(pairs) == 2                                   # 冷启动不再开天窗
    texts = [t for _sid, t in pairs]
    assert any("海风把盐粒" in t or "烟按灭" in t for t in texts)
    assert all("机甲" not in t for t in texts)               # adopted_ghost 排除
    assert all("不该跨书" not in t for t in texts)           # 未认证 manual 排除

    engine.dispose()


def test_own_samples_prevent_cross_leak(tmp_path):
    """本书有自己的样本 → 只吃本书的，绝不跨书。"""
    engine, maker = _make_stack(tmp_path, "cross_own.db")

    async def run():
        async with maker() as session:
            await _seed_books(session, with_b_sample=True)
            return await retrieve_author_samples_with_meta(
                session, str(BOOK_B), query_text="他抬头看了看塔尖的风", k=2,
            )

    pairs = asyncio.run(run())
    assert len(pairs) == 1
    assert "塔尖" in pairs[0][1]                              # 新书自己的样本
    assert all("旧书" not in t for _s, t in pairs)

    engine.dispose()


def test_card_layer_stays_book_isolated(tmp_path):
    """卡层隔离红线：跨书兜底只发生在样本检索层——新书的生效卡仍为 None
    （画像空串、旧书负面清单不出现在新书任何面）。"""
    engine, maker = _make_stack(tmp_path, "cross_card.db")

    async def run():
        async with maker() as session:
            await _seed_books(session)
            card_b = await StyleCardRepository(session).get_effective_card(str(BOOK_B))
            card_a = await StyleCardRepository(session).get_effective_card(str(BOOK_A))
            return card_b, card_a

    card_b, card_a = asyncio.run(run())
    assert card_b is None                                     # 新书无卡（不合成幽灵卡）
    assert render_style_positive(card_b) == ""                # 画像零泄漏
    assert render_style_positive(card_a).startswith("- 句长节奏")  # 对照组：A 卡健在
    assert any(item.get("word") == _OLD_BAN_WORD for item in (card_a.negative_list or []))

    engine.dispose()
