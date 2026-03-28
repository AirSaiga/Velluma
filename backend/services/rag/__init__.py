# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
RAG 记忆检索系统模块导出

职责：
- 统一导出 RAG 相关类型和函数
- 提供与章节生成流程的集成接口

使用方式：
    from backend.services.rag import (
        # 类型定义
        MemoryType,
        RetrievalStrategy,
        RetrievalResult,
        ContextPackage,
        
        # 检索器
        MultiTypeMemoryRetriever,
        retrieve_chapter_memories,
        
        # 上下文构建
        ContextPackagerBuilder,
        build_context_package,
        
        # 伏笔管理
        ForeshadowingTracker,
        HookOmissionDetector,
        
        # 可解释性
        generate_retrieval_report,
        explain_retrieval,
    )
"""

# =============================================================================
# 类型定义
# =============================================================================

from backend.services.rag.retrieval_types import (
    # 枚举
    MemoryType,
    RetrievalMethod,
    ContentPriority,
    ContentType,
    RetrievalStrategy,
    
    # 配置
    MemoryTypeConfig,
    RetrievalStrategyConfig,
    STRATEGY_PRESETS,
    
    # 数据结构
    RetrievalScore,
    RetrievedItem,
    RetrievalResult,
    ContextSection,
    ContextPackage,
)

# =============================================================================
# 评分系统
# =============================================================================

from backend.services.rag.scoring import (
    ScoringConfig,
    MultiDimensionScorer,
    MemoryDeduplicator,
    RetrievalSorter,
)

# =============================================================================
# 检索器
# =============================================================================

from backend.services.rag.retriever import (
    RetrievalContext,
    MultiTypeMemoryRetriever,
    retrieve_chapter_memories,
)

# =============================================================================
# 上下文构建
# =============================================================================

from backend.services.rag.context_packager import (
    ContentSummarizer,
    ContentMerger,
    ContextPackagerBuilder,
    ContextInjector,
    build_context_package,
)

# =============================================================================
# 伏笔管理
# =============================================================================

from backend.services.rag.foreshadowing import (
    HookStatus,
    HookPriority,
    HookDetectionResult,
    HookClosureCheckResult,
    ForeshadowingTracker,
    HookMemoryInjector,
    HookOmissionDetector,
    create_and_track_hook,
)

# =============================================================================
# 可解释性
# =============================================================================

from backend.services.rag.explainability import (
    ExplanationLevel,
    RetrievalExplanation,
    RetrievalReport,
    ExplanationGenerator,
    RetrievalReportGenerator,
    RetrievalStrategyRecorder,
    explain_retrieval,
    generate_retrieval_report,
)


# =============================================================================
# 与章节生成流程的集成接口
# =============================================================================

async def assemble_chapter_context(
    chapter_id: str,
    db,
    api_key: str,
    base_url: str = None,
    strategy: RetrievalStrategy = RetrievalStrategy.BALANCED_REFERENCE,
    stage: str = "drafting",
) -> tuple[ContextPackage, RetrievalResult]:
    """
    章节上下文组装接口
    
    这是与章节生成流程的主要集成点，提供完整的上下文组装功能。
    
    Args:
        chapter_id: 章节 ID
        db: 数据库会话
        api_key: API Key
        base_url: Base URL
        strategy: 检索策略
        stage: 生成阶段（planning/drafting/reviewing/refining）
    
    Returns:
        tuple[ContextPackage, RetrievalResult]: (上下文包, 检索结果)
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from backend.models import (
        Chapter, Book, ChapterEntity, CharacterRelationship,
        PlotLedger, ChapterMapLocation,
    )
    from backend.world_state_schemas import WorldTerminalState
    
    # 1. 加载基础数据
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    
    if not chapter:
        raise ValueError(f"章节不存在: {chapter_id}")
    
    book_result = await db.execute(
        select(Book).where(Book.id == chapter.book_id)
    )
    book = book_result.scalar_one_or_none()
    
    # 2. 加载角色和关系
    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = list(entities_result.scalars().all())
    
    character_ids = [e.entity_id for e in entities]
    
    if character_ids:
        relationships_result = await db.execute(
            select(CharacterRelationship)
            .options(
                selectinload(CharacterRelationship.source_character),
                selectinload(CharacterRelationship.target_character),
            )
            .where(
                CharacterRelationship.source_char_id.in_(character_ids),
                CharacterRelationship.target_char_id.in_(character_ids),
            )
        )
        relationships = list(relationships_result.scalars().all())
    else:
        relationships = []
    
    # 3. 加载开放伏笔
    hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            PlotLedger.created_at_chapter < chapter.chapter_number,
        )
    )
    open_hooks = [
        {
            "hook_id": str(h.id),
            "ledger_key": h.ledger_key or "",
            "content": h.content or "",
        }
        for h in hook_result.scalars().all()
    ]
    
    # 4. 加载上一章摘要
    previous_summary = None
    if chapter.chapter_number > 1:
        prev_result = await db.execute(
            select(Chapter).where(
                Chapter.book_id == chapter.book_id,
                Chapter.chapter_number == chapter.chapter_number - 1,
            )
        )
        prev_chapter = prev_result.scalar_one_or_none()
        if prev_chapter:
            previous_summary = prev_chapter.summary
    
    # 5. 加载世界状态
    previous_world_state = None
    if chapter.chapter_number > 1:
        prev_result = await db.execute(
            select(Chapter).where(
                Chapter.book_id == chapter.book_id,
                Chapter.chapter_number == chapter.chapter_number - 1,
            )
        )
        prev_chapter = prev_result.scalar_one_or_none()
        if prev_chapter and prev_chapter.world_snapshot:
            previous_world_state = WorldTerminalState.from_chapter_snapshot(
                prev_chapter.world_snapshot
            )
    
    # 6. 执行检索
    result = await retrieve_chapter_memories(
        chapter=chapter,
        book=book,
        db=db,
        entities=entities,
        relationships=relationships,
        open_hooks=open_hooks,
        previous_summary=previous_summary,
        previous_world_state=previous_world_state,
        strategy=strategy,
        api_key=api_key,
        base_url=base_url,
    )
    
    # 7. 构建上下文包
    package = build_context_package(result, stage=stage)
    
    return package, result


async def get_context_for_planning(
    chapter_id: str,
    db,
    api_key: str,
    base_url: str = None,
) -> ContextPackage:
    """获取规划阶段上下文"""
    package, _ = await assemble_chapter_context(
        chapter_id, db, api_key, base_url,
        strategy=RetrievalStrategy.BALANCED_REFERENCE,
        stage="planning",
    )
    return package


async def get_context_for_drafting(
    chapter_id: str,
    db,
    api_key: str,
    base_url: str = None,
) -> ContextPackage:
    """获取起草阶段上下文"""
    package, _ = await assemble_chapter_context(
        chapter_id, db, api_key, base_url,
        strategy=RetrievalStrategy.BALANCED_REFERENCE,
        stage="drafting",
    )
    return package


async def get_context_for_reviewing(
    chapter_id: str,
    db,
    api_key: str = None,
    base_url: str = None,
) -> ContextPackage:
    """获取审阅阶段上下文"""
    package, _ = await assemble_chapter_context(
        chapter_id, db, api_key, base_url,
        strategy=RetrievalStrategy.CHARACTER_FOCUSED,
        stage="reviewing",
    )
    return package


async def check_foreshadowing_omissions(
    chapter_id: str,
    chapter_text: str,
    db,
) -> list[dict]:
    """
    检查伏笔遗漏
    
    在审阅阶段调用，检测未处理的伏笔。
    
    Args:
        chapter_id: 章节 ID
        chapter_text: 章节文本
        db: 数据库会话
    
    Returns:
        list[dict]: 遗漏报告
    """
    from sqlalchemy import select
    from backend.models import Chapter
    
    # 获取章节信息
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    
    if not chapter:
        return []
    
    # 检测遗漏
    tracker = ForeshadowingTracker(db)
    detector = HookOmissionDetector(tracker)
    
    return await detector.detect_omissions(
        text=chapter_text,
        book_id=chapter.book_id,
        chapter_number=chapter.chapter_number,
    )


# =============================================================================
# 模块导出
# =============================================================================

# =============================================================================
# 增强组件导出
# =============================================================================

from backend.services.rag.enhanced_scoring import (
    EnhancedScoringConfig,
    EnhancedRetrievalScorer,
    RetrievalContextBuilder,
    OutlineKeywordExtractor,
)

from backend.services.rag.retrieval_orchestrator import (
    RetrievalOrchestrator,
    RetrievalOrchestratorConfig,
    RetrievalPhase,
    orchestrate_retrieval,
)

from backend.services.rag.smart_context_packager import (
    SmartContextPackager,
    SmartSummarizer,
    SmartMerger,
    PackagerConfig,
    build_smart_context,
)

from backend.services.rag.enhanced_foreshadowing import (
    EnhancedForeshadowingTracker,
    EnhancedHookOmissionDetector,
    EnhancedHookMemoryInjector,
    HookMetadata,
    HookDetectionResult,
    HookClosureCheckResult,
    HookScoringConfig,
    create_and_track_hook,
    get_hooks_for_chapter_context,
)

from backend.services.rag.workflow_integration import (
    WorkflowRetrievalIntegrator,
    WorkflowIntegrationConfig,
    WorkflowStage,
    RetrievalFailureMode,
    RetrievalCache,
    integrate_retrieval_with_workflow,
    prepare_planning_context,
    prepare_drafting_context,
    prepare_reviewing_context,
)


__all__ = [
    # 类型
    "MemoryType",
    "RetrievalMethod",
    "ContentPriority",
    "ContentType",
    "RetrievalStrategy",
    "MemoryTypeConfig",
    "RetrievalStrategyConfig",
    "STRATEGY_PRESETS",
    "RetrievalScore",
    "RetrievedItem",
    "RetrievalResult",
    "ContextSection",
    "ContextPackage",
    
    # 评分
    "ScoringConfig",
    "MultiDimensionScorer",
    "MemoryDeduplicator",
    "RetrievalSorter",
    
    # 检索
    "RetrievalContext",
    "MultiTypeMemoryRetriever",
    "retrieve_chapter_memories",
    
    # 上下文
    "ContentSummarizer",
    "ContentMerger",
    "ContextPackagerBuilder",
    "ContextInjector",
    "build_context_package",
    
    # 伏笔
    "HookStatus",
    "HookPriority",
    "HookDetectionResult",
    "HookClosureCheckResult",
    "ForeshadowingTracker",
    "HookMemoryInjector",
    "HookOmissionDetector",
    "create_and_track_hook",
    
    # 可解释性
    "ExplanationLevel",
    "RetrievalExplanation",
    "RetrievalReport",
    "ExplanationGenerator",
    "RetrievalReportGenerator",
    "RetrievalStrategyRecorder",
    "explain_retrieval",
    "generate_retrieval_report",
    
    # 集成接口
    "assemble_chapter_context",
    "get_context_for_planning",
    "get_context_for_drafting",
    "get_context_for_reviewing",
    "check_foreshadowing_omissions",
    
    # 增强组件
    "EnhancedScoringConfig",
    "EnhancedRetrievalScorer",
    "RetrievalContextBuilder",
    "OutlineKeywordExtractor",
    "RetrievalOrchestrator",
    "RetrievalOrchestratorConfig",
    "RetrievalPhase",
    "orchestrate_retrieval",
    "SmartContextPackager",
    "SmartSummarizer",
    "SmartMerger",
    "PackagerConfig",
    "build_smart_context",
    
    # 增强伏笔
    "EnhancedForeshadowingTracker",
    "EnhancedHookOmissionDetector",
    "EnhancedHookMemoryInjector",
    "HookMetadata",
    "HookDetectionResult",
    "HookClosureCheckResult",
    "HookScoringConfig",
    "create_and_track_hook",
    "get_hooks_for_chapter_context",
    
    # 工作流集成
    "WorkflowRetrievalIntegrator",
    "WorkflowIntegrationConfig",
    "WorkflowStage",
    "RetrievalFailureMode",
    "RetrievalCache",
    "integrate_retrieval_with_workflow",
    "prepare_planning_context",
    "prepare_drafting_context",
    "prepare_reviewing_context",
]
