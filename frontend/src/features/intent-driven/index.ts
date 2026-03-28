// 创作意图驱动层导出

export { useIntentDrivenConfig } from './useIntentDrivenConfig'
export { CREATIVE_INTENT_TEMPLATES, CHAPTER_GOAL_TEMPLATES } from './intentTemplates'

// 组件导出
export { default as IntentSelector } from './components/IntentSelector.vue'
export { default as GoalSelector } from './components/GoalSelector.vue'
export { default as RecommendedPlanCard } from './components/RecommendedPlanCard.vue'
export { default as ExpertOverridePanel } from './components/ExpertOverridePanel.vue'
export { default as IntentDrivenPanel } from './components/IntentDrivenPanel.vue'

// 类型重新导出
export type {
  CreativeIntentType,
  ChapterGoalType,
  PlanType,
  CreativeIntentTemplate,
  ChapterGoalTemplate,
  RecommendedPlan,
  GenerationPolicy,
  IntentDrivenGeneratePayload,
  IntentDrivenState
} from '@/types/intentDriven'
