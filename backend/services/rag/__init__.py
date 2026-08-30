# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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

子模块：
- retrieval_types: 类型定义
- scoring / enhanced_scoring: 评分系统
- retriever: 检索器
- context_packager: 上下文构建
- foreshadowing_types: 伏笔类型定义
- foreshadowing_tracker: 伏笔追踪（增强版）
- foreshadowing_detector: 伏笔检测器（增强版）
- enhanced_foreshadowing: 伏笔便捷函数
- explainability: 可解释性
- context_assembly: 章节上下文组装接口
- retrieval_orchestrator: 检索编排
- smart_context_packager: 智能上下文打包
- workflow_integration: 工作流集成
"""

from backend.services.rag.retrieval_types import (
    MemoryType,
    RetrievalMethod,
    ContentPriority,
    ContentType,
    RetrievalStrategy,
    MemoryTypeConfig,
    RetrievalStrategyConfig,
    STRATEGY_PRESETS,
    RetrievalScore,
    RetrievedItem,
    RetrievalResult,
    ContextSection,
    ContextPackage,
)

from backend.services.rag.scoring import (
    ScoringConfig,
    MultiDimensionScorer,
    MemoryDeduplicator,
    RetrievalSorter,
)

from backend.services.rag.retriever import (
    RetrievalContext,
    MultiTypeMemoryRetriever,
    retrieve_chapter_memories,
)

from backend.services.rag.context_packager import (
    ContentSummarizer,
    ContentMerger,
    ContextPackagerBuilder,
    ContextInjector,
    build_context_package,
)

from backend.services.rag.foreshadowing_types import (
    HookStatus,
    HookPriority,
    HookClosureType,
    HookMetadata,
    HookDetectionResult,
    HookClosureCheckResult,
    HookScoringConfig,
)

from backend.services.rag.foreshadowing_tracker import (
    EnhancedForeshadowingTracker,
)

from backend.services.rag.foreshadowing_detector import (
    EnhancedHookOmissionDetector,
    EnhancedHookMemoryInjector,
)

from backend.services.rag.enhanced_foreshadowing import (
    create_and_track_hook,
    get_hooks_for_chapter_context,
)

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

from backend.services.rag.context_assembly import (
    assemble_chapter_context,
    get_context_for_planning,
    get_context_for_drafting,
    get_context_for_reviewing,
    check_foreshadowing_omissions,
)

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

    "ScoringConfig",
    "MultiDimensionScorer",
    "MemoryDeduplicator",
    "RetrievalSorter",

    "RetrievalContext",
    "MultiTypeMemoryRetriever",
    "retrieve_chapter_memories",

    "ContentSummarizer",
    "ContentMerger",
    "ContextPackagerBuilder",
    "ContextInjector",
    "build_context_package",

    "HookStatus",
    "HookPriority",
    "HookClosureType",
    "HookMetadata",
    "HookDetectionResult",
    "HookClosureCheckResult",
    "HookScoringConfig",

    "EnhancedForeshadowingTracker",
    "EnhancedHookOmissionDetector",
    "EnhancedHookMemoryInjector",
    "create_and_track_hook",
    "get_hooks_for_chapter_context",

    "ExplanationLevel",
    "RetrievalExplanation",
    "RetrievalReport",
    "ExplanationGenerator",
    "RetrievalReportGenerator",
    "RetrievalStrategyRecorder",
    "explain_retrieval",
    "generate_retrieval_report",

    "assemble_chapter_context",
    "get_context_for_planning",
    "get_context_for_drafting",
    "get_context_for_reviewing",
    "check_foreshadowing_omissions",

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
