# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""书级备份往返对拍（备份 → 删除清理 → 还原 → 软引用抽查）。

对拍口径：本文件锁「整本书数据离开数据库再回来，一字不丢、引用不断」
的契约——含 DB 34 表行数、JSONB 书级列、canon 软关联、world 自引用链
（supersedes/parent_id）、地图底图文件、jsonl 台账幂等回填。
改 tables.py 注册表 / codecs.py 编解码 / 导入顺序时必须跑本文件。

运行：`.venv/Scripts/python.exe -m pytest backend/services/book_archive/test_book_archive.py -v`

注意：每个测试独立事件循环（asyncio.run）+ 独立临时库文件，
台账与图片路径全部 monkeypatch 进临时目录——绝不触碰真实 data/。
"""
import asyncio
import base64
import json
import uuid

import pytest
from sqlalchemy import select

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite

import backend.services.book_archive as ba
from backend.services.book_archive import (
    BACKUP_FORMAT,
    BackupFormatError,
    BookAlreadyExistsError,
    export_book_payload,
    import_book_payload,
    purge_book_files,
)
from backend.services.book_archive.codecs import (
    _b64_to_floats,
    _floats_to_b64,
    deserialize_column_value,
    serialize_column_value,
)
from backend.services.book_archive.logs_io import LEDGERS, restore_book_events
from backend.services.book_archive.tables import book_scoped_models, build_export_stmt


# ============================================================
# 夹具基建
# ============================================================

def _make_stack(tmp_path):
    engine = build_sqlite_engine(tmp_path / "test.db")
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


@pytest.fixture()
def redirected_paths(tmp_path, monkeypatch):
    """台账/图片/logs 路径全部指向临时目录（不碰真实 data/ 与 logs/）。"""
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    data_dir.mkdir()
    logs_dir.mkdir()

    monkeypatch.setattr(ba, "WORLD_IMAGES_DIR", str(data_dir / "world_images"))

    # 台账家模块的路径助手逐一替换（logs_io 借它们的坐标，patch 源头即生效）
    import backend.routes.chapter_generation.adaptive.events as collab_mod
    import backend.services.constraints.events as constraint_mod
    import backend.services.deai.pairs as pairs_mod
    import backend.services.world.ask_book as ask_mod
    import backend.routes.chapter_generation.adaptive.opening_card as opening_mod
    import backend.services.style.events as style_events_mod

    collab_path = data_dir / "collab_events.jsonl"
    monkeypatch.setattr(collab_mod, "_collab_events_path", lambda: collab_path)
    monkeypatch.setattr(collab_mod, "_collab_events_rotated_path",
                        lambda: data_dir / "collab_events.jsonl.1")
    monkeypatch.setattr(constraint_mod, "_events_path",
                        lambda: data_dir / "constraint_events.jsonl")
    monkeypatch.setattr(constraint_mod, "_rotated_path",
                        lambda: data_dir / "constraint_events.jsonl.1")
    monkeypatch.setattr(pairs_mod, "_pairs_path",
                        lambda: data_dir / "deai_pairs.jsonl")
    monkeypatch.setattr(ask_mod, "_metrics_path",
                        lambda: data_dir / "ask_book_metrics.jsonl")
    monkeypatch.setattr(opening_mod, "_metrics_path",
                        lambda: data_dir / "opening_card_metrics.jsonl")
    monkeypatch.setattr(style_events_mod, "STYLE_EVENTS_FILE",
                        str(data_dir / "style_events.jsonl"))
    return {"data_dir": data_dir, "logs_dir": logs_dir}


async def _seed_book(db) -> uuid.UUID:
    """造一本「全谱系」夹具书：覆盖直接/经章/经角色三类表 + 自引用链 + 软关联。"""
    book = m.Book(
        title="灯塔与雾",
        genre="悬疑",
        core_motifs_taboos="禁用：梦境收尾",
        worldview_settings={"era": "1998", "place": "海岬镇"},
        reader_mirror={"expectations": [{"key": "灯还亮着"}]},
        texture_contracts={"stitch_tail": {"body": "少解释", "updated_at": "2026-09-01"}},
        golden_snippets=["雾从海面爬上来，像一件湿透的斗篷。"],
    )
    db.add(book)
    await db.flush()

    ch1 = m.Chapter(book_id=book.id, chapter_number=1, chapter_name="第一章", content_text="<p>雾来了。</p>")
    ch2 = m.Chapter(book_id=book.id, chapter_number=2, chapter_name="第二章", content_text="<p>灯亮了。</p>")
    db.add_all([ch1, ch2])
    await db.flush()

    # 角色与关系（经 character 圈定的表）
    aunt = m.Character(book_id=book.id, name="明姐", static_prompt="守塔人")
    girl = m.Character(book_id=book.id, name="小满", static_prompt="来写生的学生")
    db.add_all([aunt, girl])
    await db.flush()
    db.add(m.CharacterRelationship(
        source_char_id=aunt.id, target_char_id=girl.id,
        relation_type="师徒", interaction_prompt="教她辨认海况",
    ))

    # 旧实体三件 + 章绑定
    loc = m.MapLocation(book_id=book.id, name="灯塔")
    asset = m.Asset(book_id=book.id, name="黄铜钥匙")
    db.add_all([loc, asset])
    await db.flush()
    db.add(m.ChapterEntity(chapter_id=ch1.id, entity_id=aunt.id))

    # world 自引用链：事件修订链 + 地点父子树
    parent_loc = m.WorldLocation(book_id=book.id, name="海岬镇")
    db.add(parent_loc)
    await db.flush()
    child_loc = m.WorldLocation(book_id=book.id, name="灯塔", parent_id=parent_loc.id)
    db.add(child_loc)
    await db.flush()

    ev1 = m.WorldEvent(
        book_id=book.id, sequence_num=1, event_type="move",
        time_start=0, time_end=0, location_id=parent_loc.id,
        participant_ids=[str(uuid.uuid4())], payload={"via": "山路"},
        title="明姐进镇",
    )
    db.add(ev1)
    await db.flush()
    ev2 = m.WorldEvent(
        book_id=book.id, sequence_num=2, event_type="move",
        time_start=1, time_end=1, location_id=child_loc.id,
        supersedes=ev1.id,  # 修订链：导入侧两阶段回填的靶点
        payload={"via": "礁石路"}, title="明姐进镇（修订）",
    )
    db.add(ev2)

    we = m.WorldEntity(book_id=book.id, entity_type="character", name="明姐")
    db.add(we)
    await db.flush()
    db.add(m.WorldRelation(book_id=book.id, source_entity_id=we.id, target_entity_id=we.id, relation_type="self"))
    db.add(m.WorldEventEdge(book_id=book.id, subject_event_id=ev1.id, object_event_id=ev2.id, kind="before"))

    # canon 软关联（ref_id 无 FK——原 ID 直复语义的守护对象）
    node = m.CanonNode(book_id=book.id, type="secret", label="灯下埋着信",
                       canon_text="[private]信是写给小满母亲的。",
                       ref_type="ledger", ref_id=str(uuid.uuid4()))
    db.add(node)
    await db.flush()
    db.add(m.CanonEdge(book_id=book.id, source_id=node.id, target_id=node.id, type="related"))

    # 叙事/文风/记忆杂项
    db.add(m.PlotLedger(book_id=book.id, ledger_key="k1", content="钥匙的下落", status="open"))
    db.add(m.StoryBeat(book_id=book.id, chapter_id=ch1.id, summary="雾夜抵达"))
    db.add(m.SceneIntent(book_id=book.id, chapter_id=ch1.id, intent_label="抵达", goal="安顿"))
    db.add(m.MemoryChunk(book_id=book.id, chapter_id=ch1.id, chunk_text="雾从海面爬上来。"))
    db.add(m.AuthorSample(book_id=book.id, content="海风咸涩，灯影摇晃。", source="golden_snippet"))
    db.add(m.StyleCard(book_id=book.id, positive_profile={"tone": "冷"}))
    db.add(m.ChapterCard(book_id=book.id, chapter_number=1))
    db.add(m.GenerationRun(chapter_id=ch1.id, run_id="adaptive_x", stage="stitching",
                           model_name="test", prompt_tokens=10, completion_tokens=5))
    db.add(m.QualityReport(chapter_id=ch1.id, verdict="pass"))
    db.add(m.WorldModelORM(chapter_id=ch1.id))
    db.add(m.WorldIntent(book_id=book.id, kind="foreshadow", target_text="灯还亮着",
                         source_key=f"legacy:plot_ledgers:{uuid.uuid4()}"))
    db.add(m.WorldDepiction(book_id=book.id, subject_type="entity",
                            subject_id=str(we.id), chapter_id=ch1.id))
    db.add(m.WorldEventCandidate(book_id=book.id, chapter_id=ch2.id))
    db.add(m.WorldDigestSection(book_id=book.id, section_key="s1"))
    db.add(m.GenerationTask(book_id=book.id, chapter_id=ch1.id, status="pending"))

    await db.commit()
    return book.id


def _write_fixture_sidecar(book_id, data_dir):
    """底图文件 + 台账记录（备份的非 DB 部分）。"""
    img_dir = data_dir / "world_images" / str(book_id)
    img_dir.mkdir(parents=True)
    (img_dir / "map.png").write_bytes(b"\x89PNG-fake-bytes")

    collab = data_dir / "collab_events.jsonl"
    other_book_id = str(uuid.uuid4())
    records = [
        {"ts": "2026-09-19T01:00:00", "book_id": str(book_id), "kind": "ghost_adopt", "detail": "{}"},
        {"ts": "2026-09-19T01:01:00", "book_id": other_book_id, "kind": "ghost_adopt", "detail": "{}"},
    ]
    collab.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    (data_dir / "style_events.jsonl").write_text(
        json.dumps({"ts": "2026-09-19", "book_id": str(book_id), "kind": "wash", "detail": "x"}) + "\n",
        encoding="utf-8",
    )
    return other_book_id


async def _book_table_counts(db, book_id) -> dict:
    """该书在注册表全部表里的行数（导出前后/还原后对拍）。"""
    counts = {}
    for model in book_scoped_models():
        result = await db.execute(build_export_stmt(model, book_id))
        counts[model.__tablename__] = len(result.scalars().all())
    return counts


# ============================================================
# 主往返：导出 → 删除清理 → 还原 → 对拍
# ============================================================

def test_full_round_trip(tmp_path, redirected_paths):
    engine, maker = _make_stack(tmp_path)
    data_dir = redirected_paths["data_dir"]
    logs_dir = redirected_paths["logs_dir"]

    async def scenario():
        async with maker() as db:
            book_id = await _seed_book(db)
            other_book_id = _write_fixture_sidecar(book_id, data_dir)

            # 该书 chapter 的 trace 日志（删除清理的靶点）
            ch_ids = (await db.execute(
                select(m.Chapter.id).where(m.Chapter.book_id == book_id)
            )).scalars().all()
            trace_files = []
            for cid in ch_ids:
                t = logs_dir / f"trace_adaptive_{cid}.jsonl"
                t.write_text("{}\n", encoding="utf-8")
                trace_files.append(t)

            before_counts = await _book_table_counts(db, book_id)
            assert sum(before_counts.values()) > 20  # 夹具 sanity：谱系足够宽

            # ---- 导出（走 json.dumps/loads 全程——锁「真能落成文件」）----
            payload = await export_book_payload(db, book_id)
            payload = json.loads(json.dumps(payload, ensure_ascii=False))

            assert payload["format"] == BACKUP_FORMAT
            assert payload["version"] == 1
            assert len(payload["rows"]["books"]) == 1
            assert payload["rows"]["books"][0]["title"] == "灯塔与雾"
            assert payload["world_images"] and payload["world_images"][0]["path"] == "map.png"
            assert base64.b64decode(payload["world_images"][0]["b64"]) == b"\x89PNG-fake-bytes"
            assert all(r["book_id"] == str(book_id) for r in payload["event_logs"]["collab_events"])
            assert len(payload["event_logs"]["collab_events"]) == 1  # 他书记录不混入
            ev1_row = next(r for r in payload["rows"]["world_events"] if r["sequence_num"] == 1)
            ev2_row = next(r for r in payload["rows"]["world_events"] if r["sequence_num"] == 2)
            assert ev2_row["supersedes"] == ev1_row["id"]  # 自引用链在备份里完整

            # ---- 删除（ORM 级联 + 文件清理）----
            book = await db.get(m.Book, book_id)
            await db.delete(book)
            await db.commit()
            purged = purge_book_files(book_id, [str(c) for c in ch_ids], logs_dir=logs_dir)
            assert purged["images_dir_removed"] is True
            assert not (data_dir / "world_images" / str(book_id)).exists()
            assert purged["events_deleted"]["collab_events"] == 1
            assert purged["events_deleted"]["style_events"] == 1
            remaining = [json.loads(line) for line in
                         (data_dir / "collab_events.jsonl").read_text(encoding="utf-8").splitlines()]
            assert [r["book_id"] for r in remaining] == [other_book_id]  # 他书保留
            assert all(not t.exists() for t in trace_files)
            after_delete = await _book_table_counts(db, book_id)
            assert after_delete == {k: 0 for k in before_counts}

            # ---- 还原 ----
            report = await import_book_payload(db, payload)
            assert report["book_title"] == "灯塔与雾"
            assert report["table_counts"] == before_counts
            assert report["images"] == 1
            assert (data_dir / "world_images" / str(book_id) / "map.png").read_bytes() == b"\x89PNG-fake-bytes"
            assert await _book_table_counts(db, book_id) == before_counts

            # 软引用与自引用链抽查（原 ID 直复语义）
            ev2 = (await db.execute(
                select(m.WorldEvent).where(m.WorldEvent.sequence_num == 2)
            )).scalars().one()
            assert str(ev2.supersedes) == ev1_row["id"]
            child = (await db.execute(
                select(m.WorldLocation).where(m.WorldLocation.name == "灯塔")
            )).scalars().one()
            assert child.parent_id is not None  # 两阶段回填成功
            canon_edge = (await db.execute(select(m.CanonEdge))).scalars().one()
            canon_node = (await db.execute(select(m.CanonNode))).scalars().one()
            assert str(canon_edge.source_id) == str(canon_node.id)  # 软关联不断
            restored_book = await db.get(m.Book, book_id)
            assert restored_book.reader_mirror == {"expectations": [{"key": "灯还亮着"}]}
            assert restored_book.texture_contracts["stitch_tail"]["body"] == "少解释"
            intent = (await db.execute(select(m.WorldIntent))).scalars().one()
            assert intent.source_key.startswith("legacy:plot_ledgers:")

            # 台账幂等：再回填一次不双计
            spec = next(s for s in LEDGERS if s.key == "collab_events")
            restore_book_events(spec, book_id, payload["event_logs"]["collab_events"])
            lines = (data_dir / "collab_events.jsonl").read_text(encoding="utf-8").splitlines()
            mine = [json.loads(line) for line in lines if json.loads(line)["book_id"] == str(book_id)]
            assert len(mine) == 1

            # ---- 重复还原被拒（原 ID 直复语义）----
            with pytest.raises(BookAlreadyExistsError):
                await import_book_payload(db, payload)

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


# ============================================================
# 校验分支与列漂移
# ============================================================

def test_import_rejects_bad_payload(tmp_path):
    engine, maker = _make_stack(tmp_path)

    async def scenario():
        async with maker() as db:
            for bad in (
                {"format": "other"},
                {"format": BACKUP_FORMAT, "version": 99, "rows": {"books": [{"id": str(uuid.uuid4())}]}},
                {"format": BACKUP_FORMAT, "version": 1, "rows": {}},
                {"format": BACKUP_FORMAT, "version": 1, "rows": {"books": []}},
                {"format": BACKUP_FORMAT, "version": 1, "rows": {"books": [{"id": "not-a-uuid"}]}},
                "not-a-dict",
            ):
                with pytest.raises(BackupFormatError):
                    await import_book_payload(db, bad)

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


def test_import_column_drift_reports_warning(tmp_path, redirected_paths):
    engine, maker = _make_stack(tmp_path)

    async def scenario():
        async with maker() as db:
            book_id = await _seed_book(db)
            payload = await export_book_payload(db, book_id)
            book = await db.get(m.Book, book_id)
            await db.delete(book)
            await db.commit()

            # 模拟列漂移：备份里多一列（新版本程序导的备份进老版本程序）
            payload["rows"]["story_beats"][0]["ghost_column_x"] = 1
            report = await import_book_payload(db, payload)
            assert any("ghost_column_x" in w for w in report["warnings"])
            assert report["table_counts"]["story_beats"] == 1  # 行仍导入

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


# ============================================================
# 编解码单元：向量 b64 往返 + 方言门控
# ============================================================

def test_vector_codec_roundtrip():
    embedding_col = m.Base.metadata.tables["memory_chunks"].c.embedding
    floats = [0.25, -1.5, 3.14159, 0.0, 1e-8]

    packed = serialize_column_value(embedding_col, floats)
    assert isinstance(packed, dict) and "$b64f32" in packed and packed["dim"] == 5

    # PG 方言回填：浮点无损往返（float32 精度内）
    restored = deserialize_column_value(embedding_col, packed, "postgresql")
    assert restored is not None and len(restored) == 5
    assert abs(restored[0] - 0.25) < 1e-6 and abs(restored[2] - 3.14159) < 1e-5

    # SQLite 方言：向量列恒 None（type_compat 契约）
    assert deserialize_column_value(embedding_col, packed, "sqlite") is None

    # 文本形态（asyncpg 未注册 codec 时的 pgvector 文本格式）也能打包
    from_text = serialize_column_value(embedding_col, "[0.5, 0.25]")
    assert from_text is not None and from_text["dim"] == 2


def test_b64_floats_helpers():
    floats = [1.0, 2.0, 3.0]
    assert _b64_to_floats(_floats_to_b64(floats)) == floats
