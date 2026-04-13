<script setup lang="ts">
import { ref, watch, computed } from 'vue'

export interface ClarifyingQuestion {
  id: string
  question: string
  options: {
    label: string
    value: string
  }[]
}

const props = defineProps<{
  show: boolean
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

const editableOutline = ref('')
const selectedOptions = ref<Record<string, string>>({})
const customAnswers = ref<Record<string, string>>({})

// 是否有修正后的大纲（第二轮返回）
const hasRefinedText = computed(() => {
  return !!props.clarificationResult?.refined_text?.trim()
})

// 监听弹窗显示状态变化
watch(() => props.show, (newVal) => {
  if (newVal) {
    updateEditableOutline()
    // 每次打开弹窗重置选择状态（仅在第一轮时）
    if (!props.clarificationResult?.refined_text?.trim()) {
      selectedOptions.value = {}
      customAnswers.value = {}
    }
  }
})

// 监听clarificationResult变化
watch(() => props.clarificationResult, () => {
  if (props.show) {
    updateEditableOutline()
  }
}, { deep: true })

// 更新可编辑大纲
function updateEditableOutline() {
  // 如果有修正后的大纲（第二轮），则显示；否则显示原始大纲或空
  if (props.clarificationResult?.refined_text?.trim()) {
    editableOutline.value = props.clarificationResult.refined_text
  } else {
    // 第一轮：显示原始大纲或空
    // 尝试从clarificationResult中获取原始大纲，如果没有则显示空
    editableOutline.value = props.clarificationResult?.original_outline || ''
  }
}

function handleClose() {
  emit('close')
}

function handleOptionSelect(qId: string, value: string) {
  if (selectedOptions.value[qId] === value) {
    // 再次点击取消选中
    selectedOptions.value[qId] = ''
  } else {
    selectedOptions.value[qId] = value
    // 选中预设选项时，清空当前问题的自定义回答
    customAnswers.value[qId] = ''
  }
}

// 是否已选择答案
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
  // 收集用户的回答
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

  // 发送第二轮请求生成修正大纲
  if (answers.length > 0) {
    emit('submit-answers', answers, editableOutline.value)
  }
}

function handleConfirm() {
  // 第二轮：确认修正后的大纲并继续生成
  emit('apply', editableOutline.value)
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-[100] flex items-center justify-center bg-black/45 p-4"
      @click.self="handleClose"
    >
      <div class="bg-white rounded-xl shadow-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        
        <!-- Header -->
        <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center bg-amber-50/50">
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </div>
            <h3 class="text-lg font-bold text-gray-800">AI 意图澄清建议</h3>
          </div>
          <button @click="handleClose" class="text-gray-400 hover:text-gray-600 transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <!-- Body -->
        <div class="p-6 overflow-y-auto custom-scrollbar flex flex-col gap-6">
          
          <div v-if="clarificationResult?.identified_issues?.length" class="bg-amber-50/50 border border-amber-100 rounded-lg p-4">
            <h4 class="text-sm font-semibold text-amber-800 mb-2">发现信息空白：</h4>
            <ul class="list-disc list-inside text-sm text-gray-700 space-y-1 ml-2">
              <li v-for="(issue, i) in clarificationResult.identified_issues" :key="i">
                {{ issue }}
              </li>
            </ul>
          </div>

          <!-- 交互式问题区域 -->
          <div v-if="clarificationResult?.clarifying_questions?.length" class="flex flex-col gap-4">
            <h4 class="text-sm font-semibold text-blue-800">请补充以下细节：</h4>
            <div 
              v-for="q in clarificationResult.clarifying_questions" 
              :key="q.id"
              class="bg-blue-50/30 border border-blue-100 rounded-lg p-4 flex flex-col gap-3"
            >
              <p class="text-sm font-medium text-gray-800">{{ q.question }}</p>
              
              <!-- 选项列表 -->
              <div v-if="q.options?.length" class="flex flex-col gap-2">
                <button
                  v-for="(opt, i) in q.options"
                  :key="i"
                  @click="handleOptionSelect(q.id, opt.value)"
                  class="text-left px-3 py-2 rounded-md border text-sm transition-colors duration-200"
                  :class="[
                    selectedOptions[q.id] === opt.value 
                      ? 'bg-blue-100 border-blue-300 text-blue-800' 
                      : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
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
                  class="w-full px-3 py-2 text-sm bg-white border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow"
                  :class="[
                    customAnswers[q.id] ? 'border-blue-300' : 'border-gray-200',
                    selectedOptions[q.id] ? 'opacity-50' : 'opacity-100'
                  ]"
                  @focus="selectedOptions[q.id] = ''"
                />
              </div>
            </div>
          </div>

          <!-- 保留原有的补充建议展示 -->
          <div v-else-if="clarificationResult?.clarification_suggestions?.length" class="bg-blue-50/50 border border-blue-100 rounded-lg p-4">
            <h4 class="text-sm font-semibold text-blue-800 mb-2">AI 的补充建议：</h4>
            <ul class="list-disc list-inside text-sm text-gray-700 space-y-1 ml-2">
              <li v-for="(sugg, i) in clarificationResult.clarification_suggestions" :key="i">
                {{ sugg }}
              </li>
            </ul>
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-sm font-semibold text-gray-800">
              {{ hasRefinedText ? '修正后的大纲 (您可以继续修改)：' : '当前大纲 (选择选项后将生成修正版本)：' }}
            </label>
            <textarea
              v-model="editableOutline"
              :disabled="!hasRefinedText"
              :class="[
                'w-full h-40 p-3 border rounded-lg text-sm custom-scrollbar resize-none',
                hasRefinedText 
                  ? 'bg-white border-gray-200 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent' 
                  : 'bg-gray-100 border-gray-200 text-gray-700 cursor-not-allowed'
              ]"
              :placeholder="editableOutline ? '' : (hasRefinedText ? '在此处补充细节...' : '请先选择上方的选项，系统将基于您的选择生成修正大纲')"
            ></textarea>
            <p v-if="!hasRefinedText" class="text-xs text-amber-600">
              第 1 步：选择上方的选项，然后点击"生成修正大纲"
            </p>
            <p v-else class="text-xs text-green-600">
              第 2 步：您可以继续编辑修正后的大纲，然后点击"确认并生成节拍"
            </p>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-gray-200 bg-gray-50 flex justify-end gap-3">
          <button 
            @click="handleClose" 
            class="px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            {{ hasRefinedText ? '取消' : '忽略建议并继续' }}
          </button>
          <button 
            v-if="!hasRefinedText"
            @click="handleApply" 
            :disabled="!hasSelectedAnswers"
            :class="[
              'px-4 py-2 text-sm font-medium rounded-lg shadow-sm transition-colors flex items-center gap-2',
              hasSelectedAnswers 
                ? 'text-white bg-blue-600 hover:bg-blue-700' 
                : 'text-gray-400 bg-gray-300 cursor-not-allowed'
            ]"
          >
            生成修正大纲
          </button>
          <button 
            v-else
            @click="handleConfirm" 
            class="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 shadow-sm transition-colors flex items-center gap-2"
          >
            确认并生成节拍
          </button>
        </div>

      </div>
    </div>
  </Teleport>
</template>
