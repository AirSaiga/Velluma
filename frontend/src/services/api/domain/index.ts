import { streamSse } from '../stream'
import { requestJson, requestRaw } from '../transport'

export const bookApi = {
  getAll: () => requestJson('/books'),
  get: (id: string) => requestJson(`/books/${id}`),
  create: (data: any) => requestJson('/books', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => requestJson(`/books/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => requestJson(`/books/${id}`, { method: 'DELETE' }),
  getWorldview: (id: string) => requestJson(`/books/${id}/worldview`),
  updateWorldview: (id: string, data: any) =>
    requestJson(`/books/${id}/worldview`, { method: 'PATCH', body: JSON.stringify(data) }),
  getGoldenSnippets: (id: string) => requestJson(`/books/${id}/golden-snippets`),
  updateGoldenSnippets: (id: string, data: string[]) =>
    requestJson(`/books/${id}/golden-snippets`, { method: 'PUT', body: JSON.stringify({ golden_snippets: data }) }),
  getStyleBlacklist: (id: string) => requestJson(`/books/${id}/style-blacklist`),
  updateStyleBlacklist: (id: string, data: string[]) =>
    requestJson(`/books/${id}/style-blacklist`, { method: 'PUT', body: JSON.stringify({ style_blacklist: data }) }),
}

export const characterApi = {
  getAll: (bookId: string) => {
    const url = bookId ? `/books/${bookId}/characters` : '/characters'
    return requestJson(url)
  },
  get: (id: string) => requestJson(`/characters/${id}`),
  create: (data: any) => requestJson('/characters', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => requestJson(`/characters/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => requestJson(`/characters/${id}`, { method: 'DELETE' }),
  updateDynamicState: (id: string, data: any) =>
    requestJson(`/characters/${id}/update-dynamic-state`, { method: 'POST', body: JSON.stringify(data) })
}

export const chapterApi = {
  getAll: (bookId: string) => {
    const url = bookId ? `/books/${bookId}/chapters` : '/chapters'
    return requestJson(url)
  },
  get: (id: string) => requestJson(`/chapters/${id}`),
  create: (data: any) => requestJson(`/books/${data.book_id}/chapters`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => requestJson(`/chapters/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => requestJson(`/chapters/${id}`, { method: 'DELETE' }),
  getEntities: (chapterId: string) => requestJson(`/chapters/${chapterId}/entities`),
  updateEntities: (chapterId: string, entityIds: any) =>
    requestJson(`/chapters/${chapterId}/entities`, { method: 'PUT', body: JSON.stringify(entityIds) }),
  publish: (chapterId: string, data: any) =>
    requestJson(`/chapters/${chapterId}/publish`, { method: 'PATCH', body: JSON.stringify(data || {}) }),
}

export const relationshipApi = {
  getAll: (bookId: string) => {
    const url = bookId ? `/relationships?book_id=${bookId}` : '/relationships'
    return requestJson(url)
  },
  create: (data: any) => requestJson('/relationships', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => requestJson(`/relationships/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => requestJson(`/relationships/${id}`, { method: 'DELETE' })
}

export const mapApi = {
  getLocations(bookId: string) {
    return requestJson(`/books/${bookId}/locations`)
  },
  createLocation(bookId: string, data: any) {
    return requestJson(`/books/${bookId}/locations`, {
      method: 'POST',
      body: JSON.stringify({ ...data, book_id: bookId })
    })
  },
  updateLocation(id: string, data: any) {
    return requestJson(`/locations/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    })
  },
  deleteLocation(id: string) {
    return requestJson(`/locations/${id}`, {
      method: 'DELETE'
    })
  },
  getChapterLocations(chapterId: string) {
    return requestJson(`/chapters/${chapterId}/locations`)
  },
  addLocationToChapter(chapterId: string, locationId: string) {
    return requestJson(`/chapters/${chapterId}/locations`, {
      method: 'POST',
      body: JSON.stringify({ location_id: locationId })
    })
  },
  removeLocationFromChapter(chapterId: string, locationId: string) {
    return requestJson(`/chapters/${chapterId}/locations/${locationId}`, {
      method: 'DELETE'
    })
  }
}

export const generateApi = {
  optimizeSelection: async (data: any) => {
    const response = await requestRaw('/optimize_selection', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`优化请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  },

  formatText: async (data: { text: string }) => {
    const response = await requestRaw('/format_text', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`格式整理请求失败: ${response.status} ${response.statusText}`)
    }

    return await response.json()
  },

  generateInspiration: async (data: {
    book_id: string
    chapter_id: string
    chapter_title?: string
    current_context_snippet: string
    active_character_ids: string[]
    author_intent?: string
  }) => {
    const response = await requestRaw('/generate_inspiration', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`点子启发请求失败: ${response.status} ${response.statusText}`)
    }

    return await response.json()
  },
}

// ============================================================
// 模型设置（设置面板）
// ============================================================

/** LLM profile（reasoning / creative / wash），api_key 永远为掩码形式 */
export interface LLMProfileConfig {
  provider: string
  api_key_masked: string
  has_api_key: boolean
  base_url: string
  default_base_url: string
  model: string
  enabled: boolean
  effort: string
  /** 仅 wash 槽返回：是否已配置独立洗涤模型（false = 跟随创意模型） */
  configured?: boolean
}

export interface ModelConfig {
  llm: {
    reasoning: LLMProfileConfig
    creative: LLMProfileConfig
    wash: LLMProfileConfig
  }
  embedding: {
    api_key_masked: string
    has_api_key: boolean
    model: string
    dimensions: number
  }
  proxy: {
    enabled: boolean
    url: string
  }
}

/** 更新载荷：api_key 留空表示保持不变 */
export interface ModelConfigUpdatePayload {
  reasoning?: Partial<Pick<LLMProfileConfig, 'provider' | 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  creative?: Partial<Pick<LLMProfileConfig, 'provider' | 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  wash?: Partial<Pick<LLMProfileConfig, 'provider' | 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  embedding?: { api_key?: string; model?: string; dimensions?: number }
  proxy?: { enabled: boolean; url: string }
}

export const systemApi = {
  /**
   * 获取模型配置（LLM / Embedding / 代理）
   * 后端从 model_config.json 读取，API Key 以掩码返回
   */
  getModelConfig: async (): Promise<ModelConfig> => {
    return requestJson('/system/model-config')
  },

  /**
   * 保存模型配置（写回 model_config.json）
   * LLM/代理保存后立即生效；embedding 维度变更需重启后端且会重建向量列
   */
  updateModelConfig: async (payload: ModelConfigUpdatePayload): Promise<ModelConfig> => {
    return requestJson('/system/model-config', {
      method: 'PUT',
      body: JSON.stringify(payload)
    })
  },

  /**
   * 测试模型连接（V4.1: 后端从 model_config.json 读取配置）
   * @returns 测试结果
   */
  testModel: async (): Promise<{
    success: boolean
    message: string
    model_info?: {
      reasoning_model?: string
      creative_model?: string
      reasoning_provider?: string
      creative_provider?: string
      reasoning_success?: boolean
      creative_success?: boolean
    }
    reasoning_supported?: boolean
    reasoning_message?: string
    response_time_ms?: number
  }> => {
    return requestJson('/system/test-model', {
      method: 'POST',
      body: JSON.stringify({})
    })
  }
}

// ============================================================
// CP2.5a 新增：合并闸门 / 文风体系 / 成本报告 API
// ============================================================

import type {
  StyleCard,
  StyleExtractResponse,
  AuthorSample,
  AuthorSampleSearchHit,
  CostReport,
  QualityReport,
} from '../../../types'

/**
 * 文风体系 API（蓝图 §4.4 + §5.1 + §6.2）。
 */
export const styleApi = {
  /** 获取生效的文风卡（章级覆盖优先，回退书级）。 */
  get: async (bookId: string, chapterId?: string): Promise<StyleCard | null> => {
    const query = chapterId ? `?chapter_id=${chapterId}` : ''
    return requestJson(`/books/${bookId}/style-card${query}`)
  },

  /** 创建/更新书级或章级文风卡。 */
  upsert: async (bookId: string, payload: Partial<StyleCard>): Promise<StyleCard> => {
    return requestJson(`/books/${bookId}/style-card`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },

  /** 从作者样本提炼文风画像（Match My Style）。 */
  extract: async (
    bookId: string,
    samples: string[],
    genre?: string,
  ): Promise<StyleExtractResponse> => {
    return requestJson(
      `/books/${bookId}/style-card/extract`,
      {
        method: 'POST',
        body: JSON.stringify({ samples, genre }),
      },
      300000,  // 5 分钟超时
    )
  },

  /** 列出书籍的作者样本。 */
  listSamples: async (
    bookId: string,
    sceneType?: string,
  ): Promise<AuthorSample[]> => {
    const query = sceneType ? `?scene_type=${sceneType}` : ''
    return requestJson(`/books/${bookId}/samples${query}`)
  },

  /** 创建作者样本（保存时自动向量化）。 */
  createSample: async (
    bookId: string,
    payload: { content: string; scene_type?: string; chapter_id?: string; source?: string },
  ): Promise<AuthorSample> => {
    return requestJson(`/books/${bookId}/samples`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /** 删除作者样本。 */
  deleteSample: async (bookId: string, sampleId: string): Promise<void> => {
    await requestRaw(`/books/${bookId}/samples/${sampleId}`, { method: 'DELETE' })
  },

  /** 向量检索相似样本。 */
  searchSamples: async (
    bookId: string,
    queryText: string,
    sceneType?: string,
  ): Promise<AuthorSampleSearchHit[]> => {
    return requestJson(`/books/${bookId}/samples/search`, {
      method: 'POST',
      body: JSON.stringify({ query_text: queryText, scene_type: sceneType || null, limit: 3 }),
    })
  },
}

/**
 * 成本报告 API（Phase 0 观测层，T1.6）。
 */
export const costReportApi = {
  /** 获取章级成本报告（分阶段 token 计量）。 */
  get: async (chapterId: string, runId?: string): Promise<CostReport> => {
    const query = runId ? `?run_id=${runId}` : ''
    return requestJson(`/chapters/${chapterId}/cost-report${query}`)
  },
}

/**
 * 质量报告 API（Phase 2 CP3.1c 双层审计）。
 */
export const qualityReportApi = {
  /** 获取本章最新质量报告（含 metrics / findings / verdict / degraded）。 */
  get: async (chapterId: string, runId?: string): Promise<QualityReport> => {
    const query = runId ? `?run_id=${runId}` : ''
    return requestJson(`/chapters/${chapterId}/quality-report${query}`)
  },
}

// ============================================================
// 已剥离：detonationApi / unifiedApi
// ============================================================
// V3.0 Detonation 与 V3.1 Unified 引擎后端已整体剥离，
// 端点 GET /detonation-chain 与 POST /generate 均不存在，前端死代码一并删除。

export type Tier = 'auto' | 'climax' | 'turn' | 'progress' | 'transition'

// ============================================================
// V3.2 ADF（Anchor-Driven Flow）引擎 API（adfApi）
// ============================================================
// 端点（前缀 /api/chapters/{chapter_id}）：
// - POST /generate-adf  ADF 生成（参数 tier + target_word_count + max_segments）
//
// SSE v3.2 事件序列（设计文档 §7）：
// - ADF_STAGE / ADF_SPINE_BUILT / ADF_ANCHOR_DESIGNED / TIER_DECIDED /
//   ADF_PROGRESS / ADF_PRECONDITION_LANDED / ADF_AUDIT / ADF_METADATA /
//   DEGRADED / UNIFIED_METRIC / TEXT_CHUNK / COMPLETE / ERROR

export type AdfEngine = 'v3.1' | 'v3.2'

export interface AdfPrecondition {
  id: string
  category: string
  description: string
  must_use_terms: string[]
  min_landing_offset?: number
  landed?: boolean
  landed_segment?: number | null
  landed_evidence?: string | null
}

export interface AdfEmotionSample {
  progress: number
  register: string
  energy: number
}

export interface AdfAnchorDesigned {
  climax_intensity: number
  climax_description: string
  setup_point_count: number
  emotion_flow_samples: AdfEmotionSample[]
}

export interface AdfAuditResult {
  verdict: 'pass' | 'needs_refinement' | 'fail' | 'unaudited'
  missing_setup_points: string[]
  emotion_mismatches: string[]
  structure_issues: string[]
  climax_score?: number | null
  fix_targets: string[]
}

export interface AdfCompleteResult {
  text: string
  engine: 'adf'
  generation_run_id: string
  tier?: string | null
  tier_reason?: string | null
  target_word_count?: number | null
  segment_count: number
  setup_points_total: number
  setup_points_landed: number
  climax_score?: number | null
  audit_verdict?: string | null
  stats: Record<string, any>
}

// ============================================================
// V4.2 对话式介入点 1：章节规划建议
// ============================================================

export interface PlanSuggestionQuestion {
  id: string
  type: 'confirm' | 'expectation_action' | 'hooks' | 'free_text'
  question: string
  default?: string
  options?: string[]
  option_labels?: Record<string, string>
  expectation_id?: string
  hook_ids?: string[]
}

export interface PlanSuggestionResponse {
  chapter_id: string
  chapter_number: number
  outline: string
  reader_mirror_plan: any | null
  active_expectations: Array<{
    id: string
    type: string
    description: string
    current_tension: number
    recommended_action: string
  }>
  open_hooks: Array<{
    id: string
    label: string
    strength: number
    expected_reveal_chapter: number | null
  }>
  canon_summary_excerpt: string
  suggested_questions: PlanSuggestionQuestion[]
}

export const adfApi = {
  /**
   * V4.2 介入点 1：获取章节规划建议（生成前）。
   */
  getPlanSuggestion: async (chapterId: string): Promise<PlanSuggestionResponse> => {
    return await requestJson<PlanSuggestionResponse>(`/chapters/${chapterId}/plan-suggestion`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
  },

  /**
   * SSE ADF 生成（V3.2）。
   * tier=auto 时程序自主定档；其余值强制指定档位。
   * target_word_count=null 时由 tier 自动推导；max_segments 控制段数上限。
   */
  streamGenerate: async (
    chapterId: string,
    params: {
      tier?: Tier
      target_word_count?: number | null
      max_segments?: number
      enable_spine?: boolean
      enable_anchor_audit?: boolean
      enable_refinement?: boolean
      user_tier_hint?: string | null
      author_intent?: string | null
      expectation_actions?: Record<string, string> | null
    } | undefined,
    callbacks: {
      onEvent?: (event: string, data: any) => void
      onChunk?: (chunk: string) => void
      onStage?: (stage: string, data: any) => void
      onSpineBuilt?: (data: any) => void
      onAnchorDesigned?: (anchor: AdfAnchorDesigned) => void
      onTierDecided?: (decision: { tier: string; reason: string; climax_score?: number; target_word_count?: number; max_segments?: number }) => void
      onProgress?: (segmentIndex: number, total: number, data: any) => void
      onPreconditionLanded?: (data: { precondition_id: string; segment: number; evidence: string; category: string }) => void
      onAudit?: (audit: AdfAuditResult) => void
      onMetric?: (metrics: any) => void
      onDone?: (result: AdfCompleteResult) => void
      onError?: (error: string) => void
    },
    signal?: AbortSignal
  ) => {
    let hasCompleted = false

    streamSse(`/chapters/${chapterId}/generate-adf`, params || {}, {
      onPayload: payload => {
        if (!payload || !payload.event) return
        callbacks.onEvent?.(payload.event, payload)

        if (payload.event === 'TEXT_CHUNK' && payload.content) {
          callbacks.onChunk?.(payload.content)
        } else if (payload.event === 'ADF_STAGE') {
          callbacks.onStage?.(payload.stage, payload)
        } else if (payload.event === 'ADF_SPINE_BUILT') {
          callbacks.onSpineBuilt?.(payload)
        } else if (payload.event === 'ADF_ANCHOR_DESIGNED') {
          callbacks.onAnchorDesigned?.({
            climax_intensity: payload.climax_intensity,
            climax_description: payload.climax_description,
            setup_point_count: payload.setup_point_count,
            emotion_flow_samples: payload.emotion_flow_samples || [],
          })
        } else if (payload.event === 'TIER_DECIDED') {
          callbacks.onTierDecided?.({
            tier: payload.tier,
            reason: payload.reason,
            climax_score: payload.climax_score,
            target_word_count: payload.target_word_count,
            max_segments: payload.max_segments,
          })
        } else if (payload.event === 'ADF_PROGRESS') {
          callbacks.onProgress?.(payload.segment_index, payload.total_segments, payload)
        } else if (payload.event === 'ADF_PRECONDITION_LANDED') {
          callbacks.onPreconditionLanded?.({
            precondition_id: payload.precondition_id,
            segment: payload.segment,
            evidence: payload.evidence || '',
            category: payload.category || '',
          })
        } else if (payload.event === 'ADF_AUDIT') {
          callbacks.onAudit?.({
            verdict: payload.verdict,
            missing_setup_points: payload.missing_setup_points || [],
            emotion_mismatches: payload.emotion_mismatches || [],
            structure_issues: payload.structure_issues || [],
            climax_score: payload.climax_score,
            fix_targets: payload.fix_targets || [],
          })
        } else if (payload.event === 'UNIFIED_METRIC') {
          callbacks.onMetric?.(payload.metrics)
        } else if (payload.event === 'COMPLETE') {
          hasCompleted = true
          callbacks.onDone?.({
            text: payload.text,
            engine: payload.engine || 'adf',
            generation_run_id: payload.generation_run_id,
            tier: payload.tier,
            tier_reason: payload.tier_reason,
            target_word_count: payload.target_word_count,
            segment_count: payload.segment_count || 0,
            setup_points_total: payload.setup_points_total || 0,
            setup_points_landed: payload.setup_points_landed || 0,
            climax_score: payload.climax_score,
            audit_verdict: payload.audit_verdict,
            stats: payload.stats || {},
          })
          return true
        }
      },
      onDone: () => {
        if (!hasCompleted) {
          callbacks.onError?.('生成过程意外中断，未收到完成信号')
        }
      },
      onError: message => {
        hasCompleted = true
        callbacks.onError?.(message)
      },
    }, signal).catch(err => {
      if (!hasCompleted) {
        callbacks.onError?.(err.message)
      }
    })
  },
}

// ============================================================
// V4.1 Refinery 精修流水线 API
// ============================================================
// 端点（前缀 /api/chapters/{chapter_id}/refinery）：
// - POST /diagnose   SSE：第一阶段（诊断），返回 REFINERY_ISSUES + run_id
// - POST /confirm    SSE：第二阶段（手术+回读+抛光），需要 run_id + 作者决策
//
// 两阶段 SSE 设计（对话式介入点 2）：
// 1. diagnose 流：REFINERY_STAGE(DIAGNOSTIC) → REFINERY_ISSUES → REFINERY_STAGE(DIALOGUE) → 流结束
// 2. 用户在前端审阅问题清单，做决策
// 3. confirm 流：REFINERY_STAGE(SURGERY) → REFINERY_SURGERY×N → REFINERY_REREAD →
//    REFINERY_POLISH → FINAL_TEXT_STREAM → COMPLETE

export type IssueType =
  | 'tell_not_show' | 'pacing_drag' | 'pacing_break' | 'scene_jump'
  | 'info_leak' | 'character_off' | 'redundancy' | 'weak_hook'
  | 'emotion_mismatch' | 'custom'

export type IssueSeverity = 'high' | 'medium' | 'low'

export interface RefineryIssue {
  id: string
  location: {
    paragraph?: number | null
    paragraph_range?: [number, number] | null
    quote: string
    char_offset?: [number, number] | null
  }
  type: IssueType
  severity: IssueSeverity
  diagnosis: string
  suggestion: string
  impact_radius: 'local' | 'multi_paragraph' | 'global'
  status: 'pending' | 'confirmed' | 'ignored' | 'auto'
}

export interface RefinerySurgery {
  operation_id: string
  original_text?: string
  revised_text?: string
  diff_summary: string
  applied: boolean
  target_indices?: number[]
}

export interface RefineryHolisticVerdict {
  verdict: 'pass' | 'needs_final_touch'
  remaining_issues: string[]
  final_touch_suggestion: string
}

export interface RefineryCompleteResult {
  polished_text: string
  stats: Record<string, any>
  generation_run_id: string
  issues_total: number
  issues_confirmed: number
  operations_executed: number
  holistic_verdict: string | null
}

export interface IssueDecision {
  issue_id: string
  decision: 'confirmed' | 'ignored'
  edited_suggestion?: string
}

// ============================================================
// BS-ADF 引擎（Beat-Slot Anchor-Driven Flow）
// ============================================================
// 端点（前缀 /api/chapters/{chapter_id}）：
// - POST /generate-bsadf  Track A 全自动 / Track B 跑到槽位卡暂停
// - POST /confirm-beats   Track B 作者编辑后恢复渲染
// - POST /rerender-beat   降级单卡恢复（同步 JSON，非 SSE）
//
// SSE 事件序列（设计文档）：
// - BSADF_STAGE / ADF_STAGE / BEAT_SLOTS_BUILT（Track B 暂停点）/
//   BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED / TEXT_CHUNK / COMPLETE / ERROR

/** 槽位卡：每一段的写作契约（Track B 作者可编辑） */
export interface BeatSlot {
  beat_id: string
  segment_index: number
  beat_type: string
  target_word_count: number
  anchor_actions: string[]
  sensory_details: string[]
  text_carrier: string
  conflict_trigger: string
  psych_subtext: string
  ban_words: string[]
  sentence_rhythm: string
  perspective: string
  emotion_register: string
  emotion_energy: number
  landed_preconditions: string[]
  shot_type: string
  transition: string
  status: string
  edit_count: number
  render_attempts: number
  edited: boolean
}

/** 渲染进度事件：每个 beat 渲染完成时推送 */
export interface RenderProgress {
  beat_id: string
  segment_index: number
  status: string  // rendering | rendered | degraded
  word_count: number
  reason?: string
}

/** 降级事件：某 beat 多次失败后降级 */
export interface DegradedBeat {
  beat_id: string
  segment_index: number
  reason: string  // ai_smell | coverage_fail | gate_fail | llm_error
  attempts: number
}

/** BS-ADF 生成完成结果 */
export interface BSAdfCompleteResult {
  text: string
  engine: 'bsadf'
  tier: string
  reason?: string
  target_word_count?: number
  segment_count: number
  climax_score: number | null
  audit_verdict: string | null
  generation_run_id: string
  stats: Record<string, any>
  degraded_count: number
}

export const refineryApi = {
  /**
   * 第一阶段：诊断（SSE）。
   * 流结束后回调 onIssues，前端渲染问题清单 UI 等待作者确认。
   */
  diagnose: async (
    chapterId: string,
    params: {
      raw_text?: string | null
      mode?: 'deep' | 'light'
      enable_polish?: boolean
      canon_context?: string
    } | undefined,
    callbacks: {
      onEvent?: (event: string, data: any) => void
      onStage?: (stage: string, data: any) => void
      onIssues?: (payload: { run_id: string; issues: RefineryIssue[]; stats: any }) => void
      onError?: (error: string) => void
    },
    signal?: AbortSignal,
  ) => {
    let receivedIssues = false

    streamSse(`/chapters/${chapterId}/refinery/diagnose`, params || {}, {
      onPayload: payload => {
        if (!payload || !payload.event) return
        callbacks.onEvent?.(payload.event, payload)

        if (payload.event === 'REFINERY_STAGE') {
          callbacks.onStage?.(payload.stage, payload)
        } else if (payload.event === 'REFINERY_ISSUES') {
          receivedIssues = true
          callbacks.onIssues?.({
            run_id: payload.run_id,
            issues: payload.issues || [],
            stats: payload.stats || {},
          })
        }
      },
      onDone: () => {
        if (!receivedIssues) {
          callbacks.onError?.('诊断未返回问题清单')
        }
      },
      onError: message => {
        callbacks.onError?.(message)
      },
    }, signal).catch(err => {
      callbacks.onError?.(err.message)
    })
  },

  /**
   * V4.3 介入点 3：读者反馈（POST，非 SSE，同步返回）。
   * 1 次 LLM 扮演读者，写叙述性感受。
   */
  getReaderFeedback: async (chapterId: string, rawText?: string | null): Promise<{
    chapter_id: string
    feedback: string
    word_count: number
    generation_run_id: string
  }> => {
    return await requestJson(`/chapters/${chapterId}/reader-feedback`, {
      method: 'POST',
      body: JSON.stringify({ raw_text: rawText || null }),
    })
  },

  /**
   * 第二阶段：作者确认后执行手术+回读+抛光（SSE）。
   * 需要 run_id（从 diagnose 获得）+ decisions（作者对每个 issue 的决策）。
   */
  confirm: async (
    chapterId: string,
    params: {
      run_id: string
      decisions: IssueDecision[]
      custom_issues?: RefineryIssue[]
      mode?: 'deep' | 'light'
    },
    callbacks: {
      onEvent?: (event: string, data: any) => void
      onStage?: (stage: string, data: any) => void
      onOperation?: (data: { operation_id: string; operation_index: number; total_operations: number; issue_ids: string[] }) => void
      onSurgery?: (surgery: RefinerySurgery) => void
      onReread?: (verdict: RefineryHolisticVerdict) => void
      onPolish?: () => void
      onChunk?: (chunk: string) => void
      onDone?: (result: RefineryCompleteResult) => void
      onError?: (error: string) => void
    },
    signal?: AbortSignal,
  ) => {
    let hasCompleted = false

    streamSse(`/chapters/${chapterId}/refinery/confirm`, params, {
      onPayload: payload => {
        if (!payload || !payload.event) return
        callbacks.onEvent?.(payload.event, payload)

        if (payload.event === 'REFINERY_STAGE') {
          callbacks.onStage?.(payload.stage, payload)
        } else if (payload.event === 'REFINERY_OPERATION') {
          callbacks.onOperation?.({
            operation_id: payload.operation_id,
            operation_index: payload.operation_index,
            total_operations: payload.total_operations,
            issue_ids: payload.issue_ids || [],
          })
        } else if (payload.event === 'REFINERY_SURGERY') {
          callbacks.onSurgery?.({
            operation_id: payload.operation_id,
            diff_summary: payload.diff_summary || '',
            applied: payload.applied ?? false,
            target_indices: payload.target_indices,
          })
        } else if (payload.event === 'REFINERY_REREAD') {
          callbacks.onReread?.({
            verdict: payload.verdict,
            remaining_issues: payload.remaining_issues || [],
            final_touch_suggestion: payload.final_touch_suggestion || '',
          })
        } else if (payload.event === 'REFINERY_POLISH') {
          callbacks.onPolish?.()
        } else if (payload.event === 'TEXT_CHUNK' && payload.content) {
          callbacks.onChunk?.(payload.content)
        } else if (payload.event === 'COMPLETE') {
          hasCompleted = true
          callbacks.onDone?.({
            polished_text: payload.polished_text || '',
            stats: payload.stats || {},
            generation_run_id: payload.generation_run_id || '',
            issues_total: payload.issues_total || 0,
            issues_confirmed: payload.issues_confirmed || 0,
            operations_executed: payload.operations_executed || 0,
            holistic_verdict: payload.holistic_verdict || null,
          })
        }
      },
      onDone: () => {
        if (!hasCompleted) {
          callbacks.onError?.('精修过程意外中断')
        }
      },
      onError: message => {
        hasCompleted = true
        callbacks.onError?.(message)
      },
    }, signal).catch(err => {
      if (!hasCompleted) {
        callbacks.onError?.(err.message)
      }
    })
  },
}

// ============================================================
// BS-ADF 引擎 API（Beat-Slot Anchor-Driven Flow）
// ============================================================
// 端点（前缀 /api/chapters/{chapter_id}）：
// - POST /generate-bsadf  Track A 全自动 / Track B 跑到槽位卡暂停（SSE）
// - POST /confirm-beats   Track B 作者编辑后恢复渲染（SSE）
// - POST /rerender-beat   降级单卡恢复（同步 JSON，非 SSE）

export const bsadfApi = {
  /**
   * 启动 BS-ADF 生成（SSE）。
   * - Track A：全自动，跑到底（COMPLETE）。
   * - Track B：跑到 BEAT_SLOTS_BUILT 暂停，回调 onSlots，前端渲染槽位卡编辑界面。
   */
  start: async (
    chapterId: string,
    params: {
      tier?: string
      track?: 'A' | 'B'
      target_word_count?: number | null
      max_segments?: number
      author_intent?: string
      expectation_actions?: Record<string, string>
    },
    callbacks: {
      onStage?: (stage: string, data: any) => void
      onSlots?: (payload: { run_id: string; slots: BeatSlot[] }) => void
      onRenderProgress?: (data: RenderProgress) => void
      onDowngraded?: (data: DegradedBeat) => void
      onChunk?: (chunk: string) => void
      onDone?: (result: BSAdfCompleteResult) => void
      onError?: (error: string) => void
    },
    signal?: AbortSignal,
  ) => {
    let hasCompleted = false
    let receivedSlots = false  // Track B 暂停标志：收到 BEAT_SLOTS_BUILT 后流关闭是正常的

    streamSse(`/chapters/${chapterId}/generate-bsadf`, params, {
      onPayload: payload => {
        if (!payload || !payload.event) return

        if (payload.event === 'BSADF_STAGE' || payload.event === 'ADF_STAGE') {
          callbacks.onStage?.(payload.stage, payload)
        } else if (payload.event === 'BEAT_SLOTS_BUILT') {
          // Track B 暂停触发：槽位卡就绪
          receivedSlots = true
          callbacks.onSlots?.({
            run_id: payload.run_id,
            slots: payload.beat_slots || [],
          })
        } else if (payload.event === 'BEAT_RENDER_PROGRESS') {
          callbacks.onRenderProgress?.({
            beat_id: payload.beat_id,
            segment_index: payload.segment_index,
            status: payload.status,
            word_count: payload.word_count || 0,
            reason: payload.reason,
          })
        } else if (payload.event === 'BEAT_DOWNGRADED') {
          callbacks.onDowngraded?.({
            beat_id: payload.beat_id,
            segment_index: payload.segment_index,
            reason: payload.reason,
            attempts: payload.attempts || 0,
          })
        } else if (payload.event === 'TEXT_CHUNK' && payload.content) {
          callbacks.onChunk?.(payload.content)
        } else if (payload.event === 'COMPLETE') {
          hasCompleted = true
          callbacks.onDone?.({
            text: payload.text || '',
            engine: 'bsadf',
            tier: payload.tier || 'auto',
            reason: payload.reason,
            target_word_count: payload.target_word_count,
            segment_count: payload.segment_count || 0,
            climax_score: payload.climax_score ?? null,
            audit_verdict: payload.audit_verdict ?? null,
            generation_run_id: payload.generation_run_id || '',
            stats: payload.stats || {},
            degraded_count: payload.degraded_count || 0,
          })
        }
      },
      onDone: () => {
        // Track B 收到 BEAT_SLOTS_BUILT 后流关闭是正常的暂停，不是错误；
        // Track A 必须收到 COMPLETE 才算成功
        if (!hasCompleted && !receivedSlots) callbacks.onError?.('BS-ADF 生成意外中断')
      },
      onError: message => {
        hasCompleted = true
        callbacks.onError?.(message)
      },
    }, signal).catch(err => {
      if (!hasCompleted) callbacks.onError?.(err.message)
    })
  },

  /**
   * Track B：作者编辑槽位卡后恢复渲染（SSE）。
   * 需要 run_id（来自 start 的 BEAT_SLOTS_BUILT）+ edited_slots（作者编辑后的槽位）。
   */
  confirm: async (
    chapterId: string,
    params: { run_id: string; edited_slots: BeatSlot[] },
    callbacks: {
      onStage?: (stage: string, data: any) => void
      onRenderProgress?: (data: RenderProgress) => void
      onDowngraded?: (data: DegradedBeat) => void
      onChunk?: (chunk: string) => void
      onDone?: (result: BSAdfCompleteResult) => void
      onError?: (error: string) => void
    },
    signal?: AbortSignal,
  ) => {
    let hasCompleted = false

    streamSse(`/chapters/${chapterId}/confirm-beats`, params, {
      onPayload: payload => {
        if (!payload || !payload.event) return

        if (payload.event === 'BSADF_STAGE') {
          callbacks.onStage?.(payload.stage, payload)
        } else if (payload.event === 'BEAT_RENDER_PROGRESS') {
          callbacks.onRenderProgress?.({
            beat_id: payload.beat_id,
            segment_index: payload.segment_index,
            status: payload.status,
            word_count: payload.word_count || 0,
            reason: payload.reason,
          })
        } else if (payload.event === 'BEAT_DOWNGRADED') {
          callbacks.onDowngraded?.({
            beat_id: payload.beat_id,
            segment_index: payload.segment_index,
            reason: payload.reason,
            attempts: payload.attempts || 0,
          })
        } else if (payload.event === 'TEXT_CHUNK' && payload.content) {
          callbacks.onChunk?.(payload.content)
        } else if (payload.event === 'COMPLETE') {
          hasCompleted = true
          callbacks.onDone?.({
            text: payload.text || '',
            engine: 'bsadf',
            tier: payload.tier || 'auto',
            segment_count: payload.segment_count || 0,
            climax_score: payload.climax_score ?? null,
            audit_verdict: payload.audit_verdict ?? null,
            generation_run_id: payload.generation_run_id || '',
            stats: payload.stats || {},
            degraded_count: payload.degraded_count || 0,
          })
        }
      },
      onDone: () => {
        if (!hasCompleted) callbacks.onError?.('BS-ADF 渲染意外中断')
      },
      onError: message => {
        hasCompleted = true
        callbacks.onError?.(message)
      },
    }, signal).catch(err => {
      if (!hasCompleted) callbacks.onError?.(err.message)
    })
  },

  /**
   * 降级单卡恢复（同步 JSON，非 SSE）。
   * 重新渲染某张降级 beat，返回渲染段（含 text）+ 更新后的槽位卡 + 可能的新降级句柄。
   *
   * 后端响应结构（routes/chapter_generation/bsadf.py::rerender_beat）：
   * - segment: { index, text, scene_summary, emotion_register, landed_preconditions }
   * - card: 更新后的槽位卡（status=pending/rendered/degraded）
   * - degraded: 再次降级时返回新 DegradedBeat；成功时为 null
   * - generation_run_id: 本次重渲染的 run id（rerender_xxx）
   */
  rerenderBeat: async (
    chapterId: string,
    params: { beat_id: string; edited_slot: BeatSlot },
  ): Promise<{
    chapter_id: string
    generation_run_id: string
    segment: {
      index: number
      text: string
      scene_summary?: string
      emotion_register?: string
      landed_preconditions?: string[]
    }
    card: BeatSlot
    degraded: DegradedBeat | null
  }> => {
    return requestJson(`/chapters/${chapterId}/rerender-beat`, {
      method: 'POST',
      body: JSON.stringify(params),
    })
  },
}

// ============================================================
// 伏笔账本 API（V3.1 F4 新增）
// ============================================================
// 后端 PlotLedger 表的 REST 暴露：GET /api/books/{id}/ledgers（已实现）。
// 保留 404 降级为空数组的容错，防御端点不可用场景。

export interface PlotLedgerEntry {
  id: string
  book_id: string
  chapter_id?: string | null
  ledger_key: string
  hook_id?: string | null
  entry_type: string
  content: string
  status: 'open' | 'closed' | 'dropped'
  created_at_chapter?: number | null
  resolved_in_chapter_id?: string | null
  meta?: Record<string, any>
}

export interface PlotLedgerCreateInput {
  ledger_key: string
  content: string
  hook_id?: string | null
  entry_type?: string
  status?: 'open' | 'closed' | 'dropped'
  created_at_chapter?: number | null
  meta?: Record<string, any>
}

export interface PlotLedgerUpdateInput {
  ledger_key?: string
  content?: string
  hook_id?: string | null
  entry_type?: string
  status?: 'open' | 'closed' | 'dropped'
  created_at_chapter?: number | null
  resolved_in_chapter_id?: string | null
  meta?: Record<string, any>
}

export const plotLedgerApi = {
  /** 列出书籍的全部伏笔。后端 404 时降级为空列表。 */
  listByBook: async (bookId: string): Promise<PlotLedgerEntry[]> => {
    try {
      return await requestJson<PlotLedgerEntry[]>(`/books/${bookId}/ledgers`)
    } catch {
      // 后端 404 时降级为空列表
      return []
    }
  },
  /** 手动创建伏笔。后端要求 body 带 book_id（以路径为准覆盖）。 */
  create: (bookId: string, data: PlotLedgerCreateInput): Promise<PlotLedgerEntry> =>
    requestJson<PlotLedgerEntry>(`/books/${bookId}/ledgers`, {
      method: 'POST',
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),
  /** 更新伏笔（仅传需要变更的字段）。 */
  update: (ledgerId: string, data: PlotLedgerUpdateInput): Promise<PlotLedgerEntry> =>
    requestJson<PlotLedgerEntry>(`/ledgers/${ledgerId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  /** 删除伏笔（物理删除；不再需要建议改 status=dropped）。 */
  remove: (ledgerId: string): Promise<{ ok: boolean }> =>
    requestJson<{ ok: boolean }>(`/ledgers/${ledgerId}`, { method: 'DELETE' }),
}
