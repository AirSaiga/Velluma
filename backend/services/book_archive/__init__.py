# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""书籍级备份 / 还原 / 删除清理——书架「备份 → 删除 → 还原」闭环的服务层。

契约（routes/books.py 的 GET /books/{id}/backup、POST /books/restore、
DELETE /books/{id} 三个端点共用）：

- 备份 = 单个 JSON（扩展名 .vellumabook）：34 张书籍级表的全部行
  （tables.py 注册表圈定）+ 地图底图 base64 + 6 个 jsonl 台账按书过滤。
- 还原 = **原 ID 直复**：UUID 原样写回，不做 ID 重映射。这不是偷懒——
  canon_nodes.ref_id（无 FK 软关联）与 world_intents.source_key
  （"legacy:<表>:<id>" 字符串内嵌 ID）都按原 ID 语义存活，重映射会
  静默切断这些引用。书架已存在同 ID 书时拒绝导入（409）。
- 导入幂等：jsonl 台账先滤本书旧记录再追加；图片按 book_id 目录覆盖写。
- 删除清理：DELETE /books/{id} 删 DB 后调 purge_book_files 清理
  world_images/{book_id}/、6 个台账的本书记录、按章 trace/prompt 日志
  ——否则「删→还原」会让台账双份（学习状态双计）。

SQLite/PG 双路径：纯 ORM + 类型驱动编解码（codecs.py），无方言分支
（唯一例外：向量列仅 PG 回填，SQLite 方言恒 NULL 是 type_compat 契约）。
"""
import base64
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import class_mapper

from backend.core.config import WORLD_IMAGES_DIR
from backend.models import Book

from .codecs import deserialize_column_value, serialize_column_value
from .logs_io import LEDGERS, filter_ledger_files, read_book_events, restore_book_events
from .tables import book_scoped_models, build_export_stmt, self_referential_columns

logger = logging.getLogger(__name__)

BACKUP_FORMAT = "velluma.book-backup"
BACKUP_VERSION = 1


class BackupFormatError(ValueError):
    """备份文件结构/版本不被接受（路由层映射 400）。"""


class BookAlreadyExistsError(Exception):
    """书架中已存在同 ID 书（路由层映射 409——原 ID 直复语义下的重复还原）。"""

    def __init__(self, book_id, title: str = ""):
        super().__init__(f"book {book_id} already exists")
        self.book_id = book_id
        self.title = title


# ============================================================
# 导出
# ============================================================

async def export_book_payload(db: AsyncSession, book_id: UUID) -> dict:
    """组装某本书的完整备份 dict（路由层负责转 JSON 响应）。

    副作用：纯读（DB + 台账文件 + 图片目录），无任何写入。
    """
    book = await db.get(Book, book_id)
    if book is None:
        raise BackupFormatError("书籍不存在")

    rows: dict = {}
    for model in book_scoped_models():
        result = await db.execute(build_export_stmt(model, book_id))
        objs = result.scalars().all()
        rows[model.__tablename__] = [_row_to_dict(model, obj) for obj in objs]

    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "world_images": _read_world_images(book_id),
        "event_logs": {spec.key: read_book_events(spec, book_id) for spec in LEDGERS},
    }


def _row_to_dict(model: type, obj) -> dict:
    """ORM 实例 → 列值 dict。只走 column_attrs 不碰 relationship——
    防级联重插（scripts/migrate_pg_to_sqlite.py 同款纪律）。"""
    out: dict = {}
    for attr in class_mapper(model).column_attrs:
        out[attr.key] = serialize_column_value(attr.columns[0], getattr(obj, attr.key))
    return out


# ============================================================
# 导入
# ============================================================

async def import_book_payload(db: AsyncSession, payload) -> dict:
    """把备份 dict 写回数据库与文件系统，返回导入报告。

    事务语义：DB 全部插入（含自引用列两阶段回填）单事务提交；
    提交成功后才写图片与台账——文件侧失败不回滚 DB（图片以 book_id
    目录为键、下次导入覆盖写，无脏残留），错误进 warnings。
    """
    if not isinstance(payload, dict):
        raise BackupFormatError("备份文件内容不是 JSON 对象")
    if payload.get("format") != BACKUP_FORMAT:
        raise BackupFormatError("这不是一份 Velluma 书籍备份文件")
    version = payload.get("version")
    if not isinstance(version, int) or version > BACKUP_VERSION:
        raise BackupFormatError(f"备份版本不支持（{version}，当前支持 ≤ {BACKUP_VERSION}）")

    rows = payload.get("rows")
    if not isinstance(rows, dict):
        raise BackupFormatError("备份里缺少数据（rows）")
    book_rows = rows.get("books")
    if not isinstance(book_rows, list) or len(book_rows) != 1 or not isinstance(book_rows[0], dict):
        raise BackupFormatError("备份里缺少书籍数据（books 应为恰好一行）")

    try:
        book_id = UUID(str(book_rows[0].get("id") or ""))
    except ValueError:
        raise BackupFormatError("备份里的书籍 ID 无效")

    if await db.get(Book, book_id) is not None:
        raise BookAlreadyExistsError(book_id, str(book_rows[0].get("title") or ""))

    dialect_name = db.get_bind().dialect.name
    warnings: list = []
    counts: dict = {}
    deferred_updates: list = []
    warned_tables: set = set()

    for model in book_scoped_models():
        table_name = model.__tablename__
        table_rows = rows.get(table_name) or []
        if not isinstance(table_rows, list):
            raise BackupFormatError(f"备份里 {table_name} 的数据格式不对")
        attr_map = {a.key: a.columns[0] for a in class_mapper(model).column_attrs}
        deferred_cols = set(self_referential_columns(model))
        for row in table_rows:
            if not isinstance(row, dict):
                raise BackupFormatError(f"备份里 {table_name} 的某行不是对象")
            unknown = [k for k in row if k not in attr_map]
            if unknown and table_name not in warned_tables:
                warnings.append(
                    f"{table_name}: 备份多出 {len(unknown)} 个当前版本没有的列"
                    f"（{'、'.join(sorted(unknown)[:3])}{'…' if len(unknown) > 3 else ''}），已跳过"
                )
                warned_tables.add(table_name)
            kwargs = {}
            deferred_vals = {}
            for key, column in attr_map.items():
                if key not in row:
                    continue
                if key in deferred_cols:
                    # 自引用 FK 拓扑序无解：先插 NULL，flush 后 UPDATE 回填
                    deferred_vals[key] = row[key]
                    kwargs[key] = None
                else:
                    kwargs[key] = deserialize_column_value(column, row[key], dialect_name)
            db.add(model(**kwargs))
            if deferred_vals:
                deferred_updates.append((model, attr_map, row, deferred_vals))
        counts[table_name] = len(table_rows)
        # 逐表 flush：SQLAlchemy 单元工作按 relationship（非裸 FK）排插入序，
        # 无 relationship 的跨表 FK（如 generation_runs→chapters）会被乱序插
        # ——按 sorted_tables 拓扑序显式 flush 每张表（migrate 脚本同款纪律）
        if table_rows:
            await db.flush()

    for model, attr_map, row, deferred_vals in deferred_updates:
        values = {
            key: deserialize_column_value(attr_map[key], raw, dialect_name)
            for key, raw in deferred_vals.items()
        }
        # 显式回写 updated_at 抑制 onupdate——自引用回填不应碰时间戳
        if "updated_at" in attr_map and row.get("updated_at") is not None:
            values["updated_at"] = deserialize_column_value(
                attr_map["updated_at"], row["updated_at"], dialect_name
            )
        pk = deserialize_column_value(attr_map["id"], row.get("id"), dialect_name)
        await db.execute(update(model).where(model.id == pk).values(**values))

    await db.commit()

    # ---- 文件侧（DB 已提交；失败进 warnings 不回滚）----
    images_written = _write_world_images(book_id, payload.get("world_images") or [])
    event_counts = {}
    logs = payload.get("event_logs") if isinstance(payload.get("event_logs"), dict) else {}
    for spec in LEDGERS:
        records = logs.get(spec.key) or []
        if not isinstance(records, list):
            warnings.append(f"台账 {spec.key} 数据格式不对，已跳过")
            records = []
        event_counts[spec.key] = restore_book_events(spec, book_id, records)
    _invalidate_quiet_caches(book_id)

    logger.info(
        "[book_archive] 还原完成：book=%s 总行数=%s 图片=%s",
        book_id, sum(counts.values()), images_written,
    )
    return {
        "book_id": str(book_id),
        "book_title": book_rows[0].get("title"),
        "table_counts": counts,
        "event_counts": event_counts,
        "images": images_written,
        "warnings": warnings,
    }


# ============================================================
# 删除清理
# ============================================================

def purge_book_files(book_id, chapter_ids, logs_dir: "Path | None" = None) -> dict:
    """删书后的文件侧清理（DELETE /books/{id} 调用，DB 已删之后）。

    覆盖三类 DB 外数据：world_images/{book_id}/ 底图目录（全库唯一的
    按书落盘二进制资产）、6 个 jsonl 台账的本书记录、该书各章的
    trace/prompt 日志。全部失败容忍——清理失败不阻断删除响应。
    logs_dir 仅测试注入用，生产恒为项目根 logs/。
    """
    report: dict = {}

    book_dir = Path(WORLD_IMAGES_DIR) / str(book_id)
    if book_dir.is_dir():
        shutil.rmtree(book_dir, ignore_errors=True)
    report["images_dir_removed"] = book_dir.exists() is False

    report["events_deleted"] = {
        spec.key: filter_ledger_files(spec, book_id) for spec in LEDGERS
    }

    if logs_dir is None:
        logs_dir = Path(__file__).resolve().parents[3] / "logs"
    log_files_removed = 0
    for chapter_id in chapter_ids:
        cid = str(chapter_id)
        trace_path = logs_dir / f"trace_adaptive_{cid}.jsonl"
        if trace_path.exists():
            try:
                trace_path.unlink()
                log_files_removed += 1
            except OSError:
                pass
        # prompt 日志命名含时间戳前缀，chapter_id 截前 8 位（prompt_logger.py:408）
        for prompt_path in logs_dir.glob(f"prompt_log_*_{cid[:8]}.json"):
            try:
                prompt_path.unlink()
                log_files_removed += 1
            except OSError:
                pass
    report["log_files_removed"] = log_files_removed

    _invalidate_quiet_caches(book_id)
    return report


def _invalidate_quiet_caches(book_id) -> None:
    """台账变动后失效「学着闭嘴」派生缓存（30s TTL 自然过期，主动失效更快）。"""
    try:
        from backend.services.adaptive.quiet_learning import invalidate_quiet_caches

        invalidate_quiet_caches(book_id)
    except Exception as e:  # pragma: no cover - 缓存失效失败无害
        logger.debug(f"[book_archive] 静音缓存失效失败（TTL 自然过期）: {e}")


# ============================================================
# 地图底图（DB 只存 URL，二进制在 data/world_images/{book_id}/）
# ============================================================

def _read_world_images(book_id) -> list:
    book_dir = Path(WORLD_IMAGES_DIR) / str(book_id)
    if not book_dir.is_dir():
        return []
    out = []
    for f in sorted(book_dir.iterdir()):
        if f.is_file():
            out.append({
                "path": f.name,
                "b64": base64.b64encode(f.read_bytes()).decode("ascii"),
            })
    return out


def _write_world_images(book_id, entries) -> int:
    book_dir = Path(WORLD_IMAGES_DIR) / str(book_id)
    written = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # 防路径穿越：只取文件名部分，不接受任何目录层级
        name = os.path.basename(str(entry.get("path") or ""))
        b64_text = entry.get("b64")
        if not name or not b64_text:
            continue
        try:
            data = base64.b64decode(b64_text)
        except Exception:
            continue
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / name).write_bytes(data)
        written += 1
    return written
