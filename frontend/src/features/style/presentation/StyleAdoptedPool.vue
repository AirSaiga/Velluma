<script setup lang="ts">
/**
 * 「AI 采纳收样本」池（三平面分权·选择平面 P5，2026-08-29）。
 *
 * 作者采纳过的幽灵草稿列在这里——「这段 AI 写的你觉得像你，收为样本？」
 * 红线：候选不直接生效，作者点「收为样本」才入库（source=adopted_ghost，
 * few-shot 装配时 AI 来源样本每批 ≤1，防采纳幽灵自蒸馏把文风拉向 AI 味）。
 *
 * 分层纪律：presentation 纯 props/emits——池数据与收编动作由容器接线。
 */
import { ref } from 'vue'
import Icon from '../../../components/Icon.vue'

export interface AdoptedGhostItem {
  ts: string
  source: string
  wash_hits: number
  text: string
}

const props = defineProps<{
  items: AdoptedGhostItem[]
  busyId: string | null
}>()

const emit = defineEmits<{
  collect: [item: AdoptedGhostItem]
}>()

const expanded = ref(false)
</script>

<template>
  <div v-if="items.length" class="adopted-pool">
    <button class="adopted-pool__head" @click="expanded = !expanded">
      <Icon class="adopted-pool__icon" name="sparkles" :size="14" />
      <span class="adopted-pool__title">AI 写的、你留下的</span>
      <span class="adopted-pool__toggle">{{ expanded ? '收起' : '展开' }}</span>
    </button>
    <div v-if="expanded" class="adopted-pool__list">
      <p class="adopted-pool__note">
        这些都是 AI 写、你留下过的段落。觉得像你的字就收进字帖——不过 AI 写的内容每次续写至多当一小段范例用，防止文风被它带偏。
      </p>
      <div v-for="(g, i) in items" :key="g.ts + i" class="adopted-pool__item">
        <div class="adopted-pool__text" :title="g.text">{{ g.text }}</div>
        <div class="adopted-pool__meta">
          <button
            class="adopted-pool__btn"
            :disabled="busyId === g.ts"
            @click="emit('collect', g)"
          >{{ busyId === g.ts ? '收编中…' : '收进字帖' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.adopted-pool {
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
  padding: 6px 10px;
}
.adopted-pool__head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  border: none;
  background: none;
  cursor: pointer;
  font-family: inherit;
  color: var(--text-secondary);
  padding: 2px 0;
}
.adopted-pool__title { font-size: var(--text-xs); font-weight: 600; }
.adopted-pool__icon { color: var(--text-muted); flex-shrink: 0; }
.adopted-pool__count { flex: 1; text-align: left; font-size: var(--text-sm); color: var(--text-secondary); }
.adopted-pool__toggle { min-height: 24px; padding: 0.125rem 0.5rem; font-size: var(--text-xs); color: var(--text-secondary); background: transparent; border: 1px solid var(--line-faint); border-radius: var(--radius-sm); cursor: pointer; }
.adopted-pool__note { font-size: var(--text-sm); color: var(--text-secondary); margin: 4px 0 8px; line-height: var(--lh-normal); }
.adopted-pool__list { display: flex; flex-direction: column; gap: 8px; }
.adopted-pool__item { border: 1px solid var(--line-faint); border-radius: var(--radius-md); padding: 6px 8px; }
.adopted-pool__text {
  font-family: var(--editor-font-family);  /* 身份层①：摘录衬线化（字帖墨迹感） */
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.adopted-pool__meta { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.adopted-pool__time { font-size: var(--text-xs); color: var(--text-muted); }
.adopted-pool__wash { font-size: var(--text-xs); color: var(--ok); }
.adopted-pool__btn {
  margin-left: auto;
  min-height: 28px;
  font-size: var(--text-xs);
  padding: 2px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-400);
  background: transparent;
  color: var(--accent-500);
  cursor: pointer;
}
.adopted-pool__btn:disabled { opacity: 0.5; cursor: default; }
.adopted-pool__btn:hover:not(:disabled) { background: color-mix(in srgb, var(--accent-500) 8%, transparent); }
</style>
