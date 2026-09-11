<script setup lang="ts">
/**
 * 幽灵洗层条（三平面分权·呈现平面 P1，2026-08-29，docs/style-paradigm.md）。
 *
 * 洗层命中时在感知带停靠区出一行薄荷条「已规避 N 处你的禁忌词」——洗是
 * 「已处理」语义（区别疑点条的琥珀「请过目」），配色与幽灵草稿同系。
 * 展开：替换明细（原词 → 替代词）；有原稿快照时提供「用原稿」——作者明示
 * 保留被洗的词（可逆学习：该禁忌此后降为提醒，一次肯定胜过三次否定）。
 *
 * 分层纪律：presentation 纯 props/emits——wash 由容器注入，用原稿动作由
 * 容器接线（重灌幽灵 + wash-prefer-original 降级端点）。
 */
import { ref } from 'vue'
import type { GhostWashPayload } from '../composables/useGhostDraft'

const props = defineProps<{
  wash: GhostWashPayload
}>()

const emit = defineEmits<{
  /** 作者明示保留原词：容器负责重灌原稿 + 对每个已替换命中调降级端点 */
  'use-original': []
}>()

const expanded = ref(false)

const replacedCount = () => props.wash.hits.filter((h) => h.replaced).length
</script>

<template>
  <div v-if="wash.hits.length" class="ghost-wash">
    <button
      class="ghost-wash__head"
      title="AI 写的时候避开了你的禁忌词（只改 AI 的稿子，Enter 采纳才进正文）"
      @click="expanded = !expanded"
    >
      <span class="ghost-wash__icon">✓</span>
      <span class="ghost-wash__count">已换掉 {{ wash.hits.length }} 处禁忌词</span>
      <span class="ghost-wash__sub">（替换 {{ replacedCount() }}）</span>
      <span class="ghost-wash__toggle">{{ expanded ? '收起' : '明细' }}</span>
    </button>
    <div v-if="expanded" class="ghost-wash__list">
      <div v-for="(h, i) in wash.hits" :key="i" class="ghost-wash__item">
        <span class="ghost-wash__tag" :class="h.replaced ? 'is-fixed' : 'is-kept'">
          {{ h.replaced ? '已替换' : '已标记' }}
        </span>
        <span class="ghost-wash__span">「{{ h.span }}」</span>
        <span v-if="h.replaced && h.alternative" class="ghost-wash__alt">→ {{ h.alternative }}</span>
        <span v-else-if="!h.replaced" class="ghost-wash__alt">（没有合适的替代词，只标出来）</span>
      </div>
      <div v-if="wash.original_text" class="ghost-wash__actions">
        <button class="ghost-wash__btn" title="恢复 AI 原来的稿子，这些词以后只提醒不替换" @click="emit('use-original')">
          用原稿（保留这些词）
        </button>
      </div>
      <div class="ghost-wash__foot">只改 AI 的稿子，不碰你的正文 · Enter 采纳 / Esc 蒸发照常</div>
    </div>
  </div>
</template>

<style scoped>
/* 薄荷系：洗是「已处理」，与幽灵草稿同语义色（区别疑点条琥珀） */
.ghost-wash {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #6ee7b7;
  border-radius: 8px;
  background: #ecfdf5;
  padding: 5px 8px;
  margin-bottom: 8px;
}
:root.dark .ghost-wash {
  background: rgba(16, 46, 38, 0.5);
  border-color: rgba(110, 231, 183, 0.35);
}

.ghost-wash__head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 2px 0;
  border: none;
  background: none;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  color: #065f46;
}
:root.dark .ghost-wash__head {
  color: #6ee7b7;
}

.ghost-wash__icon { font-size: 12px; line-height: 1; }
.ghost-wash__count { font-size: 12px; font-weight: 600; white-space: nowrap; }
.ghost-wash__sub { flex: 1; min-width: 0; font-size: 11px; opacity: 0.8; }

.ghost-wash__toggle {
  flex-shrink: 0;
  font-size: 10px;
  color: #047857;
  border: 1px solid #6ee7b7;
  border-radius: 6px;
  padding: 0 6px;
  line-height: 1.5;
}
:root.dark .ghost-wash__toggle {
  color: #6ee7b7;
  border-color: rgba(110, 231, 183, 0.4);
}

.ghost-wash__list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 5px;
  margin-top: 4px;
  border-top: 1px dashed rgba(4, 120, 87, 0.3);
}

.ghost-wash__item {
  display: flex;
  align-items: baseline;
  gap: 5px;
  font-size: 11px;
  line-height: 1.5;
  color: #57534e;
  flex-wrap: wrap;
}
:root.dark .ghost-wash__item { color: #d6d3d1; }

.ghost-wash__tag {
  flex-shrink: 0;
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 9999px;
  white-space: nowrap;
}
.ghost-wash__tag.is-fixed { background: #d1fae5; color: #047857; }
.ghost-wash__tag.is-kept { background: #f3f4f6; color: #6b7280; }

.ghost-wash__span { font-weight: 600; color: #065f46; word-break: break-all; }
:root.dark .ghost-wash__span { color: #6ee7b7; }
.ghost-wash__alt { color: #78716c; }
:root.dark .ghost-wash__alt { color: #a8a29e; }

.ghost-wash__actions { margin-top: 2px; }
.ghost-wash__btn {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 6px;
  border: 1px solid #6ee7b7;
  background: transparent;
  color: #047857;
  cursor: pointer;
}
.ghost-wash__btn:hover { background: rgba(110, 231, 183, 0.15); }
:root.dark .ghost-wash__btn { color: #6ee7b7; }

.ghost-wash__foot { font-size: 10px; color: #a8a29e; }
</style>
