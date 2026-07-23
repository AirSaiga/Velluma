<script setup lang="ts">
/**
 * 章节规划确认弹窗（V4.2 对话式介入点 1）。
 *
 * 职责：
 * - 生成前弹出，展示 Reader Mirror + Canon 综合建议
 * - 让作者对每个建议问题做决策
 * - 作者确认后，把决策透传给 /generate-adf（作为 author_override / author_intent）
 *
 * 设计依据：第 8 轮——"系统永远在建议，作者永远在决策"
 */
import { ref, computed, watchEffect } from 'vue'
import type { PlanSuggestionResponse, PlanSuggestionQuestion } from '../../../services/api/domain'

const props = defineProps<{
  suggestion: PlanSuggestionResponse | null
}>()

const emit = defineEmits<{
  (e: 'confirm', payload: {
    authorIntent: string
    expectationActions: Record<string, string>
    payoffDecision: string
  }): void
  (e: 'skip'): void
  (e: 'cancel'): void
}>()

// 每个问题的答案
const answers = ref<Record<string, string>>({})
const authorIntent = ref('')

watchEffect(() => {
  if (props.suggestion) {
    const newAnswers: Record<string, string> = {}
    for (const q of props.suggestion.suggested_questions) {
      newAnswers[q.id] = q.default || (q.options ? q.options[0] : '')
    }
    answers.value = newAnswers
    authorIntent.value = ''
  }
})

const expectationActions = computed(() => {
  const result: Record<string, string> = {}
  if (!props.suggestion) return result
  for (const q of props.suggestion.suggested_questions) {
    if (q.type === 'expectation_action' && q.expectation_id) {
      result[q.expectation_id] = answers.value[q.id] || 'ignore'
    }
  }
  return result
})

const payoffDecision = computed(() => {
  return answers.value['Q_PAYOFF'] || 'none'
})

function handleConfirm() {
  // 把作者意图 + 期待决策组装成 authorIntent 文本
  const parts: string[] = []
  if (payoffDecision.value === 'confirm') parts.push('本章释放爽点')
  else if (payoffDecision.value === 'delay') parts.push('本章继续累积，不释放')
  else if (payoffDecision.value === 'subvert') parts.push('本章故意反转期待（不打脸）')

  for (const [expId, action] of Object.entries(expectationActions.value)) {
    if (action === 'accumulate') parts.push(`期待 ${expId}: 继续累积`)
    else if (action === 'payoff') parts.push(`期待 ${expId}: 释放`)
  }

  if (authorIntent.value.trim()) parts.push(`作者补充：${authorIntent.value.trim()}`)

  emit('confirm', {
    authorIntent: parts.join('；'),
    expectationActions: { ...expectationActions.value },
    payoffDecision: payoffDecision.value,
  })
}
</script>

<template>
  <div v-if="suggestion" class="modal-overlay" @click.self="emit('cancel')">
    <div class="modal-card">
      <header class="modal-header">
        <h2>第 {{ suggestion.chapter_number }} 章规划确认</h2>
        <button class="close-btn" @click="emit('cancel')">×</button>
      </header>

      <div class="modal-body">
        <!-- 大纲 -->
        <div class="section">
          <h3>章节大纲</h3>
          <p class="outline">{{ suggestion.outline || '（未提供大纲）' }}</p>
        </div>

        <!-- Reader Mirror 建议 -->
        <div v-if="suggestion.reader_mirror_plan" class="section rm-section">
          <h3>Reader Mirror 建议</h3>
          <div class="rm-plan">
            <span class="rm-tension">建议张力 {{ suggestion.reader_mirror_plan.suggested_tension }}/10</span>
            <span v-if="suggestion.reader_mirror_plan.is_payoff_chapter_recommended" class="badge payoff">
              ⚡ 建议释放爽点
            </span>
          </div>
          <p class="rationale">{{ suggestion.reader_mirror_plan.rationale }}</p>
        </div>

        <!-- 活跃期待 -->
        <div v-if="suggestion.active_expectations.length" class="section">
          <h3>活跃期待（{{ suggestion.active_expectations.length }}）</h3>
          <div class="exp-grid">
            <div v-for="exp in suggestion.active_expectations" :key="exp.id" class="exp-item">
              <span class="exp-tension">{{ exp.current_tension }}/10</span>
              <span class="exp-desc">{{ exp.description }}</span>
              <span class="exp-action" :class="`action-${exp.recommended_action}`">
                {{ exp.recommended_action }}
              </span>
            </div>
          </div>
        </div>

        <!-- 问题清单（核心交互） -->
        <div v-if="suggestion.suggested_questions.length" class="section">
          <h3>系统提问（请确认）</h3>
          <div class="questions">
            <div v-for="q in suggestion.suggested_questions" :key="q.id" class="question-card">
              <label class="question-text">{{ q.question }}</label>

              <div v-if="q.type === 'free_text'" class="free-text">
                <textarea
                  v-model="authorIntent"
                  rows="2"
                  placeholder="可选，留空表示无特别要求"
                ></textarea>
              </div>

              <div v-else class="question-options">
                <button
                  v-for="opt in q.options"
                  :key="opt"
                  class="opt-btn"
                  :class="{ active: answers[q.id] === opt }"
                  @click="answers[q.id] = opt"
                >
                  {{ q.option_labels?.[opt] || opt }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Canon 摘要（折叠） -->
        <details v-if="suggestion.canon_summary_excerpt" class="section canon-section">
          <summary>Canon 摘要（点击展开）</summary>
          <pre class="canon-text">{{ suggestion.canon_summary_excerpt }}</pre>
        </details>
      </div>

      <footer class="modal-footer">
        <button class="btn-danger" @click="emit('cancel')">取消生成</button>
        <div class="spacer"></div>
        <button class="btn-secondary" @click="emit('skip')">跳过（用默认）</button>
        <button class="btn-primary" @click="handleConfirm">确认并生成</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal-card {
  background: var(--bg-primary); border-radius: 0.5rem;
  width: 90%; max-width: 640px; max-height: 90vh;
  display: flex; flex-direction: column; overflow: hidden;
}
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 1rem 1.25rem; border-bottom: 1px solid var(--border-color);
}
.modal-header h2 { font-size: 1rem; margin: 0; }
.close-btn {
  background: transparent; border: none; font-size: 1.5rem;
  cursor: pointer; color: var(--text-muted); line-height: 1;
}
.modal-body { padding: 1rem 1.25rem; overflow-y: auto; flex: 1; }
.section { margin-bottom: 1rem; }
.section h3 { font-size: 0.8125rem; margin: 0 0 0.5rem; color: var(--text-secondary); }
.outline {
  font-size: 0.8125rem; color: var(--text-primary); line-height: 1.5;
  margin: 0; padding: 0.625rem; background: var(--bg-secondary); border-radius: 0.375rem;
}
.rm-section { padding: 0.625rem; background: #eff6ff; border-radius: 0.375rem; border-left: 3px solid #3b82f6; }
.rm-plan { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.375rem; }
.rm-tension { font-weight: 600; font-size: 0.8125rem; color: #1e40af; }
.badge.payoff { padding: 0.125rem 0.5rem; background: #fee2e2; color: #dc2626; border-radius: 0.25rem; font-size: 0.6875rem; }
.rationale { font-size: 0.75rem; color: var(--text-secondary); margin: 0; line-height: 1.5; }

.exp-grid { display: flex; flex-direction: column; gap: 0.375rem; }
.exp-item {
  display: flex; gap: 0.5rem; align-items: center;
  padding: 0.375rem 0.5rem; background: var(--bg-secondary); border-radius: 0.25rem;
  font-size: 0.75rem;
}
.exp-tension { font-weight: 600; color: #f59e0b; min-width: 36px; }
.exp-desc { flex: 1; }
.exp-action {
  padding: 0.125rem 0.375rem; border-radius: 0.25rem; font-size: 0.625rem;
  text-transform: uppercase;
}
.action-payoff { background: #fee2e2; color: #dc2626; }
.action-accumulate { background: #fef3c7; color: #b45309; }
.action-setup { background: #f1f5f9; color: #64748b; }
.action-none { background: transparent; color: var(--text-muted); }

.questions { display: flex; flex-direction: column; gap: 0.625rem; }
.question-card {
  padding: 0.625rem; background: var(--bg-secondary); border-radius: 0.375rem;
  border-left: 3px solid var(--accent-500);
}
.question-text {
  display: block; font-size: 0.8125rem; margin-bottom: 0.5rem; color: var(--text-primary);
}
.question-options { display: flex; gap: 0.375rem; flex-wrap: wrap; }
.opt-btn {
  padding: 0.375rem 0.75rem; border: 1px solid var(--border-color);
  background: var(--bg-primary); border-radius: 0.25rem;
  font-size: 0.75rem; cursor: pointer; color: var(--text-primary);
}
.opt-btn.active { background: var(--accent-500); color: white; border-color: var(--accent-500); }
.free-text textarea {
  width: 100%; padding: 0.375rem; border: 1px solid var(--border-color);
  border-radius: 0.25rem; background: var(--bg-primary);
  font-size: 0.75rem; font-family: inherit; resize: vertical;
}

.canon-section { font-size: 0.75rem; }
.canon-section summary { cursor: pointer; color: var(--text-secondary); }
.canon-text {
  font-size: 0.6875rem; color: var(--text-muted); white-space: pre-wrap;
  margin: 0.5rem 0 0; max-height: 200px; overflow-y: auto;
  font-family: monospace;
}

.modal-footer {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.75rem 1.25rem; border-top: 1px solid var(--border-color);
}
.modal-footer .spacer { flex: 1; }
.btn-primary, .btn-secondary, .btn-danger {
  padding: 0.5rem 1rem; border-radius: 0.375rem; font-size: 0.8125rem;
  cursor: pointer; border: 1px solid var(--border-color);
}
.btn-primary { background: var(--accent-500); color: white; border-color: var(--accent-500); }
.btn-secondary { background: var(--bg-primary); }
.btn-danger { background: transparent; color: #dc2626; border-color: transparent; }
.btn-danger:hover { background: #fef2f2; }
</style>
