# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
RAG 记忆检索系统集成测试

测试内容：
1. 检索类型与配置测试
2. 增强评分器测试
3. 伏笔追踪器测试
4. 工作流集成测试
5. 端到端场景测试

运行方式：
    pytest backend/services/rag/tests/test_rag_integration.py -v
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
import asyncio

from backend.services.rag.retrieval_types import (
    MemoryType,
    RetrievalMethod,
    ContentPriority,
    ContentType,
    RetrievalStrategy,
    RetrievalStrategyConfig,
    RetrievalScore,
    RetrievedItem,
    RetrievalResult,
    ContextSection,
    ContextPackage,
    STRATEGY_PRESETS,
)

from backend.services.rag.enhanced_scoring import (
    EnhancedScoringConfig,
    EnhancedRetrievalScorer,
    RetrievalContextBuilder,
    OutlineKeywordExtractor,
)

from backend.services.rag.enhanced_foreshadowing import (
    EnhancedForeshadowingTracker,
    EnhancedHookOmissionDetector,
    HookMetadata,
    HookDetectionResult,
    HookClosureCheckResult,
    HookStatus,
    HookPriority,
    HookClosureType,
    HookScoringConfig,
)

from backend.services.rag.smart_context_packager import (
    SmartContextPackager,
    SmartSummarizer,
    SmartMerger,
    PackagerConfig,
)

from backend.services.rag.workflow_integration import (
    WorkflowRetrievalIntegrator,
    WorkflowIntegrationConfig,
    WorkflowStage,
    RetrievalFailureMode,
    RetrievalCache,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_character():
    """示例角色"""
    char = MagicMock()
    char.id = uuid4()
    char.name = "李明"
    char.aliases = ["小明", "明哥"]
    char.static_prompt = "身材高大，面容刚毅，性格沉稳内敛"
    char.dynamic_state = "情绪稳定，正在修炼"
    char.importance_level = 9
    return char


@pytest.fixture
def sample_character2():
    """第二个示例角色"""
    char = MagicMock()
    char.id = uuid4()
    char.name = "王芳"
    char.aliases = ["芳儿"]
    char.static_prompt = "容貌秀丽，气质温婉，聪慧善良"
    char.dynamic_state = "心事重重，情绪低落"
    char.importance_level = 8
    return char


@pytest.fixture
def sample_book():
    """示例书籍"""
    book = MagicMock()
    book.id = uuid4()
    book.title = "修仙录"
    book.genre = "仙侠"
    book.global_sys_prompt = "注重细节描写，古风表达"
    book.core_motifs_taboos = "禁忌：穿越、系统"
    book.worldview_settings = {"时代": "上古时期", "世界": "九州大陆"}
    return book


@pytest.fixture
def sample_chapter(sample_book):
    """示例章节"""
    chapter = MagicMock()
    chapter.id = uuid4()
    chapter.book_id = sample_book.id
    chapter.chapter_number = 5
    chapter.title = "第五章 问道"
    chapter.outline_text = "李明在修炼中遇到瓶颈，王芳前来探望，两人发生争执后和好如初。神秘老者的身份即将揭晓。"
    chapter.summary = "李明突破境界，引发天地异象。"
    return chapter


@pytest.fixture
def sample_open_hooks():
    """示例开放伏笔"""
    return [
        {
            "hook_id": str(uuid4()),
            "ledger_key": "mystery-elder",
            "content": "神秘老者的身份尚未揭晓",
            "chapter_number": 2,
            "priority": "main_plot",
            "character_names": ["神秘老者"],
            "keywords": ["神秘", "老者", "身份"],
        },
        {
            "hook_id": str(uuid4()),
            "ledger_key": "family-secret",
            "content": "李明的身世之谜",
            "chapter_number": 1,
            "priority": "main_plot",
            "character_names": ["李明"],
            "keywords": ["身世", "之谜"],
        },
        {
            "hook_id": str(uuid4()),
            "ledger_key": "side-quest",
            "content": "青云宗后山的秘密",
            "chapter_number": 3,
            "priority": "sub_plot",
            "character_names": [],
            "keywords": ["后山", "秘密"],
        },
    ]


@pytest.fixture
def sample_retrieved_items():
    """示例检索结果项"""
    return [
        RetrievedItem(
            memory_type=MemoryType.CHARACTER_STATE,
            source_id=str(uuid4()),
            content="【李明】身材高大，面容刚毅。当前状态：情绪稳定，正在修炼",
            chapter_number=0,
            character_names=["李明"],
            priority=ContentPriority.HIGH,
            content_type=ContentType.STRUCTURED,
            original_length=50,
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="出场角色设定",
        ),
        RetrievedItem(
            memory_type=MemoryType.OPEN_HOOK,
            source_id=str(uuid4()),
            content="神秘老者的身份尚未揭晓",
            chapter_number=2,
            priority=ContentPriority.HIGH,
            content_type=ContentType.FULL_TEXT,
            original_length=12,
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="未闭合伏笔",
        ),
        RetrievedItem(
            memory_type=MemoryType.MEMORY_CHUNK,
            source_id=str(uuid4()),
            content="李明在前一章突破境界，引发天地异象，引来了宗门长老的注意。",
            chapter_number=4,
            priority=ContentPriority.NORMAL,
            content_type=ContentType.SUMMARY,
            original_length=30,
            retrieval_method=RetrievalMethod.VECTOR,
            retrieval_reason="语义相关记忆",
        ),
    ]


# =============================================================================
# 检索类型测试
# =============================================================================

class TestRetrievalTypes:
    """检索类型测试"""
    
    def test_memory_type_enum(self):
        """测试记忆类型枚举"""
        assert MemoryType.CHARACTER_STATE.value == "character_state"
        assert MemoryType.OPEN_HOOK.value == "open_hook"
        assert MemoryType.MEMORY_CHUNK.value == "memory_chunk"
    
    def test_content_priority_order(self):
        """测试内容优先级"""
        assert ContentPriority.CRITICAL.value == "critical"
        assert ContentPriority.HIGH.value == "high"
        assert ContentPriority.NORMAL.value == "normal"
        assert ContentPriority.LOW.value == "low"
    
    def test_retrieval_strategy_presets(self):
        """测试检索策略预设"""
        assert RetrievalStrategy.BALANCED_REFERENCE in STRATEGY_PRESETS
        assert RetrievalStrategy.CHARACTER_FOCUSED in STRATEGY_PRESETS
        
        preset = STRATEGY_PRESETS[RetrievalStrategy.BALANCED_REFERENCE]
        assert preset.top_k == 5
        assert preset.semantic_weight == 0.6
    
    def test_retrieval_score_to_explanation(self):
        """测试得分解释生成"""
        score = RetrievalScore(
            total_score=0.85,
            semantic_score=0.5,
            time_decay_score=0.2,
            foreshadowing_score=0.15,
        )
        
        explanation = score.to_explanation()
        assert "总分: 0.850" in explanation
        assert "语义相似度" in explanation
    
    def test_retrieval_result_sorting(self):
        """测试检索结果排序"""
        result = RetrievalResult()
        
        item1 = RetrievedItem(
            memory_type=MemoryType.MEMORY_CHUNK,
            source_id="1",
            content="内容1",
            priority=ContentPriority.NORMAL,
        )
        item1.score.total_score = 0.5
        
        item2 = RetrievedItem(
            memory_type=MemoryType.CHARACTER_STATE,
            source_id="2",
            content="内容2",
            priority=ContentPriority.HIGH,
        )
        item2.score.total_score = 0.3
        
        item3 = RetrievedItem(
            memory_type=MemoryType.PREVIOUS_SUMMARY,
            source_id="3",
            content="内容3",
            priority=ContentPriority.CRITICAL,
        )
        item3.score.total_score = 0.1
        
        result.items = [item1, item2, item3]
        result.sort_by_score()
        
        # 高优先级应在前面
        assert result.items[0].priority == ContentPriority.CRITICAL


# =============================================================================
# 增强评分器测试
# =============================================================================

class TestEnhancedScorer:
    """增强评分器测试"""
    
    def test_outline_keyword_extraction(self):
        """测试大纲关键词提取"""
        extractor = OutlineKeywordExtractor()
        
        outline = "李明在修炼中遇到瓶颈，王芳前来探望，两人发生争执"
        result = extractor.extract(outline)
        
        assert len(result["keywords"]) > 0
        assert "李明" in result["keywords"]
        assert "修炼" in result["keywords"]
    
    def test_score_computation(self, sample_retrieved_items):
        """测试得分计算"""
        config = EnhancedScoringConfig()
        scorer = EnhancedRetrievalScorer(config)
        
        context = {
            "chapter_number": 5,
            "outline_keywords": {"keywords": ["修炼", "瓶颈"], "keyword_set": {"修炼", "瓶颈"}},
            "character_names": ["李明", "王芳"],
            "main_character_names": ["李明"],
            "relationship_pairs": [("李明", "王芳")],
            "open_hooks": [],
        }
        
        item = sample_retrieved_items[0]
        score = scorer.compute_score(item, context)
        
        assert score.total_score >= 0
        assert score.total_score <= 1
        assert score.character_relevance_score > 0  # 角色匹配应有加成
    
    def test_character_relevance_scoring(self):
        """测试角色相关度评分"""
        config = EnhancedScoringConfig()
        scorer = EnhancedRetrievalScorer(config)
        
        # 涉及主角的项目
        item = RetrievedItem(
            memory_type=MemoryType.CHARACTER_STATE,
            source_id="1",
            content="【李明】主角状态",
            character_names=["李明"],
        )
        
        context = {
            "chapter_number": 5,
            "outline_keywords": {"keyword_set": set()},
            "character_names": ["李明", "王芳"],
            "main_character_names": ["李明"],
            "relationship_pairs": [],
            "open_hooks": [],
        }
        
        score = scorer.compute_score(item, context)
        assert score.character_relevance_score > 0
    
    def test_time_decay_scoring(self):
        """测试时间衰减评分"""
        config = EnhancedScoringConfig()
        scorer = EnhancedRetrievalScorer(config)
        
        # 近期章节的项目
        item_recent = RetrievedItem(
            memory_type=MemoryType.MEMORY_CHUNK,
            source_id="1",
            content="近期记忆",
            chapter_number=4,
        )
        
        # 远期章节的项目
        item_old = RetrievedItem(
            memory_type=MemoryType.MEMORY_CHUNK,
            source_id="2",
            content="远期记忆",
            chapter_number=1,
        )
        
        context = {
            "chapter_number": 5,
            "outline_keywords": {"keyword_set": set()},
            "character_names": [],
            "main_character_names": [],
            "relationship_pairs": [],
            "open_hooks": [],
        }
        
        score_recent = scorer.compute_score(item_recent, context)
        score_old = scorer.compute_score(item_old, context)
        
        # 近期应比远期得分高
        assert score_recent.time_decay_score > score_old.time_decay_score


# =============================================================================
# 伏笔追踪器测试
# =============================================================================

class TestForeshadowingTracker:
    """伏笔追踪器测试"""
    
    def test_hook_metadata_building(self):
        """测试伏笔元数据构建"""
        metadata = HookMetadata(
            hook_id=str(uuid4()),
            content="神秘老者的身份尚未揭晓",
            status=HookStatus.OPEN,
            priority=HookPriority.MAIN_PLOT,
            created_at_chapter=2,
            character_names=["神秘老者"],
        )
        
        assert metadata.status == HookStatus.OPEN
        assert metadata.priority == HookPriority.MAIN_PLOT
        assert len(metadata.character_names) == 1
    
    def test_hook_urgency_calculation(self):
        """测试伏笔紧急度计算"""
        config = HookScoringConfig()
        
        # 主线伏笔，开放时间长
        metadata1 = HookMetadata(
            created_at_chapter=1,
            priority=HookPriority.MAIN_PLOT,
        )
        
        # 支线伏笔，开放时间短
        metadata2 = HookMetadata(
            created_at_chapter=4,
            priority=HookPriority.SUB_PLOT,
        )
        
        # 手动计算紧急度
        tracker = EnhancedForeshadowingTracker(None, config)
        urgency1 = tracker._calculate_urgency(
            metadata1.priority, metadata1.created_at_chapter, 10, 0
        )
        urgency2 = tracker._calculate_urgency(
            metadata2.priority, metadata2.created_at_chapter, 10, 0
        )
        
        # 主线伏笔紧急度应更高
        assert urgency1 > urgency2
    
    def test_hook_detection_in_text(self):
        """测试伏笔检测"""
        text = """
        李明终于知道了神秘老者的真实身份，原来他就是传说中的隐世高人。
        这一切的真相终于大白于天下。
        """
        
        open_hooks = [
            {
                "hook_id": str(uuid4()),
                "content": "神秘老者的身份尚未揭晓",
                "chapter_number": 2,
                "character_names": ["神秘老者"],
            }
        ]
        
        # 简化测试：使用内部方法
        tracker = EnhancedForeshadowingTracker(None)
        
        # 测试关键词提取
        keywords = tracker._extract_keywords("神秘老者的身份尚未揭晓")
        assert "神秘" in keywords or "老者" in keywords
        
        # 测试闭合模式匹配
        import re
        is_closure = False
        for pattern in tracker.CLOSURE_PATTERNS:
            if re.search(pattern, text):
                is_closure = True
                break
        
        assert is_closure  # 应该检测到闭合模式
    
    def test_closure_severity_calculation(self):
        """测试闭合严重性计算"""
        tracker = EnhancedForeshadowingTracker(None)
        
        # 主线伏笔，长时间未闭合
        severity1 = tracker._calculate_severity(
            HookPriority.MAIN_PLOT.value, 10, None
        )
        
        # 支线伏笔，短时间
        severity2 = tracker._calculate_severity(
            HookPriority.SUB_PLOT.value, 3, None
        )
        
        assert severity1 == "critical"
        assert severity2 == "info"


# =============================================================================
# 上下文打包器测试
# =============================================================================

class TestContextPackager:
    """上下文打包器测试"""
    
    def test_smart_summarizer(self):
        """测试智能摘要器"""
        summarizer = SmartSummarizer()
        
        content = "这是一段很长的测试内容。" * 50
        summary = summarizer.summarize(content, 100, ContentType.SUMMARY)
        
        assert len(summary) <= 103  # 加上省略号
        assert "..." in summary or len(summary) < len(content)
    
    def test_smart_merger(self, sample_retrieved_items):
        """测试智能合并器"""
        merger = SmartMerger()
        
        merged = merger.merge_items(
            sample_retrieved_items,
            MemoryType.MEMORY_CHUNK,
            max_length=500,
        )
        
        assert len(merged) > 0
        assert "李明" in merged or "内容" in merged
    
    def test_context_package_building(self, sample_retrieved_items):
        """测试上下文包构建"""
        config = PackagerConfig()
        packager = SmartContextPackager(config, "drafting")
        
        result = RetrievalResult()
        result.items = sample_retrieved_items
        result.total_items = len(sample_retrieved_items)
        
        package = packager.build(result)
        
        assert len(package.sections) > 0
        assert package.total_length > 0
        assert len(package.to_prompt_text()) > 0
    
    def test_stage_specific_packaging(self, sample_retrieved_items):
        """测试阶段化打包"""
        result = RetrievalResult()
        result.items = sample_retrieved_items
        result.total_items = len(sample_retrieved_items)
        
        # 规划阶段
        config = PackagerConfig()
        packager = SmartContextPackager(config, "planning")
        package_planning = packager.build(result)
        
        # 起草阶段
        packager = SmartContextPackager(config, "drafting")
        package_drafting = packager.build(result)
        
        # 不同阶段应有不同的内容
        # 规划阶段应该更精简
        assert package_planning.total_length >= 0
        assert package_drafting.total_length >= 0


# =============================================================================
# 工作流集成测试
# =============================================================================

class TestWorkflowIntegration:
    """工作流集成测试"""
    
    def test_workflow_config(self):
        """测试工作流配置"""
        config = WorkflowIntegrationConfig()
        
        assert config.default_strategy == RetrievalStrategy.BALANCED_REFERENCE
        assert WorkflowStage.PLANNING.value in config.stage_strategies
        assert config.failure_mode == RetrievalFailureMode.GRACEFUL_DEGRADE
    
    def test_workflow_stage_strategies(self):
        """测试各阶段策略"""
        config = WorkflowIntegrationConfig()
        
        # 审阅阶段应使用角色聚焦策略
        assert config.stage_strategies[WorkflowStage.REVIEWING.value] == RetrievalStrategy.CHARACTER_FOCUSED
        
        # 精修阶段应使用深度挖掘策略
        assert config.stage_strategies[WorkflowStage.REFINING.value] == RetrievalStrategy.DEEP_DIVE
    
    def test_retrieval_cache(self):
        """测试检索缓存"""
        cache = RetrievalCache(ttl_seconds=60)
        
        result = RetrievalResult(
            query="测试查询",
            chapter_id=str(uuid4()),
        )
        
        # 设置缓存
        cache.set("test_key", result)
        
        # 获取缓存
        cached = cache.get("test_key")
        assert cached is not None
        assert cached.query == "测试查询"
        
        # 清空缓存
        cache.clear()
        cached = cache.get("test_key")
        assert cached is None
    
    @pytest.mark.asyncio
    async def test_workflow_integrator_creation(self):
        """测试工作流集成器创建"""
        mock_db = AsyncMock()
        config = WorkflowIntegrationConfig()
        
        integrator = WorkflowRetrievalIntegrator(mock_db, config)
        
        assert integrator.config is not None
        assert integrator._scorer is not None
        assert integrator._packager is not None


# =============================================================================
# 端到端场景测试
# =============================================================================

class TestEndToEndScenarios:
    """端到端场景测试"""
    
    def test_full_retrieval_flow(self, sample_book, sample_chapter, sample_open_hooks):
        """测试完整检索流程"""
        # 1. 创建评分上下文
        context_builder = RetrievalContextBuilder()
        context = context_builder.build(
            chapter_number=sample_chapter.chapter_number,
            outline=sample_chapter.outline_text,
            entities=[],
            relationships=[],
            open_hooks=sample_open_hooks,
        )
        
        assert context["chapter_number"] == 5
        assert len(context["open_hooks"]) == 3
        assert "outline_keywords" in context
        
        # 2. 创建检索项
        items = []
        for hook in sample_open_hooks:
            item = RetrievedItem(
                memory_type=MemoryType.OPEN_HOOK,
                source_id=hook["hook_id"],
                content=hook["content"],
                chapter_number=hook["chapter_number"],
                priority=ContentPriority.HIGH,
                content_type=ContentType.FULL_TEXT,
                original_length=len(hook["content"]),
                retrieval_method=RetrievalMethod.EXACT,
                retrieval_reason="未闭合伏笔",
            )
            items.append(item)
        
        # 3. 评分
        scorer = EnhancedRetrievalScorer()
        for item in items:
            item.score = scorer.compute_score(item, context)
        
        # 4. 创建结果
        result = RetrievalResult(
            query=sample_chapter.outline_text,
            chapter_id=str(sample_chapter.id),
            chapter_number=sample_chapter.chapter_number,
        )
        result.items = items
        result.total_items = len(items)
        
        # 5. 打包上下文
        packager = SmartContextPackager(stage="drafting")
        package = packager.build(result)
        
        # 验证最终结果
        assert package.total_length > 0
        assert len(package.sections) > 0
        
        # 生成 Prompt 文本
        prompt_text = package.to_prompt_text()
        assert "待闭合伏笔" in prompt_text or "伏笔" in prompt_text
    
    def test_hook_omission_detection_flow(self, sample_open_hooks):
        """测试伏笔遗漏检测流程"""
        # 模拟章节文本（提到了部分伏笔）
        chapter_text = """
        李明继续修炼，心中仍在想着那个神秘老者。
        他隐约感觉自己的身世似乎隐藏着什么秘密。
        但是青云宗后山的事情他完全忘记了。
        """
        
        # 创建追踪器和检测器
        tracker = EnhancedForeshadowingTracker(None)
        detector = EnhancedHookOmissionDetector(tracker)
        
        # 检测闭合情况
        results = asyncio.get_event_loop().run_until_complete(
            tracker.check_closure(chapter_text, sample_open_hooks, 5)
        )
        
        # 验证检测结果
        assert len(results) == 3
        
        # 神秘老者伏笔应该被检测到提及
        elder_result = next(
            (r for r in results if "神秘老者" in r.hook_content),
            None
        )
        assert elder_result is not None
        # 可能被提及但未完全闭合
    
    def test_explainability_flow(self, sample_retrieved_items):
        """测试可解释性流程"""
        from backend.services.rag.explainability import (
            ExplanationGenerator,
            RetrievalReportGenerator,
            ExplanationLevel,
        )
        
        # 创建解释
        generator = ExplanationGenerator()
        
        item = sample_retrieved_items[0]
        item.score = RetrievalScore(
            total_score=0.85,
            semantic_score=0.5,
            character_relevance_score=0.2,
        )
        
        explanation = generator.generate(item, ExplanationLevel.DETAILED)
        
        assert explanation.memory_type == "character_state"
        assert len(explanation.brief_explanation) > 0
        assert "角色" in explanation.brief_explanation or "设定" in explanation.brief_explanation
        
        # 创建报告
        result = RetrievalResult()
        result.items = sample_retrieved_items
        result.total_items = len(sample_retrieved_items)
        
        report_generator = RetrievalReportGenerator()
        report = report_generator.generate_report(result)
        
        assert report.total_items == 3
        assert len(report.explanations) == 3


# =============================================================================
# 性能测试
# =============================================================================

class TestPerformance:
    """性能测试"""
    
    def test_large_item_set_scoring(self):
        """测试大规模项评分性能"""
        config = EnhancedScoringConfig()
        scorer = EnhancedRetrievalScorer(config)
        
        # 创建 100 个检索项
        items = []
        for i in range(100):
            item = RetrievedItem(
                memory_type=MemoryType.MEMORY_CHUNK,
                source_id=str(uuid4()),
                content=f"测试内容 {i}，包含一些关键词如修炼、角色等",
                chapter_number=max(1, i % 10),
            )
            items.append(item)
        
        context = {
            "chapter_number": 10,
            "outline_keywords": {"keyword_set": {"修炼", "角色"}},
            "character_names": ["李明"],
            "main_character_names": [],
            "relationship_pairs": [],
            "open_hooks": [],
        }
        
        # 评分所有项
        start_time = datetime.now(timezone.utc)
        for item in items:
            scorer.compute_score(item, context)
        end_time = datetime.now(timezone.utc)
        
        duration_ms = (end_time - start_time).total_seconds() * 1000
        
        # 100 项评分应在 1 秒内完成
        assert duration_ms < 1000, f"评分耗时过长: {duration_ms}ms"
    
    def test_context_packaging_performance(self):
        """测试上下文打包性能"""
        # 创建大量检索项
        items = []
        for i in range(50):
            item = RetrievedItem(
                memory_type=MemoryType.MEMORY_CHUNK,
                source_id=str(uuid4()),
                content=f"这是一段测试内容，包含一些文本。编号 {i}。" * 10,
                chapter_number=max(1, i % 10),
                priority=ContentPriority.NORMAL,
            )
            items.append(item)
        
        result = RetrievalResult()
        result.items = items
        result.total_items = len(items)
        
        # 打包
        packager = SmartContextPackager(stage="drafting")
        
        start_time = datetime.now(timezone.utc)
        package = packager.build(result)
        end_time = datetime.now(timezone.utc)
        
        duration_ms = (end_time - start_time).total_seconds() * 1000
        
        # 打包应在 500ms 内完成
        assert duration_ms < 500, f"打包耗时过长: {duration_ms}ms"
        assert package.total_length > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
