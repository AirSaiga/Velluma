// 创作意图驱动层导出

export { useIntentDrivenConfig, buildAgenticPayloadFromIntent } from './useIntentDrivenConfig'
export { CREATIVE_INTENT_TEMPLATES, CHAPTER_GOAL_TEMPLATES } from './intentTemplates'

// 容器组件导出
export { default as IntentDrivenPanel } from './containers/IntentDrivenPanel.vue'

// 展示组件导出
export { default as IntentSelector } from './presentation/IntentSelector.vue'
export { default as GoalSelector } from './presentation/GoalSelector.vue'
export { default as RecommendedPlanCard } from './presentation/RecommendedPlanCard.vue'
export { default as ExpertOverridePanel } from './presentation/ExpertOverridePanel.vue'

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
