<script setup lang="ts">
/**
 * 文风页「试写对比」（v4 工坊中栏主角）——可验证核心。
 *
 * 同一句开头，两遍真实生成：
 * - 上栏「不带你的文风」：后端 bare 开关跳过画像+字帖，只留系统基座
 *   ——AI 平时的普通写法；
 * - 下栏「照你的文风写」：画像+亲笔字+写作规矩全上（stitch 同源管线）。
 * 两栏皮肤的差异（素面 vs 纸面朱丝栏衬线）本身就在演示「带上文风」的价值。
 *
 * 就地闭环：下栏文字内划选任意词 → 浮出「添入禁词库」——点击即入右栏
 * 拦截清单。选区安全（Phase 0 红队 Q2）：仅当 Selection 的
 * commonAncestorContainer 落在下栏容器内才响应；选区消失/越界浮层即收；
 * 动作后 removeAllRanges；卸载时清文档级监听。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from '../../../components/Icon.vue'

export interface SandboxRunState {
  running: boolean
  text: string
}

const props = defineProps<{
  runs: { baseline: SandboxRunState; styled: SandboxRunState }
}>()

const emit = defineEmits<{
  (e: 'run', text: string): void
  (e: 'ban', word: string): void
}>()

// 引子默认放空：引子应是一句开头，不是自家原文——零成本诉求由作者自填。
const inputText = ref('')
const styledPaneRef = ref<HTMLElement | null>(null)
const banChip = ref<{ x: number; y: number; text: string } | null>(null)

const runningAny = computed(() => props.runs.baseline.running || props.runs.styled.running)

function fire() {
  const text = inputText.value.trim()
  if (!text || runningAny.value) return
  emit('run', text)
}

// ---------- 划词加拦截（选区安全：容器包含判定） ----------

function selectionInPane(): { text: string; rect: DOMRect } | null {
  const pane = styledPaneRef.value
  if (!pane) return null
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null
  const range = sel.getRangeAt(0)
  // 红队 Q2：commonAncestor 须在下栏容器内——越界选区（拖到别的区/页面）不响应
  if (!pane.contains(range.commonAncestorContainer)) return null
  const text = sel.toString().trim()
  // 1~20 字、不含换行的词级片段才给入禁（防整段误加）
  if (!text || text.length > 20 || text.includes('\n')) return null
  return { text, rect: range.getBoundingClientRect() }
}

function onStyledMouseUp() {
  const hit = selectionInPane()
  if (!hit) {
    banChip.value = null
    return
  }
  // 坐标基准=styled pane 本体（chip 渲染在它里面，position:relative 的原点
  // 就是它）——按 .ab-row 算会整体偏出 pane 自身偏移量，且可能被
  // overflow:hidden 裁掉。
  const pr = styledPaneRef.value!.getBoundingClientRect()
  banChip.value = {
    text: hit.text,
    x: Math.max(4, hit.rect.left - pr.left),
    y: Math.max(4, hit.rect.top - pr.top - 36),
  }
}

function onSelectionChange() {
  if (!selectionInPane()) banChip.value = null
}

function doBan() {
  if (!banChip.value) return
  emit('ban', banChip.value.text)
  window.getSelection()?.removeAllRanges()
  banChip.value = null
}

onMounted(() => {
  document.addEventListener('selectionchange', onSelectionChange)
})
onBeforeUnmount(() => {
  document.removeEventListener('selectionchange', onSelectionChange)
})
</script>

<template>
  <section id="style-sec-sandbox" class="style-section sandbox">
    <div class="fire-row">
      <input
        v-model="inputText"
        class="fire-input"
        placeholder="输入一句测试开头，如：林尘推开门，屋里弥漫着煤油味……"
        @keydown.enter="fire"
      >
      <button
        class="fire-btn"
        :disabled="runningAny || !inputText.trim()"
        @click="fire"
      >{{ runningAny ? '正在写…' : '现场试写' }}</button>
    </div>

    <div class="ab-row">
      <div class="ab-pane bare">
        <div class="ab-label">
          不带你的文风
          <span class="ab-label-sub">· AI 平时的普通写法</span>
        </div>
        <div class="ab-text" :class="{ placeholder: !runs.baseline.text }">
          {{ runs.baseline.text || '这一遍会以 AI 平时的写法呈现。' }}
          <span v-if="runs.baseline.running" class="caret" />
        </div>
      </div>

      <div
        ref="styledPaneRef"
        class="ab-pane styled"
        @mouseup="onStyledMouseUp"
      >
        <div class="ab-label">
          照你的文风写
          <span class="ab-label-sub">· 学你的字、守你的规矩</span>
        </div>
        <div class="ab-text" :class="{ placeholder: !runs.styled.text }">
          {{ runs.styled.text || '这一遍会照你的文风写。' }}
          <span v-if="runs.styled.running" class="caret" />
        </div>
        <button
          v-if="banChip"
          class="ban-chip"
          :style="{ left: banChip.x + 'px', top: banChip.y + 'px' }"
          title="把划选的词加入拦截清单"
          @mousedown.prevent
          @click="doBan"
        >
          <Icon name="no-symbol" :size="12" />
          拦下这个词
        </button>
      </div>
    </div>

    <p class="sandbox-hint">下面这段「照你文风写」的文字里，划选不顺眼的词——点浮出的小签就加进右边的拦截，AI 以后不再这么写。</p>
  </section>
</template>

<style scoped>
.style-section {
  margin-top: 0; /* 列内间距归容器 workshop-col gap */
}
.fire-row {
  display: flex;
  gap: var(--space-2);
}
.fire-input {
  flex: 1;
  min-width: 0;
  min-height: var(--control-h-md);
  padding: 0 var(--control-px);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--field-bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.fire-input:focus-visible {
  border-color: var(--accent-400);
}
.fire-btn {
  flex-shrink: 0;
  min-height: var(--control-h-md);
  padding: 0 var(--space-4);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
}
.fire-btn:hover:not(:disabled) {
  background: var(--accent-600);
}
.fire-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
/* 两栏恒为上下堆叠（中栏宽度供不起并排；上下对比阅读更清楚） */
.ab-row {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-top: var(--space-3);
}
.ab-pane {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}
.ab-label {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  font-weight: 600;
  border-bottom: 1px solid var(--line-faint);
}
.ab-label-sub {
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--text-faint);
}
.ab-text {
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
}
.ab-text.placeholder {
  color: var(--text-faint);
}
/* 上栏：素面（塑料味的普通写法） */
.ab-pane.bare {
  background: var(--surface-well);
}
.ab-pane.bare .ab-label {
  color: var(--text-muted);
}
.ab-pane.bare .ab-text {
  padding: var(--space-4);
  min-height: 148px;
  font-size: var(--text-base);
  line-height: 1.9;
  color: var(--text-muted);
}
/* 下栏：纸面+朱丝栏+衬线（像你的字帖）——皮肤差异即价值演示 */
.ab-pane.styled {
  background-color: var(--paper-bg);
  background-image: repeating-linear-gradient(90deg,
    transparent 0 55px,
    color-mix(in srgb, var(--cinnabar-bright) 14%, transparent) 55px 56px);
  border-color: color-mix(in srgb, var(--accent-500) 45%, var(--border-color));
  user-select: text;
}
.ab-pane.styled .ab-label {
  color: var(--accent-500);
  background: color-mix(in srgb, var(--accent-500) 7%, transparent);
}
.ab-pane.styled .ab-text {
  padding: var(--space-4);
  min-height: 148px;
  font-family: var(--editor-font-family);
  font-size: var(--text-base);
  line-height: 2;
  color: var(--text-primary);
}
.caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 1px;
  vertical-align: -0.15em;
  background: var(--accent-500);
  animation: blink 0.8s step-end infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
.ban-chip {
  position: absolute;
  z-index: 20;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--bg-canvas);
  background: var(--danger);
  border: none;
  border-radius: var(--radius-pill);
  box-shadow: var(--elev-2-shadow);
  cursor: pointer;
  white-space: nowrap;
}
.ban-chip:hover {
  background: color-mix(in srgb, var(--danger) 85%, black);
}
.sandbox-hint {
  margin: var(--space-2) 0 0;
  font-size: var(--text-xs);
  line-height: var(--lh-compact);
  color: var(--text-muted);
}
/* 窄可用宽：引子输入组纵排（双栏本就上下堆叠，无需再降级） */
@container stylepage (max-width: 48rem) {
  .fire-row {
    flex-direction: column;
  }
  .fire-btn {
    width: 100%;
  }
}
</style>
