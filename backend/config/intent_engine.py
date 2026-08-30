# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
意图推导引擎

职责：
- 从创作意图推导生成策略
- 处理多意图合并
- 生成推荐方案
- 提供推导解释
"""

from typing import Any, Dict, List, Optional
import logging

from backend.config.intent_driven import (
    CreativeIntent,
    CreativeIntentType,
    ChapterGoal,
    GenerationPolicy,
    RecommendedPlan,
    PlanType,
    INTENT_DERIVATION_RULES,
    PLAN_TYPE_ADJUSTMENTS,
    MEMORY_SPAN_RAG_PRESETS,
)

logger = logging.getLogger(__name__)


class IntentDerivationEngine:
    """
    意图推导引擎
    
    核心方法：
    - derive_policy: 从意图推导生成策略
    - generate_plans: 生成推荐方案列表
    - merge_intents: 合并多个意图
    - explain_derivation: 解释推导过程
    """
    
    def __init__(self):
        self._derivation_log: List[Dict[str, Any]] = []
    
    def derive_policy(
        self,
        intents: List[CreativeIntent],
        goals: Optional[List[ChapterGoal]] = None,
        plan_type: PlanType = PlanType.BALANCED,
    ) -> GenerationPolicy:
        """
        从意图推导生成策略
        
        Args:
            intents: 创作意图列表（最多2个）
            goals: 章节目标列表
            plan_type: 方案类型
            
        Returns:
            GenerationPolicy: 推导后的生成策略
        """
        self._derivation_log = []
        
        # 1. 合并意图
        merged_params = self._merge_intents(intents)
        self._log("intent_merge", f"合并 {len(intents)} 个意图")
        
        # 2. 应用方案类型调整
        if plan_type != PlanType.BALANCED:
            adjustments = PLAN_TYPE_ADJUSTMENTS.get(plan_type, {})
            for key, value in adjustments.items():
                if key not in merged_params or plan_type == PlanType.QUALITY:
                    merged_params[key] = value
            self._log("plan_adjustment", f"应用 {plan_type.value} 方案调整")
        
        # 3. 构建策略对象
        policy = GenerationPolicy(**merged_params)
        
        # 4. 推导 RAG 参数
        policy = self._derive_rag_params(policy)
        
        # 5. 处理章节目标约束
        if goals:
            policy = self._apply_goal_constraints(policy, goals)
        
        return policy
    
    def _merge_intents(self, intents: List[CreativeIntent]) -> Dict[str, Any]:
        """合并多个意图的推导参数"""
        if not intents:
            return {}
        
        # 获取第一个意图的基础参数
        first_intent = intents[0]
        base_rules = INTENT_DERIVATION_RULES.get(first_intent.intent_type, {})
        merged = self._extract_params(base_rules)
        
        # 如果有第二个意图，进行合并
        if len(intents) > 1:
            second_intent = intents[1]
            second_rules = INTENT_DERIVATION_RULES.get(second_intent.intent_type, {})
            second_params = self._extract_params(second_rules)
            
            # 智能合并
            merged = self._smart_merge(merged, second_params, intents)
        
        return merged
    
    def _extract_params(self, rules: Dict[str, Any]) -> Dict[str, Any]:
        """从规则中提取参数"""
        params = {}
        for key, value in rules.items():
            if isinstance(value, dict) and "base" in value:
                # 数值范围参数，取基准值
                params[key] = value["base"]
            else:
                params[key] = value
        return params
    
    def _smart_merge(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
        intents: List[CreativeIntent]
    ) -> Dict[str, Any]:
        """智能合并两个意图的参数"""
        merged = first.copy()
        
        first_priority = intents[0].priority
        second_priority = intents[1].priority
        
        for key, second_value in second.items():
            first_value = merged.get(key)
            
            if first_value is None:
                merged[key] = second_value
                continue
            
            # 数值类型
            if isinstance(first_value, (int, float)) and isinstance(second_value, (int, float)):
                if key == "tension_level":
                    # 张力取较高值
                    merged[key] = max(first_value, second_value)
                else:
                    # 按优先级加权
                    if first_priority >= second_priority:
                        weight = first_priority / (first_priority + second_priority)
                        merged[key] = round(first_value * weight + second_value * (1 - weight), 2)
                    else:
                        weight = second_priority / (first_priority + second_priority)
                        merged[key] = round(second_value * weight + first_value * (1 - weight), 2)
            
            # 字符串类型：按优先级选择
            elif isinstance(first_value, str) and isinstance(second_value, str):
                if second_priority > first_priority:
                    merged[key] = second_value
            
            # 布尔类型：或逻辑
            elif isinstance(first_value, bool) and isinstance(second_value, bool):
                merged[key] = first_value or second_value
        
        self._log(
            "smart_merge",
            f"合并意图: tension={merged.get('tension_level')}, pacing={merged.get('pacing_style')}"
        )
        
        return merged
    
    def _derive_rag_params(self, policy: GenerationPolicy) -> GenerationPolicy:
        """推导 RAG 参数"""
        preset = MEMORY_SPAN_RAG_PRESETS.get(
            policy.memory_span, 
            MEMORY_SPAN_RAG_PRESETS["balanced_reference"]
        )
        
        # 如果意图规则中指定了 rag_gamma，使用它并重新归一化
        if hasattr(policy, "rag_gamma") and policy.rag_gamma and policy.rag_gamma > preset["gamma"]:
            preset = preset.copy()
            preset["gamma"] = policy.rag_gamma
            total = preset["alpha"] + preset["beta"] + preset["gamma"]
            if total > 0:
                preset["alpha"] = round(preset["alpha"] / total, 4)
                preset["beta"] = round(preset["beta"] / total, 4)
                preset["gamma"] = round(preset["gamma"] / total, 4)
        
        policy.rag_top_k = preset["top_k"]
        policy.rag_alpha = preset["alpha"]
        policy.rag_beta = preset["beta"]
        policy.rag_gamma = preset["gamma"]
        policy.rag_lambda = preset["lambda"]
        
        self._log(
            "rag_derivation",
            f"memory_span={policy.memory_span} → top_k={policy.rag_top_k}, "
            f"alpha={policy.rag_alpha:.2f}, beta={policy.rag_beta:.2f}, gamma={policy.rag_gamma:.2f}"
        )
        
        return policy
    
    def _apply_goal_constraints(
        self,
        policy: GenerationPolicy,
        goals: List[ChapterGoal]
    ) -> GenerationPolicy:
        """应用章节目标约束"""
        # 章节目标主要影响生成内容，对策略参数影响较小
        # 可根据需要扩展
        return policy
    
    def generate_plans(
        self,
        intents: List[CreativeIntent],
        goals: Optional[List[ChapterGoal]] = None,
    ) -> List[RecommendedPlan]:
        """生成推荐方案列表"""
        plans = []
        
        # 均衡方案
        balanced_policy = self.derive_policy(intents, goals, PlanType.BALANCED)
        plans.append(RecommendedPlan(
            plan_id="balanced_default",
            plan_name="均衡方案",
            plan_type=PlanType.BALANCED,
            description="在速度与质量之间取得平衡，适合大多数场景",
            reasoning=self._generate_reasoning(intents, PlanType.BALANCED),
            policy=balanced_policy,
            estimated_time="约 2-3 分钟",
            risk_hints=[],
            derivation_log=self._derivation_log.copy(),
        ))
        
        # 快速方案
        fast_policy = self.derive_policy(intents, goals, PlanType.FAST)
        plans.append(RecommendedPlan(
            plan_id="fast_track",
            plan_name="快速方案",
            plan_type=PlanType.FAST,
            description="快速生成，适合快速预览或过渡章节",
            reasoning="如果您希望快速看到结果，或这是一个过渡章节，可以选择此方案。",
            policy=fast_policy,
            estimated_time="约 1-2 分钟",
            risk_hints=["质量可能略低于均衡方案", "连贯性检查较弱"],
            derivation_log=self._derivation_log.copy(),
        ))
        
        # 质量优先方案
        quality_policy = self.derive_policy(intents, goals, PlanType.QUALITY)
        plans.append(RecommendedPlan(
            plan_id="quality_first",
            plan_name="精雕细琢",
            plan_type=PlanType.QUALITY,
            description="最高质量输出，适合重要章节",
            reasoning="如果这是关键章节，建议选择此方案以获得最佳质量。",
            policy=quality_policy,
            estimated_time="约 4-6 分钟",
            risk_hints=["耗时较长", "可能需要多轮迭代"],
            derivation_log=self._derivation_log.copy(),
        ))
        
        # 创意优先方案（仅在特定意图时出现）
        intent_types = [i.intent_type for i in intents]
        if any(t in intent_types for t in [
            CreativeIntentType.ATMOSPHERE_BUILDING,
            CreativeIntentType.WORLDBUILDING,
            CreativeIntentType.BIG_SCENE,
        ]):
            creative_policy = self.derive_policy(intents, goals, PlanType.CREATIVE)
            plans.append(RecommendedPlan(
                plan_id="creative_first",
                plan_name="创意优先",
                plan_type=PlanType.CREATIVE,
                description="给予AI更大创作自由，适合需要创意的场景",
                reasoning="您选择的意图适合创意发挥，此方案给予AI更大的创作空间。",
                policy=creative_policy,
                estimated_time="约 3-4 分钟",
                risk_hints=["结果可能偏离预期", "建议仔细审阅"],
                derivation_log=self._derivation_log.copy(),
            ))
        
        return plans
    
    def _generate_reasoning(
        self,
        intents: List[CreativeIntent],
        plan_type: PlanType
    ) -> str:
        """生成推荐原因说明"""
        intent_names = [self._get_intent_display_name(i.intent_type) for i in intents]
        
        if len(intents) == 1:
            base_reason = f"基于您选择的「{intent_names[0]}」意图"
        else:
            base_reason = f"基于您选择的「{' + '.join(intent_names)}」组合意图"
        
        if plan_type == PlanType.BALANCED:
            return f"{base_reason}，系统推荐此均衡配置，能够满足大部分创作需求。"
        elif plan_type == PlanType.FAST:
            return f"{base_reason}，如果您希望快速预览效果，可选择此快速方案。"
        elif plan_type == PlanType.QUALITY:
            return f"{base_reason}，建议选择此方案以获得最佳质量。"
        else:
            return f"{base_reason}，适合需要创意发挥的场景。"
    
    def _get_intent_display_name(self, intent_type: CreativeIntentType) -> str:
        """获取意图显示名称"""
        display_names = {
            CreativeIntentType.ADVANCE_MAINLINE: "推进主线",
            CreativeIntentType.CHARACTER_DEVELOPMENT: "塑造人物",
            CreativeIntentType.ATMOSPHERE_BUILDING: "营造氛围",
            CreativeIntentType.BUILD_CONFLICT: "制造冲突",
            CreativeIntentType.CLOSE_HOOKS: "回收伏笔",
            CreativeIntentType.WORLDBUILDING: "展开世界观",
            CreativeIntentType.EMOTIONAL_WARMING: "情感升温",
            CreativeIntentType.DIALOGUE_SCENE: "对话戏",
            CreativeIntentType.BIG_SCENE: "大场面",
            CreativeIntentType.TRANSITION_CHAPTER: "过渡章节",
            CreativeIntentType.SUSPENSE_ENDING: "悬念结尾",
        }
        return display_names.get(intent_type, intent_type.value)
    
    def explain_derivation(self, policy: GenerationPolicy) -> Dict[str, Any]:
        """解释推导过程"""
        return {
            "tension_level": {
                "value": policy.tension_level,
                "source": "intent_derivation",
                "reason": "根据意图类型推导的张力等级",
            },
            "pacing_style": {
                "value": policy.pacing_style,
                "source": "intent_derivation",
                "reason": "根据意图类型推导的节奏风格",
            },
            "memory_span": {
                "value": policy.memory_span,
                "source": "intent_derivation",
                "reason": "根据意图类型推导的记忆检索深度",
            },
            "rag_params": {
                "value": {
                    "top_k": policy.rag_top_k,
                    "alpha": policy.rag_alpha,
                    "beta": policy.rag_beta,
                    "gamma": policy.rag_gamma,
                },
                "source": "memory_span_preset",
                "reason": f"根据 memory_span={policy.memory_span} 推导",
            },
            "workflow_tier": {
                "value": policy.workflow_tier,
                "source": "tension_level_mapping",
                "reason": f"根据 tension_level={policy.tension_level} 推导",
            },
        }
    
    def _log(self, rule_name: str, result: str) -> None:
        """记录推导日志"""
        self._derivation_log.append({
            "rule": rule_name,
            "result": result,
        })
    
    def get_derivation_log(self) -> List[Dict[str, Any]]:
        """获取推导日志"""
        return self._derivation_log.copy()
