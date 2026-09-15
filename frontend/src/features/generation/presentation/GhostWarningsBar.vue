<script setup lang="ts">
/**
 * 幽灵草稿疑点条（P5 C1 上屏前快检的两档展示——停靠区形态）。
 *
 * 幽灵在屏且快检有命中时，在感知带停靠区出一行「N 处疑点」；点击展开
 * 明细（span_text 触发词 + message 人话说明 + kind 标签）。疑点数据来自
 * GHOST_DONE 帧的 warnings（后端 ghost_guard 纯算法产，只提示不拦截——
 * 采纳永远可用，本组件也不提供任何拦截动作）。
 *
 * 分层纪律：presentation 纯 props——warnings 由容器（WorkspaceView）从
 * useGhostDraft 单例注入；展开/收起是纯 UI 内部状态。
 */
import { ref, computed } from 'vue'
import type { GhostWarning } from '../../../services/api/domain/adaptive.api'

const props = defineProps<{
  warnings: GhostWarning[]
}>()

const expanded = ref(false)

/** kind → 短标签 + 色档（琥珀系：疑点是「请过目」不是「报错」） */
const KIND_META: Record<GhostWarning['kind'], { label: string; cls: string }> = {
  dead_speak: { label: '死者开口', cls: 'is-dead' },
  canon_leak: { label: '秘密穿帮', cls: 'is-canon' },
  secret_leak: { label: '秘密外泄', cls: 'is-secret' },
  // 二期扩（约束治理 2026-09-02）：禁忌面/不在场/地点跳变/熔断降级
  cliche_hit: { label: '禁忌词', cls: 'is-cliche' },
  out_of_scene: { label: '人物不在场', cls: 'is-oos' },
  location_jump: { label: '地点跳变', cls: 'is-loc' },
  quality_breaker: { label: '自动修正暂停', cls: 'is-breaker' },
  // 抢拍闸（2026-09-03 live）：拒稿逃生舱/熔断降级路径会随帧到前端
  beat_rush: { label: '抢拍', cls: 'is-rush' },
}

function meta(kind: GhostWarning['kind']) {
  return KIND_META[kind] || { label: kind, cls: '' }
}

const kindSummary = computed(() => {
  const counts = new Map<string, number>()
  for (const w of props.warnings) {
    const label = meta(w.kind).label
    counts.set(label, (counts.get(label) || 0) + 1)
  }
  return [...counts.entries()].map(([l, n]) => (n > 1 ? `${l}×${n}` : l)).join('、')
})
</script>

<template>
  <div v-if="warnings.length" class="ghost-warn">
    <button class="ghost-warn__head" title="自动检查发现的疑点（只提醒，Enter 照常采纳）" @click="expanded = !expanded">
      <span class="ghost-warn__icon">⚠</span>
      <span class="ghost-warn__count">{{ warnings.length }} 处疑点</span>
      <span class="ghost-warn__kinds">{{ kindSummary }}</span>
      <span class="ghost-warn__toggle">{{ expanded ? '收起' : '明细' }}</span>
    </button>
    <div v-if="expanded" class="ghost-warn__list">
      <div
        v-for="(w, i) in warnings"
        :key="i"
        class="ghost-warn__item"
        :class="meta(w.kind).cls"
      >
        <span class="ghost-warn__tag">{{ meta(w.kind).label }}</span>
        <span class="ghost-warn__span" :title="w.span_text">「{{ w.span_text }}」</span>
        <span class="ghost-warn__msg">{{ w.message }}</span>
      </div>
      <div class="ghost-warn__foot">Enter 采纳 · Esc 蒸发——疑点只是提醒，不拦你</div>
    </div>
  </div>
</template>

<style scoped>
/* 琥珀系：「请过目」警示语义 → --warn 族 token（暗档由 token 自带） */
.ghost-warn {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--warn) 8%, var(--bg-canvas));
  padding: 5px 8px;
  margin-bottom: 8px;
}

.ghost-warn__head {
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
  color: var(--warn);
}

.ghost-warn__icon {
  font-size: var(--text-xs);
  line-height: 1;
}

.ghost-warn__count {
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

.ghost-warn__kinds {
  flex: 1;
  min-width: 0;
  font-size: var(--text-xs);
  opacity: 0.85;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ghost-warn__toggle {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--warn);
  border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent);
  border-radius: var(--radius-sm);
  padding: 0 6px;
  line-height: 1.5;
}

.ghost-warn__list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 5px;
  margin-top: 4px;
  border-top: 1px dashed color-mix(in srgb, var(--warn) 30%, transparent);
}

.ghost-warn__item {
  display: flex;
  align-items: baseline;
  gap: 5px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-secondary);
  flex-wrap: wrap;
}

.ghost-warn__tag {
  flex-shrink: 0;
  font-size: var(--text-xs);
  padding: 1px 5px;
  border-radius: 9999px;
  background: var(--warn-bg);
  color: var(--warn);
  white-space: nowrap;
}
.ghost-warn__item.is-dead .ghost-warn__tag {
  background: var(--info-bg);
  color: var(--info);
}
.ghost-warn__item.is-canon .ghost-warn__tag {
  background: var(--danger-bg);
  color: var(--danger);
}
.ghost-warn__item.is-secret .ghost-warn__tag {
  background: color-mix(in srgb, var(--foreshadow) 14%, var(--bg-canvas));
  color: var(--foreshadow);
}

.ghost-warn__span {
  font-weight: 600;
  color: var(--warn);
  word-break: break-all;
}

.ghost-warn__msg {
  flex: 1;
  min-width: 100%;
  color: var(--text-muted);
}

.ghost-warn__foot {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
</style>
