// 创作意图驱动层类型定义

// 创作意图类型
export type CreativeIntentType = 
  | 'advance_mainline'
  | 'character_development'
  | 'atmosphere_building'
  | 'build_conflict'
  | 'close_hooks'
  | 'worldbuilding'
  | 'emotional_warming'
  | 'dialogue_scene'
  | 'big_scene'
  | 'transition_chapter'
  | 'suspense_ending'

// 章节目标类型
export type ChapterGoalType =
  | 'introduce_character'
  | 'resolve_conflict'
  | 'reveal_secret'
  | 'change_relationship'
  | 'set_scene'

// 方案类型
export type PlanType = 'balanced' | 'fast' | 'quality' | 'creative'

// 创作意图模板
export interface CreativeIntentTemplate {
  id: CreativeIntentType
  display_name: string
  short_desc: string
  detailed_desc: string
  applicable_scenarios: string[]
  style_recommendation: string
  icon: string
  combo_suggestions?: CreativeIntentType[]
}

// 章节目标模板
export interface ChapterGoalTemplate {
  id: ChapterGoalType
  display_name: string
  description: string
  required_elements: string[]
  success_criteria: string[]
}

// 推荐方案
export interface RecommendedPlan {
  plan_id: string
  plan_name: string
  plan_type: PlanType
  description: string
  reasoning: string
  estimated_time: string
  risk_hints: string[]
  derivation_log: Array<{ rule: string; result: string }>
  policy: GenerationPolicy
}

// 生成策略
export interface GenerationPolicy {
  tension_level: number
  pacing_style: 'slow_burn' | 'balanced' | 'fast_paced'
  memory_span: 'recent_only' | 'balanced_reference' | 'deep_dive'
  creativity_level: 'strict_prompt' | 'balanced_creation' | 'wild_imagination'
  refinement_depth: 'light' | 'standard' | 'deep'
  progression_preference: 'focus_scene_action' | 'push_mainline'
  workflow_tier: 'TIER_1_FAST' | 'TIER_2_STANDARD' | 'TIER_3_FORTRESS'
  enable_dual_track: boolean
  enable_fail_fast: boolean
  rag_top_k: number
  rag_alpha: number
  rag_beta: number
  rag_gamma: number
  rag_lambda: number
}

// 意图驱动请求
export interface IntentDrivenGeneratePayload {
  chapter_id: string
  
  // 意图参数
  creative_intents?: CreativeIntentType[]
  intent_priorities?: number[]
  custom_intent_description?: string
  
  // 章节目标
  chapter_goals?: ChapterGoalType[]
  target_entity_ids?: string[]
  
  // 方案选择
  selected_plan_type: PlanType
  
  // 用户覆盖
  user_overrides?: Record<string, any>
  
  // 基础参数
  word_count: number
  author_intent?: string
}

// 意图状态
export interface IntentDrivenState {
  selectedIntents: CreativeIntentType[]
  selectedGoals: ChapterGoalType[]
  selectedPlanType: PlanType
  recommendedPlans: RecommendedPlan[]
  userOverrides: Record<string, { original: any; current: any }>
  isExpertModeExpanded: boolean
  // 篇幅与创作意图：从 IntentDrivenPanel 组件本地 ref 提升到单例状态
  wordCount: number        // 默认 3000
  authorIntent: string     // 默认 ''
}

// 推荐方案响应
export interface RecommendResponse {
  plans: RecommendedPlan[]
  intent_analysis: {
    selected_intents: string[]
    merged_strategy: Record<string, any>
  }
  derivation_explanation: Array<{ rule: string; result: string }>
}

// 模板响应
export interface TemplatesResponse {
  creative_intents: CreativeIntentTemplate[]
  chapter_goals: ChapterGoalTemplate[]
}
