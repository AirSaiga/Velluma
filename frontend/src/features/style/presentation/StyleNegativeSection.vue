<script setup lang="ts">
/**
 * 文风页 ③「负面清单」——禁词台账 + 系统陈词库（三层可见性，S4 补全）。
 *
 * 台账化：每条禁词带近 10 章命中计数（清单是否在工作的直接证据；
 * 命中为零反向提醒可能不需要）。
 * 三层可见：系统陈词库默认折叠，可展开逐条「本书豁免」（不删全局层，
 * 仅本书审计/扫描/合并不生效）——设计稿 §6.4。
 */
import { ref } from 'vue'
import type { NegativeItem } from '../../../types'

export interface SystemClicheItem {
  id: string
  pattern: string
  alternative?: string | null
  severity: string
}

const props = defineProps<{
  negativeList: NegativeItem[]
  /** 台账：各禁词近 10 章命中次数 */
  hitCounts?: Record<string, number>
  /** 系统陈词库（全局层，折叠展示） */
  systemCliches?: SystemClicheItem[]
  /** 本书已豁免的 pattern 列表 */
  exemptions?: string[]
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
  (e: 'scan'): void
  (e: 'toggle-exemption', pattern: string, exempted: boolean): void
}>()

const showSystem = ref(false)

function addNegative() {
  props.negativeList.unshift({ word: '', alternative: '' })
  emit('dirty')
}

function removeNegative(index: number) {
  props.negativeList.splice(index, 1)
  emit('dirty')
}

function hitCount(word: string): number {
  return props.hitCounts?.[word] ?? -1  // -1 = 未统计（无章数据）
}
</script>

<template>
  <section id="style-sec-negative" class="style-section">
    <header class="sec-head">
      <h2 class="sec-title">负面清单</h2>
      <p class="sec-sub">
        每条禁令配一条替代规则——AI 写作与审校时三层禁词（系统陈词库 + 本书黑名单 + 本清单）合并生效。
      </p>
    </header>

    <div class="neg-toolbar">
      <span class="neg-count">{{ negativeList.filter(n => n.word.trim()).length }} 条生效</span>
      <span class="neg-actions">
        <button class="btn-scan" title="用三层禁词扫描章节正文，逐条裁决替换" @click="emit('scan')">
          扫描章节
        </button>
        <button class="btn-ghost" @click="addNegative">+ 添加</button>
      </span>
    </div>

    <div v-if="negativeList.length === 0" class="empty-note">
      暂无负面清单——「从样本提炼」会带出建议清单，也可以手动添加你最烦的 AI 腔。
    </div>

    <div
      v-for="(item, idx) in negativeList"
      :key="idx"
      class="neg-row"
    >
      <input
        v-model="item.word"
        class="neg-input"
        placeholder="禁用词/句式"
        @input="emit('dirty')"
      >
      <span class="neg-arrow">→</span>
      <input
        v-model="item.alternative"
        class="neg-input"
        placeholder="替代规则（如：删掉，或换成具体动作）"
        @input="emit('dirty')"
      >
      <span
        v-if="hitCount(item.word) >= 0"
        class="hit-chip"
        :class="{ 'hit-zero': hitCount(item.word) === 0 }"
        :title="hitCount(item.word) === 0 ? '近 10 章零命中——这条可能不需要了' : '近 10 章命中次数'"
      >{{ hitCount(item.word) === 0 ? '未命中' : `近10章 ×${hitCount(item.word)}` }}</span>
      <button class="icon-danger" title="删除此条" @click="removeNegative(idx)">✕</button>
    </div>

    <!-- 系统陈词库：全局层折叠可见 + 本书豁免 -->
    <div class="system-block">
      <button class="system-toggle" @click="showSystem = !showSystem">
        {{ showSystem ? '▾' : '▸' }} AI 高频陈词库（全局共享 · {{ (systemCliches || []).length }} 条）
        <span v-if="(exemptions || []).length > 0" class="exempt-count">本书已豁免 {{ exemptions!.length }} 条</span>
      </button>
      <div v-if="showSystem" class="system-list">
        <p class="system-note">
          全局内置的 AI 腔禁词（系统层）。豁免 = 本书不生效（检查/扫描/生成合并都会跳过），
          不影响其他书。有替代建议的会随禁词一并注入。
        </p>
        <div
          v-for="c in systemCliches || []"
          :key="c.id"
          class="system-row"
          :class="{ exempted: exemptions?.includes(c.pattern) }"
        >
          <span class="system-pattern">{{ c.pattern }}</span>
          <span v-if="c.alternative" class="system-alt">→ {{ c.alternative }}</span>
          <span v-if="c.severity === 'blocker'" class="system-sev">硬禁</span>
          <button
            class="btn-exempt"
            @click="emit('toggle-exemption', c.pattern, !exemptions?.includes(c.pattern))"
          >{{ exemptions?.includes(c.pattern) ? '恢复' : '本书豁免' }}</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.style-section {
  padding: 1.25rem 0 1.5rem;
  scroll-margin-top: 4.5rem;
}
.sec-head {
  margin-bottom: 0.75rem;
}
.sec-title {
  margin: 0;
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.sec-sub {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-muted);
}
.neg-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}
.neg-actions {
  display: flex;
  gap: 0.375rem;
}
.neg-count {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.btn-scan {
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  color: #1d4ed8;
  background: #dbeafe;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-scan:hover {
  background: #bfdbfe;
}
.btn-ghost {
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-ghost:hover {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.empty-note {
  padding: 1rem;
  font-size: 0.75rem;
  text-align: center;
  color: var(--text-muted);
}
.neg-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  margin-bottom: 0.375rem;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.neg-input {
  flex: 1;
  min-width: 0;
  padding: 0.3rem 0.5rem;
  font-size: 0.75rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
}
.neg-input:focus {
  outline: none;
  border-color: var(--accent-400);
}
.neg-arrow {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}
.hit-chip {
  flex-shrink: 0;
  padding: 0.125rem 0.4375rem;
  font-size: 0.625rem;
  color: #b91c1c;
  background: #fee2e2;
  border-radius: 0.25rem;
  white-space: nowrap;
}
.hit-chip.hit-zero {
  color: var(--text-muted);
  background: var(--bg-tertiary);
}
.icon-danger {
  flex-shrink: 0;
  padding: 0.25rem 0.375rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
}
.icon-danger:hover {
  color: #dc2626;
  background: #fee2e2;
}

/* ---- 系统陈词库 ---- */
.system-block {
  margin-top: 0.875rem;
}
.system-toggle {
  padding: 0.25rem 0;
  font-size: 0.6875rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
}
.system-toggle:hover {
  color: var(--text-secondary);
}
.exempt-count {
  margin-left: 0.5rem;
  color: #b45309;
}
.system-list {
  max-height: 260px;
  padding: 0.5rem 0.625rem;
  margin-top: 0.25rem;
  overflow-y: auto;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.system-note {
  margin: 0 0 0.5rem;
  font-size: 0.625rem;
  line-height: 1.6;
  color: var(--text-muted);
}
.system-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
  border-bottom: 1px dashed var(--border-color);
}
.system-row:last-child {
  border-bottom: none;
}
.system-row.exempted {
  opacity: 0.55;
}
.system-pattern {
  flex-shrink: 0;
  max-width: 40%;
  overflow: hidden;
  font-size: 0.6875rem;
  color: var(--text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
  text-decoration: line-through;
}
.system-row.exempted .system-pattern {
  text-decoration: line-through;
}
.system-alt {
  flex: 1;
  overflow: hidden;
  font-size: 0.625rem;
  color: var(--text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.system-sev {
  flex-shrink: 0;
  padding: 0.0625rem 0.3125rem;
  font-size: 0.5625rem;
  color: #b91c1c;
  background: #fee2e2;
  border-radius: 0.25rem;
}
.btn-exempt {
  flex-shrink: 0;
  padding: 0.125rem 0.4375rem;
  font-size: 0.625rem;
  color: #b45309;
  background: #fef3c7;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-exempt:hover {
  background: #fde68a;
}
</style>
