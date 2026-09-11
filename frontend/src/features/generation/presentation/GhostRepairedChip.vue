<script setup lang="ts">
/**
 * 幽灵返修条（约束治理二期，2026-09-02，docs/constraint-governance.md）。
 *
 * 返修环检出设定硬伤并自动修正成功时，在感知带停靠区出一行薄荷条
 * 「已自动修正 N 处穿帮」——与洗层条同系（「已处理」语义，区别疑点条的
 * 琥珀「请过目」）。只展示计数与类目（人话标签），不暴露被拒原稿
 * （防回退污染纪律：违规原稿不进任何可回退/可展示通道）。
 *
 * 09-08 作者可见性：点「明细」展开逐条人话说明（ghost_guard 的设定侧
 * 触发词 + message，与疑点条明细同口径同词表）——「修了什么」可见，
 * 带伤原稿仍然不可见。旧后端帧无 items 时退化为纯计数条（无入口）。
 *
 * 分层纪律：presentation 纯 props——repaired 由容器从 useGhostDraft 单例注入。
 */
import { computed, ref } from 'vue'
import { warningKindLabel } from '../composables/useGhostDraft'
import type { GhostWarning } from '../../../services/api/domain/adaptive.api'

const props = defineProps<{
  repaired: { count: number; kinds: string[]; action: string; items?: GhostWarning[] }
}>()

const kindsSummary = computed(() =>
  (props.repaired.kinds || []).map((k) => warningKindLabel(k)).join('、'),
)
const actionLabel = computed(() =>
  props.repaired.action === 'excised' ? '删掉问题句' : '改写修复',
)
/** 逐条明细（缺省=旧后端帧，退化为纯计数条不出入口） */
const items = computed(() => props.repaired.items || [])
const expanded = ref(false)

function toggle(): void {
  if (items.value.length) expanded.value = !expanded.value
}
</script>

<template>
  <div class="ghost-repaired">
    <button
      class="ghost-repaired__head"
      :title="`AI 稿子里的设定错误已自动改掉（${actionLabel}）：${kindsSummary}`"
      @click="toggle"
    >
      <span class="ghost-repaired__icon">🩹</span>
      <span class="ghost-repaired__count">已自动修正 {{ repaired.count }} 处穿帮</span>
      <span class="ghost-repaired__kinds">{{ kindsSummary }}</span>
      <span v-if="items.length" class="ghost-repaired__toggle">{{ expanded ? '收起' : '明细' }}</span>
    </button>
    <div v-if="expanded && items.length" class="ghost-repaired__list">
      <div v-for="(w, i) in items" :key="i" class="ghost-repaired__item">
        <span class="ghost-repaired__tag">{{ warningKindLabel(w.kind) }}</span>
        <span class="ghost-repaired__span" :title="w.span_text">「{{ w.span_text }}」</span>
        <span class="ghost-repaired__msg">{{ w.message }}</span>
      </div>
      <div class="ghost-repaired__foot">上屏的是修正稿，带伤原稿已丢弃</div>
    </div>
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
  font-size: 12px;
  color: #047857;
}
:root.dark .ghost-repaired {
  background: rgba(20, 46, 38, 0.55);
  border-color: rgba(110, 231, 183, 0.35);
  color: #6ee7b7;
}

.ghost-repaired__head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  width: 100%;
  padding: 0;
  border: none;
  background: none;
  cursor: default;
  text-align: left;
  font-family: inherit;
  font-size: inherit;
  color: inherit;
}
/* 有明细可看时才是按钮（手型） */
.ghost-repaired__head:has(.ghost-repaired__toggle) {
  cursor: pointer;
}

.ghost-repaired__icon {
  font-size: 12px;
  line-height: 1;
}

.ghost-repaired__count {
  font-weight: 600;
  white-space: nowrap;
}

.ghost-repaired__kinds {
  color: #059669;
  opacity: 0.85;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
:root.dark .ghost-repaired__kinds {
  color: #34d399;
}

.ghost-repaired__toggle {
  flex-shrink: 0;
  font-size: 10px;
  color: #047857;
  border: 1px solid #6ee7b7;
  border-radius: 6px;
  padding: 0 6px;
  line-height: 1.5;
}
:root.dark .ghost-repaired__toggle {
  color: #6ee7b7;
  border-color: rgba(110, 231, 183, 0.4);
}

.ghost-repaired__list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 5px;
  margin-top: 4px;
  border-top: 1px dashed rgba(5, 150, 105, 0.3);
}

.ghost-repaired__item {
  display: flex;
  align-items: baseline;
  gap: 5px;
  font-size: 11px;
  line-height: 1.5;
  color: #065f46;
  flex-wrap: wrap;
}
:root.dark .ghost-repaired__item {
  color: #a7f3d0;
}

.ghost-repaired__tag {
  flex-shrink: 0;
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 9999px;
  background: #d1fae5;
  color: #047857;
  white-space: nowrap;
}
:root.dark .ghost-repaired__tag {
  background: rgba(6, 95, 70, 0.5);
  color: #a7f3d0;
}

.ghost-repaired__span {
  font-weight: 600;
  word-break: break-all;
}

.ghost-repaired__msg {
  flex: 1;
  min-width: 100%;
  opacity: 0.85;
}

.ghost-repaired__foot {
  font-size: 10px;
  opacity: 0.7;
}
</style>
