import { ref } from 'vue'
import { generateApi } from '../services/api'
import type { SketchSegment, SketchEmotionPoint } from '../types'

export type WorkflowEvent =
  | 'ASSEMBLING_CONTEXT'
  | 'PLANNING'
  | 'DRAFTING'
  | 'SCENE_INTENT'
  | 'STITCHING'
  | 'REVIEWING'
  | 'REFINING'
  | 'FORMATTING'
  | 'METRICS'
  | 'FINAL_TEXT_STREAM'
  | 'TEXT_CHUNK'
  | 'DONE'
  // CP2.5f：CP2.4 sketch 先行模式事件
  | 'SKETCH_GENERATION'
  | 'SKETCH_DONE'
  // CP3.4：双层审计实时事件（蓝图 §4.8 + 病灶 9）
  | 'AUDIT_START'
  | 'AUDIT_DONE'
  | 'DEGRADED'

export interface WorkflowState {
  currentEvent: WorkflowEvent | null
  message: string
  iteration: number
  passed: boolean
  revisionCount: number
  // CP4.2：速写骨架分段（SKETCH_DONE 捕获，供 SketchEditorPanel 展示）
  sketchSegments?: SketchSegment[]
  sketchEmotionArc?: SketchEmotionPoint[]
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
  let abortController: AbortController | null = null

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
      onError?: (err: string) => void
    },
    endpoint = '/generate_chapter_agentic'
  ) {
    if (isGenerating.value) {
      return
    }

    abortController = new AbortController()
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
          case 'PLANNING':
            state.currentEvent = 'PLANNING'
            state.message = data.message || 'Planner 正在拆分章节 beats...'
            state.iteration = data.iteration || 1
            break
          case 'DRAFTING':
            state.currentEvent = 'DRAFTING'
            state.message = data.message || '主笔 Agent 正在创作初稿...'
            state.iteration = data.iteration || 1
            break
          case 'SCENE_INTENT':
            state.currentEvent = 'SCENE_INTENT'
            state.message = data.message || '正在计算 SceneIntent...'
            state.iteration = data.iteration || state.iteration
            break
          // CP4.2：sketch 先行事件 + segments 捕获（蓝图 §4.5）
          case 'SKETCH_GENERATION':
            state.currentEvent = 'SKETCH_GENERATION'
            state.message = data.message || '生成速写骨架...'
            break
          case 'SKETCH_DONE':
            state.message = data.message || '速写骨架完成'
            // 捕获 segments + emotion_arc（CP4.2 新增 payload）
            if (Array.isArray(data.segments)) {
              state.sketchSegments = data.segments
            }
            if (Array.isArray(data.emotion_arc)) {
              state.sketchEmotionArc = data.emotion_arc
            }
            break
          case 'STITCHING':
            state.currentEvent = 'STITCHING'
            state.message = data.message || '统稿 Agent 正在拼接 chunks...'
            state.iteration = data.iteration || state.iteration
            break
          case 'REVIEWING':
            state.currentEvent = 'REVIEWING'
            state.message = data.message || '审阅 Agent 正在进行逻辑校验和 OOC 排查...'
            state.iteration = data.iteration || state.iteration
            break
          // CP3.4：双层审计实时事件
          case 'AUDIT_START':
            state.currentEvent = 'REVIEWING'  // 复用 REVIEWING 阶段显示（审计是 REVIEWING 的子步骤）
            state.message = data.message || '双层审计中（代码级 + LLM 级）...'
            break
          case 'AUDIT_DONE':
            state.message = data.message || '审计完成'
            // verdict/findings_count 在 data 中，UI 可按需展示
            break
          case 'DEGRADED':
            state.message = data.message || '阶段降级（已兜底）'
            break
          case 'REFINING':
            state.currentEvent = 'REFINING'
            state.message = data.message || '发现逻辑遗漏，正在通知责编重写...'
            state.iteration = data.iteration || state.iteration + 1
            break
          case 'FORMATTING':
            state.currentEvent = 'FORMATTING'
            state.message = data.message || '正在进行最终段落排版...'
            state.iteration = data.iteration || state.iteration
            break
          case 'METRICS':
            state.message = data.label ? `耗时统计更新: ${data.label}` : state.message
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
        // 双轨模式返回 revision_count，普通模式可能返回 iterations
        workflowState.value.revisionCount = result.revision_count ?? result.iterations ?? 0
        isGenerating.value = false
        abortController = null
        callbacks.onComplete?.(result)
      },
      onError: (err) => {
        error.value = err
        isGenerating.value = false
        abortController = null
        callbacks.onError?.(err)
      }
    }, endpoint, false, abortController.signal)
  }

  function cancelGeneration() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    isGenerating.value = false
    workflowState.value.currentEvent = null
    workflowState.value.message = ''
  }

  async function optimizeChapter(request: any) {
    if (isGenerating.value) return
    
    isGenerating.value = true
    error.value = null
    workflowState.value = {
      currentEvent: 'REFINING' as any,
      message: '正在根据您的反馈进行优化...',
      iteration: 0,
      passed: false,
      revisionCount: 0
    }
    
    try {
      const result = await generateApi.optimize(request)
      return result.optimized_content
    } catch (err: any) {
      error.value = err.message || 'Optimization failed'
      throw err
    } finally {
      isGenerating.value = false
      workflowState.value = {
        currentEvent: 'DONE' as any,
        message: '优化完成',
        iteration: 0,
        passed: true,
        revisionCount: 0
      }
    }
  }

  function reset() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
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
    cancelGeneration,
    optimizeChapter,
    reset
  }
}
