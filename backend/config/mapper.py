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
参数映射和验证模块。

职责：
- 将前端请求参数映射到统一配置对象
- 处理字段名转换（友好命名 → 技术命名）
- 处理类型转换与默认值填充
- 校验配置完整性和一致性

使用场景：
- backend/services/workflow/: 工作流模块使用映射器和验证器
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.config.schemas import GenerationConfig


class ParameterMapper:
    """
    参数映射器

    职责：
    - 将前端请求参数映射到统一配置对象
    - 处理字段名转换（友好命名 → 技术命名）
    - 处理类型转换与默认值填充
    """

    FIELD_MAPPING = {
        "styleGuide": "style_guide",
        "themesAndTaboos": "themes_and_taboos",
        "worldviewSettings": "worldview_settings",

        "targetWordCount": "target_word_count",
        "authorIntent": "author_intent",
        "tensionLevel": "tension_level",
        "pacingStyle": "pacing_style",
        "forbiddenContent": "forbidden_content",
        "workflowTier": "workflow_tier",
        "expectedIterations": "expected_iterations",

        "baseUrl": "base_url",
        "defaultModel": "default_model",
        "reasoningModel": "reasoning_model",
        "creativeModel": "creative_model",
        "reasoningConfig": "default_reasoning_config",

        "topK": "top_k",
        "semanticWeight": "semantic_weight",
        "timeDecayWeight": "time_decay_weight",
        "foreshadowingWeight": "foreshadowing_weight",
        "decayFactor": "decay_factor",
        "enableMemoryInjection": "enable_memory_injection",

        "maxIterations": "max_iterations",
        "fastMode": "fast_mode",
        "skipMinorRefine": "skip_minor_refine",
        "forceParallelProse": "force_parallel_prose",
        "semiParallelProse": "semi_parallel_prose",
        "beatConcurrency": "beat_concurrency",
        "creativityLevel": "creativity_level",
        "refinementDepth": "refinement_depth",

        "enableSketchTrack": "enable_sketch_track",
        "enableAdversarialAlignment": "enable_adversarial_alignment",
        "useSketchForRefinement": "use_sketch_for_refinement",
        "alignmentThreshold": "alignment_threshold",
        "sketchRatio": "sketch_ratio",

        "enableFailFast": "enable_fail_fast",
        "failFastMaxAttempts": "fail_fast_max_attempts",
        "failFastTemperatureStep": "fail_fast_temperature_step",
        "enableEmotionalScratchpad": "enable_emotional_scratchpad",
        "qualityThreshold": "quality_threshold",
        "consistencyThreshold": "consistency_threshold",

        "enableWhisperMemory": "enable_whisper_memory",
        "enableWorldbuildingInjection": "enable_worldbuilding_injection",
        "enableCrossChapterValidation": "enable_cross_chapter_validation",
        "enableDynamicStateUpdate": "enable_dynamic_state_update",

        "excludeProcess": "exclude_process",
    }

    DEFAULTS = {
        "tension_level": 3,
        "pacing_style": "balanced",
        "target_word_count": 3000,
        "max_iterations": 2,
        "top_k": 5,
        "semantic_weight": 0.6,
        "time_decay_weight": 0.2,
        "foreshadowing_weight": 0.2,
        "decay_factor": 0.1,
        "quality_threshold": 0.7,
        "beat_concurrency": 6,
        "alignment_threshold": 70.0,
        "sketch_ratio": 0.45,
    }

    @classmethod
    def map_request_to_config(
        cls,
        request_data: Dict[str, Any],
        chapter: Optional[Any] = None,
        book: Optional[Any] = None,
    ) -> GenerationConfig:
        """
        将请求字典映射到配置对象

        Args:
            request_data: 前端请求字典
            chapter: Chapter 实体
            book: Book 实体

        Returns:
            GenerationConfig: 统一配置对象
        """
        normalized = cls._normalize_field_names(request_data)
        filled = cls._fill_defaults(normalized)
        config = GenerationConfig.from_request(filled, chapter, book)
        return config

    @classmethod
    def _normalize_field_names(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """转换字段名"""
        result = {}
        for key, value in data.items():
            mapped_key = cls.FIELD_MAPPING.get(key, key)
            if mapped_key == key and any(c.isupper() for c in key):
                mapped_key = cls._camel_to_snake(key)
            result[mapped_key] = value
        return result

    @classmethod
    def _fill_defaults(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """填充默认值"""
        result = data.copy()
        for key, default_value in cls.DEFAULTS.items():
            if key not in result or result[key] is None:
                result[key] = default_value
        return result

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """驼峰转下划线"""
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class ConfigValidator:
    """
    配置验证器

    职责：
    - 校验配置完整性和一致性
    - 检查参数范围和依赖关系
    - 收集验证错误
    """

    @classmethod
    def validate(cls, config: GenerationConfig) -> Tuple[bool, List[str]]:
        """
        验证配置

        Args:
            config: 统一配置对象

        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误列表)
        """
        errors = []

        if config.llm:
            if not config.llm.api_key:
                errors.append("api_key 不能为空")
        else:
            errors.append("LLM 配置缺失")

        if config.chapter.target_word_count < 500:
            errors.append("目标字数不能少于 500")
        if config.chapter.target_word_count > 20000:
            errors.append("目标字数不能超过 20000")

        if not 1 <= config.chapter.tension_level <= 5:
            errors.append("张力等级必须在 1-5 之间")

        total_weight = (
            config.rag.semantic_weight +
            config.rag.time_decay_weight +
            config.rag.foreshadowing_weight
        )
        if abs(total_weight - 1.0) > 1e-6:
            errors.append(f"RAG 权重和必须为 1.0，当前为 {total_weight:.4f}")

        if config.workflow.max_iterations < 1 or config.workflow.max_iterations > 5:
            errors.append("迭代次数必须在 1-5 之间")

        expected_iterations = {
            "TIER_1_FAST": 1,
            "TIER_2_STANDARD": 2,
            "TIER_3_FORTRESS": 3,
        }.get(config.chapter.workflow_tier, 2)

        if not config.workflow.fast_mode and config.workflow.max_iterations < expected_iterations:
            errors.append(
                f"工作流层级 {config.chapter.workflow_tier} 建议至少 {expected_iterations} 次迭代"
            )

        return len(errors) == 0, errors

    @classmethod
    def validate_for_generation(cls, config: GenerationConfig) -> Tuple[bool, List[str]]:
        """
        验证生成前配置（更严格）

        Args:
            config: 统一配置对象

        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误列表)
        """
        valid, errors = cls.validate(config)

        if not valid:
            return False, errors

        if not config.chapter_id:
            errors.append("chapter_id 不能为空")

        if not config.chapter.outline:
            errors.append("章节大纲不能为空")

        return len(errors) == 0, errors
