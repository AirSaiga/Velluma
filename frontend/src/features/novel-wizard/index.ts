/**
 * 小说创作向导模块
 * 
 * 提供用户友好的小说创建和章节生成输入界面
 */

// 类型导出
export * from './types/wizard.types'

// 组合式函数导出
export { useNovelWizard, type UseNovelWizardReturn } from './composables/useNovelWizard'

// 容器组件导出
export { default as NovelCreationWizard } from './containers/NovelCreationWizard.vue'

// 展示组件导出
export { default as StoryBasicsPanel } from './presentation/StoryBasicsPanel.vue'
export { default as WorldBuildingPanel } from './presentation/WorldBuildingPanel.vue'
export { default as CharacterManagerPanel } from './presentation/CharacterManagerPanel.vue'
export { default as ChapterConfigPanel } from './presentation/ChapterConfigPanel.vue'
export { default as ExpertSettingsPanel } from './presentation/ExpertSettingsPanel.vue'
