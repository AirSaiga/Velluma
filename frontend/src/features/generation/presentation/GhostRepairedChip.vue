<script setup lang="ts">
/**
 * 幽灵返修条（约束治理二期，2026-09-02，docs/constraint-governance.md）。
 *
 * 返修环检出设定硬伤并自动修正成功时，在感知带停靠区出一行薄荷条
 * 「已自动修正 N 处穿帮」——与洗层条同系（「已处理」语义，区别疑点条的
 * 琥珀「请过目」）。只展示计数与类目（人话标签），不暴露被拒原稿
 * （防回退污染纪律：违规原稿不进任何可回退/可展示通道）。
 *
 * 分层纪律：presentation 纯 props——repaired 由容器从 useGhostDraft 单例注入。
 */
import { computed } from 'vue'
import { warningKindLabel } from '../composables/useGhostDraft'

const props = defineProps<{
  repaired: { count: number; kinds: string[]; action: string }
}>()

const kindsSummary = computed(() =>
  (props.repaired.kinds || []).map((k) => warningKindLabel(k)).join('、'),
)
const actionLabel = computed(() =>
  props.repaired.action === 'excised' ? '删去违规句' : '改写修复',
)
</script>

<template>
  <div class="ghost-repaired" :title="`检出的设定硬伤已自动修正（${actionLabel}）：${kindsSummary}`">
    <span class="ghost-repaired__icon">🩹</span>
    <span class="ghost-repaired__count">已自动修正 {{ repaired.count }} 处穿帮</span>
    <span class="ghost-repaired__kinds">{{ kindsSummary }}</span>
  </div>
</template>

<style scoped>
/* 薄荷系：与洗层条同语义色（「已处理」，区别疑点条琥珀） */
.ghost-repaired {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #6ee7b7;
  border-radius: 8px;
  background: #ecfdf5;
  padding: 5px 8px;
  margin-bottom: 8px;
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
  color: #047857;
}
:root.dark .ghost-repaired {
  background: rgba(20, 46, 38, 0.55);
  border-color: rgba(110, 231, 183, 0.35);
  color: #6ee7b7;
}
.ghost-repaired__kinds {
  color: #059669;
  opacity: 0.85;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
:root.dark .ghost-repaired__kinds {
  color: #34d399;
}
</style>
