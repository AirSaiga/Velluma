<script setup lang="ts">
/**
 * 右缘助手栏（08 期 §4.5，AI 辅助的唯一的家）——逐像素同构世界页图标栏
 * 心智：图标栏常驻右缘、点击开、一次一格、Esc/外点收。hover 瞥看已退役（拍板 P-2）。
 *
 * 栏位序（自上而下固定）：✨ AI 辅助总开关（带状态点）→ 分隔线 →
 * 打算/此刻/本章/检查（Ctrl+1~4）→ 分隔线 → AI 视角（Ctrl+5）→ ？快捷键一览。
 * 检查图标带 6px 朱点 = 完稿报告到达且尚未看过。纯受控件，状态全在容器。
 */
import Icon from '../../../components/Icon.vue'

defineProps<{
  assistEnabled: boolean
  /** 当前打开的面板分区（面板关闭时容器传 null，栏无高亮） */
  activeTab: string | null
  /** 完稿报告到达且尚未看过 → 检查图标朱点 */
  reportUnread: boolean
}>()

const emit = defineEmits<{
  (e: 'toggleAssist'): void
  (e: 'selectTab', key: string): void
  (e: 'openCheatsheet'): void
}>()

// 图标沿用 InspectorPanel 既有 tab 图标名，零图标映射变化
const SECTION_TABS = [
  { key: 'planning', label: '打算', icon: 'light-bulb' },
  { key: 'now', label: '此刻', icon: 'map' },
  { key: 'chapter', label: '本章', icon: 'document' },
  { key: 'review', label: '检查', icon: 'check-circle' },
] as const
</script>

<template>
  <nav class="assist-rail" aria-label="写作助手">
    <!-- AI 辅助总开关（title 继承 07 表 A3/A4 原文） -->
    <button
      class="assist-rail__btn"
      :class="{ 'assist-rail__btn--active': assistEnabled }"
      :title="assistEnabled ? 'AI 辅助开着——Space 会叫 AI 接着写，停顿会浮出卡舱；点击关闭' : 'AI 辅助已关——Space 是普通空格；点击开启'"
      @click="emit('toggleAssist')"
    >
      <Icon name="sparkles" :size="15" />
      <span class="assist-rail__dot" :class="{ 'assist-rail__dot--on': assistEnabled }"></span>
    </button>

    <div class="assist-rail__divider"></div>

    <button
      v-for="(t, i) in SECTION_TABS"
      :key="t.key"
      class="assist-rail__btn"
      :class="{ 'assist-rail__btn--active': activeTab === t.key }"
      :title="`${t.label}（Ctrl+${i + 1}）`"
      @click="emit('selectTab', t.key)"
    >
      <Icon :name="t.icon" :size="15" />
      <span v-if="t.key === 'review' && reportUnread" class="assist-rail__badge"></span>
    </button>

    <div class="assist-rail__divider"></div>

    <button
      class="assist-rail__btn"
      :class="{ 'assist-rail__btn--active': activeTab === 'debug' }"
      title="AI 视角（Ctrl+5）"
      @click="emit('selectTab', 'debug')"
    >
      <Icon name="magnifying-glass" :size="15" />
    </button>

    <button
      class="assist-rail__btn"
      title="快捷键一览"
      @click="emit('openCheatsheet')"
    >
      <Icon name="question-mark-circle" :size="15" />
    </button>
  </nav>
</template>
