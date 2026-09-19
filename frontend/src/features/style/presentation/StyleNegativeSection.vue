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
import Icon from '../../../components/Icon.vue'
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

/** 档位切换（Phase 3）：提醒 ⇄ 硬禁。缺省/未设 = 提醒（与后端 warning 兜底一致） */
function toggleSeverity(item: NegativeItem) {
  item.severity = item.severity === 'blocker' ? 'warning' : 'blocker'
  emit('dirty')
}

function hitCount(word: string): number {
  return props.hitCounts?.[word] ?? -1  // -1 = 未统计（无章数据）
}
</script>

<template>
  <section id="style-sec-negative" class="style-section">
    <header class="sec-head">
      <h2 class="sec-title">禁词全量与陈词库</h2>
      <p class="sec-sub">
        这里管全部禁词：逐条改词、改替代写法、换档位；下方内置陈词库可按这本书逐条豁免。
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
        class="neg-input neg-word"
        placeholder="禁用词/句式"
        @input="emit('dirty')"
      >
      <input
        v-model="item.alternative"
        class="neg-input neg-alt"
        placeholder="替代规则（如：删掉，或换成具体动作）"
        @input="emit('dirty')"
      >
      <span
        v-if="hitCount(item.word) >= 0"
        class="hit-chip"
        :class="{ 'hit-zero': hitCount(item.word) === 0 }"
        :title="hitCount(item.word) === 0 ? '近 10 章零命中——这条可能不需要了' : '近 10 章命中次数'"
      >{{ hitCount(item.word) === 0 ? '未命中' : `近10章 ×${hitCount(item.word)}` }}</span>
      <button
        class="sev-toggle"
        :class="{ 'sev-blocker': item.severity === 'blocker' }"
        title="硬禁：检查时命中即判不通过（只提示，绝不自动改正文）/ 提醒：仅提示与统计"
        @click="toggleSeverity(item)"
      >{{ item.severity === 'blocker' ? '硬禁' : '提醒' }}</button>
      <button class="icon-danger" title="删除此条" @click="removeNegative(idx)">
        <Icon name="x-mark" :size="12" />
      </button>
    </div>

    <!-- 系统陈词库：全局层折叠可见 + 本书豁免 -->
    <div class="system-block">
      <button class="system-toggle" @click="showSystem = !showSystem">
        <Icon :name="showSystem ? 'chevron-down' : 'chevron-right'" :size="12" />
        AI 高频陈词库（全局共享 · {{ (systemCliches || []).length }} 条）
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
          <span v-if="c.alternative" class="system-alt">
            <Icon name="arrow-right" :size="12" /> {{ c.alternative }}
          </span>
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
/* .sec-head/.sec-title 吃 style.css 全局工具类（00 期 §3.1）；
   sec-sub 按 §6 归 token（原 muted 过淡） */
.sec-sub {
  margin: 0.25rem 0 0;
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  color: var(--text-secondary);
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
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.btn-scan {
  min-height: 28px;
  padding: 0.25rem 0.625rem;
  font-size: var(--text-base);
  color: var(--accent-500);
  background: color-mix(in srgb, var(--accent-500) 10%, transparent);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-scan:hover {
  background: color-mix(in srgb, var(--accent-500) 16%, transparent);
}
.btn-ghost {
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
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
  /* §4.5 双档 grid：默认（双栏半宽）两行布局——词/替代词各占整行 40%+，
     严重度与台账第二行，删除钮跨两行右缘；塌单列全宽时五件单行 */
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  grid-template-areas:
    "word alt  del"
    "sev  hits del";
  gap: var(--space-2) var(--space-3);
  align-items: center;
  padding: var(--space-2);
  margin-bottom: 0.375rem;
  background: var(--surface-overlay);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}
.neg-word {
  grid-area: word;
}
.neg-alt {
  grid-area: alt;
}
.sev-toggle {
  grid-area: sev;
  justify-self: start;
}
.hit-chip {
  grid-area: hits;
  justify-self: start;
}
@container stylepage (max-width: 60rem) {
  .neg-row {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto auto auto;
    grid-template-areas: "word alt sev hits del";
  }
}
.neg-input {
  min-width: 0;
  min-height: 28px;
  padding: 0.3rem 0.5rem;
  font-size: var(--text-sm);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.neg-input:focus {
  border-color: var(--accent-400);
}
.hit-chip {
  flex-shrink: 0;
  padding: 0.125rem 0.4375rem;
  font-size: var(--text-xs);
  color: var(--danger);
  background: var(--danger-bg);
  border-radius: var(--radius-xs);
  white-space: nowrap;
}
.hit-chip.hit-zero {
  color: var(--text-faint);
  background: var(--bg-tertiary);
}
/* 档位切换：提醒（灰、可点） ⇄ 硬禁（红 chip，同系统陈词库 system-sev 视觉）；
   2026-09-17：点击目标升 --control-h-sm（28px） */
.sev-toggle {
  min-height: var(--control-h-sm);
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  color: var(--warn);
  background: var(--warn-bg);
  border: none;
  border-radius: var(--radius-xs);
  white-space: nowrap;
  cursor: pointer;
}
.sev-toggle:hover {
  color: var(--text-secondary);
}
.sev-toggle.sev-blocker {
  color: var(--danger);
  background: var(--danger-bg);
}
.icon-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  grid-area: del;
  align-self: center;
  width: 24px;
  height: 24px;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  cursor: pointer;
}
.icon-danger:hover {
  color: var(--danger);
  background: var(--danger-bg);
}

/* ---- 系统陈词库 ---- */
.system-block {
  margin-top: 0.875rem;
}
.system-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) 0;
  font-size: var(--text-xs);
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
  color: var(--warn);
}
.system-list {
  max-height: 260px;
  padding: 0.5rem 0.625rem;
  margin-top: 0.25rem;
  overflow-y: auto;
  background: var(--surface-overlay);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}
.system-note {
  margin: 0 0 0.5rem;
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
  color: var(--text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
  text-decoration: line-through;
}
.system-row.exempted .system-pattern {
  text-decoration: line-through;
}
.system-alt {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.system-sev {
  flex-shrink: 0;
  padding: 0.0625rem 0.3125rem;
  font-size: var(--text-xs);
  color: var(--danger);
  background: var(--danger-bg);
  border-radius: var(--radius-xs);
}
.btn-exempt {
  flex-shrink: 0;
  min-height: 24px;
  padding: 0.125rem 0.4375rem;
  font-size: var(--text-xs);
  color: var(--warn);
  background: var(--warn-bg);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-exempt:hover {
  background: var(--warn-bg);
}
</style>
