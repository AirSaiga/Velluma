# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""文风体系层：ChapterCard / StyleCard / AuthorSample / SystemCliche / StyleInboxItem。"""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

from ._common import generate_uuid, utc_now


# ============================================================
# Phase 1 CP2.1 新增模型 - 文风体系 / 章节卡 / 作者样本 / 系统禁词
# ============================================================
# 设计依据：蓝图 §4.1.3（ChapterCard）、§4.4（StyleCard）、§5.1（AuthorSample）、
# §4.4 禁词表（SystemCliche 替代 validators.py 硬编码）


class ChapterCard(Base):
    """章节卡 - 章节间胶水（蓝图 §4.1.3）。

    业务含义：
    - 填补 Sudowrite 缺失的 chapter glue：每章一张，记录本章 purpose + 必达事件
    - CP2.3 合并闸门的核心数据载体（卡 + 节拍联合预览）
    - 形成章节卡链：任意时刻可回答"第 N 章时剧情进展到哪"

    状态流转：
    - draft: AI 生成或人工创建后待确认
    - confirmed: 用户确认（CP2.3 合并闸门）
    - generating: 进入生成主流程
    - done: 章节定稿
    """
    __tablename__ = "chapter_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    chapter_number = Column(Integer, nullable=False)
    purpose = Column(Text, nullable=True)                       # 一句话主旨（场景化语言）
    must_hit_events = Column(JSONB, default=list)               # [{"event","emotion","must"}]
    involved_characters = Column(JSONB, default=list)           # [{"id","entry","exit"}]
    foreshadow_ops = Column(JSONB, default=list)                # [{"action","ledger_id","note"}]
    continuity = Column(JSONB, default=dict)                    # {"from_chapter","time_gap","location"}
    word_target = Column(Integer, default=3000)
    pacing = Column(String(50), default="medium")
    tension = Column(Integer, default=5)
    style_override_id = Column(UUID(as_uuid=True), ForeignKey("style_cards.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="draft")
    # V3.0 引爆链：章节卡生成时同步产出的引爆点候选列表（闸门 1 的输入）
    # 结构：[{"description", "emotional_target", "answers_question", "opens_question", "why_now"}]
    payload_moment = Column(JSONB, default=list)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class StyleCard(Base):
    """文风卡 - 书级一张 + 章级可覆盖（蓝图 §4.4）。

    业务含义：
    - 正面画像（positive_profile）：句长节奏 / 词汇层级 / 语域 / 开头结尾习惯
    - 负面清单（negative_list）：禁词 / 禁句式 + 每条替代规则
    - chapter_id=null → 书级（默认）；非 null → 章级覆盖
    """
    __tablename__ = "style_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    positive_profile = Column(JSONB, default=dict)
    negative_list = Column(JSONB, default=list)                 # [{word, alternative, severity: warning|blocker}]（severity 缺省=warning，旧数据零迁移）
    dialogue_ratio_target = Column(Float, nullable=True)        # 对话占比目标（0-1）
    paragraph_rhythm = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    # 意图旋钮档位（S4）：{knob_key: tier 1-5}——register/rhythm/density/warmth；
    # 缺键 = 自动档（不注入该维度，交给画像与样本）。对话旋钮落 dialogue_ratio_target 不在此。
    style_knobs = Column(JSONB, default=dict)
    # 画像字段锁（完整落地批）：positive_profile 中被作者锁定的键名列表——
    # 锁定字段不被「从样本提炼」结果覆盖（特殊文体/亲笔描述的保护，设计稿 §6.6）
    locked_keys = Column(JSONB, default=list)
    # 指纹写穿缓存：GET /style-fingerprint 计算后回写（读路径仍实时算保新鲜，
    # 此列供未来消费方如漂移提醒直接取用，非读缓存）
    fingerprint = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class AuthorSample(Base):
    """作者样本库 - few-shot 文风锚定（蓝图 §5.1）。

    业务含义：
    - 用户上传的作者已写文本（或从已发布章节提取）
    - 向量化后供 ContextEngine P0 检索做 few-shot（蓝图 §4.3.2）
    - 与 MemoryChunk 区分：本表是"写作风格检索"，无时间衰减，无 PlotLedger 权重

    数据流：
    - 写入：POST /api/books/{id}/samples 或自动从已发布章节提取
    - 向量化：保存时调 embedding 入库
    - 检索：ContextEngine 用本章 outline 做 embedding → cosine 检索 top-k
    """
    __tablename__ = "author_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    scene_type = Column(String(50), default="general")          # dialogue/action/lyrical/suspense/general
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    word_count = Column(Integer, default=0)
    source = Column(String(50), default="manual")               # manual/golden_snippet/published_chapter
    # 时期标记（完整落地批）：recent=近期（语料聚合与检索兜底优先）/ early=早期（仅存档与逐条指纹）
    era = Column(String(16), default="recent")
    # 收藏（完整落地批）：检索兜底流优先取收藏样本（作者认证的最佳示范）
    favorite = Column(Boolean, default=False)
    # 归属维度（全局笔迹库批）：book=仅本书（默认）/ global=我的笔迹库（全库可用）。
    # 存量门票（favorite=1 或 source=golden_snippet）由启动迁移自动升为 global；
    # adopted_ghost 禁止 global（创建/修改 422——防 AI 学 AI 跨库扩散）。
    # nullable 列 + Python 侧默认：迁移路径以 NULL 为「未迁移」标记（幂等锚）。
    scope = Column(String(10), default="book")
    created_at = Column(DateTime, default=utc_now)


class SystemCliche(Base):
    """系统级禁词表 - 替代 validators.py 硬编码（蓝图 §4.4）。

    业务含义：
    - 内置默认禁词表（CP2.1c 种子化），含中英双语
    - 与 book.style_blacklist（书级）+ style_card.negative_list（书级 StyleCard）三层合并
    - severity=blocker 的硬阻断 fail-fast；warning 的仅记日志

    数据流：
    - 启动时若表为空，从 services/style/default_cliches.py 种子化
    - 用户可全局 CRUD 覆盖（POST/PUT/DELETE /api/system/cliches）
    - validators.StyleClicheValidator 通过 cliche_provider 读此表（带内存缓存）
    """
    __tablename__ = "system_cliches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    pattern = Column(String(200), nullable=False)               # 字面词或正则
    is_regex = Column(Boolean, default=False)
    language = Column(String(10), default="zh")                 # zh/en
    category = Column(String(50), default="cliche")             # cliche/house_voice/transition
    severity = Column(String(20), default="warning")            # warning/blocker
    alternative = Column(Text, nullable=True)                   # 替代建议
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class StyleInboxItem(Base):
    """文风收件箱 - 候选池（文风模块重构 S3，docs/style-module-redesign.md §5/§7.1）。

    业务含义：
    - 写作台「这不像我」/ 负面清单抓虫等产生的**候选**，先进收件箱待作者过目，
      绝不直接生效（红线：候选不落库生效，作者裁决即闸门）
    - 与 world_event_candidates 同构的物理隔离候选池（✓/✗/撤销契约）
    - confirm 负面候选 → 写入书级 StyleCard.negative_list（任务包 B 起不再
      同步 book.style_blacklist——该列冻结只读，负面清单唯一权威）

    kind 语义：
    - negative_candidate  禁词候选 {word, alternative?, source_text?}
    - sample_candidate    样本候选 {content, scene_type?}（预留，黄金片段自动汇入可走此）
    """
    __tablename__ = "style_inbox_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(50), default="negative_candidate")     # negative_candidate / sample_candidate
    payload = Column(JSONB, default=dict)                       # kind 对应的结构化载荷
    status = Column(String(20), default="pending")              # pending / confirmed / dismissed
    source = Column(String(50), default="writing_desk")         # writing_desk / scan / audit
    created_at = Column(DateTime, default=utc_now)
    resolved_at = Column(DateTime, nullable=True)


