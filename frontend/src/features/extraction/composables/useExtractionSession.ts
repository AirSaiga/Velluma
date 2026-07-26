/**
 * 正文逆向提取会话组合函数（状态机驱动）。
 *
 * 职责：
 * - 持有提取流程的状态机（idle → analyzing → reviewing → committing → done）
 * - 管理 analyze / confirm 两阶段的 SSE 调用
 * - 暴露响应式状态供 Modal 容器渲染
 *
 * 状态流转：
 *   idle → analyzing（LLM 提取中）
 *        → reviewing（提取完成，等用户确认）
 *        → committing（用户确认，落库中）
 *        → done（完成）
 */
import { ref, computed } from 'vue'
import { extractionApi } from '../../../services/api/domain/extraction.api'
import type {
  ExtractionResult,
  ExtractionCommitStats,
  ExtractedCharacter,
  ExtractedRelationship,
  ExtractedLocation,
  ExtractedAsset,
  ExtractedForeshadow,
} from '../../../services/api/domain/extraction.api'

export type ExtractionStep = 'idle' | 'analyzing' | 'reviewing' | 'committing' | 'done'

/** 用户确认的提取子集（各类型的保留条目） */
export interface ConfirmedExtraction {
  characters: ExtractedCharacter[]
  relationships: ExtractedRelationship[]
  locations: ExtractedLocation[]
  assets: ExtractedAsset[]
  foreshadows: ExtractedForeshadow[]
}

export function useExtractionSession() {
  /** 当前步骤 */
  const step = ref<ExtractionStep>('idle')
  /** analyze 返回的完整结果 */
  const result = ref<ExtractionResult | null>(null)
  /** run_id（confirm 阶段引用） */
  const runId = ref<string | null>(null)
  /** confirm 阶段每步进度 */
  const progressSteps = ref<{ step: string; created: number }[]>([])
  /** confirm 完成后的创建计数 */
  const commitStats = ref<ExtractionCommitStats | null>(null)
  /** 错误信息 */
  const error = ref<string | null>(null)
  /** AbortController（用户取消） */
  let abortController: AbortController | null = null

  /** 是否进行中 */
  const isProcessing = computed(
    () => step.value === 'analyzing' || step.value === 'committing',
  )

  /**
   * 第一阶段：启动 LLM 分析。
   *
   * Args:
   *   chapterId: 要分析的章节 ID
   */
  async function startAnalyze(chapterId: string): Promise<void> {
    step.value = 'analyzing'
    error.value = null
    result.value = null
    runId.value = null
    abortController = new AbortController()

    await extractionApi.analyze(
      chapterId,
      {
        onResult: (res) => {
          result.value = res
          runId.value = res.run_id
          step.value = 'reviewing'
        },
        onError: (msg) => {
          error.value = msg
          step.value = 'idle'
        },
      },
      abortController.signal,
    )
  }

  /**
   * 第二阶段：确认入库。
   *
   * Args:
   *   chapterId: 章节 ID
   *   confirmed: 用户勾选确认的子集
   */
  async function startConfirm(
    chapterId: string,
    confirmed: ConfirmedExtraction,
  ): Promise<void> {
    if (!runId.value) return
    step.value = 'committing'
    error.value = null
    progressSteps.value = []
    commitStats.value = null
    abortController = new AbortController()

    await extractionApi.confirm(
      chapterId,
      { run_id: runId.value, confirmed },
      {
        onProgress: (progStep, created) => {
          progressSteps.value.push({ step: progStep, created })
        },
        onComplete: (stats) => {
          commitStats.value = stats
          step.value = 'done'
        },
        onError: (msg) => {
          error.value = msg
          step.value = 'reviewing'
        },
      },
      abortController.signal,
    )
  }

  /** 取消当前操作 */
  function cancel(): void {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    reset()
  }

  /** 重置全部状态 */
  function reset(): void {
    step.value = 'idle'
    result.value = null
    runId.value = null
    progressSteps.value = []
    commitStats.value = null
    error.value = null
  }

  /** 回到预览态（从 done 重试） */
  function backToReview(): void {
    step.value = 'reviewing'
    progressSteps.value = []
    commitStats.value = null
  }

  return {
    // 状态
    step,
    result,
    runId,
    progressSteps,
    commitStats,
    error,
    isProcessing,
    // 操作
    startAnalyze,
    startConfirm,
    cancel,
    reset,
    backToReview,
  }
}
