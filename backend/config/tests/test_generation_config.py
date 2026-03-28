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
统一配置模块测试

测试内容：
1. 配置对象构建测试
2. 推导规则测试
3. 参数映射测试
4. 配置验证测试
5. 向后兼容测试

运行方式：
    pytest backend/config/tests/test_generation_config.py -v
"""

import pytest
from uuid import uuid4, UUID
from unittest.mock import MagicMock

from backend.config import (
    GenerationConfig,
    StoryConfig,
    ChapterPlan,
    LLMConfig,
    RAGPolicy,
    WorkflowPolicy,
    ValidationPolicy,
    FeatureFlags,
    DualTrackSettings,
    ReasoningSettings,
    DerivationEngine,
    ParameterMapper,
    ConfigValidator,
    derive_config,
    MemoryStrategy,
    CreativityLevel,
    RefinementDepth,
    WorkflowTier,
)
from backend.config.adapter import adapt_request_to_config, config_to_legacy_dict


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_book():
    """示例 Book 实体"""
    book = MagicMock()
    book.id = uuid4()
    book.title = "测试小说"
    book.genre = "奇幻"
    book.global_sys_prompt = "注重描写细腻，古风表达"
    book.core_motifs_taboos = "避免现代用语"
    book.worldview_settings = {"world": "修仙世界"}
    book.golden_snippets = ["天地不仁，以万物为刍狗"]
    book.style_blacklist = ["网络用语"]
    return book


@pytest.fixture
def sample_chapter():
    """示例 Chapter 实体"""
    chapter = MagicMock()
    chapter.id = uuid4()
    chapter.book_id = uuid4()
    chapter.chapter_number = 5
    chapter.title = "第五章 问道"
    chapter.chapter_name = "问道"
    chapter.outline_text = "主角遭遇瓶颈，遇到神秘老者指点"
    chapter.tension_level = 3
    chapter.pacing_style = "balanced"
    return chapter


@pytest.fixture
def sample_request_dict():
    """示例请求字典"""
    return {
        "chapter_id": uuid4(),
        "api_key": "sk-test-key",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "reasoning_model": "o1",
        "creative_model": "gpt-4o",
        "word_count": 5000,
        "author_intent": "展示主角内心成长",
        "tension_level": 4,
        "pacing_style": "fast_paced",
        "rag_top_k": 5,
        "rag_alpha": 0.6,
        "rag_beta": 0.2,
        "rag_gamma": 0.2,
        "rag_lambda": 0.1,
        "max_iterations": 3,
        "fast_mode": False,
        "skip_minor_refine": True,
        "memory_strategy": "balanced_reference",
        "creativity_level": "balanced_creation",
        "refinement_depth": "standard",
        "feature_flags": {
            "enable_fail_fast": True,
            "enable_emotional_scratchpad": True,
            "enable_whisper_memory": False,
            "fail_fast_max_attempts": 2,
            "fail_fast_temperature_step": 0.2,
            "workflow_tier": "TIER_2_STANDARD",
            "force_parallel_prose": False,
            "semi_parallel_prose": True,
        },
    }


# =============================================================================
# 配置对象构建测试
# =============================================================================

class TestStoryConfig:
    """StoryConfig 测试"""
    
    def test_from_book(self, sample_book):
        """测试从 Book 实体构建"""
        config = StoryConfig.from_book(sample_book)
        
        assert config.genre == "奇幻"
        assert config.style_guide == "注重描写细腻，古风表达"
        assert config.themes_and_taboos == "避免现代用语"
        assert config.worldview_settings == {"world": "修仙世界"}
        assert len(config.golden_snippets) == 1
    
    def test_default_values(self):
        """测试默认值"""
        config = StoryConfig()
        assert config.genre == ""
        assert config.style_guide == ""
        assert config.worldview_settings == {}


class TestChapterPlan:
    """ChapterPlan 测试"""
    
    def test_from_chapter(self, sample_chapter):
        """测试从 Chapter 实体构建"""
        request_data = {
            "author_intent": "展示成长",
            "word_count": 4000,
            "tension_level": 4,
        }
        config = ChapterPlan.from_chapter(sample_chapter, request_data)
        
        assert config.chapter_number == 5
        assert config.title == "第五章 问道"
        assert config.outline == "主角遭遇瓶颈，遇到神秘老者指点"
        assert config.author_intent == "展示成长"
        assert config.target_word_count == 4000
        assert config.tension_level == 4
    
    def test_derive_workflow_tier(self):
        """测试工作流层级推导"""
        # 张力等级 1-2 → TIER_1_FAST
        plan = ChapterPlan(tension_level=1)
        assert plan.derive_workflow_tier() == "TIER_1_FAST"
        
        plan = ChapterPlan(tension_level=2)
        assert plan.derive_workflow_tier() == "TIER_1_FAST"
        
        # 张力等级 3 → TIER_2_STANDARD
        plan = ChapterPlan(tension_level=3)
        assert plan.derive_workflow_tier() == "TIER_2_STANDARD"
        
        # 张力等级 4-5 → TIER_3_FORTRESS
        plan = ChapterPlan(tension_level=4)
        assert plan.derive_workflow_tier() == "TIER_3_FORTRESS"
        
        plan = ChapterPlan(tension_level=5)
        assert plan.derive_workflow_tier() == "TIER_3_FORTRESS"
    
    def test_derive_expected_iterations(self):
        """测试预期迭代次数推导"""
        # fast_mode → 1
        plan = ChapterPlan()
        assert plan.derive_expected_iterations(fast_mode=True) == 1
        
        # TIER_1_FAST → 1
        plan = ChapterPlan(workflow_tier="TIER_1_FAST")
        assert plan.derive_expected_iterations() == 1
        
        # TIER_2_STANDARD → 2
        plan = ChapterPlan(workflow_tier="TIER_2_STANDARD")
        assert plan.derive_expected_iterations() == 2
        
        # TIER_3_FORTRESS → 3
        plan = ChapterPlan(workflow_tier="TIER_3_FORTRESS")
        assert plan.derive_expected_iterations() == 3
    
    def test_clamp_tension_level(self):
        """测试张力等级裁剪"""
        plan = ChapterPlan(tension_level=0)
        assert plan.tension_level == 1  # 裁剪到 1
        
        plan = ChapterPlan(tension_level=10)
        assert plan.tension_level == 5  # 裁剪到 5


class TestLLMConfig:
    """LLMConfig 测试"""
    
    def test_get_effective_models(self):
        """测试有效模型获取"""
        # 单模型模式
        config = LLMConfig(
            api_key="test",
            default_model="gpt-4o-mini",
        )
        assert config.get_effective_reasoning_model() == "gpt-4o-mini"
        assert config.get_effective_creative_model() == "gpt-4o-mini"
        
        # 双模型模式
        config = LLMConfig(
            api_key="test",
            default_model="gpt-4o-mini",
            reasoning_model="o1",
            creative_model="gpt-4o",
        )
        assert config.get_effective_reasoning_model() == "o1"
        assert config.get_effective_creative_model() == "gpt-4o"
        assert config.is_dual_model_mode() is True
    
    def test_reasoning_settings_to_api_params(self):
        """测试推理配置转换为 API 参数"""
        # 未启用
        settings = ReasoningSettings(enabled=False)
        assert settings.to_api_params() == {}
        
        # 已启用
        settings = ReasoningSettings(
            enabled=True,
            effort="high",
            max_tokens=1000,
            exclude_process=True,
        )
        params = settings.to_api_params()
        assert params["reasoning"]["enabled"] is True
        assert params["reasoning"]["effort"] == "high"
        assert params["reasoning"]["max_tokens"] == 1000
        assert params["reasoning"]["exclude"] is True


class TestRAGPolicy:
    """RAGPolicy 测试"""
    
    def test_weight_normalization(self):
        """测试权重归一化"""
        # 权重和不为 1 时自动归一化
        policy = RAGPolicy(
            semantic_weight=0.5,
            time_decay_weight=0.3,
            foreshadowing_weight=0.3,  # 总和 = 1.1
        )
        # 归一化后应该和为 1
        total = policy.semantic_weight + policy.time_decay_weight + policy.foreshadowing_weight
        assert abs(total - 1.0) < 1e-6
    
    def test_apply_strategy_preset(self):
        """测试策略预设应用"""
        # RECENT_ONLY 预设
        policy = RAGPolicy(memory_strategy=MemoryStrategy.RECENT_ONLY)
        policy.apply_strategy_preset()
        assert policy.top_k == 3
        assert policy.decay_factor == 0.3
        
        # DEEP_DIVE 预设
        policy = RAGPolicy(memory_strategy=MemoryStrategy.DEEP_DIVE)
        policy.apply_strategy_preset()
        assert policy.top_k == 10
        assert policy.foreshadowing_weight == 0.35


class TestWorkflowPolicy:
    """WorkflowPolicy 测试"""
    
    def test_derive_from_tier_fast(self):
        """测试从 TIER_1_FAST 推导"""
        policy = WorkflowPolicy()
        policy.derive_from_tier("TIER_1_FAST")
        
        assert policy.max_iterations == 1
        assert policy.fast_mode is True
        assert policy.skip_minor_refine is True
        assert policy.dual_track.enable_sketch_track is False
    
    def test_derive_from_tier_standard(self):
        """测试从 TIER_2_STANDARD 推导"""
        policy = WorkflowPolicy()
        policy.derive_from_tier("TIER_2_STANDARD")
        
        assert policy.max_iterations == 2
        assert policy.fast_mode is False
        assert policy.dual_track.enable_sketch_track is True
    
    def test_derive_from_tier_fortress(self):
        """测试从 TIER_3_FORTRESS 推导"""
        policy = WorkflowPolicy()
        policy.derive_from_tier("TIER_3_FORTRESS")
        
        assert policy.max_iterations == 3
        assert policy.skip_minor_refine is False
        assert policy.dual_track.alignment_threshold == 80.0
    
    def test_derive_from_creativity(self):
        """测试从创作自由度推导"""
        # STRICT_PROMPT
        policy = WorkflowPolicy(creativity_level=CreativityLevel.STRICT_PROMPT)
        policy.derive_from_creativity()
        assert policy.force_parallel_prose is False
        assert policy.semi_parallel_prose is False
        
        # WILD_IMAGINATION
        policy = WorkflowPolicy(creativity_level=CreativityLevel.WILD_IMAGINATION)
        policy.derive_from_creativity()
        assert policy.force_parallel_prose is True
        assert policy.semi_parallel_prose is True


# =============================================================================
# 推导引擎测试
# =============================================================================

class TestDerivationEngine:
    """DerivationEngine 测试"""
    
    def test_derive_tension_to_tier(self, sample_request_dict, sample_chapter, sample_book):
        """测试张力等级到工作流层级的推导"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        engine = DerivationEngine()
        
        # 张力等级 4 应该推导为 TIER_3_FORTRESS
        config.chapter.tension_level = 4
        engine.derive(config)
        assert config.chapter.workflow_tier == "TIER_3_FORTRESS"
    
    def test_derive_iterations(self, sample_request_dict, sample_chapter, sample_book):
        """测试迭代次数推导"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        engine = DerivationEngine()
        
        # fast_mode = True 时强制 1 次迭代
        config.workflow.fast_mode = True
        engine.derive(config)
        assert config.chapter.expected_iterations == 1
        
        # TIER_3_FORTRESS 应该推导为 3 次迭代
        config.workflow.fast_mode = False
        config.chapter.tension_level = 5
        engine.derive(config)
        assert config.chapter.expected_iterations == 3
    
    def test_derive_dual_track(self, sample_request_dict, sample_chapter, sample_book):
        """测试双轨配置推导"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        engine = DerivationEngine()
        
        # TIER_1_FAST 不启用双轨
        config.chapter.tension_level = 1
        engine.derive(config)
        assert config.workflow.dual_track.enable_sketch_track is False
        
        # TIER_2_STANDARD 启用双轨
        config.chapter.tension_level = 3
        engine.derive(config)
        assert config.workflow.dual_track.enable_sketch_track is True
        assert config.workflow.dual_track.enable_adversarial_alignment is True
    
    def test_derive_rag_params(self, sample_request_dict, sample_chapter, sample_book):
        """测试 RAG 参数推导"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        config.rag.memory_strategy = MemoryStrategy.DEEP_DIVE
        engine = DerivationEngine()
        engine.derive(config)
        
        assert config.rag.top_k == 10
        assert config.rag.foreshadowing_weight == 0.35


# =============================================================================
# 参数映射测试
# =============================================================================

class TestParameterMapper:
    """ParameterMapper 测试"""
    
    def test_normalize_field_names(self):
        """测试字段名标准化"""
        data = {
            "targetWordCount": 5000,
            "authorIntent": "测试意图",
            "tensionLevel": 4,
            "enableSketchTrack": True,
        }
        normalized = ParameterMapper._normalize_field_names(data)
        
        assert normalized["target_word_count"] == 5000
        assert normalized["author_intent"] == "测试意图"
        assert normalized["tension_level"] == 4
        assert normalized["enable_sketch_track"] is True
    
    def test_fill_defaults(self):
        """测试默认值填充"""
        data = {"tension_level": 4}
        filled = ParameterMapper._fill_defaults(data)
        
        assert filled["tension_level"] == 4  # 保留原值
        assert filled["pacing_style"] == "balanced"  # 填充默认值
        assert filled["target_word_count"] == 3000  # 填充默认值


# =============================================================================
# 配置验证测试
# =============================================================================

class TestConfigValidator:
    """ConfigValidator 测试"""
    
    def test_validate_valid_config(self, sample_request_dict, sample_chapter, sample_book):
        """测试有效配置验证"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        engine = DerivationEngine()
        config = engine.derive(config)
        
        valid, errors = ConfigValidator.validate(config)
        assert valid is True
        assert len(errors) == 0
    
    def test_validate_missing_api_key(self, sample_request_dict, sample_chapter, sample_book):
        """测试缺少 API Key"""
        sample_request_dict["api_key"] = None
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        
        valid, errors = ConfigValidator.validate(config)
        assert valid is False
        assert any("api_key" in e for e in errors)
    
    def test_validate_invalid_word_count(self, sample_request_dict, sample_chapter, sample_book):
        """测试无效字数"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        config.chapter.target_word_count = 100  # 太少
        
        valid, errors = ConfigValidator.validate(config)
        assert valid is False
        assert any("字数" in e for e in errors)
    
    def test_validate_rag_weight_sum(self, sample_request_dict, sample_chapter, sample_book):
        """测试 RAG 权重和验证"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        config.rag.semantic_weight = 0.3
        config.rag.time_decay_weight = 0.3
        config.rag.foreshadowing_weight = 0.3  # 总和 = 0.9
        
        valid, errors = ConfigValidator.validate(config)
        # 权重和不为 1 时应该报错
        assert valid is False


# =============================================================================
# 向后兼容测试
# =============================================================================

class TestBackwardCompatibility:
    """向后兼容测试"""
    
    def test_to_legacy_format(self, sample_request_dict, sample_chapter, sample_book):
        """测试转换为旧版格式"""
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        engine = DerivationEngine()
        config = engine.derive(config)
        
        legacy = config.to_legacy_format()
        
        # 检查关键字段
        assert legacy["api_key"] == "sk-test-key"
        assert legacy["word_count"] == 5000
        assert legacy["tension_level"] == 4
        assert legacy["rag_top_k"] == 5
        assert legacy["max_iterations"] == 3
        assert "feature_flags" in legacy
    
    def test_roundtrip_conversion(self, sample_request_dict):
        """测试往返转换"""
        # 请求 -> 配置 -> 旧版字典
        config = GenerationConfig.from_request(sample_request_dict)
        engine = DerivationEngine()
        config = engine.derive(config)
        legacy = config.to_legacy_format()
        
        # 验证关键字段保持一致
        assert legacy["chapter_id"] == str(sample_request_dict["chapter_id"])
        assert legacy["word_count"] == sample_request_dict["word_count"]
        assert legacy["tension_level"] == sample_request_dict["tension_level"]


# =============================================================================
# 集成测试
# =============================================================================

class TestIntegration:
    """集成测试"""
    
    def test_derive_config_function(self, sample_request_dict, sample_chapter, sample_book):
        """测试 derive_config 便捷函数"""
        config = derive_config(sample_request_dict, sample_chapter, sample_book)
        
        assert config.chapter is not None
        assert config.llm is not None
        assert config.chapter.workflow_tier in ["TIER_1_FAST", "TIER_2_STANDARD", "TIER_3_FORTRESS"]
    
    def test_full_workflow(self, sample_request_dict, sample_chapter, sample_book):
        """测试完整工作流"""
        # 1. 从请求构建配置
        config = GenerationConfig.from_request(sample_request_dict, sample_chapter, sample_book)
        
        # 2. 执行推导
        engine = DerivationEngine()
        config = engine.derive(config)
        
        # 3. 验证
        valid, errors = ConfigValidator.validate(config)
        assert valid, f"验证失败: {errors}"
        
        # 4. 转换为旧版格式
        legacy = config.to_legacy_format()
        assert legacy is not None
        
        # 5. 检查推导日志
        log = engine.get_derivation_log()
        assert len(log) > 0
        assert any("tension_to_tier" in entry["rule"] for entry in log)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
