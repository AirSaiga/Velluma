import { ref, computed, watch } from 'vue'
import type { 
  CreativeIntentType, 
  ChapterGoalType, 
  PlanType,
  RecommendedPlan,
  IntentDrivenState,
  IntentDrivenGeneratePayload,
  RecommendResponse
} from '@/types/intentDriven'
import { CREATIVE_INTENT_TEMPLATES, CHAPTER_GOAL_TEMPLATES } from './intentTemplates'

// 默认状态
const defaultState: IntentDrivenState = {
  selectedIntents: [],
  selectedGoals: [],
  selectedPlanType: 'balanced',
  recommendedPlans: [],
  userOverrides: {},
  isExpertModeExpanded: false
}

// 全局状态
const state = ref<IntentDrivenState>({ ...defaultState })

export function useIntentDrivenConfig() {
  // 计算属性
  const selectedIntents = computed(() => state.value.selectedIntents)
  const selectedGoals = computed(() => state.value.selectedGoals)
  
  const selectedIntentTemplates = computed(() => {
    return state.value.selectedIntents
      .map(id => CREATIVE_INTENT_TEMPLATES.find(t => t.id === id))
      .filter(Boolean)
  })
  
  const selectedGoalTemplates = computed(() => {
    return state.value.selectedGoals
      .map(id => CHAPTER_GOAL_TEMPLATES.find(t => t.id === id))
      .filter(Boolean)
  })
  
  const canSelectMore = computed(() => {
    return state.value.selectedIntents.length < 2
  })
  
  const canSelectMoreIntents = computed(() => {
    return state.value.selectedIntents.length < 2
  })
  
  const hasSelection = computed(() => {
    return state.value.selectedIntents.length > 0 || state.value.selectedGoals.length > 0
  })
  
  const recommendedPlan = computed(() => {
    return state.value.recommendedPlans.find(
      p => p.plan_type === state.value.selectedPlanType
    )
  })
  
  const recommendedPlans = computed(() => state.value.recommendedPlans)
  
  const selectedPlanType = computed(() => state.value.selectedPlanType)
  
  const isExpertModeExpanded = computed(() => state.value.isExpertModeExpanded)
  
  const hasOverrides = computed(() => {
    return Object.keys(state.value.userOverrides).length > 0
  })
  
  const overrideCount = computed(() => {
    return Object.keys(state.value.userOverrides).length
  })
  
  const userOverrides = computed(() => state.value.userOverrides)
  
  // 方法
  function toggleIntent(intentId: CreativeIntentType) {
    const index = state.value.selectedIntents.indexOf(intentId)
    
    if (index > -1) {
      state.value.selectedIntents.splice(index, 1)
    } else if (canSelectMoreIntents.value) {
      state.value.selectedIntents.push(intentId)
    }
    
    refreshRecommendations()
  }
  
  function toggleGoal(goalId: ChapterGoalType) {
    const index = state.value.selectedGoals.indexOf(goalId)
    
    if (index > -1) {
      state.value.selectedGoals.splice(index, 1)
    } else {
      state.value.selectedGoals.push(goalId)
    }
    
    refreshRecommendations()
  }
  
  function selectPlanType(planType: PlanType) {
    state.value.selectedPlanType = planType
  }
  
  function toggleExpertMode() {
    state.value.isExpertModeExpanded = !state.value.isExpertModeExpanded
  }
  
  function setOverride(field: string, value: any, originalValue: any) {
    state.value.userOverrides[field] = {
      original: originalValue,
      current: value
    }
  }
  
  function clearOverride(field: string) {
    delete state.value.userOverrides[field]
  }
  
  function clearAllOverrides() {
    state.value.userOverrides = {}
  }
  
  function reset() {
    state.value = { ...defaultState }
  }
  
  async function refreshRecommendations() {
    if (!hasSelection.value) {
      state.value.recommendedPlans = []
      return
    }
    
    try {
      const response = await fetch('/api/intent-driven/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          creative_intents: state.value.selectedIntents,
          chapter_goals: state.value.selectedGoals.length > 0 ? state.value.selectedGoals : null
        })
      })
      
      const data: RecommendResponse = await response.json()
      state.value.recommendedPlans = data.plans
    } catch (error) {
      console.error('获取推荐方案失败:', error)
      state.value.recommendedPlans = generateLocalRecommendations()
    }
  }
  
  function generateLocalRecommendations(): RecommendedPlan[] {
    const plans: RecommendedPlan[] = []
    
    plans.push({
      plan_id: 'balanced_default',
      plan_name: '均衡方案',
      plan_type: 'balanced',
      description: '在速度与质量之间取得平衡',
      reasoning: '基于您选择的意图，系统推荐此均衡配置',
      estimated_time: '约 2-3 分钟',
      risk_hints: [],
      derivation_log: [],
      policy: {
        tension_level: 3,
        pacing_style: 'balanced',
        memory_span: 'balanced_reference',
        creativity_level: 'balanced_creation',
        refinement_depth: 'standard',
        progression_preference: 'focus_scene_action',
        workflow_tier: 'TIER_2_STANDARD',
        enable_dual_track: true,
        enable_fail_fast: true,
        rag_top_k: 5,
        rag_alpha: 0.6,
        rag_beta: 0.2,
        rag_gamma: 0.2,
        rag_lambda: 0.1
      }
    })
    
    plans.push({
      plan_id: 'fast_track',
      plan_name: '快速方案',
      plan_type: 'fast',
      description: '快速生成，适合预览',
      reasoning: '如果您希望快速看到结果',
      estimated_time: '约 1-2 分钟',
      risk_hints: ['质量可能略低'],
      derivation_log: [],
      policy: {
        tension_level: 2,
        pacing_style: 'balanced',
        memory_span: 'recent_only',
        creativity_level: 'balanced_creation',
        refinement_depth: 'light',
        progression_preference: 'focus_scene_action',
        workflow_tier: 'TIER_1_FAST',
        enable_dual_track: false,
        enable_fail_fast: false,
        rag_top_k: 3,
        rag_alpha: 0.4,
        rag_beta: 0.5,
        rag_gamma: 0.1,
        rag_lambda: 0.3
      }
    })
    
    plans.push({
      plan_id: 'quality_first',
      plan_name: '精雕细琢',
      plan_type: 'quality',
      description: '最高质量输出',
      reasoning: '如果这是关键章节',
      estimated_time: '约 4-6 分钟',
      risk_hints: ['耗时较长'],
      derivation_log: [],
      policy: {
        tension_level: 4,
        pacing_style: 'balanced',
        memory_span: 'deep_dive',
        creativity_level: 'balanced_creation',
        refinement_depth: 'deep',
        progression_preference: 'focus_scene_action',
        workflow_tier: 'TIER_3_FORTRESS',
        enable_dual_track: true,
        enable_fail_fast: true,
        rag_top_k: 10,
        rag_alpha: 0.5,
        rag_beta: 0.15,
        rag_gamma: 0.35,
        rag_lambda: 0.05
      }
    })
    
    return plans
  }
  
  function buildPayload(baseParams: {
    chapterId: string
    apiConfig: {
      api_key: string
      base_url?: string
      model?: string
    }
    wordCount: number
    authorIntent?: string
  }): IntentDrivenGeneratePayload {
    const overrides = Object.fromEntries(
      Object.entries(state.value.userOverrides).map(([k, v]) => [k, v.current])
    )
    
    return {
      chapter_id: baseParams.chapterId,
      api_key: baseParams.apiConfig.api_key,
      base_url: baseParams.apiConfig.base_url,
      model: baseParams.apiConfig.model,
      
      creative_intents: state.value.selectedIntents.length > 0 
        ? state.value.selectedIntents 
        : undefined,
      chapter_goals: state.value.selectedGoals.length > 0 
        ? state.value.selectedGoals 
        : undefined,
      selected_plan_type: state.value.selectedPlanType,
      
      user_overrides: Object.keys(overrides).length > 0 ? overrides : undefined,
      
      word_count: baseParams.wordCount,
      author_intent: baseParams.authorIntent
    }
  }
  
  function getIntentDisplayName(intentType: CreativeIntentType): string {
    const template = CREATIVE_INTENT_TEMPLATES.find(t => t.id === intentType)
    return template?.display_name || intentType
  }
  
  return {
    // 状态
    state,
    
    // 计算属性
    selectedIntents,
    selectedGoals,
    userOverrides,
    selectedIntentTemplates,
    selectedGoalTemplates,
    canSelectMore,
    canSelectMoreIntents,
    hasSelection,
    recommendedPlans,
    recommendedPlan,
    selectedPlanType,
    isExpertModeExpanded,
    hasOverrides,
    overrideCount,
    
    // 模板数据
    intentTemplates: CREATIVE_INTENT_TEMPLATES,
    goalTemplates: CHAPTER_GOAL_TEMPLATES,
    
    // 方法
    toggleIntent,
    toggleGoal,
    selectPlanType,
    toggleExpertMode,
    setOverride,
    clearOverride,
    clearAllOverrides,
    reset,
    refreshRecommendations,
    buildPayload,
    getIntentDisplayName
  }
}
