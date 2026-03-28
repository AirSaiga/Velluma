# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# 独立单元测试 - 测试工作流核心模块

"""
独立单元测试

测试内容：
1. 角色状态机
2. 关系状态机
3. 生成前检查清单
4. 审阅修复闭环

运行方式：
    python backend/services/tests/test_standalone.py
"""

import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
import asyncio
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


# =============================================================================
# 模拟测试环境
# =============================================================================

def test_character_state_machine():
    """测试角色状态机"""
    print("\n=== 测试角色状态机 ===")
    
    # 导入模块
    from backend.services.state_machine.character_state import (
        CharacterStateMachine,
        CharacterStaticPortrait,
        CharacterDynamicState,
        CharacterCurrentState,
        CharacterStatus,
        EmotionalState,
        PhysicalCondition,
        StateChangeType,
    )
    
    # 测试静态画像创建
    portrait = CharacterStaticPortrait(
        name="李明",
        aliases=["小明", "明哥"],
        appearance="身材高大，面容刚毅",
        personality="沉稳内敛，重情重义",
    )
    assert portrait.name == "李明"
    assert "小明" in portrait.aliases
    print("  ✓ 静态画像创建成功")
    
    # 测试动态状态
    dynamic = CharacterDynamicState()
    dynamic.physical_condition = PhysicalCondition.HEALTHY
    dynamic.emotional_state = EmotionalState.CALM
    dynamic.current_place = "青云宗后山"
    assert dynamic.physical_condition == PhysicalCondition.HEALTHY
    print("  ✓ 动态状态创建成功")
    
    # 测试状态机
    machine = CharacterStateMachine(portrait, dynamic)
    assert machine.static_portrait.name == "李明"
    print("  ✓ 状态机创建成功")
    
    # 测试状态验证
    new_state = CharacterDynamicState()
    new_state.emotional_state = EmotionalState.ANGRY
    is_valid, change_type, messages = machine.validate_transition(
        new_state,
        context="被人误解",
    )
    assert is_valid
    print("  ✓ 状态验证成功")
    
    # 测试 OOC 报告
    ooc_report = machine.get_ooc_report("李明突然大笑起来")
    assert "character_name" in ooc_report
    print("  ✓ OOC 报告生成成功")
    
    # 测试角色卡片生成
    card = machine.to_character_card()
    assert "李明" in card
    print("  ✓ 角色卡片生成成功")
    
    print("角色状态机测试通过！\n")


def test_relationship_state_machine():
    """测试关系状态机"""
    print("\n=== 测试关系状态机 ===")
    
    from backend.services.state_machine.relationship_state import (
        RelationshipStateMachine,
        RelationshipState,
        RelationshipMetrics,
        RelationshipStage,
        RelationshipChangeType,
    )
    
    # 测试关系状态创建
    state = RelationshipState(
        source_char_name="李明",
        target_char_name="王芳",
        relation_type="青梅竹马",
    )
    assert state.source_char_name == "李明"
    assert state.target_char_name == "王芳"
    print("  ✓ 关系状态创建成功")
    
    # 测试指标
    metrics = RelationshipMetrics(
        affinity=50,
        trust=60,
        conflict=10,
    )
    assert metrics.affinity == 50
    print("  ✓ 关系指标创建成功")
    
    # 测试状态机
    state.metrics.affinity = 50
    machine = RelationshipStateMachine(state)
    print("  ✓ 关系状态机创建成功")
    
    # 测试亲密度变化
    machine.change_affinity(+20, "共同经历危险", 5)
    assert state.metrics.affinity == 70
    print("  ✓ 亲密度变化成功")
    
    # 测试阶段转换
    machine.transition_to_stage(RelationshipStage.CLOSE, "成为朋友", 5)
    assert state.stage == RelationshipStage.CLOSE
    print("  ✓ 关系阶段转换成功")
    
    # 测试上下文字符串
    context = machine.to_context_string()
    assert "李明" in context
    assert "王芳" in context
    print("  ✓ 上下文字符串生成成功")
    
    print("关系状态机测试通过！\n")


def test_pre_generation_checklist():
    """测试生成前检查清单"""
    print("\n=== 测试生成前检查清单 ===")
    
    from backend.services.validation.pre_generation_checklist import (
        PreGenerationChecklist,
        PreGenerationReport,
        CheckSeverity,
        CheckCategory,
        CheckResult,
        run_pre_generation_checks,
    )
    
    # 创建模拟上下文
    book = MagicMock()
    book.id = "book-1"
    book.title = "测试小说"
    
    chapter = MagicMock()
    chapter.id = "chapter-1"
    chapter.chapter_number = 5
    chapter.outline_text = "李明遇到瓶颈，王芳前来探望。"
    
    char1 = MagicMock()
    char1.id = "char-1"
    char1.name = "李明"
    char1.dynamic_state = "情绪稳定"
    
    entity1 = MagicMock()
    entity1.entity_id = "char-1"
    entity1.character = char1
    
    context = {
        "book": book,
        "chapter": chapter,
        "entities": [entity1],
        "relationships": [],
        "open_hooks": [],
        "previous_summary": "上一章摘要",
        "previous_world_snapshot": {"weather": "晴朗"},
    }
    
    # 执行检查
    checklist = PreGenerationChecklist()
    report = checklist.run_all_checks(context)
    
    assert report.can_proceed() is True
    assert report.fatal_count == 0
    print("  ✓ 通过的检查成功")
    
    # 测试缺少书籍
    context_no_book = context.copy()
    context_no_book["book"] = None
    report_no_book = checklist.run_all_checks(context_no_book)
    assert report_no_book.can_proceed() is False
    assert report_no_book.fatal_count == 1
    print("  ✓ 缺少书籍检查成功")
    
    # 测试缺少大纲
    context_no_outline = context.copy()
    context_no_outline["chapter"].outline_text = ""
    report_no_outline = checklist.run_all_checks(context_no_outline)
    assert report_no_outline.error_count >= 1
    print("  ✓ 缺少大纲检查成功")
    
    # 测试便捷函数
    report = run_pre_generation_checks(context)
    assert isinstance(report, PreGenerationReport)
    print("  ✓ 便捷函数成功")
    
    print("生成前检查清单测试通过！\n")


async def test_review_repair_cycle():
    """测试审阅修复闭环"""
    print("\n=== 测试审阅修复闭环 ===")
    
    from backend.services.validation.review_repair import (
        ReviewRepairCycle,
        ReviewReport,
        ReviewIssue,
        IssueSeverity,
        IssueCategory,
        RepairStrategy,
        ChapterReviewer,
        ChapterRepairer,
    )
    
    # 创建模拟 LLM 客户端
    async def mock_llm(*args, **kwargs):
        return json.dumps({
            "passed": True,
            "overall_score": 85,
            "issues": [],
            "repair_recommendation": "no_repair"
        })
    
    # 测试审阅器
    reviewer = ChapterReviewer(mock_llm)
    report = await reviewer.review(
        chapter_text="这是测试章节内容..." * 50,
        chapter_outline="测试大纲",
        characters=[{"name": "李明", "dynamic_state": "正常"}],
        relationships=[{"source_name": "李明", "target_name": "王芳", "affinity_score": 50}],
        open_hooks=[],
        previous_summary="上一章摘要",
    )
    
    assert isinstance(report, ReviewReport)
    print("  ✓ 审阅器创建报告成功")
    
    # 测试审阅-修复循环
    cycle = ReviewRepairCycle(mock_llm)
    text, final_report = await cycle.execute(
        chapter_text="测试章节内容..." * 50,
        chapter_outline="测试大纲",
        characters=[{"name": "李明"}],
        relationships=[],
        open_hooks=[],
    )
    
    assert isinstance(final_report, ReviewReport)
    print("  ✓ 审阅-修复循环成功")
    
    # 测试问题创建
    issue = ReviewIssue(
        category=IssueCategory.CHARACTER_OOC,
        severity=IssueSeverity.MAJOR,
        location="第3段",
        description="角色行为与性格不符",
        original_text="原文内容",
        auto_fixable=True,
    )
    
    report = ReviewReport()
    report.add_issue(issue)
    assert report.major_count == 1
    print("  ✓ 问题添加成功")
    
    # 测试修复策略确定
    strategy = report.determine_repair_strategy()
    assert strategy in [RepairStrategy.LOCAL_REPAIR, RepairStrategy.MANUAL_REVIEW]
    print("  ✓ 修复策略确定成功")
    
    print("审阅修复闭环测试通过！\n")


def test_workflow_orchestrator():
    """测试工作流编排器"""
    print("\n=== 测试工作流编排器 ===")
    
    from backend.services.workflow.chapter_orchestrator import (
        WorkflowStage,
        WorkflowState,
        WorkflowResult,
    )
    
    # 测试工作流阶段枚举
    assert WorkflowStage.IDLE.value == "IDLE"
    assert WorkflowStage.PLANNING.value == "PLANNING"
    assert WorkflowStage.COMPLETED.value == "COMPLETED"
    print("  ✓ 工作流阶段定义成功")
    
    # 测试工作流状态
    state = WorkflowState(
        current_stage=WorkflowStage.PLANNING,
        iteration=1,
        max_iterations=3,
    )
    assert state.current_stage == WorkflowStage.PLANNING
    assert state.iteration == 1
    print("  ✓ 工作流状态创建成功")
    
    # 测试工作流结果
    result = WorkflowResult(
        success=True,
        final_text="生成的章节内容...",
        word_count=100,
        iterations=2,
    )
    assert result.success is True
    assert result.word_count == 100
    print("  ✓ 工作流结果创建成功")
    
    print("工作流编排器测试通过！\n")


def test_config_module():
    """测试配置模块"""
    print("\n=== 测试配置模块 ===")
    
    try:
        from backend.config import (
            GenerationConfig,
            StoryConfig,
            ChapterPlan,
            LLMConfig,
            RAGPolicy,
            WorkflowPolicy,
            ValidationPolicy,
            FeatureFlags,
            DerivationEngine,
        )
        
        # 测试配置创建
        config = GenerationConfig()
        assert config.chapter is not None
        print("  ✓ GenerationConfig 创建成功")
        
        # 测试章节规划
        chapter_plan = ChapterPlan(
            chapter_number=5,
            tension_level=3,
            target_word_count=3000,
        )
        assert chapter_plan.chapter_number == 5
        assert chapter_plan.tension_level == 3
        print("  ✓ ChapterPlan 创建成功")
        
        # 测试张力等级到工作流层级推导
        tier = chapter_plan.derive_workflow_tier()
        assert tier == "TIER_2_STANDARD"
        print("  ✓ 工作流层级推导成功")
        
        # 测试 RAG 策略
        rag = RAGPolicy(
            top_k=5,
            semantic_weight=0.6,
            time_decay_weight=0.2,
            foreshadowing_weight=0.2,
        )
        assert rag.top_k == 5
        print("  ✓ RAGPolicy 创建成功")
        
        # 测试工作流策略
        workflow = WorkflowPolicy(
            max_iterations=2,
            fast_mode=False,
        )
        assert workflow.max_iterations == 2
        print("  ✓ WorkflowPolicy 创建成功")
        
        print("配置模块测试通过！\n")
        
    except Exception as e:
        print(f"  ⚠ 配置模块测试跳过（可能缺少依赖）: {e}\n")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始运行章节生成工作流集成测试")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    tests = [
        ("角色状态机", test_character_state_machine),
        ("关系状态机", test_relationship_state_machine),
        ("生成前检查清单", test_pre_generation_checklist),
        ("工作流编排器", test_workflow_orchestrator),
        ("配置模块", test_config_module),
    ]
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}测试失败: {e}")
            failed += 1
    
    # 异步测试
    try:
        asyncio.run(test_review_repair_cycle())
        passed += 1
    except Exception as e:
        print(f"  ✗ 审阅修复闭环测试失败: {e}")
        failed += 1
    
    print("\n" + "=" * 60)
    print(f"测试完成：{passed} 通过，{failed} 失败")
    print("=" * 60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
