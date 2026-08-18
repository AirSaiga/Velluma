# Velluma - C2 canon 换源契约单测
# AGPL-3.0
"""
C2 往返契约测试（docs/canon-world-fusion.md §6 护栏）。

锁定：build_canon_context_for_prompt 换源（ref 挂接 label 推演 + [hook] 装配源
切 plot_ledgers）后，三段输出格式**逐字节不变**——段标记 / 行格式 / 截断长度，
且喂回 settings_bundle 的 hard_constraints 解析器能取到同样的 labels/facts
（防改源时顺手改了段标记——下游 canon_checks/CanonHighlight 强耦合此格式）。

用 db_sqlite 的真实 ORM 栈种数据（与 test_db_sqlite.py 同 _make_stack 模式），
不 mock 查询。
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.db_sqlite.type_compat import register_sqlite_type_compat  # noqa: F401（方言编译副作用注册）

register_sqlite_type_compat()

import backend.models as m
from backend.services.canon.consistency import build_canon_context_for_prompt
from backend.services.context.settings_bundle import (
    _extract_canon_private_labels,
    _extract_canon_public_facts,
)


def _make_stack(tmp_path):
    engine = build_sqlite_engine(tmp_path / "canon_contract.db")
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _seed(maker):
    """一本书：实体 overlay（ref 挂接）+ 自由 private 节点 + public 节点 +
    账本伏笔（真相面）+ 未迁移存量 canon hook。"""
    book_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    loc_id = uuid.uuid4()

    async def run():
        async with maker() as s:
            s.add(m.Book(id=book_id, title="契约书"))
            s.add(m.WorldEntity(id=entity_id, book_id=book_id, name="兰星", entity_type="character"))
            s.add(m.WorldLocation(id=loc_id, book_id=book_id, name="北岸要塞"))
            # 实体 overlay：label 故意写旧名（迁移期快照）——读取时应被世界名覆盖
            s.add(m.CanonNode(
                book_id=book_id, type="character", label="旧名字（漂移前）",
                canon_text="兰星与老人是失散祖孙", public_text="",
                visibility="private", ref_type="entity", ref_id=entity_id,
                reveal_plan="第 45 章相认",
            ))
            # 地点 overlay（public）
            s.add(m.CanonNode(
                book_id=book_id, type="place", label="旧地名",
                canon_text="", public_text="北岸要塞是帝国最北的军镇",
                visibility="public", ref_type="location", ref_id=loc_id,
            ))
            # 自由 private 节点（无 ref，label 原样）
            s.add(m.CanonNode(
                book_id=book_id, type="event", label="信件伪造者",
                canon_text="伪造信件的是兰星的养父", visibility="private",
            ))
            # 账本伏笔（C2 换源后的 [hook] 主数据）
            s.add(m.PlotLedger(
                book_id=book_id, ledger_key="针脚歪斜暗示身世", content="针脚歪斜",
                status="open", canon_text="针脚歪斜暗示兰星身世", meta={"strength": "强"},
            ))
            # 未迁移存量 canon hook（无 ref_id + status=open → 兜底路径）
            s.add(m.CanonNode(
                book_id=book_id, type="hook", label="灯下的旧信",
                canon_text="灯下的旧信将在雨夜被重提", visibility="partial",
                metadata_={"status": "open"},
            ))
            await s.commit()
    asyncio.run(run())
    return book_id, entity_id


def test_c2_context_contract(tmp_path):
    engine, maker = _make_stack(tmp_path)
    try:
        book_id, entity_id = _seed(maker)

        async def run():
            async with maker() as s:
                return await build_canon_context_for_prompt(s, book_id)
        ctx = asyncio.run(run())

        # ---- 段1 [private]：ref label 被世界名覆盖（漂移根治），reveal_plan 附注 ----
        assert "## 作者脑中的真相 [private] ★ 绝不许在正文直接写出" in ctx
        assert "- 兰星：兰星与老人是失散祖孙（揭示计划：第 45 章相认）" in ctx, ctx
        assert "旧名字" not in ctx                      # 迁移期快照 label 不再出场
        assert "- 信件伪造者：伪造信件的是兰星的养父" in ctx

        # ---- 段2 [public]：地点 overlay 用世界侧真名 ----
        assert "## 必须遵守的已建立事实 [public]" in ctx
        assert "- 北岸要塞：北岸要塞是帝国最北的军镇" in ctx, ctx
        assert "旧地名" not in ctx

        # ---- 段3 [hook]：账本优先 + 未迁移兜底，行格式逐字节锁定 ----
        assert "## 活跃伏笔 [hook]（本章可推进/回收）" in ctx
        assert "- [针脚歪斜暗示身世] 强度=强：针脚歪斜暗示兰星身世" in ctx, ctx
        assert "- [灯下的旧信] 强度=?：灯下的旧信将在雨夜被重提" in ctx

        # ---- 往返：喂回 hard_constraints 解析器 ----
        labels = _extract_canon_private_labels(ctx)
        assert "兰星" in labels and "信件伪造者" in labels, labels
        assert "旧名字" not in labels                    # 泄密检测词表用世界真名
        facts = _extract_canon_public_facts(ctx)
        assert any("北岸要塞是帝国最北的军镇" in f for f in facts), facts

        # ---- 世界改名后 label 跟随（漂移根治的直接验证） ----
        async def rename():
            async with maker() as s:
                ent = await s.get(m.WorldEntity, entity_id)
                ent.name = "兰星·改"
                await s.commit()
        asyncio.run(rename())

        async def run2():
            async with maker() as s:
                return await build_canon_context_for_prompt(s, book_id)
        ctx2 = asyncio.run(run2())
        assert "- 兰星·改：兰星与老人是失散祖孙" in ctx2, ctx2
        assert "兰星：" not in ctx2
    finally:
        asyncio.run(engine.dispose())
