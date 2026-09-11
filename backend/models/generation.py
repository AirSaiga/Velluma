# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""生成观测层：GenerationTask / GenerationRun / QualityReport（双层审计报告）。"""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

from ._common import generate_uuid, utc_now, TaskStatus


class GenerationTask(Base):
    """
    章节生成任务�?- 异步任务队列

    业务含义�?
    - 支持将章节生成任务提交到队列，异步执�?
    - 用户可立即获得任务ID，通过轮询或WebSocket获取进度
    - 支持任务取消、重试、查看历�?
    """
    __tablename__ = "generation_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    
    # 任务状�?
    status = Column(String(20), default=TaskStatus.PENDING, nullable=False)
    current_stage = Column(String(50), nullable=True)
    progress_percent = Column(Integer, default=0)
    
    # 任务配置
    config = Column(JSONB, default=dict)
    beats = Column(JSONB, default=list)
    
    # 结果数据
    partial_result = Column(Text, nullable=True)
    final_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Celery 相关
    celery_task_id = Column(String(100), nullable=True)
    retry_count = Column(Integer, default=0)
    
    # 时间�?
    submitted_at = Column(DateTime, default=utc_now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # 关联关系 - 明确指定 foreign_keys 避免歧义
    chapter = relationship("Chapter", back_populates="generation_tasks", foreign_keys=[chapter_id])
    book = relationship("Book", back_populates="generation_tasks", foreign_keys=[book_id])

    def to_dict(self) -> dict:
        """转换为字典（用于API响应）"""
        return {
            "id": str(self.id),
            "chapter_id": str(self.chapter_id),
            "book_id": str(self.book_id),
            "status": self.status,
            "current_stage": self.current_stage,
            "progress": self.progress_percent,
            "config": self.config,
            "partial_result": self.partial_result,
            "final_text": self.final_text if self.status == TaskStatus.SUCCESS else None,
            "error": self.error_message if self.status == TaskStatus.FAILED else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ============================================================
# 观测层 - GenerationRun 记录单次 LLM 调用（Phase 0 观测基础设施）
# ============================================================
# 设计意图（2.0 Phase 0）：
#   - 调研报告 §2.2-13 指出全链路零 token 计量，call_llm 丢弃 response.usage。
#   - 本表是观测层的物理载体，每章生成产出 ~15-20 行（6 拍计）。
#   - 字段 model_slot 与 2.0 三槽位（reasoning/creative/light）对齐；
#     thinking_tokens 拆分用于验证 creative 槽位 thinking 确实关闭（T3 验收）。
#   - degraded 字段承接 T5 降级显式化：所有 fallback 写入 {reason, action}。
#
# 与 Chapter.generation_run_id 的关系：
#   - chapter.generation_run_id 存的是本次生成的 run_id（字符串）
#   - 本表 run_id 列与之对齐，便于按 run 聚合查询
class GenerationRun(Base):
    """
    生成调用计量表 - 记录单次 LLM 调用的 token/耗时/模型/降级。

    业务含义：
    - 观测层核心：每章可按 stage 聚合 token 成本，产出章级成本报告
    - degraded 字段承接"失败不静默"原则（2.0 设计原则 P5）
    - thinking_tokens 拆分用于验证 creative 槽位 thinking 关闭效果

    数据流：
    - 由 services/observability/run_recorder.py 在 call_llm_with_usage 包装层写入
    - chapter_id 与 Chapter 关联，run_id 与 Chapter.generation_run_id 对齐
    """
    __tablename__ = "generation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    run_id = Column(String(64), nullable=True, index=True)
    stage = Column(String(64), nullable=False)  # planning.beats / drafting.beat_3 / stitching / reviewing / refining / publish.*
    model_slot = Column(String(32), nullable=True)  # reasoning / creative / light
    model_name = Column(String(128), nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    thinking_tokens = Column(Integer, nullable=True)  # 解析 response.usage.completion_tokens_details.reasoning_tokens
    cached_tokens = Column(Integer, nullable=True)  # 缓存命中输入 token（成本核算：prompt_tokens_details.cached_tokens / DeepSeek prompt_cache_hit_tokens；历史行 NULL=未回报）
    latency_ms = Column(Integer, nullable=True)
    degraded = Column(JSONB, nullable=True)  # {reason, action, detail?}
    created_at = Column(DateTime, default=utc_now)


created_at = Column(DateTime, default=utc_now)



# ============================================================
# Phase 2 CP3.1a 新增模型 - QualityReport 双层审计报告
# ============================================================
# 设计依据：蓝图 §4.8.3（校验引擎 QualityReport 数据载体）
#
# 业务含义：
# - 承载双层审计（CP3.1b 代码级 + CP3.1c LLM 级）的结构化结果
# - metrics 列存代码级量化指标（禁词命中率/句长 CV/对话占比/字数达标率/红线违反）
# - findings 列存 LLM 级证据链问题（severity/category/quote/offset/beat_id/detail/suggestion）
# - degraded 列承接"失败不静默"原则：审计降级时填 {reason, action}
# - verdict 三态：pass / pass_with_fixes / fail / unaudited（降级时）
#
# 数据流：
# - 由 services/validation/code_auditors.py（CP3.1b）+ llm_auditor.py（CP3.1c）写入
# - 由 routes/chapter_generation/__init__.py 的 GET /quality-report 读取（CP3.1c 加）
# - chapter_id + run_id 组合定位一次生成 run 的审计结果


class QualityReport(Base):
    """质量报告表 - 章节双层审计结构化结果（蓝图 §4.8.3）。

    业务含义：
    - 每章生成后由代码级审计（7 个 Auditor）+ LLM 级审计（证据链）产出一份报告
    - metrics 承载量化指标，供前端 QualityReportPanel 展示指标卡片
    - findings 承载证据链问题，供精修阶段（CP3.2）作为证据驱动输入
    - verdict 是最终闸门结论，影响是否进入精修/重写

    数据流：
    - 写入：CP3.1b/CP3.1c 审计流程通过 QualityReportRepository.create() 写入
    - 读取：GET /api/chapters/{id}/quality-report（CP3.1c）+ 精修阶段（CP3.2）
    - 关联：chapter_id 指向被审计章节；run_id 与 Chapter.generation_run_id 对齐，
      便于按生成 run 聚合查询
    """
    __tablename__ = "quality_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(String(64), nullable=True, index=True)
    # 量化指标（代码级审计产出，蓝图 §4.8.1）
    # 示例：{"cliche_hits_per_1k": 0.4, "sentence_len_cv": 0.62,
    #        "dialogue_ratio": 0.31, "word_achieve_rate": 0.97, "red_line_violations": 0}
    metrics = Column(JSONB, default=dict)
    # 发现的问题（LLM 审计产出，带证据链）
    # 每项：{"severity": "blocker|warning|info", "category": "timeline|characterization|
    #        worldview|fact|style", "quote": "原文引用", "offset": [start, end],
    #        "beat_id": int|null, "detail": "...", "suggestion": "..."}
    findings = Column(JSONB, default=list)
    # 降级标记（CP3.1c 审计降级时填充）：{reason, action, detail?}
    degraded = Column(JSONB, nullable=True)
    # 审计结论：pass / pass_with_fixes / fail / unaudited（降级时）
    verdict = Column(String(50))
    created_at = Column(DateTime, default=utc_now)


