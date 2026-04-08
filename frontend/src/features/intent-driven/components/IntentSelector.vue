<template>
  <div class="intent-selector">
    <div class="selector-header">
      <h3 class="selector-title">这一章要什么效果？</h3>
      <p class="selector-subtitle">选择 1-2 个创作意图，系统将智能匹配最佳生成策略</p>
    </div>
    
    <div class="intent-grid">
      <button
        v-for="intent in intentTemplates"
        :key="intent.id"
        type="button"
        class="intent-card"
        :class="{
          'selected': selectedIntents.includes(intent.id),
          'disabled': !canSelectMore && !selectedIntents.includes(intent.id)
        }"
        :disabled="!canSelectMore && !selectedIntents.includes(intent.id)"
        @click="toggleIntent(intent.id)"
        :title="intent.detailed_desc"
      >
        <!-- 选中指示器 -->
        <div class="selection-indicator">
          <svg v-if="selectedIntents.includes(intent.id)" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        
        <!-- SVG 图标 -->
        <div class="intent-icon">
          <Component :is="getIntentIcon(intent.id)" class="w-6 h-6" />
        </div>
        
        <!-- 文字内容 -->
        <div class="intent-content">
          <div class="intent-name">{{ intent.display_name }}</div>
          <div class="intent-desc">{{ intent.short_desc }}</div>
        </div>
      </button>
    </div>
    
    <!-- 已选意图展示 -->
    <Transition name="slide-down">
      <div v-if="selectedIntents.length > 0" class="selection-bar">
        <div class="bar-content">
          <span class="bar-label">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            已选择 {{ selectedIntents.length }}/2
          </span>
          <div class="selected-chips">
            <span 
              v-for="intent in selectedIntentTemplates" 
              :key="intent.id"
              class="intent-chip"
            >
              <Component :is="getIntentIcon(intent.id)" class="w-3.5 h-3.5" />
              <span class="chip-name">{{ intent.display_name }}</span>
              <button 
                type="button"
                class="chip-remove"
                @click.stop="toggleIntent(intent.id)"
                title="移除"
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          </div>
          <button 
            v-if="selectedIntents.length > 0"
            type="button"
            class="clear-btn"
            @click="clearAll"
          >
            清空
          </button>
        </div>
        <div v-if="selectedIntents.length === 2" class="combo-hint">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          组合意图：系统将智能融合两个意图的生成策略
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { h } from 'vue'
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'

// 引入 SVG 图标组件
const icons: Record<string, any> = {}

// 推进主线 - 向上火箭/箭头
icons.advance_mainline = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M13 10V3L4 14h7v7l9-11h-7z' })
    ])
  }
}

// 塑造人物 - 用户轮廓
icons.character_development = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' })
    ])
  }
}

// 营造氛围 - 云雾
icons.atmosphere_building = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z' })
    ])
  }
}

// 制造冲突 - 闪电/交锋
icons.build_conflict = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M13 10V3L4 14h7v7l9-11h-7z' })
    ])
  }
}

// 回收伏笔 - 链接/链条
icons.close_hooks = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' })
    ])
  }
}

// 展开世界观 - 地球/网格
icons.worldbuilding = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9' })
    ])
  }
}

// 情感升温 - 心形
icons.emotional_warming = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z' })
    ])
  }
}

// 对话戏 - 对话框
icons.dialogue_scene = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' })
    ])
  }
}

// 大场面 - 聚光灯/舞台
icons.big_scene = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' })
    ])
  }
}

// 过渡章节 - 桥梁/连接
icons.transition_chapter = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4' })
    ])
  }
}

// 悬念结尾 - 问号/悬念
icons.suspense_ending = {
  render() {
    return h('svg', { class: 'w-6 h-6', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '1.5', d: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' })
    ])
  }
}

const {
  intentTemplates,
  selectedIntents,
  selectedIntentTemplates,
  canSelectMore,
  toggleIntent
} = useIntentDrivenConfig()

function getIntentIcon(intentId: string) {
  return icons[intentId] || icons.advance_mainline
}

function clearAll() {
  selectedIntents.value.forEach(id => toggleIntent(id))
}
</script>

<style scoped>
.intent-selector {
  padding: 1.25rem;
  padding-bottom: 2rem; /* 给底部栏留出足够空间 */
}

.selector-header {
  text-align: center;
  margin-bottom: 1.5rem;
}

.selector-title {
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--text-primary, #1e293b);
  margin-bottom: 0.375rem;
}

.selector-subtitle {
  font-size: 0.8125rem;
  color: var(--text-secondary, #64748b);
}

/* 意图网格 */
.intent-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

@media (min-width: 640px) {
  .intent-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (min-width: 1024px) {
  .intent-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

/* 意图卡片 */
.intent-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1rem 0.75rem;
  background: var(--bg-canvas, #f8fafc);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.875rem;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  text-align: center;
}

.intent-card:hover:not(:disabled) {
  background: var(--bg-primary, white);
  border-color: var(--accent-300, #a5b4fc);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.12);
}

.intent-card.selected {
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border-color: var(--accent-500, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2), 0 8px 20px rgba(99, 102, 241, 0.15);
}

.intent-card.disabled {
  opacity: 0.45;
  cursor: not-allowed;
  filter: grayscale(0.5);
}

/* 选中指示器 */
.selection-indicator {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  width: 1.25rem;
  height: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-500, #6366f1);
  color: white;
  border-radius: 50%;
  opacity: 0;
  transform: scale(0.5);
  transition: all 0.2s ease;
}

.intent-card.selected .selection-indicator {
  opacity: 1;
  transform: scale(1);
}

/* SVG 图标 */
.intent-icon {
  width: 3rem;
  height: 3rem;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent-500, #6366f1);
  background: var(--bg-primary, white);
  border-radius: 0.75rem;
  border: 1px solid var(--border-color, #e2e8f0);
  transition: all 0.2s ease;
  margin-bottom: 0.625rem;
}

.intent-card:hover:not(:disabled) .intent-icon {
  background: var(--accent-50, #eef2ff);
  border-color: var(--accent-200, #c7d2fe);
  transform: scale(1.05);
}

.intent-card.selected .intent-icon {
  background: white;
  border-color: var(--accent-400, #818cf8);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
}

/* 文字内容 */
.intent-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
}

.intent-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  transition: color 0.2s ease;
}

.intent-card.selected .intent-name {
  color: var(--accent-700, #4338ca);
}

.intent-desc {
  font-size: 0.6875rem;
  color: var(--text-muted, #94a3b8);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  max-width: 100%;
}

/* 选中栏 - 修复边界问题 */
.selection-bar {
  margin-top: 1.5rem;
  margin-bottom: 1rem;
  padding: 1rem;
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border: 1px solid var(--accent-200, #c7d2fe);
  border-radius: 0.75rem;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.1);
}

.bar-content {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.bar-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--accent-700, #4338ca);
  flex-shrink: 0;
}

.selected-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex: 1;
}

.intent-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  background: white;
  border: 1px solid var(--accent-300, #a5b4fc);
  border-radius: 9999px;
  font-size: 0.8125rem;
  color: var(--accent-700, #4338ca);
  box-shadow: 0 2px 4px rgba(99, 102, 241, 0.1);
  animation: chip-in 0.3s ease;
}

@keyframes chip-in {
  from {
    opacity: 0;
    transform: scale(0.9) translateY(-4px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.chip-icon {
  color: var(--accent-500, #6366f1);
}

.chip-name {
  font-weight: 500;
}

.chip-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  margin-left: 0.125rem;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 50%;
  color: var(--accent-400, #818cf8);
  cursor: pointer;
  transition: all 0.15s ease;
}

.chip-remove:hover {
  background: var(--accent-100, #e0e7ff);
  color: var(--accent-600, #4f46e5);
}

.clear-btn {
  margin-left: auto;
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  color: var(--accent-600, #4f46e5);
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.clear-btn:hover {
  background: rgba(99, 102, 241, 0.1);
}

.combo-hint {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px dashed var(--accent-300, #a5b4fc);
  font-size: 0.75rem;
  color: var(--accent-600, #4f46e5);
}

.combo-hint svg {
  flex-shrink: 0;
}

/* 动画 */
.slide-down-enter-active {
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

.slide-down-enter-from {
  opacity: 0;
  transform: translateY(-12px);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .intent-card {
    background: #0f172a;
    border-color: #334155;
  }
  
  .intent-card:hover:not(:disabled) {
    background: #1e293b;
    border-color: #4f46e5;
  }
  
  .intent-card.selected {
    background: linear-gradient(135deg, #312e81 0%, #1e1b4b 100%);
    border-color: #6366f1;
  }
  
  .intent-icon {
    background: #1e293b;
    border-color: #334155;
    color: #818cf8;
  }
  
  .intent-card.selected .intent-icon {
    background: #0f172a;
    border-color: #4f46e5;
    color: #a5b4fc;
  }
  
  .intent-name {
    color: #f1f5f9;
  }
  
  .intent-card.selected .intent-name {
    color: #a5b4fc;
  }
  
  .selection-bar {
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
    border-color: #4f46e5;
  }
  
  .bar-label {
    color: #a5b4fc;
  }
  
  .intent-chip {
    background: #0f172a;
    border-color: #4f46e5;
    color: #a5b4fc;
  }
  
  .combo-hint {
    border-color: #4f46e5;
    color: #818cf8;
  }
}
</style>
