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
创作意图驱动层 - 意图对象与推导规则

职责：
- 定义创作意图类型枚举
- 定义章节目标类型枚举
- 定义核心对象模型
- 定义意图到参数的推导规则

使用方式：
    from backend.config.intent_driven import (
        CreativeIntentType,
        CreativeIntent,
        IntentDerivationEngine,
    )
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


# =============================================================================
# 创作意图枚举
# =============================================================================

class CreativeIntentType(str, Enum):
    """创作意图类型"""
    ADVANCE_MAINLINE = "advance_mainline"        # 推进主线
    CHARACTER_DEVELOPMENT = "character_development"  # 塑造人物
    ATMOSPHERE_BUILDING = "atmosphere_building"  # 营造氛围
    BUILD_CONFLICT = "build_conflict"            # 制造冲突
    CLOSE_HOOKS = "close_hooks"                  # 回收伏笔
    WORLDBUILDING = "worldbuilding"              # 展开世界观
    EMOTIONAL_WARMING = "emotional_warming"      # 情感升温
    DIALOGUE_SCENE = "dialogue_scene"            # 对话戏
    BIG_SCENE = "big_scene"                      # 大场面
    TRANSITION_CHAPTER = "transition_chapter"    # 过渡章节
    SUSPENSE_ENDING = "suspense_ending"          # 悬念结尾


class ChapterGoalType(str, Enum):
    """章节目标类型"""
    INTRODUCE_CHARACTER = "introduce_character"  # 引入新角色
    RESOLVE_CONFLICT = "resolve_conflict"        # 解决冲突
    REVEAL_SECRET = "reveal_secret"              # 揭示秘密
    CHANGE_RELATIONSHIP = "change_relationship"  # 关系变化
    SET_SCENE = "set_scene"                      # 场景建立


class PlanType(str, Enum):
    """推荐方案类型"""
    BALANCED = "balanced"      # 均衡方案
    FAST = "fast"              # 快速方案
    QUALITY = "quality"        # 质量优先
    CREATIVE = "creative"      # 创意优先


# =============================================================================
# 核心对象定义
# =============================================================================

class CreativeIntent(BaseModel):
    """创作意图对象"""
    intent_type: CreativeIntentType = Field(..., description="意图类型")
    custom_description: Optional[str] = Field(None, description="用户自定义描述")
    priority: int = Field(default=1, ge=1, le=3, description="优先级(1-3)")


class ChapterGoal(BaseModel):
    """章节目标对象"""
    goal_type: ChapterGoalType = Field(..., description="目标类型")
    target_entity_ids: List[str] = Field(default_factory=list, description="目标实体ID")
    constraints: Dict[str, Any] = Field(default_factory=dict, description="内容约束")


class GenerationPolicy(BaseModel):
    """生成策略对象 - 包含所有推导后的参数"""
    # 高层语义参数
    tension_level: int = Field(default=3, ge=1, le=5, description="张力等级")
    pacing_style: str = Field(default="balanced", description="节奏风格")
    memory_span: str = Field(default="balanced_reference", description="记忆跨度")
    creativity_level: str = Field(default="balanced_creation", description="创作自由度")
    refinement_depth: str = Field(default="standard", description="精修深度")
    progression_preference: str = Field(default="focus_scene_action", description="推进偏好")
    
    # 工作流策略
    workflow_tier: str = Field(default="TIER_2_STANDARD", description="工作流层级")
    enable_fail_fast: bool = Field(default=True, description="启用Fail-Fast")
    
    # RAG 策略
    rag_top_k: int = Field(default=5, ge=1, le=20, description="RAG检索数量")
    rag_alpha: float = Field(default=0.6, ge=0.0, le=1.0, description="语义权重")
    rag_beta: float = Field(default=0.2, ge=0.0, le=1.0, description="时间衰减权重")
    rag_gamma: float = Field(default=0.2, ge=0.0, le=1.0, description="伏笔权重")
    rag_lambda: float = Field(default=0.1, ge=0.0, description="衰减系数")
    
    # 特殊策略
    create_open_hooks: bool = Field(default=False, description="创建开放伏笔")
    enable_worldbuilding_injection: bool = Field(default=True, description="世界观注入")

    class Config:
        extra = "allow"


class RecommendedPlan(BaseModel):
    """推荐方案对象"""
    plan_id: str
    plan_name: str
    plan_type: PlanType
    description: str
    reasoning: str
    policy: GenerationPolicy
    estimated_time: str
    risk_hints: List[str] = Field(default_factory=list)
    derivation_log: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# 意图推导规则定义
# =============================================================================

INTENT_DERIVATION_RULES = {
    CreativeIntentType.ADVANCE_MAINLINE: {
        "tension_level": {"base": 4, "range": [3, 5]},
        "pacing_style": "fast_paced",
        "memory_span": "balanced_reference",
        "creativity_level": "strict_prompt",
        "refinement_depth": "standard",
        "progression_preference": "push_mainline",
        "workflow_tier": "TIER_2_STANDARD",
    },
    CreativeIntentType.CHARACTER_DEVELOPMENT: {
        "tension_level": {"base": 2, "range": [1, 4]},
        "pacing_style": "slow_burn",
        "memory_span": "deep_dive",
        "creativity_level": "balanced_creation",
        "refinement_depth": "deep",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_3_FORTRESS",
    },
    CreativeIntentType.ATMOSPHERE_BUILDING: {
        "tension_level": {"base": 2, "range": [1, 4]},
        "pacing_style": "slow_burn",
        "memory_span": "balanced_reference",
        "creativity_level": "wild_imagination",
        "refinement_depth": "deep",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_2_STANDARD",
    },
    CreativeIntentType.BUILD_CONFLICT: {
        "tension_level": {"base": 5, "range": [4, 5]},
        "pacing_style": "fast_paced",
        "memory_span": "balanced_reference",
        "creativity_level": "balanced_creation",
        "refinement_depth": "standard",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_3_FORTRESS",
        "enable_fail_fast": True,
    },
    CreativeIntentType.CLOSE_HOOKS: {
        "tension_level": {"base": 3, "range": [2, 5]},
        "pacing_style": "balanced",
        "memory_span": "deep_dive",
        "creativity_level": "strict_prompt",
        "refinement_depth": "deep",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_2_STANDARD",
        "rag_gamma": 0.4,
    },
    CreativeIntentType.WORLDBUILDING: {
        "tension_level": {"base": 2, "range": [1, 3]},
        "pacing_style": "slow_burn",
        "memory_span": "balanced_reference",
        "creativity_level": "balanced_creation",
        "refinement_depth": "standard",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_2_STANDARD",
        "enable_worldbuilding_injection": True,
    },
    CreativeIntentType.EMOTIONAL_WARMING: {
        "tension_level": {"base": 2, "range": [1, 3]},
        "pacing_style": "slow_burn",
        "memory_span": "balanced_reference",
        "creativity_level": "balanced_creation",
        "refinement_depth": "deep",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_2_STANDARD",
    },
    CreativeIntentType.DIALOGUE_SCENE: {
        "tension_level": {"base": 3, "range": [1, 5]},
        "pacing_style": "balanced",
        "memory_span": "balanced_reference",
        "creativity_level": "balanced_creation",
        "refinement_depth": "deep",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_2_STANDARD",
    },
    CreativeIntentType.BIG_SCENE: {
        "tension_level": {"base": 5, "range": [4, 5]},
        "pacing_style": "fast_paced",
        "memory_span": "deep_dive",
        "creativity_level": "wild_imagination",
        "refinement_depth": "deep",
        "progression_preference": "push_mainline",
        "workflow_tier": "TIER_3_FORTRESS",
    },
    CreativeIntentType.TRANSITION_CHAPTER: {
        "tension_level": {"base": 2, "range": [1, 3]},
        "pacing_style": "balanced",
        "memory_span": "recent_only",
        "creativity_level": "balanced_creation",
        "refinement_depth": "light",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_1_FAST",
    },
    CreativeIntentType.SUSPENSE_ENDING: {
        "tension_level": {"base": 4, "range": [3, 5]},
        "pacing_style": "balanced",
        "memory_span": "balanced_reference",
        "creativity_level": "balanced_creation",
        "refinement_depth": "standard",
        "progression_preference": "focus_scene_action",
        "workflow_tier": "TIER_2_STANDARD",
        "create_open_hooks": True,
    },
}

# 方案类型调整规则
PLAN_TYPE_ADJUSTMENTS = {
    PlanType.FAST: {
        "workflow_tier": "TIER_1_FAST",
        "refinement_depth": "light",
        "enable_fail_fast": False,
    },
    PlanType.QUALITY: {
        "workflow_tier": "TIER_3_FORTRESS",
        "refinement_depth": "deep",
    },
    PlanType.CREATIVE: {
        "creativity_level": "wild_imagination",
    },
}

# 记忆跨度到RAG参数的映射
MEMORY_SPAN_RAG_PRESETS = {
    "recent_only": {"top_k": 3, "alpha": 0.4, "beta": 0.5, "gamma": 0.1, "lambda": 0.3},
    "balanced_reference": {"top_k": 5, "alpha": 0.6, "beta": 0.2, "gamma": 0.2, "lambda": 0.1},
    "deep_dive": {"top_k": 10, "alpha": 0.5, "beta": 0.15, "gamma": 0.35, "lambda": 0.05},
}
