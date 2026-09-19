<script setup lang="ts">
/**
 * 开章卡（01 下一阶段设计稿 M1）——空章「打算」页顶部的四面镜子。
 *
 * 三规则宪法（任何一行不许违反）：
 * 1. 计数=真实总数；相关性算不出退全书口径并带徽标（「与在场相关」/「全书」）；
 * 2. 点一下就地展开完整内容（伏笔原文/真相表里/揭示计划原文），不跳世界页；
 * 3. 空集零像素——行缺席不是「0 条」。
 * 超载降级（>6 条）：行内只显示最要紧一条 + 真实总数，展开见全量。
 * 零强制交互：不弹窗、不确认、不打断打字；扫到就扫到，扫不到直接开写。
 */
import { computed, toRef } from 'vue'
import { useOpeningCard } from '../composables/useOpeningCard'
import type { RevealRow } from '../../../services/api/domain/adaptive.api'
import { formatTime } from '../../world/engine/timeFormat'

const props = defineProps<{ chapterId: string | null }>()

const { card, expanded, toggleExpand } = useOpeningCard(toRef(props, 'chapterId'))

const OVERLOAD = 6

const dueReveals = computed(() => card.value?.due_reveals || [])
/** 超载降级：只显示逾期最深的一条（排序已按逾期深度，首条即最要紧）+ 真实总数 */
const dueHead = computed(() => dueReveals.value.slice(0, 1))
const untold = computed(() => card.value?.untold)
const untoldHead = computed(() => (untold.value?.items || []).slice(0, OVERLOAD))
const threads = computed(() => card.value?.threads)
const scene = computed(() => card.value?.scene)

function dueLine(r: RevealRow): string {
  return r.overdue_by && r.overdue_by > 0
    ? `「${r.label}」已逾期 ${r.overdue_by} 章`
    : `这章该抖出「${r.label}」了`
}

function timeLabel(t: number): string {
  try {
    return formatTime(t)
  } catch {
    return `第 ${t} 日`
  }
}

function rowKey(prefix: string, r: RevealRow, i: number): string {
  return `${prefix}:${r.label}:${r.expected_chapter ?? 'x'}:${i}`
}
</script>

<template>
  <!-- 全空整块不渲染（规则三）；渲染即至少有一行有事 -->
  <section v-if="card && Object.keys(card).length" class="opening-card">
    <div class="oc-title">开章卡<span class="oc-sub">你自己录下的事，摆在一起</span></div>

    <!-- L1 该揭 -->
    <div v-if="dueReveals.length" class="oc-row" :class="{ open: expanded.has(rowKey('due', dueReveals[0], 0)) }">
      <button class="oc-line" @click="toggleExpand(chapterId || '', rowKey('due', dueReveals[0], 0))">
        <span v-if="dueHead.length" class="oc-text">{{ dueLine(dueHead[0]) }}</span>
        <span v-if="dueReveals.length > 1" class="oc-count">，共 {{ dueReveals.length }} 条</span>
        <span class="chevron small">▾</span>
      </button>
      <ul v-if="expanded.has(rowKey('due', dueReveals[0], 0))" class="oc-detail">
        <li v-for="(r, i) in dueReveals" :key="rowKey('due', r, i)">
          <div class="oc-item-label">{{ dueLine(r) }}<span class="oc-plan">计划第 {{ r.expected_chapter }} 章揭</span></div>
          <div v-if="r.public_text" class="oc-item-text">读者目前看到的：{{ r.public_text }}</div>
          <div v-if="r.canon_text" class="oc-item-text oc-item-secret">实际真相：{{ r.canon_text }}</div>
          <div v-if="r.reveal_plan" class="oc-item-text">打算怎么抖：{{ r.reveal_plan }}</div>
        </li>
      </ul>
    </div>

    <!-- L2 别说破 -->
    <div v-if="untold && untold.items.length" class="oc-row">
      <button class="oc-line" @click="toggleExpand(chapterId || '', 'untold')">
        <span class="oc-text">这章还不能说破的：{{ untold.items.length }} 条</span>
        <span class="oc-scope" :title="untold.scope === 'presence' ? '只列与本章在场角色相关的真相' : '空章算不出在场——按全书口径列'">
          {{ untold.scope === 'presence' ? '与在场相关' : '全书' }}
        </span>
        <span class="chevron small">▾</span>
      </button>
      <ul v-if="expanded.has('untold')" class="oc-detail">
        <li v-for="(r, i) in untold.items" :key="rowKey('untold', r, i)">
          <div class="oc-item-label">{{ r.label }}<span class="oc-plan">计划第 {{ r.expected_chapter }} 章才揭</span></div>
          <div v-if="r.public_text" class="oc-item-text">读者目前看到的：{{ r.public_text }}</div>
          <div v-if="r.canon_text" class="oc-item-text oc-item-secret">实际真相：{{ r.canon_text }}</div>
        </li>
      </ul>
    </div>

    <!-- L3 线头 -->
    <div v-if="threads" class="oc-row">
      <button class="oc-line" @click="toggleExpand(chapterId || '', 'threads')">
        <span class="oc-text">没收的线头 {{ threads.count }} 条<template v-if="threads.oldest > 0">，最久吊了 {{ threads.oldest }} 章</template></span>
        <span class="oc-scope" title="全书还没收的伏笔（按吊着的章数排）">全书</span>
        <span class="chevron small">▾</span>
      </button>
      <ul v-if="expanded.has('threads')" class="oc-detail">
        <li v-for="h in threads.items" :key="h.ledger_key || h.content">
          <div class="oc-item-label">{{ h.content }}<span class="oc-plan" v-if="h.chapters_open != null">吊了 {{ h.chapters_open }} 章</span></div>
        </li>
      </ul>
    </div>

    <!-- L4 此刻 -->
    <div v-if="scene" class="oc-row oc-row--plain">
      <span class="oc-text">此刻：{{ timeLabel(scene.t) }}<template v-if="scene.location"> · {{ scene.location }}</template><template v-if="scene.present.length"> · {{ scene.present.join('、') }}在场</template></span>
    </div>
  </section>
</template>

<style scoped>
.opening-card {
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  padding: 0.5rem 0.6rem;
  margin-bottom: 0.6rem;
  background: var(--bg-canvas);
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.oc-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--accent-500);
  letter-spacing: 0.04em;
  margin-bottom: 0.15rem;
}
.oc-sub {
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 0.4em;
  letter-spacing: 0;
}
.oc-row {
  font-size: var(--text-xs);
  line-height: 1.7;
}
.oc-line {
  display: inline-flex;
  align-items: baseline;
  gap: 0.3em;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  color: var(--text-primary);
}
.oc-line:hover .oc-text {
  color: var(--accent-500);
}
.oc-row--plain .oc-text {
  color: var(--text-muted);
}
.oc-count {
  color: var(--text-muted);
}
.oc-scope {
  flex-shrink: 0;
  padding: 0 0.35em;
  border: 1px solid var(--line-faint);
  border-radius: 999px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}
.chevron {
  color: var(--text-muted);
  font-size: var(--text-xs);
}
.chevron.open {
  transform: rotate(180deg);
}
.oc-detail {
  list-style: none;
  margin: 0.2rem 0 0.3rem;
  padding: 0.3rem 0.5rem;
  border-left: 2px solid var(--line-faint);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  max-height: 40vh;
  overflow-y: auto;
}
.oc-item-label {
  color: var(--text-primary);
}
.oc-plan {
  margin-left: 0.5em;
  color: var(--text-muted);
  font-size: var(--text-xs);
}
.oc-item-text {
  color: var(--text-secondary);
  margin-top: 0.15rem;
}
.oc-item-secret {
  color: var(--cinnabar);
}
</style>
