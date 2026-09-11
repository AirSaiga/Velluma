# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
数据库配置模块。

核心职责：
1. 异步 SQLAlchemy 引擎配置 (连接池管理)
2. 会话依赖注入 (FastAPI 集成)
3. 表结构初始化与迁移

架构设计：
- 使用 asyncpg 驱动实现真正的异步 I/O
- 连接池预检 (pool_pre_ping) 防止连接因空闲超时被 DB 关闭
- 迁移策略：应用启动时检查并添加缺失列 (非生产级，建议使用 Alembic)
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Optional, Sequence
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

load_dotenv()

# 配置模块级日志记录器
logger = logging.getLogger(__name__)

# ============================================================
# 切换日（roadmap P3.1，2026-08-19）：默认 SQLite，PG 显式保留
# ------------------------------------------------------------
# - 不设 DATABASE_URL → SQLite 文件库（data/velluma.db，单机桌面零外部依赖；
#   WAL/外键/忙等 pragma 由 db_sqlite.engine 逐连接设置，NullPool 防锁竞争）
# - DATABASE_URL 显式给出（postgresql+asyncpg://…）→ 走 PG（专业级/开发路径：
#   pgvector 向量记忆、连接池、向量维度迁移——全部保留不变）
# - 存量 PG → SQLite 数据搬迁：scripts/migrate_pg_to_sqlite.py（只读拓扑序+行数对照）
# - 数据目录可用 VELLUMA_DATA_DIR 覆盖（打包/便携场景）
# ============================================================
_DATABASE_URL_ENV = os.getenv("DATABASE_URL", "").strip()
USE_SQLITE = not _DATABASE_URL_ENV


def _sqlite_db_path() -> str:
    root = Path(__file__).resolve().parents[1]  # 项目根 = backend/ 的父
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "velluma.db")


if USE_SQLITE:
    from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
    from backend.db_sqlite.type_compat import register_sqlite_type_compat

    register_sqlite_type_compat()  # JSONB/Vector → SQLite 方言编译（幂等，import 即生效）
    DATABASE_URL = f"sqlite+aiosqlite:///{_sqlite_db_path()}"
    engine = build_sqlite_engine(_sqlite_db_path())
    AsyncSessionLocal = build_sqlite_sessionmaker(engine)
else:
    DATABASE_URL = _DATABASE_URL_ENV

# 连接池预检配置：
# - 默认在 Windows 上禁用（asyncpg + greenlet 兼容性问题）
# - 在其他平台默认启用，避免空闲连接失效
# - 可通过环境变量 DB_POOL_PRE_PING 强制覆盖
_DEFAULT_POOL_PRE_PING = False if sys.platform == "win32" else True
POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", str(_DEFAULT_POOL_PRE_PING)).lower() in ("true", "1", "yes")

# 连接池配置说明：
# - pool_size=10: 常规连接数，支撑正常并发请求
# - max_overflow=20: 峰值时可额外创建20个连接 (共30个)
# - pool_pre_ping=True: 每次获取连接前先 ping DB，确认连接可用 (避免空闲连接失效)
# 权衡：生产环境需根据 QPS 调整，当前配置适合中小规模部署
# （SQLite 路径在上面分支用 db_sqlite.engine 构建，不经此处——NullPool 无池参数）
if not USE_SQLITE:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=POOL_PRE_PING,
        pool_size=10,
        max_overflow=20,
    )

    # 会话工厂配置：
    # - expire_on_commit=False: 提交后对象不过期，避免再次访问需刷新
    # - autocommit=False: 显式事务管理，需手动 commit/rollback
    # - autoflush=False: 延迟写入，需显式 flush 或 commit
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

Base = declarative_base()

MIGRATIONS: list[dict[str, Any]] = [
    # ---- 世界内核 v2（B1 · docs/world-kernel-foundation.md §3 决策 1）----
    {
        "table": "world_events",
        "column": "time_precision",
        "definition": "VARCHAR(16)",
        "expected_udt_names": {"varchar", "character varying"},
    },
    {
        "table": "books",
        "column": "cognition_surfacing",
        "definition": "BOOLEAN DEFAULT 1",
        "expected_udt_names": {"boolean"},
    },
    {
        "table": "world_events",
        "column": "supersedes",
        "definition": "UUID",
        "expected_udt_names": {"uuid", "CHARACTER(36)"},
    },
    {
        "table": "books",
        "column": "worldview_settings",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "characters",
        "column": "dynamic_state_history",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "draft_text",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "chapters",
        "column": "review_feedback",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "revision_count",
        "definition": "INTEGER DEFAULT 0",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "chapters",
        "column": "generation_run_id",
        "definition": "VARCHAR(64)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "chapters",
        "column": "generation_status",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "generation_checkpoints",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "summary",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "chapters",
        "column": "map_activity_range",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "chapters",
        "column": "chapter_name",
        "definition": "VARCHAR(200)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "chapters",
        "column": "status",
        "definition": "VARCHAR(50) DEFAULT 'draft'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "beat_id",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "location",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "pov_character",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "action_summary",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "worldbuilding_instruction",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "word_count_target",
        "definition": "INTEGER DEFAULT 0",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "story_beats",
        "column": "metadata",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "scene_intents",
        "column": "character_name",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "scene_intents",
        "column": "obstacle",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "scene_intents",
        "column": "tactic",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "scene_intents",
        "column": "constraints",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "plot_ledgers",
        "column": "hook_id",
        "definition": "VARCHAR(150)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "status",
        "definition": "VARCHAR(20) DEFAULT 'open'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "created_at_chapter",
        "definition": "INTEGER",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "plot_ledgers",
        "column": "metadata",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "tension_level",
        "definition": "INTEGER DEFAULT 5 NOT NULL",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "chapters",
        "column": "pacing_style",
        "definition": "VARCHAR(50) DEFAULT 'balanced' NOT NULL",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "entry_state",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "exit_state",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "red_lines",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "story_beats",
        "column": "beat_type",
        "definition": "VARCHAR(100) DEFAULT 'progression'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "position",
        "definition": "INTEGER DEFAULT 0",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "story_beats",
        "column": "status",
        "definition": "VARCHAR(50) DEFAULT 'planned'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "entry_type",
        "definition": "VARCHAR(50) DEFAULT 'foreshadow'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "plot_ledgers",
        "column": "content",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "books",
        "column": "core_motifs_taboos",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "books",
        "column": "golden_snippets",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "books",
        "column": "style_blacklist",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "story_beats",
        "column": "pacing_type",
        "definition": "VARCHAR(50)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "weight",
        "definition": "INTEGER DEFAULT 1",
        "expected_udt_names": {"int4"},
    },
    {
        "table": "story_beats",
        "column": "anchor_pov",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "original_actor",
        "definition": "VARCHAR(120)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "chapters",
        "column": "chapter_assets_schema",
        "definition": "TEXT DEFAULT ''",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "pov_perception_state",
        "definition": "TEXT DEFAULT '正常'",
        "expected_udt_names": {"text"},
    },
    # V4.0: 叙事光圈与持久状态锚点
    {
        "table": "story_beats",
        "column": "pov_aperture",
        "definition": "VARCHAR(50) DEFAULT 'subjective_observation'",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "story_beats",
        "column": "persistent_state_anchors",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    # 世界状态快照：章节发布时提取
    {
        "table": "chapters",
        "column": "world_snapshot",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    # 此刻状态：角色和场景从世界快照中提取的实时状态
    {
        "table": "characters",
        "column": "current_state",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "map_locations",
        "column": "current_state",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    # 意图驱动设置：保存用户的创作意图和生成配置
    {
        "table": "chapters",
        "column": "creative_intents",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "chapter_goals",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "selected_plan_type",
        "definition": "VARCHAR(50)",
        "expected_udt_names": {"varchar"},
    },
    {
        "table": "chapters",
        "column": "user_overrides",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "chapters",
        "column": "author_intent",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    # CP1.4：BeatSpec participants 字段（在场角色列表，供上下文引擎确定性通道与
    # 后续 EntityAuditor 使用；蓝图 §4.4.1）
    {
        "table": "story_beats",
        "column": "participants",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    # CP2.3a：书级大纲（章节卡生成输入）+ 滚动摘要（发布时更新，蓝图 §5.2）
    {
        "table": "books",
        "column": "outline",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "books",
        "column": "rolling_summary",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    # ============================================================
    # V3.0 引爆链：StoryBeat 6 个新列（节拍作为铺垫树阅读序视图）
    # ============================================================
    {
        "table": "story_beats",
        "column": "chain_node_ids",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "story_beats",
        "column": "sets_up",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "story_beats",
        "column": "payoff_of",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "story_beats",
        "column": "assignment",
        "definition": "VARCHAR(50)",
        "expected_udt_names": {"varchar", "character varying"},
    },
    {
        "table": "story_beats",
        "column": "question_open",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    {
        "table": "story_beats",
        "column": "question_delays",
        "definition": "TEXT",
        "expected_udt_names": {"text"},
    },
    # V3.0 引爆链：ChapterCard.payload_moment（章节卡生成时同步产出引爆点候选）
    {
        "table": "chapter_cards",
        "column": "payload_moment",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    # V4.2 Reader Mirror：Book 表新增 reader_mirror JSONB 字段
    # 存储期待账本 + 张力曲线 + 信息差（整体 JSONB，避免新建表）
    {
        "table": "books",
        "column": "reader_mirror",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    # BS-ADF：Track B 暂停时持久化全章槽位卡（List[BeatSlotCard] 序列化）
    # 供刷新后 / /rerender-beat 兜底恢复（内存 _PENDING_BEAT_SLOTS TTL 仅 1 小时）
    {
        "table": "chapters",
        "column": "bsadf_beat_slots",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    # NLE-ADF Loop3：ChapterEntity 涌现实体标记
    {
        "table": "chapter_entities",
        "column": "emergent",
        "definition": "BOOLEAN DEFAULT FALSE",
        "expected_udt_names": {"boolean", "bool"},
    },
    # NLE-ADF Loop3：ChapterMapLocation 涌现地点标记
    {
        "table": "chapter_map_locations",
        "column": "emergent",
        "definition": "BOOLEAN DEFAULT FALSE",
        "expected_udt_names": {"boolean", "bool"},
    },
    # 世界页 M1：章节叙事时间锚（docs/world-unified-settings.md §2.4，章节轴↔世界轴的桥）
    {
        "table": "chapters",
        "column": "narrative_time",
        "definition": "INTEGER",
        "expected_udt_names": {"int4", "integer"},
    },
    # 世界页 M2：实体档案扩展（别名/重要度/可见性）
    {
        "table": "world_entities",
        "column": "aliases",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "world_entities",
        "column": "importance",
        "definition": "INTEGER DEFAULT 1",
        "expected_udt_names": {"int4", "integer"},
    },
    {
        "table": "world_entities",
        "column": "visibility",
        "definition": "VARCHAR(20) DEFAULT 'public'",
        "expected_udt_names": {"varchar"},
    },
    # 字段级真相分层（2026-09-03）：档案单字段 公开/半露/秘密，缺键=公开
    {
        "table": "world_entities",
        "column": "field_layers",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    # 实体单分组（2026-09-03）：资产抽屉分组依据，组织元数据不进 prompt
    {
        "table": "world_entities",
        "column": "group_name",
        "definition": "VARCHAR(100)",
        "expected_udt_names": {"varchar"},
    },
    # 单一画布：实体画布锚位（无推演位置时的作者摆位）
    {
        "table": "world_entities",
        "column": "canvas_x",
        "definition": "FLOAT",
        "expected_udt_names": {"float8", "double precision", "real"},
    },
    {
        "table": "world_entities",
        "column": "canvas_y",
        "definition": "FLOAT",
        "expected_udt_names": {"float8", "double precision", "real"},
    },
    # 世界页 M3：伏笔双时间锚
    {
        "table": "plot_ledgers",
        "column": "world_time_planted",
        "definition": "INTEGER",
        "expected_udt_names": {"int4", "integer"},
    },
    {
        "table": "plot_ledgers",
        "column": "world_time_resolved",
        "definition": "INTEGER",
        "expected_udt_names": {"int4", "integer"},
    },
    # 写作桥 W5-lite：本章场景钉（切片「脚下」的第一优先级，缺省回落推演）
    {
        "table": "chapters",
        "column": "scene_location_id",
        "definition": (
            "UUID REFERENCES world_locations(id) ON DELETE SET NULL"
        ),
        "expected_udt_names": {"uuid"},
    },
    # 章级谋篇 M1（docs/chapter-planning-spine.md §2.1）：软脉络 JSONB（意图+≤5锚点，NULL=无脉络）
    {
        "table": "chapters",
        "column": "spine",
        "definition": "JSONB",
        "expected_udt_names": {"jsonb"},
    },
    # C2 信息面挂接（docs/canon-world-fusion.md §4.1）：canon_nodes 挂世界对象
    {
        "table": "canon_nodes",
        "column": "ref_type",
        "definition": "VARCHAR(20)",
        "expected_udt_names": {"varchar", "character varying"},
    },
    {
        "table": "canon_nodes",
        "column": "ref_id",
        "definition": "UUID",
        "expected_udt_names": {"uuid"},
    },
    # C2 伏笔真相面（§4.2）：canon hook 并入 plot_ledgers
    {
        "table": "plot_ledgers",
        "column": "canon_text",
        "definition": "TEXT DEFAULT ''",
        "expected_udt_names": {"text"},
    },
    {
        "table": "plot_ledgers",
        "column": "public_text",
        "definition": "TEXT DEFAULT ''",
        "expected_udt_names": {"text"},
    },
    {
        "table": "plot_ledgers",
        "column": "reveal_plan",
        "definition": "TEXT DEFAULT ''",
        "expected_udt_names": {"text"},
    },
    # D4 比例尺标定（docs/map-scale-spatial.md §2.1）：书级地图尺度锚（NULL=未标定）
    {
        "table": "books",
        "column": "map_scale",
        "definition": "JSONB",
        "expected_udt_names": {"jsonb"},
    },
    # 时间轴 UI 状态按书持久化（世界页游标+视野窗口；替代随前端端口扫描漂移的 localStorage）
    {
        "table": "books",
        "column": "timeline_view",
        "definition": "JSONB",
        "expected_udt_names": {"jsonb"},
    },
    # 学着闭嘴：被拒学习宽恕时间戳（静音集合从行为派生不落库，此列只存「恢复」锚点；
    # 见 services/adaptive/quiet_learning.py）
    {
        "table": "books",
        "column": "assist_mutes",
        "definition": "JSONB",
        "expected_udt_names": {"jsonb"},
    },
    # 系统自己去读：自动阅读的章级幂等锚（内容哈希 + 上次运行时刻；
    # 见 services/adaptive/read_budget.py）
    {
        "table": "chapters",
        "column": "auto_read_state",
        "definition": "JSONB",
        "expected_udt_names": {"jsonb"},
    },
    # 文风模块重构 S4：意图旋钮档位（{knob_key: tier 1-5}，缺键=自动档不注入）
    {
        "table": "style_cards",
        "column": "style_knobs",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    # 文风模块重构补全（完整落地批）：画像字段锁 + 指纹写穿缓存
    {
        "table": "style_cards",
        "column": "locked_keys",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    {
        "table": "style_cards",
        "column": "fingerprint",
        "definition": "JSONB DEFAULT '{}'",
        "expected_udt_names": {"jsonb"},
    },
    # 样本时期标记（语料聚合只用近期；文风会进化）+ 收藏（检索兜底优先）
    {
        "table": "author_samples",
        "column": "era",
        "definition": "VARCHAR(16) DEFAULT 'recent'",
        "expected_udt_names": {"varchar", "character varying", "text"},
    },
    {
        "table": "author_samples",
        "column": "favorite",
        "definition": "BOOLEAN DEFAULT FALSE",
        "expected_udt_names": {"bool", "boolean"},
    },
    # 系统陈词库本书豁免（三层禁词的系统层可见性 + 豁免，设计稿 §6.4）
    {
        "table": "books",
        "column": "style_cliche_exemptions",
        "definition": "JSONB DEFAULT '[]'",
        "expected_udt_names": {"jsonb"},
    },
    # 成本核算（2026-09-11）：缓存命中输入 token——历史行 NULL=厂商未回报，
    # 计价按未命中全价（保守估算），新行由 _parse_usage 双字段兼容提取
    {
        "table": "generation_runs",
        "column": "cached_tokens",
        "definition": "INTEGER",
        "expected_udt_names": {"int4", "integer"},
    },
]


async def _get_vector_dimension(conn, table_name: str, column_name: str) -> Optional[int]:
    """
    获取向量列的维度。
    
    pgvector 的 vector 类型在 udt_name 中会显示维度信息，如 'vector(1536)'
    """
    result = await conn.execute(
        text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    row = result.mappings().first()
    if row:
        udt_name = str(row.get("udt_name", ""))
        # 解析 vector(1536) 格式
        if "(" in udt_name and ")" in udt_name:
            try:
                return int(udt_name.split("(")[1].split(")")[0])
            except (ValueError, IndexError):
                pass
    return None


async def migrate_vector_dimension(
    conn,
    target_dimension: int,
    table_name: str = "memory_chunks",
    column_name: str = "embedding",
):
    """
    迁移向量列的维度。
    
    警告：这是一个破坏性操作，会删除并重建列，导致所有向量数据丢失！
    生产环境应先备份数据，迁移后再重新生成向量。
    
    Args:
        conn: 数据库连接
        target_dimension: 目标维度
        table_name: 表名
        column_name: 列名
    """
    current_dimension = await _get_vector_dimension(conn, table_name, column_name)
    
    if current_dimension is None:
        logger.warning(f"[MIGRATION] 向量列 {table_name}.{column_name} 不存在")
        return
    
    if current_dimension == target_dimension:
        logger.info(f"[MIGRATION] 向量维度已是 {target_dimension}，无需迁移")
        return
    
    logger.warning(
        f"[MIGRATION] 向量维度将从 {current_dimension} 迁移到 {target_dimension}。"
        f"这将删除所有现有向量数据！"
    )
    
    try:
        # 删除旧列
        await conn.execute(
            text(
                f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS "{column_name}";'
            )
        )
        logger.info(f"[MIGRATION] 已删除旧向量列 {table_name}.{column_name}")
        
        # 添加新列（使用目标维度）
        await conn.execute(
            text(
                f'ALTER TABLE "{table_name}" '
                f'ADD COLUMN "{column_name}" vector({target_dimension});'
            )
        )
        logger.info(f"[MIGRATION] 已创建新向量列 {table_name}.{column_name} ({target_dimension} 维)")
        
    except Exception as e:
        logger.error(f"[MIGRATION] 向量维度迁移失败: {e}")
        raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    依赖注入函数：获取数据库会话。

    用法：在 FastAPI 路由函数中通过 Depends(get_db) 注入。

    副作用：
    - 请求结束时自动关闭会话 (通过 async with 上下文管理器)
    - 提交后 connection 归还连接池

    权衡：不支持手动控制事务边界，适合简单 CRUD 场景。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def _migrate_legacy_profile_keys(conn) -> None:
    """world_entities.props.legacy_profile → props.background 一次性数据迁移（幂等）。

    M4 迁移期旧角色档案整段塞 legacy_profile 兼容位；策略定为「迁移而非兼容」后
    统一并入正经字段 background（生成上下文 _STRUCTURED_FIELDS 已覆盖），键摘除。
    跑过一次后 WHERE 不再命中，后续启动零开销；空串键只摘不并。
    """
    result = await conn.execute(
        text(
            """
            UPDATE world_entities
            SET props = jsonb_set(
                    props, '{background}',
                    to_jsonb(
                        CASE WHEN btrim(COALESCE(props->>'background', '')) <> ''
                             THEN props->>'background' || E'\\n\\n' || (props->>'legacy_profile')
                             ELSE props->>'legacy_profile'
                        END
                    )
                ) - 'legacy_profile'
            WHERE btrim(COALESCE(props->>'legacy_profile', '')) <> ''
            """
        )
    )
    if result.rowcount:
        logger.info(f"[MIGRATION] props.legacy_profile → background: {result.rowcount} entities")
    await conn.execute(
        text(
            """
            UPDATE world_entities SET props = props - 'legacy_profile'
            WHERE props ? 'legacy_profile'
              AND btrim(COALESCE(props->>'legacy_profile', '')) = ''
            """
        )
    )


async def _migrate_style_blacklist_into_negative_cards(session: AsyncSession) -> None:
    """books.style_blacklist（历史书级黑名单）→ 书级 StyleCard.negative_list 一次性数据迁移（幂等）。

    双写收敛（任务包 B）：负面清单唯一权威是 style_cards.negative_list（经
    services/style/prohibitions.py 四源合并消费），books.style_blacklist 冻结为
    只读列。迁移完成后置空书级黑名单——清空即「已迁移」标记，二跑不再命中
    非空条件（天然幂等，跑过一次后后续启动零写入）。

    策略：书行数少（单机桌面），SELECT 全部 Python 侧过滤；逐条归并
    （word 去重、已有条目无 alternative 而新条有则补全）；无书级卡的书自动
    建空卡再归并。副作用：由调用方包裹 try/except（迁移失败只 log，绝不阻断启动）。
    """
    from backend.models import Book, StyleCard

    result = await session.execute(select(Book))
    books = result.scalars().all()
    migrated_books = 0
    merged_words = 0
    for book in books:
        blacklist = getattr(book, "style_blacklist", None)
        if not isinstance(blacklist, list) or not blacklist:
            continue
        card = (
            await session.execute(
                select(StyleCard)
                .where(StyleCard.book_id == book.id, StyleCard.chapter_id.is_(None))
                .limit(1)
            )
        ).scalar_one_or_none()
        if card is None:
            card = StyleCard(book_id=book.id, negative_list=[])
            session.add(card)
        # 整体赋新列表触发 ORM 变更检测（JSONB 无 Mutable 追踪，原地改不落库）
        negative = list(card.negative_list or [])

        def _entry_word(e: Any) -> str:
            if isinstance(e, dict):
                return str(e.get("word") or e.get("phrase") or "").strip()
            if isinstance(e, str):
                return e.strip()
            return ""

        for item in blacklist:
            if isinstance(item, dict):
                word = str(item.get("word") or item.get("phrase") or "").strip()
                alt = str(item.get("alternative") or "").strip() or None
            elif isinstance(item, str):
                word = item.strip()
                alt = None
            else:
                continue
            if not word:
                continue
            existing = next((e for e in negative if isinstance(e, dict) and _entry_word(e) == word), None)
            if existing is not None:
                # 已有同 word 条目：仅当已有条目无 alternative 而新条有则补上
                if alt and not str(existing.get("alternative") or "").strip():
                    existing["alternative"] = alt
                continue
            negative.append({"word": word, "alternative": alt})
            merged_words += 1

        card.negative_list = negative
        book.style_blacklist = []  # 清空 = 已迁移标记
        migrated_books += 1

    await session.commit()
    if migrated_books:
        logger.info(
            f"[MIGRATION] books.style_blacklist → style_cards.negative_list: "
            f"{migrated_books} books / {merged_words} words"
        )


async def init_db():
    """
    初始化数据库表结构。

    执行顺序：
    1. 创建 pgvector 扩展 (向量搜索依赖)
    2. 创建所有 ORM 模型对应的表
    3. 执行列迁移 (添加缺失字段)
    4. 检查并迁移向量维度（如配置变更）

    警告：run_migrations 使用朴素的条件判断，不支持回滚。
    生产环境应使用 Alembic 或 Flyway 等专业迁移工具。
    """
    # 切换日分支：SQLite 走 db_sqlite.schema（建表+同源列迁移+legacy 数据迁移+
    # SystemCliche 种子化，全在那一侧完成）；PG 路径原样保留（含 pgvector 维度迁移）
    if USE_SQLITE:
        from backend.db_sqlite.schema import init_db_sqlite

        await init_db_sqlite(engine, AsyncSessionLocal)
        return

    from backend.models import (
        Book,
        Chapter,
        ChapterEntity,
        ChapterMapLocation,
        Asset,
        ChapterAsset,
        Character,
        CharacterRelationship,
        MapLocation,
        MemoryChunk,
        PlotLedger,
        SceneIntent,
        StoryBeat,
        GenerationRun,
        # CP2.1 新增模型
        ChapterCard,
        StyleCard,
        AuthorSample,
        SystemCliche,
        # CP3.1a 新增模型
        QualityReport,
        # V4.0 Canon（作者脑中世界图谱）
        CanonNode,
        CanonEdge,
        # V5.0 World 设定层（地图 + 时间线 + 事件溯源，独立于 Canon）
        WorldEvent,
        WorldLocation,
        WorldEntity,
        WorldRelation,
        WorldEventCandidate,
        WorldMapLayer,
        WorldMapStroke,
    )
    from backend.core.model_config import get_embedding_dimensions

    async with engine.begin() as conn:
        # 关键：pgvector 必须在使用向量类型前创建，且需超级用户权限
        # 副作用：IF NOT EXISTS 确保幂等性，但首次失败会中断启动
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)
        await _migrate_legacy_profile_keys(conn)

        # 检查并迁移向量维度
        target_dimension = get_embedding_dimensions()
        await migrate_vector_dimension(conn, target_dimension)

    # CP2.1c：SystemCliche 表种子化（首次启动检测空表则插入默认禁词）
    # 注意：种子化需要 AsyncSession（不是 engine.begin 的 conn），用独立会话
    await _seed_system_cliches_if_empty()

    # 任务包 B：books.style_blacklist → 书级 StyleCard.negative_list 迁移（幂等；
    # 失败只 log 不阻断启动——挂点在迁移事务外，用独立会话）
    try:
        async with AsyncSessionLocal() as session:
            await _migrate_style_blacklist_into_negative_cards(session)
    except Exception as e:
        logger.error(f"[MIGRATION] style_blacklist → negative_list 迁移失败（不阻断启动）: {e}")


async def _seed_system_cliches_if_empty() -> None:
    """首次启动时若 SystemCliche 表为空，从 default_cliches 种子化。

    幂等：表非空则跳过。
    """
    try:
        from backend.repositories import SystemClicheRepository
        from backend.services.style.default_cliches import get_all_seed_cliches

        async with AsyncSessionLocal() as session:
            repo = SystemClicheRepository(session)
            seeds = get_all_seed_cliches()
            inserted = await repo.seed_if_empty(seeds)
            if inserted > 0:
                logger.info(f"[INIT] SystemCliche 表已种子化 {inserted} 条默认禁词")
    except Exception as e:
        # 种子化失败不应阻断启动
        logger.warning(f"[INIT] SystemCliche 种子化失败（不阻断启动）: {e}")


async def _get_column_info(conn, table_name: str, column_name: str) -> Optional[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT data_type, udt_name, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    row = result.mappings().first()
    return dict(row) if row else None


def _is_column_compatible(column_info: dict[str, Any], migration: dict[str, Any]) -> bool:
    expected_udt_names: set[str] = migration.get("expected_udt_names", set())
    if not expected_udt_names:
        return True
    actual_udt_name = str(column_info.get("udt_name", "")).lower()
    return actual_udt_name in expected_udt_names


async def run_migrations(conn, migrations: Optional[Sequence[dict[str, Any]]] = None):
    """
    执行数据库迁移，自动添加缺失的列。

    朴素迁移策略：
    - 检查 information_schema.columns 是否存在目标列
    - 若不存在则 ALTER TABLE ADD COLUMN

    权衡：
    - 优点：无需外部工具，快速上手
    - 缺点：不支持列重命名、类型变更、数据迁移
    - 警告：多列并发添加可能产生锁竞争

    适配场景：开发阶段或字段较少的项目。
    """
    migrations = migrations or MIGRATIONS

    for migration in migrations:
        table_name = migration["table"]
        column_name = migration["column"]
        try:
            column_info = await _get_column_info(conn, table_name=table_name, column_name=column_name)
            if column_info:
                if not _is_column_compatible(column_info, migration):
                    logger.warning(
                        f"[MIGRATION] Column conflict on {table_name}.{column_name}: "
                        f"actual_type={column_info.get('udt_name')} expected={sorted(migration.get('expected_udt_names', []))}"
                    )
                continue
            await conn.execute(
                text(
                    f'ALTER TABLE "{table_name}" '
                    f'ADD COLUMN IF NOT EXISTS "{column_name}" {migration["definition"]};'
                )
            )
            logger.info(f"[MIGRATION] Added column {table_name}.{column_name}")
        except Exception as e:
            logger.warning(f"[MIGRATION] Skipped {table_name}.{column_name}: {e}")
