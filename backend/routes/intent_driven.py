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
意图驱动生成路由

提供意图模板查询、推荐方案生成、意图驱动生成等接口
"""

import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import List, Optional

from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_WORKFLOW
from backend.schemas import RecommendRequest

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)

from backend.config.intent_driven import (
    CreativeIntentType,
    ChapterGoalType,
    PlanType,
    CreativeIntent,
    ChapterGoal,
)
from backend.config.intent_engine import IntentDerivationEngine

router = APIRouter(prefix="/api/intent-driven", tags=["intent_driven"])


# =============================================================================
# 意图模板数据
# =============================================================================

INTENT_TEMPLATES_DATA = [
    {
        "id": "advance_mainline",
        "display_name": "推进主线",
        "short_desc": "推动核心剧情向前发展",
        "detailed_desc": "专注于主线剧情的推进，节奏明快，信息密度高，适合承上启下的关键章节。",
        "applicable_scenarios": ["需要推进主要剧情线时", "承上启下的过渡章节", "需要埋下重要伏笔时"],
        "style_recommendation": "节奏紧凑，信息密度高，减少支线干扰",
        "icon": "🚀",
        "combo_suggestions": ["build_conflict", "close_hooks"]
    },
    {
        "id": "character_development",
        "display_name": "塑造人物",
        "short_desc": "深度刻画角色内心与成长",
        "detailed_desc": "聚焦角色的内心世界、情感变化、成长弧线，强调心理描写和细节刻画。",
        "applicable_scenarios": ["主角面临重要抉择时", "角色关系发生变化时", "需要展现角色成长时"],
        "style_recommendation": "细腻心理描写，节奏舒缓，重视对话质量",
        "icon": "👤",
        "combo_suggestions": ["emotional_warming", "build_conflict"]
    },
    {
        "id": "atmosphere_building",
        "display_name": "营造氛围",
        "short_desc": "构建沉浸式环境与情绪",
        "detailed_desc": "强调环境描写、感官细节、情绪渲染，创造强烈的沉浸感和代入感。",
        "applicable_scenarios": ["重要场景首次登场时", "需要营造紧张/诡异/浪漫氛围时", "世界观展示的关键场景"],
        "style_recommendation": "多感官描写，节奏舒缓，重视画面感",
        "icon": "🌫️",
        "combo_suggestions": ["worldbuilding", "suspense_ending"]
    },
    {
        "id": "build_conflict",
        "display_name": "制造冲突",
        "short_desc": "强化矛盾冲突与戏剧张力",
        "detailed_desc": "放大角色间、角色与环境间的矛盾，提升戏剧张力，制造紧张感。",
        "applicable_scenarios": ["剧情高潮即将来临", "角色矛盾激化", "需要制造转折点"],
        "style_recommendation": "节奏紧凑，对话犀利，张力层次分明",
        "icon": "⚔️",
        "combo_suggestions": ["advance_mainline", "character_development"]
    },
    {
        "id": "close_hooks",
        "display_name": "回收伏笔",
        "short_desc": "闭合前期埋下的线索与悬念",
        "detailed_desc": "集中回收前期伏笔，确保前后呼应，给予读者满足感。",
        "applicable_scenarios": ["前期伏笔需要收束时", "悬念揭晓的关键时刻", "章节末尾需要收束时"],
        "style_recommendation": "前后呼应，节奏稳健，确保逻辑自洽",
        "icon": "🔗",
        "combo_suggestions": ["advance_mainline", "suspense_ending"]
    },
    {
        "id": "worldbuilding",
        "display_name": "展开世界观",
        "short_desc": "展示世界设定与背景细节",
        "detailed_desc": "自然地融入世界观设定，展示独特的规则、历史、文化等元素。",
        "applicable_scenarios": ["新场景首次登场", "需要解释设定背景", "世界观相关剧情"],
        "style_recommendation": "自然融入，避免说明文式，通过角色视角展示",
        "icon": "🌍",
        "combo_suggestions": ["atmosphere_building", "advance_mainline"]
    },
    {
        "id": "emotional_warming",
        "display_name": "情感升温",
        "short_desc": "深化角色间情感联结",
        "detailed_desc": "重点刻画角色间的情感互动，升温关系，制造甜蜜或感动时刻。",
        "applicable_scenarios": ["感情线关键节点", "角色关系突破", "温馨治愈场景"],
        "style_recommendation": "细腻情感描写，对话走心，氛围温馨",
        "icon": "💕",
        "combo_suggestions": ["character_development", "dialogue_scene"]
    },
    {
        "id": "dialogue_scene",
        "display_name": "对话戏",
        "short_desc": "以高质量对话推进剧情",
        "detailed_desc": "以对话为主体，通过角色间的言语交锋推进剧情，强调台词质量。",
        "applicable_scenarios": ["需要展示角色性格", "信息通过对话传递", "辩论/谈判/对峙场景"],
        "style_recommendation": "对话生动，节奏感强，避免冗长",
        "icon": "💬",
        "combo_suggestions": ["build_conflict", "emotional_warming"]
    },
    {
        "id": "big_scene",
        "display_name": "大场面",
        "short_desc": "宏大场景与多线叙事",
        "detailed_desc": "处理多角色、多视角的复杂场景，需要协调多条线索。",
        "applicable_scenarios": ["战争/战斗场面", "大型活动/集会", "多线剧情汇合"],
        "style_recommendation": "多视角切换自然，节奏把控精准，场面感强",
        "icon": "🏟️",
        "combo_suggestions": ["build_conflict", "advance_mainline"]
    },
    {
        "id": "transition_chapter",
        "display_name": "过渡章节",
        "short_desc": "平稳过渡，承上启下",
        "detailed_desc": "连接两个重要情节的过渡章节，节奏舒缓，为后续高潮做铺垫。",
        "applicable_scenarios": ["两个高潮之间", "时间/地点转换", "节奏调节需要"],
        "style_recommendation": "节奏舒缓，信息适度，避免平淡无味",
        "icon": "🌉",
        "combo_suggestions": ["character_development", "worldbuilding"]
    },
    {
        "id": "suspense_ending",
        "display_name": "悬念结尾",
        "short_desc": "制造悬念与期待感",
        "detailed_desc": "章节末尾制造悬念，吊起读者期待，为下一章埋下钩子。",
        "applicable_scenarios": ["章节末尾需要留钩子", "制造读者期待", "下一章高潮预告"],
        "style_recommendation": "节奏渐强，末段收紧，留下悬念钩子",
        "icon": "❓",
        "combo_suggestions": ["advance_mainline", "close_hooks"]
    }
]

GOAL_TEMPLATES_DATA = [
    {
        "id": "introduce_character",
        "display_name": "引入新角色",
        "description": "本章需要引入一个或多个新角色",
        "required_elements": ["角色初次登场描写", "角色基本特征展示", "角色与现有角色的互动"],
        "success_criteria": ["新角色形象清晰", "读者对角色产生印象", "角色自然融入现有关系网"]
    },
    {
        "id": "resolve_conflict",
        "display_name": "解决冲突",
        "description": "本章需要解决一个或多个现有冲突",
        "required_elements": ["冲突高潮描写", "解决方案展示", "冲突解决后的影响"],
        "success_criteria": ["冲突解决逻辑自洽", "读者获得满足感", "为后续剧情留有空间"]
    },
    {
        "id": "reveal_secret",
        "display_name": "揭示秘密",
        "description": "本章需要揭示一个重要信息或秘密",
        "required_elements": ["悬念铺垫", "揭示过程", "角色反应"],
        "success_criteria": ["揭示时机恰当", "读者获得惊讶感", "信息逻辑自洽"]
    },
    {
        "id": "change_relationship",
        "display_name": "关系变化",
        "description": "本章需要展现角色关系的重大变化",
        "required_elements": ["关系变化触发事件", "变化过程描写", "变化后的互动"],
        "success_criteria": ["关系变化可信", "读者产生情感共鸣", "为后续剧情埋下伏笔"]
    },
    {
        "id": "set_scene",
        "display_name": "场景建立",
        "description": "本章需要建立一个新的重要场景",
        "required_elements": ["地点外观描写", "地点氛围营造", "地点与剧情关联"],
        "success_criteria": ["地点形象清晰", "读者产生代入感", "地点服务于剧情"]
    }
]


# =============================================================================
# 路由处理
# =============================================================================

@router.get("/templates")
async def get_intent_templates():
    """获取意图模板和章节目标模板列表"""
    return {
        "creative_intents": INTENT_TEMPLATES_DATA,
        "chapter_goals": GOAL_TEMPLATES_DATA
    }


@router.post("/recommend")
async def generate_recommendations(request: RecommendRequest):
    """
    根据选择的意图生成推荐方案
    
    Returns:
        包含多个推荐方案的响应
    """
    # 构建意图对象
    intents = []
    for i, intent_type in enumerate(request.creative_intents[:2]):
        try:
            intent = CreativeIntent(
                intent_type=CreativeIntentType(intent_type),
                priority=2 - i
            )
            intents.append(intent)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的意图类型: {intent_type}")
    
    # 构建目标对象
    goals = None
    if request.chapter_goals:
        goals = []
        for goal_type in request.chapter_goals[:3]:
            try:
                goal = ChapterGoal(goal_type=ChapterGoalType(goal_type))
                goals.append(goal)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"无效的目标类型: {goal_type}")
    
    # 生成推荐方案
    engine = IntentDerivationEngine()
    plans = engine.generate_plans(intents, goals)
    
    # 构建响应
    response_plans = []
    for plan in plans:
        policy_dict = plan.policy.model_dump()
        
        response_plans.append({
            "plan_id": plan.plan_id,
            "plan_name": plan.plan_name,
            "plan_type": plan.plan_type.value,
            "description": plan.description,
            "reasoning": plan.reasoning,
            "estimated_time": plan.estimated_time,
            "risk_hints": plan.risk_hints,
            "derivation_log": plan.derivation_log,
            "policy": policy_dict
        })
    
    return {
        "plans": response_plans,
        "intent_analysis": {
            "selected_intents": [i.intent_type.value for i in intents],
            "merged_strategy": engine.explain_derivation(plans[0].policy) if plans else {}
        },
        "derivation_explanation": engine.get_derivation_log()
    }
