<script setup lang="ts">
/**
 * 文风页「写作规矩」开关（模块 C，2026-09 靶场批）——质感契约的开关面。
 *
 * 每条契约渲染为一组干净的checkbox（规矩项由注册表逐字拆条，全启=拍板
 * 原文）。customized_via=body（整文定制）时开关让位——去「研究数据」折叠舱
 * 恢复默认后开关重新可用。编辑只动规矩开关；病灶词执法词表恒由系统持有。
 *
 * 2026-09-17 视觉归一：分区标题退役（栏头「写作底线」接管），样式全量
 * 迁移 token 方言（docs/design/style-page-redesign.md §4.4）。
 */
import { computed } from 'vue'
import type { TextureContractItem } from '../../../types'

const props = defineProps<{
  contract: TextureContractItem | null
  busy?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle', ruleKey: string, enabled: boolean): void
}>()

/** body 整文定制态：开关不可用（避免与手改文本互相覆盖） */
const textCustomized = computed(() => props.contract?.customized_via === 'body')

const modesLabel = computed(() => {
  const names: Record<string, string> = { stitch: '断点续写', continue: '顺势续写' }
  return (props.contract?.modes || []).map(m => names[m] || m).join('、')
})
</script>

<template>
  <section v-if="contract" id="style-sec-rules" class="style-section">
    <div class="rules-card" :class="{ customized: !contract.is_default }">
      <div class="rules-head">
        <span class="rules-title">{{ contract.title }}</span>
        <span class="rules-badge" :class="contract.is_default ? 'badge-default' : 'badge-custom'">
          {{ contract.is_default ? '系统默认' : '本书定制' }}
        </span>
        <span class="rules-scope" :title="`生效范围：${modesLabel}`">只在续写时生效</span>
      </div>

      <div v-if="textCustomized" class="rules-textmode">
        这条规矩这本书改过原文（在实验室里手改的），开关暂时让位——
        去实验室点「恢复默认」就能重新用开关。
      </div>

      <label
        v-for="rule in contract.rules"
        :key="rule.key"
        class="rule-row"
        :class="{ off: !rule.enabled }"
      >
        <input
          type="checkbox"
          class="rule-check"
          :checked="rule.enabled"
          :disabled="busy || textCustomized"
          @change="emit('toggle', rule.key, ($event.target as HTMLInputElement).checked)"
        >
        <span class="rule-title">{{ rule.title }}</span>
        <span class="rule-state">{{ rule.enabled ? '在岗' : '已关' }}</span>
      </label>
    </div>
  </section>
</template>

<style scoped>
.style-section {
  margin-top: 0;
}
.rules-card {
  padding: var(--space-3);
  background: var(--surface-card);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}
.rules-card.customized {
  border-color: var(--warn);
}
.rules-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.rules-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}
.rules-badge {
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  border-radius: var(--radius-pill);
}
.badge-default {
  color: var(--text-secondary);
  background: var(--bg-tertiary);
}
.badge-custom {
  color: var(--warn);
  background: var(--warn-bg);
}
.rules-scope {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.rules-textmode {
  padding: var(--space-2) var(--space-3);
  margin: var(--space-2) 0;
  font-size: var(--text-xs);
  line-height: var(--lh-compact);
  color: var(--warn);
  background: var(--warn-bg);
  border-radius: var(--radius-sm);
}
.rule-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: var(--control-h-sm);
  padding: 0 var(--space-1);
  font-size: var(--text-base);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.rule-row:hover {
  background: var(--state-hover);
}
.rule-row.off {
  color: var(--text-muted);
}
.rule-check {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  accent-color: var(--accent-500);
  cursor: pointer;
}
.rule-check:disabled {
  cursor: not-allowed;
}
.rule-title {
  flex: 1;
}
.rule-state {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.rule-row.off .rule-state {
  color: var(--danger);
}
</style>
