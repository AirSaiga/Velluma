# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
章节生成工作流集成测试

测试内容：
1. 角色状态机测试
2. 关系状态机测试
3. 生成前检查清单测试
4. 审阅修复闭环测试
5. 工作流编排器测试

运行方式：
    pytest backend/services/tests/test_workflow_integration.py -v
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from backend.services.state_machine import (
    CharacterStateMachine,
    CharacterStaticPortrait,
    CharacterDynamicState,
    CharacterCurrentState,
    CharacterStatus,
    EmotionalState,
    PhysicalCondition,
    StateChangeType,
    RelationshipStateMachine,
    RelationshipState,
    RelationshipMetrics,
    RelationshipStage,
    RelationshipChangeType,
)
from backend.services.validation.pre_generation_checklist import (
    PreGenerationChecklist,
    PreGenerationReport,
    CheckSeverity,
    CheckCategory,
    CheckResult,
    run_pre_generation_checks,
)
from backend.services.validation.review_repair import (
    ReviewRepairCycle,
    ReviewReport,
    ReviewIssue,
    IssueCategory,
    RepairStrategy,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_character():
    """示例角色实体"""
    char = MagicMock()
    char.id = uuid4()
    char.name = "李明"
    char.aliases = ["小明", "明哥"]
    char.static_prompt = """
【外貌】身材高大，面容刚毅，眼神坚毅
【性格】沉稳内敛，重情重义，遇事冷静
【背景】出身贫寒，历经磨难
"""
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
    char.static_prompt = """
【外貌】容貌秀丽，气质温婉
【性格】聪慧善良，心思细腻
"""
    char.dynamic_state = "情绪低落，心事重重"
    char.importance_level = 8
    return char


@pytest.fixture
def sample_relationship(sample_character, sample_character2):
    """示例关系"""
    rel = MagicMock()
    rel.id = uuid4()
    rel.source_char_id = sample_character.id
    rel.target_char_id = sample_character2.id
    rel.source_character = sample_character
    rel.target_character = sample_character2
    rel.relation_type = "青梅竹马"
    rel.affinity_score = 75
    return rel


@pytest.fixture
def sample_book():
    """示例书籍"""
    book = MagicMock()
    book.id = uuid4()
    book.title = "修仙录"
    book.genre = "仙侠"
    book.global_sys_prompt = "注重细节描写，古风表达"
    return book


@pytest.fixture
def sample_chapter(sample_book):
    """示例章节"""
    chapter = MagicMock()
    chapter.id = uuid4()
    chapter.book_id = sample_book.id
    chapter.chapter_number = 5
    chapter.title = "第五章 问道"
    chapter.outline_text = "李明在修炼中遇到瓶颈，王芳前来探望，两人发生争执后和好如初。"
    return chapter


@pytest.fixture
def sample_entity(sample_character):
    """示例章节-角色关联"""
    entity = MagicMock()
    entity.entity_id = sample_character.id
    entity.character = sample_character
    return entity


@pytest.fixture
def sample_context(sample_book, sample_chapter, sample_character, sample_character2, sample_relationship):
    """示例生成上下文"""
    entity1 = MagicMock()
    entity1.entity_id = sample_character.id
    entity1.character = sample_character
    
    entity2 = MagicMock()
    entity2.entity_id = sample_character2.id
    entity2.character = sample_character2
    
    return {
        "book": sample_book,
        "chapter": sample_chapter,
        "entities": [entity1, entity2],
        "relationships": [sample_relationship],
        "open_hooks": [
            {"hook_id": "hook-1", "content": "神秘老者的身份尚未揭晓"},
        ],
        "previous_summary": "李明突破境界，引发天地异象。",
        "previous_world_snapshot": {"weather": "晴朗"},
        "relevant_memories": [],
        "locations": [],
    }


# =============================================================================
# 角色状态机测试
# =============================================================================

class TestCharacterStateMachine:
    """角色状态机测试"""
    
    def test_create_static_portrait(self, sample_character):
        """测试创建静态画像"""
        portrait = CharacterStaticPortrait(
            name=sample_character.name,
            aliases=sample_character.aliases,
            appearance="身材高大，面容刚毅",
            personality="沉稳内敛，重情重义",
        )
        
        assert portrait.name == "李明"
        assert "小明" in portrait.aliases
        assert "刚毅" in portrait.appearance
    
    def test_create_dynamic_state(self):
        """测试创建动态状态"""
        state = CharacterDynamicState()
        
        state.status = CharacterStatus.ACTIVE
        state.emotional_state = EmotionalState.CALM
        state.physical_condition = PhysicalCondition.HEALTHY
        state.location = "青云宗后山"
        
        assert state.status == CharacterStatus.ACTIVE
        assert state.emotional_state == EmotionalState.CALM
    
    def test_state_machine_creation(self, sample_character):
        """测试状态机创建"""
        portrait = CharacterStaticPortrait(
            name=sample_character.name,
            aliases=sample_character.aliases,
        )
        dynamic = CharacterDynamicState()
        machine = CharacterStateMachine(portrait, dynamic)
        
        assert machine.static_portrait.name == "李明"
        assert machine.current_state is not None
    
    def test_state_transition(self, sample_character):
        """测试状态转换"""
        portrait = CharacterStaticPortrait(name=sample_character.name)
        dynamic = CharacterDynamicState()
        machine = CharacterStateMachine(portrait, dynamic)
        
        # 执行状态转换
        machine.transition(
            new_emotional_state=EmotionalState.ANGRY,
            reason="被人误解",
            chapter_number=5,
        )
        
        assert machine.current_state.emotional_state == EmotionalState.ANGRY
        assert len(machine._history) == 1
    
    def test_forbidden_transition(self, sample_character):
        """测试禁止的状态转换"""
        portrait = CharacterStaticPortrait(name=sample_character.name)
        dynamic = CharacterDynamicState()
        dynamic.status = CharacterStatus.DEAD  # 已死亡
        machine = CharacterStateMachine(portrait, dynamic)
        
        # 尝试转换到活跃状态应该被拒绝
        result = machine.transition(
            new_status=CharacterStatus.ACTIVE,
            reason="复活",
            chapter_number=5,
        )
        
        # 死亡角色不应允许状态变更
        assert result is False or machine.current_state.status == CharacterStatus.DEAD
    
    def test_history_tracking(self, sample_character):
        """测试历史记录追踪"""
        portrait = CharacterStaticPortrait(name=sample_character.name)
        dynamic = CharacterDynamicState()
        machine = CharacterStateMachine(portrait, dynamic)
        
        # 执行多次转换
        machine.transition(EmotionalState.HAPPY, "获得宝物", 5)
        machine.transition(EmotionalState.SAD, "好友离去", 6)
        machine.transition(EmotionalState.CALM, "静心修炼", 7)
        
        assert len(machine._history) == 3
    
    def test_to_context_string(self, sample_character):
        """测试转换为上下文字符串"""
        portrait = CharacterStaticPortrait(
            name=sample_character.name,
            personality="沉稳内敛",
        )
        dynamic = CharacterDynamicState()
        dynamic.emotional_state = EmotionalState.CALM
        dynamic.location = "青云宗"
        
        machine = CharacterStateMachine(portrait, dynamic)
        context = machine.to_context_string()
        
        assert "李明" in context
        assert "沉稳" in context


# =============================================================================
# 关系状态机测试
# =============================================================================

class TestRelationshipStateMachine:
    """关系状态机测试"""
    
    def test_create_relationship_state(self):
        """测试创建关系状态"""
        state = RelationshipState(
            source_char_name="李明",
            target_char_name="王芳",
            relation_type="青梅竹马",
        )
        
        assert state.source_char_name == "李明"
        assert state.target_char_name == "王芳"
        assert state.stage == RelationshipStage.ACQUAINTANCE
    
    def test_metrics_initialization(self):
        """测试指标初始化"""
        metrics = RelationshipMetrics(
            affinity=50,
            trust=60,
            conflict=10,
        )
        
        assert metrics.affinity == 50
        assert metrics.trust == 60
        assert metrics.conflict == 10
    
    def test_affinity_change(self):
        """测试亲密度变化"""
        state = RelationshipState(
            source_char_name="李明",
            target_char_name="王芳",
        )
        state.metrics.affinity = 50
        
        machine = RelationshipStateMachine(state)
        machine.change_affinity(+20, "共同经历危险", 5)
        
        assert state.metrics.affinity == 70
    
    def test_affinity_clamping(self):
        """测试亲密度边界"""
        state = RelationshipState(
            source_char_name="李明",
            target_char_name="王芳",
        )
        state.metrics.affinity = 95
        
        machine = RelationshipStateMachine(state)
        machine.change_affinity(+20, "生死与共", 5)
        
        # 应该被裁剪到 100
        assert state.metrics.affinity <= 100
    
    def test_stage_transition(self):
        """测试关系阶段转换"""
        state = RelationshipState(
            source_char_name="李明",
            target_char_name="王芳",
        )
        state.stage = RelationshipStage.ACQUAINTANCE
        
        machine = RelationshipStateMachine(state)
        
        # 正常转换
        machine.transition_to_stage(
            RelationshipStage.FRIEND,
            "成为朋友",
            5,
        )
        
        assert state.stage == RelationshipStage.FRIEND
    
    def test_forbidden_stage_transition(self):
        """测试禁止的阶段跳跃"""
        state = RelationshipState(
            source_char_name="李明",
            target_char_name="王芳",
        )
        state.stage = RelationshipStage.ACQUAINTANCE
        state.metrics.affinity = 10  # 低亲密度
        
        machine = RelationshipStateMachine(state)
        
        # 尝试跳跃到恋人阶段应该被拒绝
        result = machine.transition_to_stage(
            RelationshipStage.LOVER,
            "一见钟情",
            5,
        )
        
        # 亲密度不足不应允许
        assert result is False or state.stage != RelationshipStage.LOVER
    
    def test_to_context_string(self):
        """测试转换为上下文字符串"""
        state = RelationshipState(
            source_char_name="李明",
            target_char_name="王芳",
            relation_type="青梅竹马",
        )
        state.metrics.affinity = 75
        state.stage = RelationshipStage.FRIEND
        
        machine = RelationshipStateMachine(state)
        context = machine.to_context_string()
        
        assert "李明" in context
        assert "王芳" in context
        assert "75" in context


# =============================================================================
# 生成前检查清单测试
# =============================================================================

class TestPreGenerationChecklist:
    """生成前检查清单测试"""
    
    def test_passing_checks(self, sample_context):
        """测试通过的检查"""
        checklist = PreGenerationChecklist()
        report = checklist.run_all_checks(sample_context)
        
        assert report.can_proceed() is True
        assert report.fatal_count == 0
    
    def test_missing_book(self, sample_context):
        """测试缺少书籍"""
        sample_context["book"] = None
        
        checklist = PreGenerationChecklist()
        report = checklist.run_all_checks(sample_context)
        
        assert report.can_proceed() is False
        assert report.fatal_count == 1
        assert any("书籍" in issue for issue in report.blocking_issues)
    
    def test_missing_outline(self, sample_context):
        """测试缺少大纲"""
        sample_context["chapter"].outline_text = ""
        
        checklist = PreGenerationChecklist()
        report = checklist.run_all_checks(sample_context)
        
        # 应该有错误但不应该是致命错误
        assert report.error_count >= 1
    
    def test_no_characters(self, sample_context):
        """测试没有角色"""
        sample_context["entities"] = []
        
        checklist = PreGenerationChecklist()
        report = checklist.run_all_checks(sample_context)
        
        # 应该有警告但可以继续
        assert report.can_proceed() is True
        assert report.warning_count >= 1
    
    def test_unconscious_character(self, sample_context):
        """测试无意识角色"""
        sample_context["entities"][0].character.dynamic_state = "陷入昏迷状态"
        
        checklist = PreGenerationChecklist()
        report = checklist.run_all_checks(sample_context)
        
        # 应该有警告
        assert report.warning_count >= 1
    
    def test_too_many_hooks(self, sample_context):
        """测试过多伏笔"""
        sample_context["open_hooks"] = [
            {"hook_id": f"hook-{i}", "content": f"伏笔{i}"}
            for i in range(15)
        ]
        
        checklist = PreGenerationChecklist()
        report = checklist.run_all_checks(sample_context)
        
        assert report.warning_count >= 1
    
    def test_convenience_function(self, sample_context):
        """测试便捷函数"""
        report = run_pre_generation_checks(sample_context)
        
        assert isinstance(report, PreGenerationReport)
        assert report.can_proceed() is True


# =============================================================================
# 审阅修复闭环测试
# =============================================================================

class TestReviewRepairCycle:
    """审阅修复闭环测试"""
    
    @pytest.mark.asyncio
    async def test_review_cycle_creation(self):
        """测试审阅循环创建"""
        mock_llm = AsyncMock()
        cycle = ReviewRepairCycle(mock_llm)
        
        assert cycle.llm_client is not None
    
    @pytest.mark.asyncio
    async def test_review_passing(self, sample_context):
        """测试审阅通过"""
        mock_llm = AsyncMock()
        mock_llm.return_value = """
        {
            "passed": true,
            "overall_score": 85,
            "issues": [],
            "repair_recommendation": "no_repair"
        }
        """
        
        cycle = ReviewRepairCycle(mock_llm)
        text, report = await cycle.execute(
            chapter_text="这是一个测试章节内容..." * 100,
            chapter_outline="测试大纲",
            characters=[{"name": "李明"}],
            relationships=[],
            open_hooks=[],
        )
        
        assert report.passed is True
        assert report.overall_score >= 80
    
    @pytest.mark.asyncio
    async def test_review_with_issues(self, sample_context):
        """测试审阅发现问题"""
        mock_llm = AsyncMock()
        mock_llm.return_value = """
        {
            "passed": false,
            "overall_score": 60,
            "issues": [
                {
                    "category": "character_consistency",
                    "severity": "major",
                    "description": "角色行为与性格不符",
                    "location": "第3段",
                    "suggestion": "调整角色反应"
                }
            ],
            "repair_recommendation": "local_repair"
        }
        """
        
        cycle = ReviewRepairCycle(mock_llm)
        text, report = await cycle.execute(
            chapter_text="测试内容..." * 100,
            chapter_outline="测试大纲",
            characters=[{"name": "李明"}],
            relationships=[],
            open_hooks=[],
        )
        
        assert report.passed is False
        assert len(report.issues) >= 1


# =============================================================================
# 工作流编排器集成测试
# =============================================================================

class TestChapterGenerationOrchestrator:
    """工作流编排器集成测试"""
    
    @pytest.mark.asyncio
    async def test_orchestrator_creation(self):
        """测试编排器创建"""
        from backend.config import GenerationConfig
        from backend.services.workflow.chapter_orchestrator import ChapterGenerationOrchestrator
        
        config = GenerationConfig()
        mock_llm = AsyncMock()
        
        orchestrator = ChapterGenerationOrchestrator(config, mock_llm)
        
        assert orchestrator.config is not None
        assert orchestrator.llm_client is not None
    
    @pytest.mark.asyncio
    async def test_full_workflow_execution(self, sample_context):
        """测试完整工作流执行"""
        from backend.config import GenerationConfig, ChapterPlan
        from backend.services.workflow.chapter_orchestrator import (
            ChapterGenerationOrchestrator,
            WorkflowStage,
        )
        
        config = GenerationConfig()
        config.chapter = ChapterPlan(
            chapter_number=5,
            target_word_count=3000,
        )
        config.workflow.max_iterations = 2
        
        mock_llm = AsyncMock()
        mock_llm.return_value = '{"passed": true, "overall_score": 80, "issues": [], "repair_recommendation": "no_repair"}'
        
        orchestrator = ChapterGenerationOrchestrator(config, mock_llm)
        
        progress_events = []
        async def progress_callback(stage, message, **kwargs):
            progress_events.append({"stage": stage, "message": message})
        
        orchestrator.set_progress_callback(progress_callback)
        
        result = await orchestrator.execute(sample_context)
        
        # 验证结果
        assert result.success is True
        assert len(result.final_text) > 0
        assert result.iterations >= 1
        
        # 验证进度事件
        assert len(progress_events) >= 5
        stages = [e["stage"] for e in progress_events]
        assert "PLANNING" in stages
        assert "COMPLETED" in stages
    
    @pytest.mark.asyncio
    async def test_workflow_pre_check_failure(self, sample_context):
        """测试生成前检查失败"""
        from backend.config import GenerationConfig
        from backend.services.workflow.chapter_orchestrator import ChapterGenerationOrchestrator
        
        # 移除书籍导致检查失败
        sample_context["book"] = None
        
        config = GenerationConfig()
        mock_llm = AsyncMock()
        
        orchestrator = ChapterGenerationOrchestrator(config, mock_llm)
        result = await orchestrator.execute(sample_context)
        
        assert result.success is False
        assert "生成前检查失败" in result.error
    
    @pytest.mark.asyncio
    async def test_state_machine_integration(self, sample_context):
        """测试状态机集成"""
        from backend.config import GenerationConfig, ChapterPlan
        from backend.services.workflow.chapter_orchestrator import ChapterGenerationOrchestrator
        
        config = GenerationConfig()
        config.chapter = ChapterPlan(chapter_number=5)
        
        mock_llm = AsyncMock()
        orchestrator = ChapterGenerationOrchestrator(config, mock_llm)
        
        # 执行工作流
        await orchestrator.execute(sample_context)
        
        # 验证状态机构建
        assert len(orchestrator.character_machines) >= 1
        assert len(orchestrator.relationship_machines) >= 1


# =============================================================================
# 端到端场景测试
# =============================================================================

class TestEndToEndScenarios:
    """端到端场景测试"""
    
    @pytest.mark.asyncio
    async def test_high_tension_chapter(self, sample_context):
        """测试高张力章节生成"""
        from backend.config import GenerationConfig, ChapterPlan
        from backend.services.workflow.chapter_orchestrator import ChapterGenerationOrchestrator
        
        # 设置高张力
        sample_context["chapter"].outline_text = "生死决战，命悬一线"
        
        config = GenerationConfig()
        config.chapter = ChapterPlan(
            chapter_number=10,
            tension_level=5,
            target_word_count=5000,
        )
        
        mock_llm = AsyncMock()
        mock_llm.return_value = '{"passed": true, "overall_score": 85, "issues": []}'
        
        orchestrator = ChapterGenerationOrchestrator(config, mock_llm)
        result = await orchestrator.execute(sample_context)
        
        assert result.success is True
    
    @pytest.mark.asyncio
    async def test_multi_iteration_refinement(self, sample_context):
        """测试多轮精修"""
        from backend.config import GenerationConfig, ChapterPlan
        from backend.services.workflow.chapter_orchestrator import ChapterGenerationOrchestrator
        
        config = GenerationConfig()
        config.chapter = ChapterPlan(chapter_number=5)
        config.workflow.max_iterations = 3
        
        call_count = 0
        async def mock_llm_with_iterations(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return '{"passed": false, "overall_score": 60, "issues": [{"severity": "major"}], "repair_recommendation": "local_repair"}'
            return '{"passed": true, "overall_score": 85, "issues": []}'
        
        mock_llm = mock_llm_with_iterations
        
        orchestrator = ChapterGenerationOrchestrator(config, mock_llm)
        result = await orchestrator.execute(sample_context)
        
        assert result.iterations >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
