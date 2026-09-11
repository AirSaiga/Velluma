# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""SQLAlchemy ORM 模型包（Velluma 全部 35 张表的声明式定义）。

2026-09-11 架构优化批：原单文件 models.py（1773 行）按领域拆为八个子模块，
本 __init__ 全量 re-export——`from backend.models import X` 消费面零变化。
子模块共享 backend.database 的同一 Base（declarative registry 全局唯一，
relationship 字符串目标在 registry 级解析，与文件布局无关）。

- _common.py:   工具函数 / 状态 Enum / TIER 常量
- narrative.py: Book / Chapter / StoryBeat / SceneIntent / PlotLedger
- entities.py:  Character / Asset / 关系 / 章级绑定
- memory.py:    MemoryChunk（RAG 向量）
- generation.py: GenerationTask / GenerationRun / QualityReport
- style.py:     文风体系五表
- canon.py:     Canon 真相层（节点/边/类型常量）
- world.py:     世界内核 world_* 全家

⚠ 新增表请放进对应领域子模块；只 import 单个子模块的脚本需先 `import
backend.models` 触发全量注册（mapper 才齐）。
"""
# db_sqlite/schema.py 等直接从本包取 Base
from backend.database import Base

from ._common import (
    PlotLedgerStatus,
    TaskStatus,
    TIER_CLIMAX,
    TIER_TURN,
    TIER_PROGRESS,
    TIER_TRANSITION,
    TIER_AUTO,
    VALID_TIERS,
    TIER_MAX_DEPTH,
    TIER_DEVELOPMENT_RATIO,
    generate_uuid,
    utc_now,
)

from .narrative import (
    Book,
    Chapter,
    StoryBeat,
    SceneIntent,
    PlotLedger,
)

from .entities import (
    ChapterEntity,
    MapLocation,
    ChapterMapLocation,
    Asset,
    ChapterAsset,
    Character,
    CharacterRelationship,
)

from .memory import (
    MemoryChunk,
)

from .generation import (
    GenerationTask,
    GenerationRun,
    QualityReport,
)

from .style import (
    ChapterCard,
    StyleCard,
    AuthorSample,
    SystemCliche,
    StyleInboxItem,
)

from .canon import (
    NODE_TYPE_CHARACTER,
    NODE_TYPE_EVENT,
    NODE_TYPE_OBJECT,
    NODE_TYPE_PLACE,
    NODE_TYPE_HOOK,
    NODE_TYPES,
    EDGE_TYPE_CAUSES,
    EDGE_TYPE_BEFORE,
    EDGE_TYPE_HINTS,
    EDGE_TYPE_SETUPS,
    EDGE_TYPE_CALLBACKS,
    EDGE_TYPE_ECHOES,
    EDGE_TYPES,
    VISIBILITY_PUBLIC,
    VISIBILITY_PRIVATE,
    VISIBILITY_PARTIAL,
    VISIBILITIES,
    CanonNode,
    CanonEdge,
)

from .world import (
    WORLD_EVENT_BIRTH,
    WORLD_EVENT_DEATH,
    WORLD_EVENT_MOVE,
    WORLD_EVENT_BATTLE,
    WORLD_EVENT_TERRITORY_CHANGE,
    WORLD_EVENT_FOUND,
    WORLD_EVENT_DESTROY,
    WORLD_EVENT_ALLIANCE,
    WORLD_EVENT_WAR_DECLARE,
    WORLD_EVENT_CORONATION,
    WORLD_EVENT_CUSTOM,
    WORLD_ENTITY_CHARACTER,
    WORLD_ENTITY_FACTION,
    WORLD_ENTITY_ASSET,
    WORLD_LOCATION_POINT,
    WORLD_LOCATION_REGION,
    WORLD_LOCATION_ROUTE,
    WorldEvent,
    WorldEventEdge,
    INTENT_KINDS,
    INTENT_LIFECYCLES,
    WorldIntent,
    DEPICTION_MODES,
    WorldDepiction,
    WorldDigestSection,
    WorldLocation,
    WorldEntity,
    WorldMapLayer,
    WorldMapStroke,
    WorldRelation,
    WorldEventCandidate,
    WorldModelORM,
)

# 跨模块 relationship 挂接（须在全部子模块之后）
from . import _links as _links  # noqa: F401

__all__ = [
    # Enums
    "PlotLedgerStatus",
    "TaskStatus",
    # Models
    "Book",
    "Chapter",
    "ChapterEntity",
    "MapLocation",
    "ChapterMapLocation",
    "Asset",
    "ChapterAsset",
    "Character",
    "CharacterRelationship",
    "MemoryChunk",
    "StoryBeat",
    "SceneIntent",
    "PlotLedger",
    "GenerationTask",
    "GenerationRun",
    # CP2.1 新增
    "ChapterCard",
    "StyleCard",
    "AuthorSample",
    "SystemCliche",
    # CP3.1a 新增
    "QualityReport",
    # V3.1 统一引擎 tier 常量
    "TIER_CLIMAX",
    "TIER_TURN",
    "TIER_PROGRESS",
    "TIER_TRANSITION",
    "TIER_AUTO",
    "VALID_TIERS",
    # V4.0 Canon（作者脑中世界图谱）
    "CanonNode",
    "CanonEdge",
    "NODE_TYPE_CHARACTER",
    "NODE_TYPE_EVENT",
    "NODE_TYPE_OBJECT",
    "NODE_TYPE_PLACE",
    "NODE_TYPE_HOOK",
    "EDGE_TYPE_CAUSES",
    "EDGE_TYPE_BEFORE",
    "EDGE_TYPE_HINTS",
    "EDGE_TYPE_SETUPS",
    "EDGE_TYPE_CALLBACKS",
    "EDGE_TYPE_ECHOES",
    "VISIBILITY_PUBLIC",
    "VISIBILITY_PRIVATE",
    "VISIBILITY_PARTIAL",
    # V5.0 World 设定层（地图 + 时间线 + 事件溯源，独立于 Canon）
    "WorldEvent",
    "WorldLocation",
    "WorldEntity",
    "WorldMapLayer",
    "WorldMapStroke",
    "WORLD_EVENT_BIRTH",
    "WORLD_EVENT_DEATH",
    "WORLD_EVENT_MOVE",
    "WORLD_EVENT_BATTLE",
    "WORLD_EVENT_TERRITORY_CHANGE",
    "WORLD_EVENT_FOUND",
    "WORLD_EVENT_DESTROY",
    "WORLD_EVENT_ALLIANCE",
    "WORLD_EVENT_WAR_DECLARE",
    "WORLD_EVENT_CORONATION",
    "WORLD_EVENT_CUSTOM",
    "WORLD_ENTITY_CHARACTER",
    "WORLD_ENTITY_FACTION",
    "WORLD_ENTITY_ASSET",
    "WORLD_LOCATION_POINT",
    "WORLD_LOCATION_REGION",
    "WORLD_LOCATION_ROUTE",
    # Utilities
    "generate_uuid",
    "utc_now",
]
