<script setup lang="ts">
/**
 * 图标栏抽屉的统一外壳骨架（2026-09 外壳重构）。
 *
 * 形态与四个内部详情抽屉对齐（全高 340px 贴边浮层——定位 CSS 在 WorldView 的
 * .atlas-drawer 上，本组件只负责内部分区）：头部（图标/标题/计数/主操作/收起）
 * + 可选搜索栏 + 滚动内容区 + 可选底部条。
 *
 * 纯展示骨架：不持业务状态，卡片交互（选中等）仍由插槽内容向 WorldView 抛事件——
 * 外壳替换不触碰详情抽屉的 selected*Id 契约。
 */
import Icon from '../../../components/Icon.vue'

defineProps<{
  icon: string
  title: string
  /** 徽标数字；null/undefined 不渲染（exp 摘要等无计数场景） */
  count?: number | null
}>()

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div class="ds">
    <div class="ds-head">
      <Icon :name="icon" :size="14" />
      <span class="ds-title">{{ title }}</span>
      <span v-if="count != null" class="ds-count">{{ count }}</span>
      <div class="ds-actions"><slot name="actions" /></div>
      <button class="ds-close" title="收起（再点右缘图标可重开）" aria-label="收起面板" @click="emit('close')">
        <Icon name="x-mark" :size="13" />
      </button>
    </div>
    <div v-if="$slots.search" class="ds-search">
      <slot name="search" />
    </div>
    <div class="ds-body">
      <slot />
    </div>
    <div v-if="$slots.footer" class="ds-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
.ds {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.ds-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px 8px;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.ds-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
}
.ds-count {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border-radius: 9999px;
  padding: 1px 8px;
}
/* 主操作按钮区（＋ 新建 / 通读本书等——沿用调用方 .side-batch-btn 样式） */
.ds-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}
.ds-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s ease;
}
.ds-close:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.ds-search {
  flex-shrink: 0;
  padding: 0 12px 8px;
}
/* 滚动内容区：外壳唯一滚动容器（sticky 年份头在此锚定） */
.ds-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 12px 12px;
}
.ds-footer {
  flex-shrink: 0;
  padding: 8px 12px;
  border-top: 1px solid var(--border-color);
}
/* 世界页滚动区统一：暖色细条（Chromium/WebKit） */
.ds-body::-webkit-scrollbar {
  width: 8px;
}
.ds-body::-webkit-scrollbar-thumb {
  background: rgba(120, 95, 50, 0.22);
  border-radius: 4px;
}
.ds-body::-webkit-scrollbar-thumb:hover {
  background: rgba(120, 95, 50, 0.38);
}
.ds-body::-webkit-scrollbar-track {
  background: transparent;
}
</style>
