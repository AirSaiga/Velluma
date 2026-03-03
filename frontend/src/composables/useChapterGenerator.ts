import { ref } from 'vue'
import { generateApi } from './useApi'

export type WorkflowEvent = 
  | 'ASSEMBLING_CONTEXT' 
  | 'DRAFTING' 
  | 'REVIEWING' 
  | 'REFINING' 
  | 'FINAL_TEXT_STREAM' 
  | 'TEXT_CHUNK' 
  | 'DONE'

export interface WorkflowState {
  currentEvent: WorkflowEvent | null
  message: string
  iteration: number
  passed: boolean
  revisionCount: number
}

export function useChapterGenerator() {
  const isGenerating = ref(false)
  const generatedText = ref('')
  const error = ref<string | null>(null)
  const workflowState = ref<WorkflowState>({
    currentEvent: null,
    message: '',
    iteration: 0,
    passed: false,
    revisionCount: 0
  })

  function startGeneration(request: any, onChunk?: (chunk: string) => void, onComplete?: () => void) {
    if (isGenerating.value) {
      return
    }

    isGenerating.value = true
    generatedText.value = ''
    error.value = null
    workflowState.value = {
      currentEvent: null,
      message: '',
      iteration: 0,
      passed: false,
      revisionCount: 0
    }

    generateApi.stream(
      request,
      (chunk) => {
        generatedText.value += chunk
        if (onChunk) onChunk(chunk)
      },
      () => {
        isGenerating.value = false
        if (onComplete) onComplete()
      },
      (err) => {
        error.value = err
        isGenerating.value = false
      }
    )
  }

  function startAgenticGeneration(
    request: any,
    callbacks: {
      onEvent?: (event: string, data: any) => void
      onChunk?: (chunk: string) => void
      onComplete?: (result: any) => void
    }
  ) {
    if (isGenerating.value) {
      return
    }

    isGenerating.value = true
    generatedText.value = ''
    error.value = null
    workflowState.value = {
      currentEvent: null,
      message: '',
      iteration: 0,
      passed: false,
      revisionCount: 0
    }

    generateApi.streamAgentic(request, {
      onEvent: (event, data) => {
        const state = workflowState.value
        
        switch (event) {
          case 'ASSEMBLING_CONTEXT':
            state.currentEvent = 'ASSEMBLING_CONTEXT'
            state.message = data.message || '正在从数据库抽取人物卡与关系网...'
            break
          case 'DRAFTING':
            state.currentEvent = 'DRAFTING'
            state.message = data.message || '主笔 Agent 正在创作初稿...'
            state.iteration = data.iteration || 1
            break
          case 'REVIEWING':
            state.currentEvent = 'REVIEWING'
            state.message = data.message || '审阅 Agent 正在进行逻辑校验和 OOC 排查...'
            state.iteration = data.iteration || state.iteration
            break
          case 'REFINING':
            state.currentEvent = 'REFINING'
            state.message = data.message || '发现逻辑遗漏，正在通知责编重写...'
            state.iteration = data.iteration || state.iteration + 1
            break
          case 'FINAL_TEXT_STREAM':
            state.currentEvent = 'FINAL_TEXT_STREAM'
            state.message = data.message || '正在输出最终文本...'
            state.passed = data.passed
            break
          case 'TEXT_CHUNK':
            state.currentEvent = 'TEXT_CHUNK'
            break
          case 'DONE':
            state.currentEvent = 'DONE'
            state.passed = data.passed
            state.revisionCount = data.revision_count || data.iterations || 0
            state.message = data.passed ? '生成完成！' : '已达到最大迭代次数，生成完成'
            break
        }
        
        callbacks.onEvent?.(event, data)
      },
      onChunk: (chunk) => {
        generatedText.value += chunk
        callbacks.onChunk?.(chunk)
      },
      onDone: (result) => {
        workflowState.value.passed = result.passed
        workflowState.value.revisionCount = result.revision_count
        isGenerating.value = false
        callbacks.onComplete?.(result)
      },
      onError: (err) => {
        error.value = err
        isGenerating.value = false
      }
    })
  }

  function reset() {
    isGenerating.value = false
    generatedText.value = ''
    error.value = null
    workflowState.value = {
      currentEvent: null,
      message: '',
      iteration: 0,
      passed: false,
      revisionCount: 0
    }
  }

  return {
    isGenerating,
    generatedText,
    error,
    workflowState,
    startGeneration,
    startAgenticGeneration,
    reset
  }
}
