# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 全局笔迹库（scope 维度）对拍：补位不抢位 + 零变化 + 卡层隔离
"""取代旧「B4 跨书黄金池冷启动兜底」对拍（2026-09 全局笔迹库重设计批）。

新语义（用户逐条拍板）：
1. 取用规则「补位不抢位」：检索时本书样本永远优先；本书样本在当前场景
   档位下不够 k 条时，才从 global 池按同样规则补位；
2. 新书零样本 → global 池是唯一来源（取代旧冷启动暗道）；
3. global 样本不参与 era 维度（era 是书级坐标系）；scene 匹配照常参与；
4. 零变化契约：global 池为空时，所有已有检索行为逐字节不变；
5. 存量门票迁移：favorite=1 或 source=golden_snippet → scope='global'；
   adopted_ghost 即便 favorite 也不升 global（AI 学 AI 不跨库扩散）；
6. **卡层隔离红线**：get_effective_card 零改动——旧书的画像/负面清单绝不
   出现在新书的生效卡（get_effective_card(B)=None、render_style_positive 空）。

运行：python -m pytest backend/services/style/test_cross_book_fallback.py -v
"""
import asyncio
import uuid

from sqlalchemy import select

import backend.models as m
from backend.database import _migrate_author_sample_scope
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.style_card_repository import StyleCardRepository
from backend.services.context.settings_bundle import render_style_positive
from backend.services.style.retrieval import retrieve_author_samples_with_meta

BOOK_A = uuid.UUID("dd450000-0000-4000-8000-00000000000a")   # 旧书（笔迹库供体）
BOOK_B = uuid.UUID("dd450000-0000-4000-8000-00000000000b")   # 新书（消费方）

_OLD_BAN_WORD = "旧书禁词庚辛壬"


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed_base(session):
    """两本书 + 旧书文风卡（隔离红线对照组）。"""
    session.add(m.Book(id=BOOK_A, title="旧书"))
    session.add(m.Book(id=BOOK_B, title="新书"))
    await session.flush()
    session.add(m.StyleCard(
        book_id=BOOK_A, chapter_id=None,
        positive_profile={"sentence_rhythm": "旧书画像：绵密抒情"},
        negative_list=[{"word": _OLD_BAN_WORD, "alternative": "", "severity": "warning"}],
    ))
    await session.commit()


def _run(coro):
    return asyncio.run(coro)


def test_fill_not_grab_scene_tier(tmp_path):
    """补位不抢位（场景档位）：本书 1 条 action + global 有 action/lyrical，
    action 场景 k=2 → 本书 action + global action，lyrical 不上桌；
    global 的 era=early 不参与排序（era 是书级坐标，scene 照常加分）。"""
    engine, maker = _make_stack(tmp_path, "scope_fill.db")

    async def run():
        async with maker() as session:
            await _seed_base(session)
            # 本书唯一样本：action
            session.add(m.AuthorSample(
                book_id=BOOK_B, content="本书动作：他拽住绳索往上攀。",
                scene_type="action", source="manual", scope="book",
            ))
            # global 池：action（era=early——era 应被忽略）+ lyrical（近期）
            session.add(m.AuthorSample(
                book_id=BOOK_A, content="旧书动作：铁门被撞开，碎片四溅。",
                scene_type="action", source="manual", scope="global",
                era="early",
            ))
            session.add(m.AuthorSample(
                book_id=BOOK_A, content="旧书抒情：晨光漫过木地板，像缓慢呼吸的海。",
                scene_type="lyrical", source="manual", scope="global",
            ))
            await session.commit()
            return await retrieve_author_samples_with_meta(
                session, str(BOOK_B), query_text="追逐戏", k=2, scene_hint="action",
            )

    pairs = _run(run())
    texts = [t for _sid, t in pairs]
    assert len(pairs) == 2
    assert "本书动作" in texts[0]                       # 本书样本绝对优先
    assert "旧书动作" in texts[1]                       # global 同型补位
    assert all("缓慢呼吸的海" not in t for t in texts)  # 异型 lyrical 不上桌

    engine.dispose()


def test_book_sufficient_global_off_table(tmp_path):
    """本书样本够 k 条 → global 完全不上桌（不抢位）。"""
    engine, maker = _make_stack(tmp_path, "scope_own.db")

    async def run():
        async with maker() as session:
            await _seed_base(session)
            session.add(m.AuthorSample(
                book_id=BOOK_B, content="本书样本一：他抬头看了看塔尖。",
                source="manual", scope="book",
            ))
            session.add(m.AuthorSample(
                book_id=BOOK_B, content="本书样本二：风从窗缝里进来。",
                source="manual", scope="book",
            ))
            session.add(m.AuthorSample(
                book_id=BOOK_A, content="旧书全局样本：海风把盐粒吹进灯罩。",
                source="golden_snippet", scope="global", favorite=True,
            ))
            await session.commit()
            return await retrieve_author_samples_with_meta(
                session, str(BOOK_B), query_text="塔尖的风", k=2,
            )

    pairs = _run(run())
    assert len(pairs) == 2
    assert all("旧书" not in t for _s, t in pairs)      # global 零上桌

    engine.dispose()


def test_new_book_zero_samples_global_only(tmp_path):
    """新书零样本 → global 池是唯一来源；scope=book 的别书样本不进。"""
    engine, maker = _make_stack(tmp_path, "scope_zero.db")

    async def run():
        async with maker() as session:
            await _seed_base(session)
            session.add(m.AuthorSample(
                book_id=BOOK_A, content="旧书全局样本：海风把盐粒吹进灯罩。",
                source="golden_snippet", scope="global",
            ))
            session.add(m.AuthorSample(
                book_id=BOOK_A, content="旧书普通手贴占位文本，不该跨书。",
                source="manual", scope="book",
            ))
            await session.commit()
            return await retrieve_author_samples_with_meta(
                session, str(BOOK_B), query_text="海边灯塔的风很大", k=2,
            )

    pairs = _run(run())
    assert len(pairs) == 1                               # 只有 global 一条
    assert "海风把盐粒" in pairs[0][1]
    assert all("不该跨书" not in t for _s, t in pairs)   # book 域别书样本排除

    engine.dispose()


def test_global_pool_empty_zero_change(tmp_path):
    """零变化契约：global 池为空（所有样本 scope=book）→ 检索只吃本书样本，
    次序与旧口径（favorite → era → 新近池序）逐一致；新书零样本开天窗 []。"""
    engine, maker = _make_stack(tmp_path, "scope_empty.db")

    async def run():
        async with maker() as session:
            await _seed_base(session)
            session.add(m.AuthorSample(
                book_id=BOOK_B, content="近期样本：他把扳手放回工具箱。",
                source="manual", scope="book",
            ))
            session.add(m.AuthorSample(
                book_id=BOOK_B, content="早期收藏样本：灯芯结了花。",
                source="manual", scope="book", era="early", favorite=True,
            ))
            # 别书样本全部 book 域——global 池为空
            session.add(m.AuthorSample(
                book_id=BOOK_A, content="旧书收藏片段：他把烟按灭在铁皮沿上。",
                source="manual", scope="book", favorite=True,
            ))
            await session.commit()
            own = await retrieve_author_samples_with_meta(
                session, str(BOOK_B), query_text="工具箱", k=2,
            )
            fresh = await retrieve_author_samples_with_meta(
                session, str(uuid.uuid4()), query_text="任何查询", k=2,
            )
            return own, fresh

    own, fresh = _run(run())
    # 旧口径：收藏优先（即便早期）→ 近期；别书样本零出现
    assert [t for _s, t in own] == ["早期收藏样本：灯芯结了花。", "近期样本：他把扳手放回工具箱。"]
    assert fresh == []                                   # 无 global 池 → 开天窗（与旧版一致）

    engine.dispose()


def test_legacy_ticket_migration(tmp_path):
    """存量门票迁移：favorite=1 或 golden_snippet → global；普通样本与
    adopted_ghost（即便 favorite）留在 book；迁移幂等（二跑零命中）。"""
    engine, maker = _make_stack(tmp_path, "scope_migrate.db")

    async def run():
        async with maker() as session:
            await _seed_base(session)
            rows = [
                m.AuthorSample(book_id=BOOK_A, content="收藏手贴",
                               source="manual", favorite=True),
                m.AuthorSample(book_id=BOOK_A, content="黄金片段",
                               source="golden_snippet"),
                m.AuthorSample(book_id=BOOK_A, content="普通手贴",
                               source="manual"),
                m.AuthorSample(book_id=BOOK_A, content="AI采纳片段",
                               source="adopted_ghost", favorite=True),
            ]
            session.add_all(rows)
            await session.commit()
            # 模拟存量库形态：列迁移（ALTER ADD COLUMN，无 DEFAULT）补出的
            # scope 列为 NULL——ORM 侧 Python 默认只在 insert 时生效，直接
            # 构造插不出 NULL，用裸 SQL 回置（等价于「列刚补上」的瞬间）
            from sqlalchemy import text
            await session.execute(text("UPDATE author_samples SET scope = NULL"))
            await session.commit()

            await _migrate_author_sample_scope(session)
            session.expire_all()
            by_content = {
                s.content: s.scope
                for s in (await session.execute(select(m.AuthorSample))).scalars().all()
            }
            # 幂等：二跑不改任何值
            await _migrate_author_sample_scope(session)
            session.expire_all()
            by_content_2 = {
                s.content: s.scope
                for s in (await session.execute(select(m.AuthorSample))).scalars().all()
            }
            return by_content, by_content_2

    by_content, by_content_2 = _run(run())
    assert by_content["收藏手贴"] == "global"
    assert by_content["黄金片段"] == "global"
    assert by_content["普通手贴"] == "book"
    assert by_content["AI采纳片段"] == "book"            # AI 学 AI 不跨库扩散
    assert by_content == by_content_2                    # 幂等

    engine.dispose()


def test_card_layer_stays_book_isolated(tmp_path):
    """卡层隔离红线：global 补位只发生在样本检索层——新书的生效卡仍为 None
    （画像空串、旧书负面清单不出现在新书任何面）。文风卡/负面清单维持书级隔离。"""
    engine, maker = _make_stack(tmp_path, "scope_card.db")

    async def run():
        async with maker() as session:
            await _seed_base(session)
            session.add(m.AuthorSample(
                book_id=BOOK_A, content="旧书全局样本：海风把盐粒吹进灯罩。",
                source="golden_snippet", scope="global",
            ))
            await session.commit()
            card_b = await StyleCardRepository(session).get_effective_card(str(BOOK_B))
            card_a = await StyleCardRepository(session).get_effective_card(str(BOOK_A))
            return card_b, card_a

    card_b, card_a = _run(run())
    assert card_b is None                                     # 新书无卡（不合成幽灵卡）
    assert render_style_positive(card_b) == ""                # 画像零泄漏
    assert render_style_positive(card_a).startswith("- 句长节奏")  # 对照组：A 卡健在
    assert any(item.get("word") == _OLD_BAN_WORD for item in (card_a.negative_list or []))

    engine.dispose()
