<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'
import type { ClarifyingQuestion } from '../../../types'

const props = defineProps<{
  show: boolean
  isProcessing?: boolean
  clarificationResult: {
    is_ambiguous: boolean
    identified_issues?: string[]
    clarifying_questions?: ClarifyingQuestion[]
    clarification_suggestions?: string[]
    refined_text?: string
    original_outline?: string
  } | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', newOutlineText: string): void
  (e: 'submit-answers', answers: { questionId: string, answer: string }[], originalOutline: string): void
}>()

const modalRef = ref<HTMLElement | null>(null)
const showRef = computed(() => props.show)
useFocusTrap(modalRef, showRef, { onEscape: () => emit('close') })

const editableOutline = ref('')
const selectedOptions = ref<Record<string, string>>({})
const customAnswers = ref<Record<string, string>>({})

const hasRefinedText = computed(() => {
  return !!props.clarificationResult?.refined_text?.trim()
})

const hasQuestions = computed(() => {
  return (props.clarificationResult?.clarifying_questions?.length || 0) > 0
})

const currentStep = computed(() => {
  if (props.isProcessing && !hasRefinedText.value) return 2
  if (hasRefinedText.value) return 3
  if (hasQuestions.value) return 1
  return 3
})

watch(() => props.show, (newVal) => {
  if (newVal) {
    updateEditableOutline()
    if (!props.clarificationResult?.refined_text?.trim()) {
      selectedOptions.value = {}
      customAnswers.value = {}
    }
  }
})

watch(() => props.clarificationResult, () => {
  if (props.show) {
    updateEditableOutline()
  }
}, { deep: true })

function updateEditableOutline() {
  if (props.clarificationResult?.refined_text?.trim()) {
    editableOutline.value = props.clarificationResult.refined_text
  } else {
    editableOutline.value = props.clarificationResult?.original_outline || ''
  }
}

function handleClose() {
  emit('close')
}

function handleOptionSelect(qId: string, value: string) {
  if (selectedOptions.value[qId] === value) {
    selectedOptions.value[qId] = ''
  } else {
    selectedOptions.value[qId] = value
    customAnswers.value[qId] = ''
  }
}

const hasSelectedAnswers = computed(() => {
  if (!props.clarificationResult?.clarifying_questions?.length) return false
  for (const q of props.clarificationResult.clarifying_questions) {
    if (selectedOptions.value[q.id] || customAnswers.value[q.id]?.trim()) {
      return true
    }
  }
  return false
})

function handleApply() {
  const answers: { questionId: string, answer: string }[] = []
  if (props.clarificationResult?.clarifying_questions) {
    for (const q of props.clarificationResult.clarifying_questions) {
      const selected = selectedOptions.value[q.id]
      const custom = customAnswers.value[q.id]?.trim()
      if (selected) {
        answers.push({ questionId: q.id, answer: selected })
      } else if (custom) {
        answers.push({ questionId: q.id, answer: custom })
      }
    }
  }
  if (answers.length > 0) {
    emit('submit-answers', answers, editableOutline.value)
  }
}

function handleConfirm() {
  emit('apply', editableOutline.value)
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      ref="modalRef"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/35 backdrop-blur-sm p-4"
      @click.self="handleClose"
    >
      <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        
        <!-- Header -->
        <div class="px-6 py-4 border-b border-[var(--border-color)] flex justify-between items-center bg-[var(--accent-100)]/20">
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-full bg-[var(--accent-100)] text-[var(--accent-700)] flex items-center justify-center">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </div>
            <h3 class="text-lg font-bold text-[var(--text-primary)]">AI 意图澄清建议</h3>
          </div>
          <button @click="handleClose" class="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <!-- Stepper -->
        <div class="px-6 pt-4">
          <div class="flex items-center gap-2">
            <div
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors"
              :class="currentStep >= 1 ? 'bg-[var(--accent-100)] text-[var(--accent-700)]' : 'bg-[var(--bg-canvas)] text-[var(--text-muted)]'"
            >
              <span class="w-4 h-4 rounded-full bg-current/20 flex items-center justify-center text-[10px]">1</span>
              <span>补充信息</span>
            </div>
            <div class="flex-1 h-px bg-[var(--border-color)]"></div>
            <div
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors"
              :class="currentStep >= 2 ? 'bg-[var(--accent-100)] text-[var(--accent-700)]' : 'bg-[var(--bg-canvas)] text-[var(--text-muted)]'"
            >
              <span class="w-4 h-4 rounded-full bg-current/20 flex items-center justify-center text-[10px]">2</span>
              <span>AI 修正</span>
            </div>
            <div class="flex-1 h-px bg-[var(--border-color)]"></div>
            <div
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors"
              :class="currentStep >= 3 ? 'bg-[var(--accent-100)] text-[var(--accent-700)]' : 'bg-[var(--bg-canvas)] text-[var(--text-muted)]'"
            >
              <span class="w-4 h-4 rounded-full bg-current/20 flex items-center justify-center text-[10px]">3</span>
              <span>确认应用</span>
            </div>
          </div>
        </div>

        <!-- Body -->
        <div class="p-6 overflow-y-auto custom-scrollbar flex flex-col gap-6">
          
          <div v-if="clarificationResult?.identified_issues?.length" class="bg-[var(--accent-100)]/15 border border-[var(--accent-100)]/40 rounded-xl p-4">
            <h4 class="text-sm font-semibold text-[var(--accent-700)] mb-2">发现信息空白：</h4>
            <ul class="list-disc list-inside text-sm text-[var(--text-secondary)] space-y-1 ml-2">
              <li v-for="(issue, i) in clarificationResult.identified_issues" :key="i">
                {{ issue }}
              </li>
            </ul>
          </div>

          <!-- 步骤 1：交互式问题区域 -->
          <div v-if="currentStep === 1 && clarificationResult?.clarifying_questions?.length" class="flex flex-col gap-4">
            <h4 class="text-sm font-semibold text-[var(--accent-700)]">请补充以下细节：</h4>
            <div 
              v-for="q in clarificationResult.clarifying_questions" 
              :key="q.id"
              class="bg-[var(--bg-panel)] border border-[var(--border-color)] rounded-xl p-4 flex flex-col gap-3"
            >
              <p class="text-sm font-medium text-[var(--text-primary)]">{{ q.question }}</p>
              
              <!-- 选项列表 -->
              <div v-if="q.options?.length" class="flex flex-col gap-2">
                <button
                  v-for="(opt, i) in q.options"
                  :key="i"
                  @click="handleOptionSelect(q.id, opt.value)"
                  class="text-left px-3 py-2 rounded-lg border text-sm transition-colors duration-200"
                  :class="[
                    selectedOptions[q.id] === opt.value 
                      ? 'bg-[var(--accent-100)]/40 border-[var(--accent-500)]/40 text-[var(--accent-700)]' 
                      : 'bg-[var(--bg-primary)] border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-canvas)]'
                  ]"
                >
                  <span class="font-medium mr-2">{{ opt.label }}:</span>
                  <span>{{ opt.value }}</span>
                </button>
              </div>

              <!-- 自定义回答 -->
              <div class="mt-1">
                <input
                  v-model="customAnswers[q.id]"
                  type="text"
                  placeholder="或者输入您的自定义设定..."
                  class="w-full px-3 py-2 text-sm bg-[var(--bg-primary)] border rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)] focus:border-transparent transition-shadow"
                  :class="[
                    customAnswers[q.id] ? 'border-[var(--accent-500)]/40' : 'border-[var(--border-color)]',
                    selectedOptions[q.id] ? 'opacity-50' : 'opacity-100'
                  ]"
                  @focus="selectedOptions[q.id] = ''"
                />
              </div>
            </div>
            <div class="flex justify-end gap-2 pt-2">
              <button
                @click="handleClose"
                class="px-4 py-2 text-sm rounded-lg bg-[var(--bg-panel)] text-[var(--text-secondary)] hover:bg-parchment-100"
              >
                跳过
              </button>
              <button
                @click="handleApply"
                :disabled="!hasSelectedAnswers || isProcessing"
                class="px-4 py-2 text-sm rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
              >
                <svg v-if="isProcessing" class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                提交回答
              </button>
            </div>
          </div>

          <!-- 步骤 2：处理中提示 -->
          <div v-else-if="currentStep === 2" class="flex flex-col items-center justify-center py-8 gap-3">
            <svg class="animate-spin h-8 w-8 text-[var(--accent-500)]" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p class="text-sm text-[var(--text-secondary)]">AI 正在根据您的回答修正大纲...</p>
          </div>

          <!-- 步骤 3：审阅修正后的大纲 -->
          <div v-else-if="currentStep === 3" class="flex flex-col gap-4">
            <div v-if="clarificationResult?.clarification_suggestions?.length" class="bg-[var(--bg-panel)] border border-[var(--border-color)] rounded-xl p-4">
              <h4 class="text-sm font-semibold text-[var(--accent-700)] mb-2">AI 的补充建议：</h4>
              <ul class="list-disc list-inside text-sm text-[var(--text-secondary)] space-y-1 ml-2">
                <li v-for="(sugg, i) in clarificationResult.clarification_suggestions" :key="i">
                  {{ sugg }}
                </li>
              </ul>
            </div>

            <div class="flex flex-col gap-2">
              <label class="text-sm font-semibold text-[var(--text-primary)]">
                修正后的大纲
              </label>
              <textarea
                v-model="editableOutline"
                rows="4"
                class="w-full px-3 py-2.5 rounded-lg bg-[var(--bg-canvas)] text-[var(--text-primary)] text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)] resize-none"
                placeholder="修正后的大纲内容..."
              />
              <p class="text-xs text-[var(--text-muted)]">您可以继续编辑，确认后应用到大纲并继续生成。</p>
            </div>

            <div class="flex justify-end gap-2 pt-2">
              <button
                v-if="hasQuestions"
                @click="selectedOptions = {}; customAnswers = {}; editableOutline = clarificationResult?.original_outline || ''"
                class="px-4 py-2 text-sm rounded-lg bg-[var(--bg-panel)] text-[var(--text-secondary)] hover:bg-parchment-100"
              >
                返回修改
              </button>
              <button
                @click="handleClose"
                class="px-4 py-2 text-sm rounded-lg bg-[var(--bg-panel)] text-[var(--text-secondary)] hover:bg-parchment-100"
              >
                取消
              </button>
              <button
                @click="handleConfirm"
                class="px-4 py-2 text-sm rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600"
              >
                确认应用并生成
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
