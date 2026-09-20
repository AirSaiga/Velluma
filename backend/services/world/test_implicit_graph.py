# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""implicit_graph 单测（docs/reports/implicit-graph-projection-feasibility.md §5 红队四问的机械化）。

覆盖六组契约 + 修订链读侧过滤（repo 级真实 SQLite 栈）：
1. 时态单调：未来事件绝不入图；superseded 事件绝不入图（纯函数层）。
2. 超边防爆：10 人 battle 只产 1 张卡，节点线性增长。
3. 2 跳过滤：普通 custom 不外扩；MAJOR 类型或近 90 天窗才外扩。
4. 上限截断：卡片配额（per_root_cards×根数）与 node_cap 严格生效。
5. 格式化器：空切片空串（零变化契约）；有卡格式合规（含时刻换算对拍）。
6. 性能基准：500 事件 / 100 实体 × 100 次均值 < 2.0ms。
7. repo.list_all_by_book 排除 superseded（真实栈）。

运行：python -m pytest backend/services/world/test_implicit_graph.py -v
"""
import asyncio
import random
import time
import uuid
from types import SimpleNamespace as NS

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.world_repository import WorldRepository
from backend.services.world.implicit_graph import (
    MAJOR_TYPES,
    format_subgraph_for_prompt,
    project_active_subgraph,
)

BOOK_ID = uuid.UUID("dd440000-0000-4000-8000-0000000000b1")


def _ev(i, etype, t, parts=(), payload=None, note="", title="", supersedes=None, seq=None, factions=()):
    """鸭子类型事件桩（project_active_subgraph 只读十个属性，零 ORM 依赖）。"""
    return NS(
        id=f"ev-{i}", event_type=etype, time_start=t, time_end=t,
        sequence_num=seq if seq is not None else i,
        participant_ids=list(parts), faction_ids=list(factions),
        payload=payload or {}, note=note, title=title,
        location_id=None, supersedes=supersedes,
    )


def _ent(name):
    return NS(name=name)


def _ents(*names):
    return {f"e-{n}": _ent(n) for n in names}


# ============================================================
# 1. 时态单调性 + superseded 排除（纯函数层双保险）
# ============================================================

class TestTemporalMonotonicity:
    def test_future_events_excluded(self):
        ents = _ents("林尘", "明姐")
        events = [
            _ev(1, "battle", 800, parts=["e-林尘", "e-明姐"], note="已发生"),
            _ev(2, "battle", 950, parts=["e-林尘", "e-明姐"], note="未来"),
        ]
        s = project_active_subgraph(events, ents, ["e-林尘"], t=900)
        assert len(s.cards) == 1
        assert s.cards[0].note_excerpt == "已发生"
        # 边界：恰在 t 的事件入图（<= 闭区间）
        events.append(_ev(3, "death", 900, parts=["e-明姐"], note="恰在t"))
        s2 = project_active_subgraph(events, ents, ["e-林尘"], t=900)
        assert any(c.event_id == "ev-3" for c in s2.cards)

    def test_superseded_events_excluded(self):
        ents = _ents("林尘", "老张")
        old = _ev(1, "battle", 100, parts=["e-林尘", "e-老张"], note="旧版本战斗")
        new = _ev(2, "battle", 150, parts=["e-林尘", "e-老张"], note="修订版战斗", supersedes="ev-1")
        s = project_active_subgraph([old, new], ents, ["e-林尘"], t=900)
        ids = [c.event_id for c in s.cards]
        assert "ev-1" not in ids and "ev-2" in ids
        assert s.cards[0].note_excerpt == "修订版战斗"

    def test_empty_roots_empty_slice(self):
        s = project_active_subgraph([_ev(1, "battle", 10, parts=["a"])], {}, [], t=100)
        assert s.cards == [] and s.nodes == [] and s.roots == []


# ============================================================
# 2. 超边防爆（10 人 battle = 1 张卡，节点线性）
# ============================================================

class TestHyperedgeNoExplosion:
    def test_ten_way_battle_one_card_linear_nodes(self):
        ten = [f"p{i:02d}" for i in range(10)]
        ents = {f"p{i:02d}": _ent(f"角色{i}") for i in range(10)}
        events = [_ev(1, "battle", 800, parts=ten, note="十方混战")]
        s = project_active_subgraph(events, ents, ["p00"], t=900)
        assert len(s.cards) == 1, "多参与者事件必须只产一张超边卡"
        assert len(s.cards[0].participant_ids) == 10
        # 节点 = 1 根 + 9 共现邻 = 10（线性），绝无 45 条点对派生物
        assert len(s.nodes) == 10
        assert {n.hop for n in s.nodes} == {0, 1}

    def test_why_strings_are_human_readable(self):
        ents = _ents("林尘", "明姐")
        events = [_ev(1, "battle", 800, parts=["e-林尘", "e-明姐"], note="突袭")]
        s = project_active_subgraph(events, ents, ["e-林尘"], t=900)
        node = next(n for n in s.nodes if n.entity_id == "e-明姐")
        assert "林尘" in node.why and "战役" in node.why and "第800天" in node.why


# ============================================================
# 3. 2 跳过滤（custom 不外扩；MAJOR ∪ 近窗才外扩）
# ============================================================

class TestSecondHopFilter:
    def _base(self):
        # 根 r 与 m1 在 t=800 共历 battle（major）→ m1 是 1 跳
        return [_ev(1, "battle", 800, parts=["e-r", "e-m1"], note="共历")]

    def test_old_custom_no_second_hop(self):
        ents = _ents("r", "m1", "x")
        events = self._base() + [
            _ev(2, "custom", 100, parts=["e-m1", "e-x"], note="远古杂事"),
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900)
        ids = {n.entity_id for n in s.nodes}
        assert "e-x" not in ids, "普通 custom 且超 90 天窗：不得外扩"

    def test_major_type_second_hop_regardless_of_age(self):
        ents = _ents("r", "m1", "y")
        events = self._base() + [
            _ev(2, "death", 100, parts=["e-m1", "e-y"], note="远古死亡"),
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900)
        ids = {n.entity_id for n in s.nodes}
        assert "e-y" in ids, "MAJOR 类型无视窗龄外扩"
        y = next(n for n in s.nodes if n.entity_id == "e-y")
        assert y.hop == 2

    def test_recent_nonmajor_second_hop_within_window(self):
        ents = _ents("r", "m1", "z")
        events = self._base() + [
            _ev(2, "move", 895, parts=["e-m1", "e-z"], payload={"character_ids": ["e-m1", "e-z"]}),
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900)
        ids = {n.entity_id for n in s.nodes}
        assert "e-z" in ids, "非重大但落在近 90 天窗：允许外扩"

    def test_second_hop_card_cap(self):
        # 两个 1 跳成员各带一张 major 卡；帽 second_hop_cards_cap=2 时取最近
        # 两张（各自成员最新），m1 的第二张旧卡被「每成员一卡」规则压掉
        ents = _ents("r", "m1", "m2")
        events = [
            _ev(1, "battle", 801, parts=["e-r", "e-m1"], note="共历一"),
            _ev(2, "battle", 800, parts=["e-r", "e-m2"], note="共历二"),
            _ev(3, "death", 706, parts=["e-m1", "e-d5"]),
            _ev(4, "death", 705, parts=["e-m2", "e-d4"]),
            _ev(5, "death", 704, parts=["e-m1", "e-d3"]),
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900, second_hop_cards_cap=2)
        hop2 = {n.entity_id for n in s.nodes if n.hop == 2}
        assert hop2 == {"e-d5", "e-d4"}, "帽取最近两张，d3 被每成员一卡规则压掉"
        assert len(s.cards) == 4  # 2 张 1 跳 + 2 张 2 跳

    def test_per_member_one_card(self):
        # m1 已带过一张 2 跳卡后，再遇含 m1 的旧 major 不重复带卡
        ents = _ents("r", "m1", "a", "b")
        events = self._base() + [
            _ev(2, "death", 500, parts=["e-m1", "e-a"]),
            _ev(3, "death", 400, parts=["e-m1", "e-b"]),
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900)
        assert len([c for c in s.cards if c.event_id in ("ev-2", "ev-3")]) == 1


# ============================================================
# 4. 上限截断（卡片配额 + node_cap）
# ============================================================

class TestCaps:
    def test_card_quota_per_root(self):
        ents = {"e-r": _ent("r")}
        events = [
            _ev(i, "battle", 100 + i, parts=["e-r", f"e-p{i}"]) for i in range(1, 101)
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900)  # 默认 per_root_cards=6
        assert len(s.cards) == 6, "1 跳卡帽 = per_root_cards × 根数"
        # 取最近 6 张（t 最大者）
        assert {c.event_id for c in s.cards} == {f"ev-{i}" for i in range(95, 101)}

    def test_node_cap_truncation(self):
        ents = {"e-r": _ent("r")}
        events = [
            _ev(i, "battle", 100 + i, parts=["e-r", f"e-p{i}"]) for i in range(1, 61)
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900,
                                    per_root_cards=50, node_cap=40)
        assert len(s.cards) == 50
        assert len(s.nodes) == 40, "全局节点帽严格截断"
        assert s.nodes[0].hop == 0 and s.nodes[0].entity_id == "e-r", "根恒居首不被截掉"


# ============================================================
# 5. 格式化器
# ============================================================

class TestFormatter:
    def test_empty_slice_empty_string(self):
        assert format_subgraph_for_prompt(project_active_subgraph([], {}, ["x"], t=1)) == ""
        s = project_active_subgraph([_ev(1, "battle", 999, parts=["a", "b"])], {}, ["c"], t=1)
        assert s.cards == [] and format_subgraph_for_prompt(s) == ""

    def test_format_contract(self):
        ents = _ents("林尘", "明姐")
        events = [
            _ev(1, "battle", 800, parts=["e-林尘", "e-明姐"], note="突袭统合局基地，意欲摧毁能源库"),
            _ev(2, "move", 700, parts=["e-林尘"], note="被击落后坠落村子"),
        ]
        s = project_active_subgraph(events, ents, ["e-林尘"], t=900)
        text = format_subgraph_for_prompt(s, ents)
        assert text.startswith("# 在场近史与因果（仅限在场者参与的历史事实）")
        lines = text.split("\n")[1:]
        assert len(lines) == 2
        # 时间倒序：t=800 在前
        assert lines[0].index("突袭") < lines[1].index("坠落")
        # 时刻换算对拍前端 timeFormat（365/30、创世元年）：t=800 → 第3年3月11日
        assert "[第3年3月11日·战役]" in lines[0]
        assert "突袭统合局基地" in lines[0]

    def test_note_missing_falls_back_to_names(self):
        ents = _ents("林尘", "明姐")
        events = [_ev(1, "alliance", 800, parts=["e-林尘", "e-明姐"], note="")]
        s = project_active_subgraph(events, ents, ["e-林尘"], t=900)
        text = format_subgraph_for_prompt(s, ents)
        # 参与者按 id 排序输出（确定性契约——卡内 participant_ids 恒为 sorted）
        assert "涉及：明姐、林尘" in text

    def test_title_fallback_chain(self):
        # 自拟 title 优先；空回退类型标签（与前端 eventDisplayName 同口径）
        events = [_ev(1, "battle", 800, parts=["a", "b"], note="x", title="夜袭")]
        s = project_active_subgraph(events, {"a": _ent("a")}, ["a"], t=900)
        assert s.cards[0].title == "夜袭"
        events2 = [_ev(1, "custom", 800, parts=["a", "b"], note="x")]
        s2 = project_active_subgraph(events2, {"a": _ent("a")}, ["a"], t=900)
        assert s2.cards[0].title == "自定义"

    def test_cards_sorted_desc_after_hop_merge(self):
        ents = _ents("r", "m1", "y")
        events = [
            _ev(1, "battle", 800, parts=["e-r", "e-m1"]),   # 1 跳（新）
            _ev(2, "death", 100, parts=["e-m1", "e-y"]),    # 2 跳 major（旧）
        ]
        s = project_active_subgraph(events, ents, ["e-r"], t=900)
        times = [c.time_start for c in s.cards]
        assert times == sorted(times, reverse=True), "合并后统一按时间倒序"


# ============================================================
# 6. 性能基准（500 事件 / 100 实体 × 100 次均值 < 2.0ms）
# ============================================================

class TestPerformance:
    def test_projection_under_2ms(self):
        random.seed(7)
        ent_ids = [f"e{i:03d}" for i in range(100)]
        ents = {i: _ent(f"实体{i}") for i in ent_ids}
        events = []
        for i in range(500):
            et = random.choices(
                ["move", "battle", "death", "custom", "territory_change", "birth"],
                weights=[40, 25, 5, 15, 5, 10])[0]
            parts = random.sample(ent_ids, random.randint(1, 4))
            if et == "move":
                payload = {"character_ids": parts}
            elif et in ("death", "birth"):
                payload = {"character_id": parts[0]}
                parts = []
            else:
                payload = {}
            events.append(_ev(i, et, random.randint(1, 900), parts=parts,
                              payload=payload, note="占位事件描述"))
        roots = ["e000", "e007", "e013"]
        project_active_subgraph(events, ents, roots, 900)  # 预热（排序缓存等）
        n = 100
        t0 = time.perf_counter()
        for _ in range(n):
            project_active_subgraph(events, ents, roots, 900)
        dt_ms = (time.perf_counter() - t0) / n * 1000
        assert dt_ms < 2.0, f"单次投影均值 {dt_ms:.3f}ms 超 2ms 预算"


# ============================================================
# 7. repo 读侧 supersedes 过滤（真实 SQLite 栈）
# ============================================================

class TestRepoSupersedesFilter:
    def test_list_all_by_book_excludes_superseded(self, tmp_path):
        engine = build_sqlite_engine(tmp_path / "supersedes.db")
        maker = build_sqlite_sessionmaker(engine)
        asyncio.run(init_db_sqlite(engine, maker))
        try:
            async def run():
                async with maker() as s:
                    s.add(m.Book(id=BOOK_ID, title="修订链测试书"))
                    await s.flush()
                    repo = WorldRepository(s)
                    old = await repo.events.create(
                        book_id=BOOK_ID, event_type="battle",
                        time_start=100, time_end=100,
                        participant_ids=["p1", "p2"], payload={}, note="旧代",
                    )
                    await repo.events.create(
                        book_id=BOOK_ID, event_type="battle",
                        time_start=150, time_end=150,
                        participant_ids=["p1", "p2"], payload={}, note="新代",
                        supersedes=old.id,
                    )
                    await s.commit()
                    listed = await repo.events.list_all_by_book(str(BOOK_ID))
                    return [(e.note, e.id) for e in listed]

            rows = asyncio.run(run())
            assert len(rows) == 1 and rows[0][0] == "新代", "链头在列、旧代被排除"

            async def run2():
                async with maker() as s:
                    # 零 supersedes 书 = 行为不变（另一本书直查）
                    s.add(m.Book(id=uuid.UUID("dd440000-0000-4000-8000-0000000000b2"), title="无修订书"))
                    await s.flush()
                    repo = WorldRepository(s)
                    await repo.events.create(
                        book_id=uuid.UUID("dd440000-0000-4000-8000-0000000000b2"),
                        event_type="custom", time_start=1, time_end=1,
                        participant_ids=[], payload={}, note="独苗",
                    )
                    await s.commit()
                    return len(await repo.events.list_all_by_book(
                        str(uuid.UUID("dd440000-0000-4000-8000-0000000000b2"))))

            assert asyncio.run(run2()) == 1
        finally:
            asyncio.run(engine.dispose())
