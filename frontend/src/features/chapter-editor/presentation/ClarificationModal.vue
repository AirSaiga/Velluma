<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  show: boolean
  clarificationResult: {
    is_ambiguous: boolean
    identified_issues?: string[]
    clarification_suggestions?: string[]
    refined_text?: string
  } | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', newOutlineText: string): void
}>()

const editableOutline = ref('')

watch(() => props.show, (newVal) => {
  if (newVal && props.clarificationResult?.refined_text) {
    editableOutline.value = props.clarificationResult.refined_text
  }
})

function handleClose() {
  emit('close')
}

function handleApply() {
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
      <div class="bg-[var(--bg-color)] rounded-xl shadow-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        
        <!-- Header -->
        <div class="px-6 py-4 border-b border-[var(--border-color)] flex justify-between items-center bg-parchment-100">
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
          
          <div class="bg-amber-50/50 border border-amber-100 rounded-lg p-4">
            <h4 class="text-sm font-semibold text-amber-800 mb-2">发现信息空白：</h4>
            <ul class="list-disc list-inside text-sm text-gray-700 space-y-1 ml-2">
              <li v-for="(issue, i) in clarificationResult?.identified_issues" :key="i">
                {{ issue }}
              </li>
            </ul>
          </div>

          <div class="bg-blue-50/50 border border-blue-100 rounded-lg p-4">
            <h4 class="text-sm font-semibold text-blue-800 mb-2">AI 的补充建议：</h4>
            <ul class="list-disc list-inside text-sm text-gray-700 space-y-1 ml-2">
              <li v-for="(sugg, i) in clarificationResult?.clarification_suggestions" :key="i">
                {{ sugg }}
              </li>
            </ul>
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-sm font-semibold text-gray-800">修正后的大纲 (您可以继续修改)：</label>
            <textarea
              v-model="editableOutline"
              class="w-full h-40 p-3 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent custom-scrollbar resize-none"
              placeholder="在此处补充细节..."
            ></textarea>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-[var(--border-color)] bg-gray-50 flex justify-end gap-3">
          <button 
            @click="handleClose" 
            class="px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            忽略建议并继续
          </button>
          <button 
            @click="handleApply" 
            class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 shadow-sm transition-colors flex items-center gap-2"
          >
            应用并生成节拍
          </button>
        </div>

      </div>
    </div>
  </Teleport>
</template>
