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
  // 双写收敛（任务包 B）：updateGoldenSnippets / GET+PUT style-blacklist 通道已删——
  // 黄金片段只写文风样本库（styleApi.createSample），负面清单唯一入口是 style-card。
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
  /** NLE-ADF 2.0 深度清脂（Alt+Shift+↓）：LLM 重洗当前段落（AI 味密度超阈值才调 LLM） */
  defatSelection: (data: { text: string; must_keep?: string[]; chapter_id?: string; book_id?: string }) =>
    requestJson('/defat_selection', { method: 'POST', body: JSON.stringify(data) }),
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
  api_key_masked: string
  has_api_key: boolean
  base_url: string
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
    /** UI 已隐藏 wash 槽；GET 仍可能返回，类型层标记为非必需 */
    wash?: LLMProfileConfig
  }
  embedding: {
    api_key_masked: string
    has_api_key: boolean
    /** 自管连接的 Base URL（follow_llm=true 时被忽略，仅作保留值） */
    base_url: string
    model: string
    dimensions: number
    /** true=连接（Key/Base URL）跟随文本模型槽，与文本模型保持一致 */
    follow_llm: boolean
    /** 跟随模式下实际生效的连接预览（creative 优先、缺 Key 回退 reasoning） */
    inherited: {
      source: 'creative' | 'reasoning' | null
      base_url: string
      has_api_key: boolean
    }
  }
  proxy: {
    enabled: boolean
    url: string
  }
}

/** 更新载荷：api_key 留空表示保持不变 */
export interface ModelConfigUpdatePayload {
  reasoning?: Partial<Pick<LLMProfileConfig, 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  creative?: Partial<Pick<LLMProfileConfig, 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  wash?: Partial<Pick<LLMProfileConfig, 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  embedding?: { api_key?: string; base_url?: string; model?: string; dimensions?: number; follow_llm?: boolean }
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
   * 测试模型连接（LLM 测已保存配置；embedding 用表单实时值探测，未保存也能测）
   * @param embedding 向量模型表单的当前值（api_key 留空表示沿用已保存 Key）
   * @returns 测试结果
   */
  testModel: async (embedding?: {
    model?: string
    base_url?: string
    dimensions?: number
    follow_llm?: boolean
    api_key?: string
  }): Promise<{
    success: boolean
    message: string
    model_info?: {
      reasoning_model?: string
      creative_model?: string
      reasoning_success?: boolean
      creative_success?: boolean
      embedding_configured?: boolean
      embedding_model?: string
      embedding_success?: boolean
      embedding_dimensions_returned?: number | null
      embedding_dimensions_expected?: number | null
    }
    reasoning_supported?: boolean
    reasoning_message?: string
    response_time_ms?: number
  }> => {
    return requestJson('/system/test-model', {
      method: 'POST',
      body: JSON.stringify(embedding ? { embedding } : {})
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
  AuthorSampleSceneType,
  AuthorSampleSearchHit,
  StyleFingerprint,
  StyleInboxItem,
  StyleInboxKind,
  StyleScanResult,
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
    payload: { content: string; scene_type?: string; chapter_id?: string; source?: string; era?: string },
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

  /** 样本局部更新：时期/收藏/场景类型/正文（正文变更时后端重算字数并重向量化）。 */
  patchSample: async (
    bookId: string,
    sampleId: string,
    patch: { era?: 'recent' | 'early'; favorite?: boolean; scene_type?: AuthorSampleSceneType; content?: string },
  ): Promise<AuthorSample> => {
    return requestRaw(`/books/${bookId}/samples/${sampleId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }).then((r: any) => r.json())
  },

  /** 黄金片段（旧表）一键导入文风样本库（按内容去重）。 */
  createSamplesFromGolden: async (bookId: string): Promise<AuthorSample[]> => {
    return requestJson(`/books/${bookId}/samples/from-golden`, { method: 'POST' })
  },

  /** 系统陈词库列表（全局层，负面清单区折叠展示用）。 */
  listSystemCliches: async (): Promise<Array<{ id: string; pattern: string; alternative?: string | null; severity: string }>> => {
    return requestJson('/system/cliches?enabled_only=true')
  },

  /** 系统陈词库本书豁免列表。 */
  getClicheExemptions: async (bookId: string): Promise<string[]> => {
    const data = await requestJson(`/books/${bookId}/cliche-exemptions`)
    return data?.patterns || []
  },

  /** 设置系统陈词库本书豁免（整体覆盖）。 */
  putClicheExemptions: async (bookId: string, patterns: string[]): Promise<void> => {
    await requestJson(`/books/${bookId}/cliche-exemptions`, {
      method: 'PUT',
      body: JSON.stringify({ patterns }),
    })
  },

  /** 文风使用埋点（本地 JSONL，fire-and-forget，绝不阻塞业务）。 */
  logStyleEvent: (bookId: string, kind: string, detail?: string): void => {
    requestRaw(`/books/${bookId}/style/events`, {
      method: 'POST',
      body: JSON.stringify({ kind, detail }),
    }).catch(() => {})
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

  /** 文风指纹：语料聚合 + 逐样本 + 可选章指纹（纯 code 测量，0 LLM）。 */
  getFingerprint: async (
    bookId: string,
    withChapters = false,
    chapterLimit = 50,
  ): Promise<StyleFingerprint> => {
    const query = `?with_chapters=${withChapters}&chapter_limit=${chapterLimit}`
    return requestJson(`/books/${bookId}/style-fingerprint${query}`)
  },

  /** 从已发布章节一键收编作者样本（零状态坡道兜底）。 */
  createSamplesFromChapters: async (
    bookId: string,
    opts?: { max_chapters?: number; excerpt_chars?: number },
  ): Promise<AuthorSample[]> => {
    return requestJson(`/books/${bookId}/samples/from-chapters`, {
      method: 'POST',
      body: JSON.stringify(opts || {}),
    })
  },

  /** 删除章级文风覆盖（本章恢复继承书级）。 */
  deleteChapterOverride: async (bookId: string, chapterId: string): Promise<void> => {
    await requestRaw(`/books/${bookId}/style-card?chapter_id=${chapterId}`, { method: 'DELETE' })
  },

  // ---- 文风收件箱（S3）----

  /** 收件箱待过目候选列表。 */
  listInbox: async (bookId: string): Promise<StyleInboxItem[]> => {
    return requestJson(`/books/${bookId}/style/inbox`)
  },

  /** 投递候选（写作台「这不像我」等入口；候选不直接生效）。 */
  addInboxItem: async (
    bookId: string,
    kind: StyleInboxKind,
    payload: Record<string, unknown>,
    source = 'writing_desk',
  ): Promise<StyleInboxItem> => {
    return requestJson(`/books/${bookId}/style/inbox`, {
      method: 'POST',
      body: JSON.stringify({ kind, payload, source }),
    })
  },

  /** 确认候选（✓）：负面候选入负面清单，样本候选入库。 */
  confirmInboxItem: async (bookId: string, itemId: string): Promise<StyleInboxItem> => {
    return requestJson(`/books/${bookId}/style/inbox/${itemId}/confirm`, { method: 'POST' })
  },

  /** 忽略候选（✗）。 */
  dismissInboxItem: async (bookId: string, itemId: string): Promise<StyleInboxItem> => {
    return requestJson(`/books/${bookId}/style/inbox/${itemId}/dismiss`, { method: 'POST' })
  },

  /** 禁词扫描（三层合并 → 命中清单；替换由作者逐条确认后应用）。 */
  scanNegative: async (
    bookId: string,
    target: { chapter_id?: string; text?: string },
  ): Promise<StyleScanResult> => {
    return requestJson(`/books/${bookId}/style/scan-negative`, {
      method: 'POST',
      body: JSON.stringify(target),
    })
  },

  /** 试听（试衣间，SSE 打字机）：给定段落 + 文风配置 → 真实注入管线改写。 */
  audition: (
    bookId: string,
    data: {
      text: string
      style_override?: Partial<StyleCard> | null
      use_samples?: boolean
      target_chars?: number
    },
    handlers: { onChunk?: (delta: string) => void; onDone?: (text: string) => void; onError?: (msg: string) => void },
    signal?: AbortSignal,
  ): Promise<void> => {
    return streamSse(`/books/${bookId}/style/audition`, data, {
      onPayload: (payload: any) => {
        if (payload.event === 'AUDITION_CHUNK' && payload.delta) handlers.onChunk?.(payload.delta)
        else if (payload.event === 'AUDITION_DONE' && payload.text) handlers.onDone?.(payload.text)
        return false
      },
      onError: (msg: string) => handlers.onError?.(msg),
    }, signal)
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

/** 槽位卡：每一段的写作契约（Track B 作者可编辑，DDE-BS 重构后 13 字段瘦身版） */
export interface BeatSlot {
  beat_id: string
  segment_index: number
  beat_type: string
  target_word_count: number
  /** 本段必须发生的剧情转折（物理硬契约） */
  core_plot_event: string
  /** 画面必现硬焦点（物理动作/名词词，coverage 校验） */
  key_anchors: string[]
  /** 锚定本段的一句对白/铭文 */
  text_carrier: string
  /** 本段大纲节拍（UI 只读展示） */
  outline_beat?: string
  /** 作者选定的剧情分支走向（DDE 注入，渲染约束，UI 只读展示） */
  branch_directive?: string
  /** 排他禁忌（DDE 否定约束；内部渲染约束，UI 不展示） */
  negative_bounds?: string[]
  sentence_rhythm: string
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

// ============================================================
// DDE 章节级剧情分叉（ChapterDecisionSet，新 schema）
// ============================================================

/** DDE 单个剧情分支选项（走向级，非物理动作级） */
export interface BranchOption {
  option_id: string
  /** 走向标签（≤20字），如「忍辱负重并暗中破坏设备」 */
  label: string
  /** 剧情后果说明（只给作者看） */
  plot_impact: string
}

/** DDE 单个剧情分叉节点（挂在某个 beat 上的一道走向选择题） */
export interface StoryBranch {
  beat_id: string
  /** 如「面对工头恶意挑衅，林尘的应对分支」 */
  node_title: string
  /** 2~3 个互斥走向选项 */
  options: BranchOption[]
  /** 默认 option_id（最顺大纲的主路径） */
  default_option: string
  /**
   * 节点来源：dde=LLM 判出的真实岔路（缺省）；loop1_gap=大纲自检缺口提示
   * （单选项提示节点，前端显示补充输入框，仅作者自定义文本才会注入 directive）
   */
  source?: 'dde' | 'loop1_gap'
}

/** 全章剧情分叉决策集（DDE 单次 LLM 调用的产出，节点硬上限 2 个） */
export interface ChapterDecisionSet {
  /** False = 全章无岔路，自动放行（常态） */
  has_story_branch: boolean
  decision_nodes: StoryBranch[]
}

/** 救援标记：审计判核心转折未落地且补写未救回的节拍（路线 C 降级救援） */
export interface RescueNeededItem {
  beat_id: string
  segment_index: number
  outline_beat: string
  core_plot_event: string
  reason: string  // core_plot_event_not_landed
}

/** 渲染进度事件：每个 beat 渲染完成时推送 */
export interface RenderProgress {
  beat_id: string
  segment_index: number
  status: string  // rendering | rendered | degraded
  word_count: number
  reason?: string
  /** 软指标：未出现在正文中的槽位词（方案书对齐——槽位词是扩展种子，
   *  缺失不参与降级判定，仅上报展示） */
  coverage_missing?: string[]
  /** 软指标：末段（结局段）超字数预算豁免截断（结局完整性 > 字数预算） */
  word_overflow?: boolean
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
  /** Track A 完成时随 COMPLETE 下发的槽位卡（Track B 前端已持有，不重复用） */
  beat_slots?: BeatSlot[]
  /** 救援标记：核心转折未落地的节拍（路线 C 内联救援卡） */
  rescue_needed?: RescueNeededItem[]
  /** 降级节拍清单（步进模式不发 BEAT_DOWNGRADED，这是 done 态降级复查的唯一来源） */
  degraded_beats?: { beat_id: string; segment_index: number; reason: string; attempts?: number }[]
  /** 审校结论（步进后处理 ADF_AUDIT 事件的丢帧兜底） */
  audit?: { verdict: string; missing_setup_points?: any[]; missing_beats?: any[]; climax_score?: number | null }
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

/** BS-ADF 流式回调集（start / confirm 共用，由 _dispatchEvent 统一分发） */
export interface BsadfStreamCallbacks {
  onStage?: (stage: string, data: any) => void
  /** Track B 暂停：槽位卡就绪（载荷内嵌 decision_set 分支信息） */
  onSlots?: (payload: { run_id: string; slots: BeatSlot[]; decision_set?: ChapterDecisionSet }) => void
  /** Track A 静默 DDE 结果：有分支=已按默认走向突变；无分支=has_story_branch=false */
  onDdeAutoApplied?: (payload: { decision_set: ChapterDecisionSet; applied: Record<string, string> }) => void
  onSlotEnrichProgress?: (current: number, total: number, beatId: string) => void
  onRenderProgress?: (data: RenderProgress) => void
  onDowngraded?: (data: DegradedBeat) => void
  /** 救援标记：审计判核心转折未落地且补写未救回的节拍 */
  onRescueNeeded?: (items: RescueNeededItem[]) => void
  /** 定档通知（复用 ADF 的 TIER_DECIDED 事件，仅 start 流 Phase 3 后发） */
  onTierDecided?: (decision: { tier: string; reason: string; climax_score?: number; target_word_count?: number; max_segments?: number }) => void
  // ===== NLE-ADF 步进事件回调 =====
  onBeatRenderStart?: (data: { beat_id: string; segment_index: number; target_word_count: number; card_snapshot: BeatSlot }) => void
  /** NLE-ADF 2.0 作者模式：拍已打开，等作者创作（写碎片微缝合 / render 召唤代笔 /
   *  lock_with_text 整拍定稿）。渲染不会自动开始。 */
  onBeatAuthoringOpen?: (data: { beat_id: string; segment_index: number; target_word_count: number; card_snapshot: BeatSlot }) => void
  /** NLE-ADF 步进岔路门：渲染某段前发现 DDE 岔路，暂停等作者选走向 */
  onBeatBranchChoice?: (data: { beat_id: string; segment_index: number; node: { beat_id: string; node_title: string; options: { option_id: string; label: string; plot_impact: string }[]; default_option: string }; card_snapshot: BeatSlot }) => void
  onBeatChunk?: (data: { beat_id: string; segment_index: number; delta: string }) => void
  onBeatReady?: (data: { beat_id: string; segment_index: number; word_count: number; degraded?: any; card_snapshot: BeatSlot }) => void
  onBeatLocked?: (data: { beat_id: string; segment_index: number; extracted_facts?: any }) => void
  /** NLE-ADF 步进回退：作者选择回退上一段，后端已弹栈并准备重渲 */
  onBeatBacked?: (data: { beat_id: string; segment_index: number; rejected?: boolean }) => void
  onBeatSkipped?: (data: { beat_id: string; segment_index: number }) => void
  onAllBeatsLocked?: (data: { segment_count: number; total_word_count: number }) => void
  onLoop1Checked?: (data: { hard_facts: any[]; gaps: any[]; critique_pass: boolean; violations: any[] }) => void
  /** 兜底事件通道：ADF_AUDIT / DEGRADED / BSADF_METADATA / UNIFIED_METRIC /
   *  FINAL_TEXT_STREAM / GENERATION_RUN（原被安全忽略，现交会话层填充产物） */
  onEvent?: (event: string, data: any) => void
  onChunk?: (chunk: string) => void
  onDone?: (result: BSAdfCompleteResult) => void
  onError?: (error: string) => void
}

/** 把 SSE 事件 payload 分流到对应回调（start / confirm 两条流共用） */
/**
 * BS-ADF 流的终态事件集：收到任一即视为正常收流（后端在这些事件后主动关流）。
 * BEAT_BACKED/BEAT_SKIPPED 列入是保守选择：它们之后本应跟重渲事件，但即便流
 * 恰在其后断开，步进轮询看门狗也能自愈——宁可漏报一次「中断」，不可误报刷屏。
 */
const BSADF_TERMINAL_EVENTS = new Set([
  'COMPLETE', 'ERROR',
  'BEAT_RENDER_READY', 'BEAT_BRANCH_CHOICE', 'BEAT_AUTHORING_OPEN',
  'STEPPING_INITIALIZED', 'BEAT_SLOTS_BUILT',
  'BEAT_BACKED', 'BEAT_SKIPPED',
])

function _dispatchEvent(
  payload: any,
  callbacks: BsadfStreamCallbacks,
) {
  if (!payload || !payload.event) return

  const ev = payload.event
  if (ev === 'BSADF_STAGE' || ev === 'ADF_STAGE') {
    callbacks.onStage?.(payload.stage, payload)
  } else if (ev === 'SLOT_ENRICH_PROGRESS') {
    callbacks.onSlotEnrichProgress?.(payload.current || 0, payload.total || 0, payload.beat_id || '')
  } else if (ev === 'DDE_AUTO_APPLIED') {
    callbacks.onDdeAutoApplied?.({
      decision_set: payload.decision_set || { has_story_branch: false, decision_nodes: [] },
      applied: payload.applied || {},
    })
  } else if (ev === 'BEAT_SLOTS_BUILT') {
    callbacks.onSlots?.({
      run_id: payload.run_id,
      slots: payload.beat_slots || [],
      decision_set: payload.decision_set,
    })
  } else if (ev === 'STEPPING_INITIALIZED') {
    // NLE-ADF 步进就绪：route 层补发，携带 run_id（workflow 内部的 BEAT_SLOTS_BUILT 不带 run_id）
    callbacks.onSlots?.({
      run_id: payload.run_id,
      slots: payload.beat_slots || [],
      decision_set: payload.decision_set,
    })
  } else if (ev === 'BEAT_RENDER_PROGRESS') {
    callbacks.onRenderProgress?.({
      beat_id: payload.beat_id,
      segment_index: payload.segment_index,
      status: payload.status,
      word_count: payload.word_count || 0,
      reason: payload.reason,
      coverage_missing: payload.coverage_missing,
      word_overflow: payload.word_overflow,
    })
  } else if (ev === 'BEAT_DOWNGRADED') {
    callbacks.onDowngraded?.({
      beat_id: payload.beat_id,
      segment_index: payload.segment_index,
      reason: payload.reason,
      attempts: payload.attempts || 0,
    })
  } else if (ev === 'RESCUE_NEEDED') {
    callbacks.onRescueNeeded?.(payload.items || [])
  } else if (ev === 'TIER_DECIDED') {
    // 复用 ADF 同名事件的载荷结构（tier/reason/climax_score/target_word_count/max_segments）
    callbacks.onTierDecided?.({
      tier: payload.tier,
      reason: payload.reason,
      climax_score: payload.climax_score,
      target_word_count: payload.target_word_count,
      max_segments: payload.max_segments,
    })
  } else if (ev === 'BEAT_RENDER_START') {
    callbacks.onBeatRenderStart?.({ beat_id: payload.beat_id, segment_index: payload.segment_index, target_word_count: payload.target_word_count, card_snapshot: payload.card_snapshot })
  } else if (ev === 'BEAT_AUTHORING_OPEN') {
    callbacks.onBeatAuthoringOpen?.({ beat_id: payload.beat_id, segment_index: payload.segment_index, target_word_count: payload.target_word_count, card_snapshot: payload.card_snapshot })
  } else if (ev === 'BEAT_BRANCH_CHOICE') {
    callbacks.onBeatBranchChoice?.({ beat_id: payload.beat_id, segment_index: payload.segment_index, node: payload.node, card_snapshot: payload.card_snapshot })
  } else if (ev === 'BEAT_TEXT_CHUNK') {
    callbacks.onBeatChunk?.({ beat_id: payload.beat_id, segment_index: payload.segment_index, delta: payload.delta || '' })
  } else if (ev === 'BEAT_RENDER_READY') {
    callbacks.onBeatReady?.({ beat_id: payload.beat_id, segment_index: payload.segment_index, word_count: payload.word_count, degraded: payload.degraded, card_snapshot: payload.card_snapshot })
  } else if (ev === 'BEAT_LOCKED') {
    callbacks.onBeatLocked?.({ beat_id: payload.beat_id, segment_index: payload.segment_index, extracted_facts: payload.extracted_facts })
  } else if (ev === 'BEAT_BACKED') {
    callbacks.onBeatBacked?.({ beat_id: payload.beat_id, segment_index: payload.segment_index, rejected: payload.rejected })
  } else if (ev === 'BEAT_SKIPPED') {
    callbacks.onBeatSkipped?.({ beat_id: payload.beat_id, segment_index: payload.segment_index })
  } else if (ev === 'ALL_BEATS_LOCKED') {
    callbacks.onAllBeatsLocked?.({ segment_count: payload.segment_count, total_word_count: payload.total_word_count })
  } else if (ev === 'LOOP1_OUTLINE_CHECKED') {
    callbacks.onLoop1Checked?.({ hard_facts: payload.hard_facts || [], gaps: payload.gaps || [], critique_pass: payload.critique_pass, violations: payload.violations || [] })
  } else if (ev === 'TEXT_CHUNK' && payload.content) {
    callbacks.onChunk?.(payload.content)
  } else if (ev === 'COMPLETE') {
    callbacks.onDone?.({
      text: payload.text || '',
      engine: 'bsadf',
      tier: payload.tier || 'auto',
      reason: payload.tier_reason,
      target_word_count: payload.target_word_count,
      segment_count: payload.segment_count || 0,
      climax_score: payload.climax_score ?? null,
      audit_verdict: payload.audit_verdict ?? null,
      generation_run_id: payload.generation_run_id || '',
      stats: payload.stats || {},
      degraded_count: payload.degraded_count || 0,
      beat_slots: payload.beat_slots,
      rescue_needed: payload.rescue_needed,
      degraded_beats: payload.degraded_beats,
      audit: payload.audit,
    })
  } else if (ev === 'ERROR') {
    callbacks.onError?.(payload.error || '生成失败')
  } else if (
    ev === 'ADF_AUDIT' || ev === 'DEGRADED' || ev === 'BSADF_METADATA'
    || ev === 'UNIFIED_METRIC' || ev === 'FINAL_TEXT_STREAM' || ev === 'GENERATION_RUN'
    || ev === 'SENTENCE_DEFECTS_UNFIXED' || ev === 'BEAT_CARDS_ENRICHED'
  ) {
    // 此前安全忽略的事件统一走 onEvent 兜底通道，由会话层按需填充产物
    // （降级详情 / 定档卡 / 审计结论 / 铺垫要点）
    callbacks.onEvent?.(ev, payload)
  }
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
  world_time_planted?: number | null
  world_time_resolved?: number | null
  meta?: Record<string, any>
}

export interface PlotLedgerCreateInput {
  ledger_key: string
  content: string
  hook_id?: string | null
  entry_type?: string
  status?: 'open' | 'closed' | 'dropped'
  created_at_chapter?: number | null
  world_time_planted?: number | null
  world_time_resolved?: number | null
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
  world_time_planted?: number | null
  world_time_resolved?: number | null
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
