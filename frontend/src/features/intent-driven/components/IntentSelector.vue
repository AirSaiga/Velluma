<template>
  <div class="intent-selector">
    <div class="selector-header">
      <h3 class="selector-title">核心意图</h3>
      <span class="required-badge">必选 1-2 项</span>
    </div>
    
    <div class="intent-grid">
      <div
        v-for="intent in intentTemplates"
        :key="intent.id"
        class="intent-card-wrapper"
      >
        <button
          type="button"
          class="intent-card"
          :class="{
            'selected': selectedIntents.includes(intent.id),
            'disabled': !canSelectMore && !selectedIntents.includes(intent.id)
          }"
          :disabled="!canSelectMore && !selectedIntents.includes(intent.id)"
          @click="toggleIntent(intent.id)"
          @mouseenter="showTooltip(intent.id, $event)"
          @mouseleave="hideTooltip"
        >
          <!-- 左侧图标 -->
          <div class="intent-icon-box">
            <Component :is="getIntentIcon(intent.id)" class="w-5 h-5" />
          </div>
          
          <!-- 中间文字 -->
          <div class="intent-content">
            <div class="intent-name">{{ intent.display_name }}</div>
            <div class="intent-desc">{{ intent.short_desc }}</div>
          </div>

          <!-- 右侧勾选圈 -->
          <div class="intent-check-ring">
            <svg class="w-3.5 h-3.5 check-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
            </svg>
          </div>
        </button>
        
        <!-- 精美 Tooltip -->
        <Transition name="tooltip-fade">
          <div 
            v-if="tooltipVisible && tooltipIntentId === intent.id"
            class="intent-tooltip"
            :class="{ 'is-bottom': tooltipPlacement === 'bottom' }"
            :style="tooltipStyle"
          >
            <div class="tooltip-header">
              <div class="tooltip-title">{{ intent.display_name }}</div>
            </div>
            <div class="tooltip-desc">{{ intent.detailed_desc }}</div>
            <div class="tooltip-section">
              <div class="tooltip-section-title">适用场景</div>
              <ul class="tooltip-list">
                <li v-for="(scenario, idx) in intent.applicable_scenarios" :key="idx">
                  {{ scenario }}
                </li>
              </ul>
            </div>
            <div class="tooltip-section">
              <div class="tooltip-section-title">风格建议</div>
              <div class="tooltip-style">{{ intent.style_recommendation }}</div>
            </div>
          </div>
        </Transition>
      </div>
    </div>

    <!-- 组合意图提示 (优雅 Inline Alert) -->
    <Transition name="fade-up">
      <div v-if="selectedIntents.length === 2" class="combo-alert">
        <div class="combo-icon">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <div class="combo-text">已开启组合意图，系统将智能融合这两种生成策略。</div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { h, ref, reactive, nextTick } from 'vue'
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'

// Tooltip 状态
const tooltipVisible = ref(false)
const tooltipIntentId = ref<string>('')
const tooltipPlacement = ref<'top' | 'bottom'>('top')
const tooltipStyle = reactive({
  position: 'fixed' as const,
  top: '0px',
  left: '0px'
})

async function showTooltip(intentId: string, event: MouseEvent) {
  tooltipIntentId.value = intentId
  tooltipVisible.value = true
  
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()

  await nextTick()

  const tooltipEl = document.querySelector('.intent-tooltip') as HTMLElement | null
  const tooltipWidth = tooltipEl?.offsetWidth ?? 300
  const tooltipHeight = tooltipEl?.offsetHeight ?? 240
  const gap = 16
  const viewportPadding = 16
  const viewportWidth = window.innerWidth

  const centerX = rect.left + rect.width / 2
  const minCenter = viewportPadding + tooltipWidth / 2
  const maxCenter = viewportWidth - viewportPadding - tooltipWidth / 2
  const left = Math.min(Math.max(centerX, minCenter), maxCenter)

  const topWhenAbove = rect.top - tooltipHeight - gap
  const canShowAbove = topWhenAbove >= viewportPadding
  const top = canShowAbove ? topWhenAbove : rect.bottom + gap

  tooltipPlacement.value = canShowAbove ? 'top' : 'bottom'
  tooltipStyle.top = `${Math.round(top)}px`
  tooltipStyle.left = `${Math.round(left)}px`
}

function hideTooltip() {
  tooltipVisible.value = false
  tooltipIntentId.value = ''
}

// 引入 SVG 图标组件
const icons: Record<string, any> = {}

// 推进主线
icons.advance_mainline = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M13 10V3L4 14h7v7l9-11h-7z' })
    ])
  }
}
// 塑造人物
icons.character_development = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' })
    ])
  }
}
// 营造氛围
icons.atmosphere_building = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z' })
    ])
  }
}
// 制造冲突
icons.build_conflict = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M13 10V3L4 14h7v7l9-11h-7z' })
    ])
  }
}
// 回收伏笔
icons.close_hooks = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' })
    ])
  }
}
// 展开世界观
icons.worldbuilding = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9' })
    ])
  }
}
// 情感升温
icons.emotional_warming = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z' })
    ])
  }
}
// 对话戏
icons.dialogue_scene = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' })
    ])
  }
}
// 大场面
icons.big_scene = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' })
    ])
  }
}
// 过渡章节
icons.transition_chapter = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4' })
    ])
  }
}
// 悬念结尾
icons.suspense_ending = {
  render() {
    return h('svg', { fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '2', d: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' })
    ])
  }
}

const {
  intentTemplates,
  selectedIntents,
  canSelectMore,
  toggleIntent
} = useIntentDrivenConfig()

function getIntentIcon(intentId: string) {
  return icons[intentId] || icons.advance_mainline
}
</script>

<style scoped>
.intent-selector {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* 标题区 */
.selector-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.selector-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary, #0f172a);
  letter-spacing: -0.01em;
  margin: 0;
}

.required-badge {
  font-size: 0.75rem;
  font-weight: 500;
  color: #6366f1;
  background: rgba(99, 102, 241, 0.1);
  padding: 0.25rem 0.625rem;
  border-radius: 9999px;
  border: 1px solid rgba(99, 102, 241, 0.2);
}

/* 网格布局 */
.intent-grid {
  display: grid;
  grid-template-columns: repeat(1, 1fr);
  gap: 0.875rem;
}

@media (min-width: 640px) {
  .intent-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 卡片样式：无边框微发光风格 */
.intent-card-wrapper {
  position: relative;
}

.intent-card {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 1rem;
  cursor: pointer;
  text-align: left;
  transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.02);
}

.intent-card:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(165, 180, 252, 0.6);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.08), 0 2px 8px rgba(99, 102, 241, 0.04);
  transform: translateY(-2px);
}

.intent-card.selected {
  background: rgba(99, 102, 241, 0.04);
  border-color: #6366f1;
  box-shadow: 0 0 0 1px #6366f1, 0 8px 24px rgba(99, 102, 241, 0.12);
}

.intent-card.disabled {
  opacity: 0.4;
  cursor: not-allowed;
  filter: grayscale(0.8);
}

/* 图标区 */
.intent-icon-box {
  width: 2.5rem;
  height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.625rem;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  color: #64748b;
  flex-shrink: 0;
  transition: all 0.3s ease;
  box-shadow: inset 0 1px 2px rgba(255, 255, 255, 0.5), 0 2px 4px rgba(15, 23, 42, 0.04);
}

.intent-card:hover:not(:disabled) .intent-icon-box {
  color: #6366f1;
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  box-shadow: inset 0 1px 2px rgba(255, 255, 255, 0.8), 0 4px 8px rgba(99, 102, 241, 0.15);
}

.intent-card.selected .intent-icon-box {
  color: #ffffff;
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  box-shadow: inset 0 1px 2px rgba(255, 255, 255, 0.2), 0 4px 12px rgba(99, 102, 241, 0.3);
}

/* 内容区 */
.intent-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.intent-name {
  font-size: 0.9375rem;
  font-weight: 600;
  color: #1e293b;
  transition: color 0.2s ease;
}

.intent-card.selected .intent-name {
  color: #4338ca;
}

.intent-desc {
  font-size: 0.75rem;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 勾选圈 */
.intent-check-ring {
  width: 1.25rem;
  height: 1.25rem;
  border-radius: 50%;
  border: 1.5px solid #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  background: transparent;
}

.check-icon {
  color: white;
  opacity: 0;
  transform: scale(0.5);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.intent-card.selected .intent-check-ring {
  border-color: #6366f1;
  background: #6366f1;
}

.intent-card.selected .check-icon {
  opacity: 1;
  transform: scale(1);
}

/* 组合提示 */
.combo-alert {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.875rem 1.25rem;
  background: rgba(99, 102, 241, 0.05);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 0.75rem;
  color: #4f46e5;
  font-size: 0.8125rem;
  font-weight: 500;
}

.combo-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  background: white;
  border-radius: 0.375rem;
  box-shadow: 0 2px 4px rgba(99, 102, 241, 0.1);
}

/* Tooltip - 优雅气泡 */
.intent-tooltip {
  position: fixed;
  z-index: 9999;
  width: 320px;
  padding: 1.25rem;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.4);
  border-radius: 1.25rem;
  box-shadow: 0 20px 40px -8px rgba(15, 23, 42, 0.15), 0 0 0 1px rgba(15, 23, 42, 0.05);
  pointer-events: none;
  transform: translateX(-50%);
}

.intent-tooltip::after {
  content: '';
  position: absolute;
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%) rotate(45deg);
  width: 12px;
  height: 12px;
  background: rgba(255, 255, 255, 0.95);
  border-right: 1px solid rgba(15, 23, 42, 0.05);
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
}

.intent-tooltip.is-bottom::after {
  top: -6px;
  bottom: auto;
  border-right: none;
  border-bottom: none;
  border-left: 1px solid rgba(15, 23, 42, 0.05);
  border-top: 1px solid rgba(15, 23, 42, 0.05);
}

.tooltip-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.tooltip-title {
  font-size: 1rem;
  font-weight: 600;
  color: #0f172a;
}

.tooltip-desc {
  font-size: 0.8125rem;
  color: #475569;
  line-height: 1.5;
}

.tooltip-section {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(226, 232, 240, 0.8);
}

.tooltip-section-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #6366f1;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.5rem;
}

.tooltip-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.tooltip-list li {
  position: relative;
  padding-left: 1rem;
  font-size: 0.8125rem;
  color: #475569;
}

.tooltip-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.4rem;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #818cf8;
}

.tooltip-style {
  font-size: 0.8125rem;
  color: #475569;
  font-style: italic;
  background: #f8fafc;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  margin-top: 0.5rem;
}

/* 动画 */
.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px) scale(0.95);
}

.fade-up-enter-active,
.fade-up-leave-active {
  transition: all 0.3s ease;
}

.fade-up-enter-from,
.fade-up-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* 深色模式适配 */
@media (prefers-color-scheme: dark) {
  .selector-title {
    color: #f1f5f9;
  }
  .required-badge {
    background: rgba(99, 102, 241, 0.2);
    border-color: rgba(99, 102, 241, 0.3);
    color: #a5b4fc;
  }
  .intent-card {
    background: rgba(30, 41, 59, 0.6);
    border-color: rgba(51, 65, 85, 0.8);
  }
  .intent-card:hover:not(:disabled) {
    background: rgba(30, 41, 59, 0.9);
    border-color: rgba(99, 102, 241, 0.5);
  }
  .intent-card.selected {
    background: rgba(99, 102, 241, 0.15);
    border-color: #6366f1;
    box-shadow: 0 0 0 1px #6366f1, 0 8px 24px rgba(0, 0, 0, 0.2);
  }
  .intent-icon-box {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    color: #94a3b8;
    box-shadow: inset 0 1px 2px rgba(255, 255, 255, 0.1);
  }
  .intent-card:hover:not(:disabled) .intent-icon-box {
    background: linear-gradient(135deg, #312e81 0%, #1e1b4b 100%);
    color: #a5b4fc;
  }
  .intent-card.selected .intent-icon-box {
    background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
    color: #ffffff;
  }
  .intent-name {
    color: #f1f5f9;
  }
  .intent-card.selected .intent-name {
    color: #c7d2fe;
  }
  .intent-desc {
    color: #94a3b8;
  }
  .intent-check-ring {
    border-color: #475569;
  }
  .combo-alert {
    background: rgba(99, 102, 241, 0.15);
    border-color: rgba(99, 102, 241, 0.3);
    color: #a5b4fc;
  }
  .combo-icon {
    background: #1e293b;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }
  .intent-tooltip {
    background: rgba(30, 41, 59, 0.95);
    border-color: rgba(255, 255, 255, 0.1);
    box-shadow: 0 20px 40px -8px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05);
  }
  .intent-tooltip::after {
    background: rgba(30, 41, 59, 0.95);
    border-color: rgba(255, 255, 255, 0.1);
  }
  .tooltip-title {
    color: #f1f5f9;
  }
  .tooltip-desc {
    color: #cbd5e1;
  }
  .tooltip-section {
    border-color: rgba(71, 85, 105, 0.8);
  }
  .tooltip-section-title {
    color: #818cf8;
  }
  .tooltip-list li {
    color: #cbd5e1;
  }
  .tooltip-style {
    background: #0f172a;
    color: #cbd5e1;
  }
}
</style>
