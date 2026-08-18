<script setup lang="ts">
/**
 * 文风页试听横条（S3 试衣间）——「调了看得见」的可感知出口。
 *
 * 原理：给定段落 + 当前文风配置 → 后端走与 stitch-ghost 完全相同的注入管线改写。
 * A/B：左 = 不注入文风的基线版，右 = 当前文风版，左右对照即注入效果本身。
 * 纯展示：SSE 调用与状态在容器（分层规范）。
 */
import { ref, watch } from 'vue'
import Icon from '../../../components/Icon.vue'

export interface AuditionRunState {
  running: boolean
  text: string
}

const props = defineProps<{
  defaultText: string
  runs: { baseline: AuditionRunState; styled: AuditionRunState }
  hasStyleConfig: boolean
}>()

const emit = defineEmits<{
  (e: 'run', text: string, baseline: boolean): void
}>()

const text = ref('')

watch(
  () => props.defaultText,
  (v) => {
    if (v && !text.value.trim()) text.value = v.slice(0, 600)
  },
  { immediate: true },
)

const anyRunning = () => props.runs.baseline.running || props.runs.styled.running

function runStyled() {
  if (!text.value.trim() || anyRunning()) return
  emit('run', text.value.trim(), false)
}

function runAB() {
  if (!text.value.trim() || anyRunning()) return
  emit('run', text.value.trim(), true)
}
</script>

<template>
  <section id="style-sec-audition" class="audition-bar">
    <header class="bar-head">
      <h2 class="bar-title">试听</h2>
      <p class="bar-sub">
        贴一段字（默认填入你样本库里最长的一段），听一听「当前文风配置」改写出来是什么声音——
        与写作台续写走完全相同的注入路径。
      </p>
    </header>

    <div class="bar-body">
      <textarea
        v-model="text"
        rows="3"
        class="bar-textarea"
        placeholder="粘贴任意一段文字试听（留空默认取样本库里最长的一段）"
      ></textarea>
      <div class="bar-actions">
        <button class="btn-primary" :disabled="anyRunning() || !text.trim()" @click="runStyled">
          <Icon name="bolt" :size="12" class="mr-1" />
          {{ runs.styled.running ? '生成中…' : '▶ 试听当前文风' }}
        </button>
        <button class="btn-ghost" :disabled="anyRunning() || !text.trim()" @click="runAB">
          A/B 对照
        </button>
        <span class="bar-cost">约 5 秒 · 每次 1 次调用（A/B 为 2 次）</span>
      </div>
    </div>

    <!-- 结果区：A/B 双栏或单栏 -->
    <div v-if="runs.baseline.text || runs.baseline.running || runs.styled.text || runs.styled.running" class="bar-results">
      <div v-if="runs.baseline.text || runs.baseline.running" class="result-pane pane-baseline">
        <span class="pane-tag">基线（不注入文风）</span>
        <p class="pane-text">{{ runs.baseline.running ? '生成中…' : runs.baseline.text }}</p>
      </div>
      <div class="result-pane pane-styled">
        <span class="pane-tag">{{ hasStyleConfig ? '当前文风' : '当前文风（未配置，仅有基础反 AI 腔）' }}</span>
        <p class="pane-text">{{ runs.styled.running ? '生成中…' : runs.styled.text }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.audition-bar {
  padding: 1rem 0.875rem;
  margin: 0.75rem 0;
  background: color-mix(in srgb, var(--accent-500) 4%, var(--bg-panel));
  border: 1px solid color-mix(in srgb, var(--accent-500) 25%, var(--border-color));
  border-radius: 0.625rem;
  scroll-margin-top: 4.5rem;
}
.bar-head {
  margin-bottom: 0.625rem;
}
.bar-title {
  margin: 0;
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.bar-sub {
  margin: 0.25rem 0 0;
  font-size: 0.6875rem;
  line-height: 1.6;
  color: var(--text-muted);
}
.bar-textarea {
  width: 100%;
  padding: 0.5rem 0.625rem;
  font-size: 0.8125rem;
  line-height: 1.7;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  resize: vertical;
}
.bar-textarea:focus {
  outline: none;
  border-color: var(--accent-400);
}
.bar-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.btn-primary {
  display: inline-flex;
  align-items: center;
  padding: 0.4rem 0.875rem;
  font-size: 0.75rem;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-ghost {
  padding: 0.4rem 0.75rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-ghost:hover:not(:disabled) {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.bar-cost {
  font-size: 0.625rem;
  color: var(--text-muted);
}
.bar-results {
  display: flex;
  gap: 0.625rem;
  margin-top: 0.625rem;
}
.result-pane {
  flex: 1;
  min-width: 0;
  padding: 0.625rem 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.pane-baseline {
  opacity: 0.75;
}
.pane-tag {
  display: block;
  margin-bottom: 0.375rem;
  font-size: 0.625rem;
  color: var(--text-muted);
}
.pane-styled .pane-tag {
  color: var(--accent-500);
}
.pane-text {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.8;
  color: var(--text-secondary);
  white-space: pre-wrap;
}
@media (max-width: 640px) {
  .bar-results {
    flex-direction: column;
  }
}
</style>
