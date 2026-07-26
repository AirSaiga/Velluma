/**
 * 正文逆向提取 API（两阶段 SSE，仿 refineryApi）。
 *
 * 职责：
 * - analyze：触发 LLM 提取，接收 EXTRACTION_RESULT 事件（带 run_id + 提取结果）
 * - confirm：凭 run_id 提交用户确认的子集，接收落库进度 + COMPLETE
 *
 * 设计依据：routes/extraction.py 的两阶段 SSE 模式。
 */
import { streamSse } from '../stream/sse'

// ============================================================
// 类型定义
// ============================================================

/** 提取出的角色条目 */
export interface ExtractedCharacter {
  name: string
  description: string
  role_type: string
  importance_level: number
  aliases: string[]
}

/** 提取出的关系条目 */
export interface ExtractedRelationship {
  source_name: string
  target_name: string
  relation_type: string
  affinity_score: number
  description: string
}

/** 提取出的地点条目 */
export interface ExtractedLocation {
  name: string
  description: string
}

/** 提取出的资产条目 */
export interface ExtractedAsset {
  name: string
  description: string
  importance_level: number
}

/** 提取出的伏笔条目 */
export interface ExtractedForeshadow {
  ledger_key: string
  content: string
  entry_type: string
  status: string
  strength: number
}

/** analyze 阶段返回的完整提取结果 */
export interface ExtractionResult {
  run_id: string
  characters: ExtractedCharacter[]
  relationships: ExtractedRelationship[]
  locations: ExtractedLocation[]
  assets: ExtractedAsset[]
  foreshadows: ExtractedForeshadow[]
  stats: {
    characters: number
    relationships: number
    locations: number
    assets: number
    foreshadows: number
  }
}

/** confirm 阶段的落库计数 */
export interface ExtractionCommitStats {
  characters: number
  relationships: number
  locations: number
  assets: number
  foreshadows: number
  memories: number
}

/** confirm 请求体 */
export interface ConfirmExtractionParams {
  run_id: string
  confirmed: {
    characters: ExtractedCharacter[]
    relationships: ExtractedRelationship[]
    locations: ExtractedLocation[]
    assets: ExtractedAsset[]
    foreshadows: ExtractedForeshadow[]
  }
}

/** analyze 阶段回调 */
export interface AnalyzeCallbacks {
  onStage?: (stage: string) => void
  onResult?: (result: ExtractionResult) => void
  onError?: (message: string) => void
}

/** confirm 阶段回调 */
export interface ConfirmCallbacks {
  onStage?: (stage: string) => void
  onProgress?: (step: string, created: number) => void
  onComplete?: (stats: ExtractionCommitStats) => void
  onError?: (message: string) => void
}

// ============================================================
// API
// ============================================================

export const extractionApi = {
  /**
   * 第一阶段：LLM 分析正文（SSE）。
   *
   * 事件序列：EXTRACTION_STAGE("analyzing") → EXTRACTION_RESULT({run_id, ...})
   */
  async analyze(
    chapterId: string,
    callbacks: AnalyzeCallbacks,
    signal?: AbortSignal,
  ): Promise<void> {
    let receivedResult = false
    await streamSse(
      `/chapters/${chapterId}/extraction/analyze`,
      {},
      {
        onPayload: (payload: any) => {
          if (payload.error) {
            callbacks.onError?.(payload.error)
            return true
          }
          if (payload.event === 'EXTRACTION_STAGE') {
            callbacks.onStage?.(payload.stage || '')
            return false
          }
          // EXTRACTION_RESULT 帧带 run_id（无 event 字段，直接是结果）
          if (payload.run_id) {
            receivedResult = true
            callbacks.onResult?.(payload as ExtractionResult)
            return false
          }
          return false
        },
        onError: (msg: string) => callbacks.onError?.(msg),
        tolerateIncompleteWhenHasContent: true,
      },
      signal,
    )
    if (!receivedResult) {
      callbacks.onError?.('分析未返回提取结果')
    }
  },

  /**
   * 第二阶段：确认入库（SSE）。
   *
   * 事件序列：EXTRACTION_STAGE("committing") → EXTRACTION_PROGRESS×N → COMPLETE
   */
  async confirm(
    chapterId: string,
    params: ConfirmExtractionParams,
    callbacks: ConfirmCallbacks,
    signal?: AbortSignal,
  ): Promise<void> {
    let receivedComplete = false
    await streamSse(
      `/chapters/${chapterId}/extraction/confirm`,
      params,
      {
        onPayload: (payload: any) => {
          if (payload.error) {
            callbacks.onError?.(payload.error)
            return true
          }
          if (payload.event === 'EXTRACTION_STAGE') {
            callbacks.onStage?.(payload.stage || '')
            return false
          }
          if (payload.event === 'EXTRACTION_PROGRESS') {
            callbacks.onProgress?.(payload.step || '', payload.created || 0)
            return false
          }
          if (payload.event === 'COMPLETE') {
            receivedComplete = true
            callbacks.onComplete?.(payload.created as ExtractionCommitStats)
            return true
          }
          return false
        },
        onError: (msg: string) => callbacks.onError?.(msg),
        tolerateIncompleteWhenHasContent: true,
      },
      signal,
    )
    if (!receivedComplete) {
      callbacks.onError?.('入库未完成')
    }
  },
}
