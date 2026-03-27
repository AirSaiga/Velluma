<template>
  <div class="h-full flex flex-col p-4 bg-parchment-50/50 backdrop-blur-sm rounded-xl overflow-hidden ring-1 ring-[var(--border-color)]/60">
    <div class="flex items-center justify-between mb-4 flex-shrink-0">
      <h3 class="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
        <span>📝</span>
        主编指导意见
      </h3>
      <div class="flex items-center gap-2">
        <div v-if="loading" class="flex items-center gap-2 text-xs text-accent-600">
          <div class="w-3 h-3 rounded-full border-2 border-accent-500 border-t-transparent animate-spin"></div>
          分析中...
        </div>
        <button
          v-if="result"
          @click="emit('close-critique')"
          class="p-1 rounded hover:bg-ink-100 text-ink-400 hover:text-ink-600 transition-colors"
          title="关闭指导"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </div>
    
    <div class="flex-1 overflow-y-auto min-h-0 pr-2 custom-scrollbar">
      <div v-if="loading && !result" class="h-full flex flex-col items-center justify-center text-center space-y-3 p-8">
        <div class="w-12 h-12 rounded-full bg-accent-50 flex items-center justify-center">
          <svg class="w-6 h-6 text-accent-500 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        </div>
        <div class="space-y-1">
          <p class="text-sm font-medium text-accent-900">正在深度阅读您的章节...</p>
          <p class="text-xs text-accent-600/70">AI主编正在分析剧情逻辑、节奏与人物表现</p>
        </div>
      </div>
      
      <div v-else-if="result" class="space-y-6">
        <!-- 总体评价 -->
        <div v-if="result.overall_praise" class="bg-accent-50/50 rounded-xl p-4 border border-accent-100">
          <h4 class="text-xs font-semibold text-accent-900 mb-2 flex items-center gap-1.5">
            <span>🌟</span>
            总体亮点
          </h4>
          <p class="text-xs text-accent-800/80 leading-relaxed whitespace-pre-line">
            {{ result.overall_praise }}
          </p>
        </div>

        <!-- 详细评论 -->
        <div v-if="result.comments && result.comments.length > 0" class="space-y-3">
          <div
            v-for="(comment, index) in result.comments"
            :key="index"
            :class="[
              'bg-parchment-50 rounded-xl ring-1 ring-[var(--border-color)]/60 p-3 shadow-sm transition-all duration-200 hover:shadow-md',
              comment.exact_quote
                ? 'cursor-pointer hover:ring-accent-400 hover:bg-accent-50/30'
                : ''
            ]"
            @click="handleCommentClick(comment)"
          >
            <div class="flex items-center justify-between mb-2">
              <span class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-ink-100 text-ink-600">
                {{ comment.type || '一般建议' }}
              </span>
              <span v-if="comment.reader_feeling" class="text-[10px] text-ink-400">
                {{ comment.reader_feeling }}
              </span>
            </div>
            
            <div v-if="comment.exact_quote" class="text-xs text-[var(--text-primary)] leading-relaxed mb-2">
              <span class="font-medium text-[var(--text-secondary)]">原句：</span>
              <span class="bg-yellow-50 px-1 rounded border-l-2 border-accent-400 pl-3 italic">"{{ comment.exact_quote }}"</span>
            </div>
            
            <div class="text-xs text-[var(--text-secondary)] leading-relaxed">
              <span class="font-medium text-accent-600">建议：</span>
              {{ comment.suggestion }}
            </div>
          </div>
        </div>
        
        <div v-if="(!result.comments || result.comments.length === 0) && !result.overall_praise" class="text-center text-[var(--text-muted)] text-xs py-4">
          虽然分析已完成，但似乎没有具体的修改建议。
        </div>
      </div>
      
      <div v-else class="h-full flex flex-col items-center justify-center text-[var(--text-muted)] text-xs p-8 text-center">
        <div class="w-12 h-12 rounded-full bg-ink-50 flex items-center justify-center mb-3">
          <span class="text-2xl">🧐</span>
        </div>
        <p>暂无指导意见</p>
        <p class="mt-1 opacity-70">点击编辑器上方的"获取主编指导"按钮开始分析</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  result: any
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'jump-to-critique', comment: any): void
  (e: 'close-critique'): void
}>()

const handleCommentClick = (comment: any) => {
  if (comment.exact_quote) {
    emit('jump-to-critique', comment)
  }
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: rgba(120, 113, 108, 0.3);
  border-radius: 20px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: rgba(120, 113, 108, 0.5);
}
</style>
