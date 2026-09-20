# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""书级备份「真实库副本」冒烟：data/velluma.db 拷贝一份，走导出→删→还原→行数对拍。

隔离承诺（⚠ 本脚本绝不写真实数据）：
- DB：只开临时目录里的副本（含 WAL 伴生文件一并拷贝）
- 图片：WORLD_IMAGES_DIR 重定向到临时目录（导出只读真实目录，导入写临时目录）
- 台账：restore_book_events 打桩为 no-op（否则会滤改真实 data/*.jsonl）
"""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="velluma_backup_smoke_"))
db_copy = tmp / "velluma.db"
shutil.copy2(ROOT / "data" / "velluma.db", db_copy)
for suffix in ("-wal", "-shm"):
    side = ROOT / "data" / f"velluma.db{suffix}"
    if side.exists():
        shutil.copy2(side, tmp / f"velluma.db{suffix}")

import backend.services.book_archive as ba  # noqa: E402

ba.WORLD_IMAGES_DIR = str(tmp / "world_images")          # 导入写临时目录
ba.restore_book_events = lambda spec, bid, recs: 0        # 台账回填打桩：不碰真实 jsonl

from sqlalchemy import select  # noqa: E402
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker  # noqa: E402
from backend.models import Book  # noqa: E402
from backend.services.book_archive.tables import book_scoped_models, build_export_stmt  # noqa: E402


async def _counts(db, book_id):
    out = {}
    for model in book_scoped_models():
        result = await db.execute(build_export_stmt(model, book_id))
        out[model.__tablename__] = len(result.scalars().all())
    return out


async def main():
    engine = build_sqlite_engine(db_copy)
    maker = build_sqlite_sessionmaker(engine)
    async with maker() as db:
        books = (await db.execute(select(Book).order_by(Book.created_at))).scalars().all()
        if not books:
            print("SMOKE SKIP：库里没有书")
            return
        # 可选 argv[1] 指定书 id（对台账/底图更富的书冒烟文件侧）
        want = sys.argv[1] if len(sys.argv) > 1 else ""
        target = next((b for b in books if str(b.id) == want), books[0])

        before = await _counts(db, target.id)
        payload = await ba.export_book_payload(db, target.id)
        payload = json.loads(json.dumps(payload, ensure_ascii=False))  # 真走一遍文件序列化

        await db.delete(target)
        await db.commit()
        after_delete = await _counts(db, target.id)
        assert all(v == 0 for v in after_delete.values()), f"删除后仍有残留: {after_delete}"

        report = await ba.import_book_payload(db, payload)
        after = await _counts(db, target.id)
        assert before == after == report["table_counts"], (
            f"行数不一致\nbefore={before}\nafter={after}\nreport={report['table_counts']}"
        )

        ledger_rows = {k: len(v) for k, v in payload["event_logs"].items() if v}
        print(f"SMOKE OK：《{target.title}》 {sum(before.values())} 行往返一致；"
              f"图片 {report['images']} 张；台账 {ledger_rows or '无记录'}；"
              f"警告 {report['warnings'] or '无'}")
    await engine.dispose()


asyncio.run(main())
