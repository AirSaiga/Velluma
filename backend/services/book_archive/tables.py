# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""书籍级数据表注册表——备份导出 / 导入还原 / 删除清理共用的
「哪些表属于一本书、如何圈出某本书的行」唯一权威。

设计意图：
- 35 表中除 system_cliches（全局种子数据，启动时种子化）外全部随书走
  （34 张，含 books 根行）；本模块用过滤谓词描述每张表的圈行方式，
  导出（读）与测试对拍共用同一份清单，防止两侧漂移。
- 插入序不手工维护：直接取 Base.metadata.sorted_tables 的 FK 拓扑序
  （scripts/migrate_pg_to_sqlite.py 同款手法），父表先插、子表后插。
- 自引用 FK（world_events.supersedes / world_locations.parent_id）在
  表间拓扑序里无解（自己依赖自己），由导入侧两阶段处理：先插 NULL，
  flush 后再 UPDATE 回填（见 __init__.py）。

三类圈行方式：
- direct：表自身带 book_id 列（26 张 + books 根）
- chapter：无 book_id，经 chapter_id → chapters 圈定（6 张）
- character：经 source_char_id → characters 圈定（character_relationships，
  双 FK 取 source 侧即可——关系的两端必属于同一本书）
"""
from uuid import UUID

from sqlalchemy import Select, select

from backend.database import Base
from backend.models import (
    Asset,
    AuthorSample,
    CanonEdge,
    CanonNode,
    Chapter,
    ChapterAsset,
    ChapterCard,
    ChapterEntity,
    ChapterMapLocation,
    Character,
    CharacterRelationship,
    GenerationRun,
    GenerationTask,
    MemoryChunk,
    MapLocation,
    PlotLedger,
    QualityReport,
    SceneIntent,
    StoryBeat,
    StyleCard,
    StyleInboxItem,
    Book,
    WorldDepiction,
    WorldDigestSection,
    WorldEntity,
    WorldEvent,
    WorldEventCandidate,
    WorldEventEdge,
    WorldIntent,
    WorldLocation,
    WorldMapLayer,
    WorldMapStroke,
    WorldModelORM,
    WorldRelation,
)


# ============================================================
# 注册表：全部书籍级模型（不含 books 根——根行单独导，见 build_export_stmt）
# ============================================================

_DIRECT_TABLES: tuple[type, ...] = (
    Chapter,
    StoryBeat,
    SceneIntent,
    PlotLedger,
    MemoryChunk,
    MapLocation,
    Asset,
    Character,
    GenerationTask,
    ChapterCard,
    StyleCard,
    AuthorSample,
    StyleInboxItem,
    CanonNode,
    CanonEdge,
    WorldEvent,
    WorldEventEdge,
    WorldIntent,
    WorldDepiction,
    WorldDigestSection,
    WorldLocation,
    WorldEntity,
    WorldMapLayer,
    WorldMapStroke,
    WorldRelation,
    WorldEventCandidate,
)

# 无 book_id 列、经 chapters 圈定的表
_CHAPTER_SCOPED_TABLES: tuple[type, ...] = (
    ChapterEntity,
    ChapterMapLocation,
    ChapterAsset,
    GenerationRun,
    QualityReport,
    WorldModelORM,
)

# 经 characters 圈定的表
_CHARACTER_SCOPED_TABLES: tuple[type, ...] = (CharacterRelationship,)

_BOOK_SCOPED_MODELS: frozenset[type] = frozenset(
    (Book,) + _DIRECT_TABLES + _CHAPTER_SCOPED_TABLES + _CHARACTER_SCOPED_TABLES
)

# 表名 → 模型（sorted_tables 给的是 Table，映射回 ORM 类）
_TABLE_NAME_TO_MODEL: dict[str, type] = {m.__tablename__: m for m in _BOOK_SCOPED_MODELS}


def book_scoped_models() -> list[type]:
    """按 FK 拓扑序返回全部书籍级模型（books 根在最前）。

    供导出（同序写 rows）与导入（同序插行）共用——同一顺序保证
    「导出什么就按什么依赖序还原」，无需两份顺序表。
    """
    return [
        _TABLE_NAME_TO_MODEL[table.name]
        for table in Base.metadata.sorted_tables
        if table.name in _TABLE_NAME_TO_MODEL
    ]


def build_export_stmt(model: type, book_id: UUID) -> Select:
    """圈出某本书在一张表里的全部行。"""
    if model is Book:
        return select(Book).where(Book.id == book_id)
    if model in _CHAPTER_SCOPED_TABLES:
        return (
            select(model)
            .join(Chapter, model.chapter_id == Chapter.id)
            .where(Chapter.book_id == book_id)
        )
    if model in _CHARACTER_SCOPED_TABLES:
        return (
            select(model)
            .join(Character, model.source_char_id == Character.id)
            .where(Character.book_id == book_id)
        )
    return select(model).where(model.book_id == book_id)


def self_referential_columns(model: type) -> list[str]:
    """检出模型的自引用 FK 列（属性名）——这些列在导入时需两阶段回填。

    例：world_events.supersedes / world_locations.parent_id。自引用在
    表间拓扑序里「先于自身」无解，且两表均未声明 relationship，
    SQLAlchemy 单元工作无法自行排序，必须显式延后。
    """
    table = model.__table__
    self_refs = []
    for column in table.columns:
        for fk in column.foreign_keys:
            if fk.column.table is table:
                # Table 列名 → ORM 属性名：column_attrs 按 key 对齐
                self_refs.append(_column_to_attr(model, column.name))
    return self_refs


def _column_to_attr(model: type, column_name: str) -> str:
    """Table 列名 → ORM 属性名（books 的 metadata 列挂在 metadata_ 属性上）。"""
    from sqlalchemy.orm import class_mapper

    for attr in class_mapper(model).column_attrs:
        if len(attr.columns) == 1 and attr.columns[0].name == column_name:
            return attr.key
    return column_name


def iter_models_with(table_names: list[str]) -> list[type]:
    """按名字取注册表内的模型（导入侧用：备份文件里的表名 → 模型，
    注册表外的表名静默忽略——备份里混入未知表不炸导入）。"""
    return [
        _TABLE_NAME_TO_MODEL[name]
        for name in table_names
        if name in _TABLE_NAME_TO_MODEL
    ]
