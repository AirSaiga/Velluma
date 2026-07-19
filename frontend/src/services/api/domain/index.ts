import { streamSse } from '../stream'
import { getApiBase, requestJson, requestRaw } from '../transport'

const PROMPT_STORAGE_KEY = 'velluma_last_prompt'
const PROMPT_CHANNEL_KEY = 'velluma_prompt_debug'

let promptChannel: BroadcastChannel | null = null

function normalizePromptData(data: any): { system_prompt: string; user_prompt: string } | null {
  if (!data || typeof data !== 'object') return null
  const system_prompt = typeof data.system_prompt === 'string' ? data.system_prompt : ''
  const user_prompt = typeof data.user_prompt === 'string' ? data.user_prompt : ''
  if (!system_prompt && !user_prompt) return null
  return { system_prompt, user_prompt }
}

function getPromptChannel() {
  if (promptChannel) return promptChannel
  if (typeof window === 'undefined' || typeof window.BroadcastChannel === 'undefined') return null
  promptChannel = new BroadcastChannel(PROMPT_CHANNEL_KEY)
  return promptChannel
}

export function publishPromptData(data: any) {
  const prompt = normalizePromptData(data)
  if (!prompt) return
  try {
    localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(prompt))
  } catch (e) {
    console.warn('保存 prompt 到 localStorage 失败', e)
  }

  const channel = getPromptChannel()
  if (channel) {
    channel.postMessage(prompt)
  }

  if (window.electronAPI) {
    window.electronAPI.send('prompt-data', prompt)
  }
}

export function readStoredPromptData() {
  try {
    const raw = localStorage.getItem(PROMPT_STORAGE_KEY)
    if (!raw) return null
    return normalizePromptData(JSON.parse(raw))
  } catch (e) {
    console.warn('读取 localStorage prompt 失败', e)
    return null
  }
}

export function subscribePromptData(handler: (data: { system_prompt: string; user_prompt: string }) => void) {
  const channel = getPromptChannel()
  if (!channel) return () => {}
  const listener = (event: MessageEvent) => {
    const prompt = normalizePromptData(event.data)
    if (prompt) {
      handler(prompt)
    }
  }
  channel.addEventListener('message', listener)
  return () => {
    channel.removeEventListener('message', listener)
  }
}

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
    requestJson(`/books/${id}/style-blacklist`, { method: 'PUT', body: JSON.stringify({ style_blacklist: data }) })
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
  generateEmbedding: (chapterId: string) =>
    requestJson(`/chapters/${chapterId}/generate-embedding`, { method: 'POST', body: JSON.stringify({}) }),
  testCharacterExtraction: (data: { chapter_content: string }) =>
    requestJson('/debug/character-extraction', { method: 'POST', body: JSON.stringify(data) })
}

export const intentDrivenApi = {
  getTemplates: () => requestJson('/intent-driven/templates'),
  recommend: (data: { creative_intents: string[]; chapter_goals?: string[] | null }) =>
    requestJson('/intent-driven/recommend', { method: 'POST', body: JSON.stringify(data) }),
  generateSync: async (data: any) => {
    const response = await requestRaw('/intent-driven/generate', {
      method: 'POST',
      body: JSON.stringify(data)
    })
    if (!response.ok) {
      throw new Error(`意图生成请求失败: ${response.status} ${response.statusText}`)
    }
    const text = await response.text()
    return text
  }
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

async function streamDualTrackFn(
  chapterId: string,
  data: any,
  callbacks: {
    onEvent?: (event: string, data: any) => void
    onChunk?: (chunk: string) => void
    onDone?: (result: any) => void
    onError?: (error: string) => void
  },
  signal?: AbortSignal
) {
  let hasCompleted = false

  streamSse(`/chapters/${chapterId}/generate-chapter`, data, {
    onPayload: payload => {
      if (payload.prompt) {
        publishPromptData(payload.prompt)
      }

      if (payload.event) {
        callbacks.onEvent?.(payload.event, payload)

        if (payload.event === 'TEXT_CHUNK' && payload.content) {
          callbacks.onChunk?.(payload.content)
        } else if (payload.event === 'COMPLETE') {
          hasCompleted = true
          // 将双轨模式的 stats 适配为标准 metrics 格式，保持与普通模式兼容
          const stats = payload.stats || {}
          const metrics = {
            total_seconds: stats.total_time,
            fast_mode: false,
            top_stage_seconds: [
              { stage: 'TRACK_GENERATION', seconds: stats.track_time || 0 },
              { stage: 'STITCHING', seconds: stats.stitch_time || 0 }
            ].filter(s => s.seconds > 0),
            aggregate_stage_seconds: [],
            llm: {
              calls: 0,
              failures: 0,
              seconds: stats.total_time || 0
            },
            // 保留原始 stats 数据
            raw_stats: stats
          }
          callbacks.onDone?.({
            text: payload.text,
            stats: payload.stats,
            metrics: metrics,
            alignment_score: payload.alignment_score,
            passed: payload.passed,
            iterations: payload.iterations,
            revision_count: payload.revision_count
          })
          return true
        }
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
    }
  }).catch(err => {
    if (!hasCompleted) {
      callbacks.onError?.(err.message)
    }
  })
}

export const generateApi = {
  stream: async (data: any, onChunk?: (chunk: string) => void, onDone?: () => void, onError?: (error: string) => void) => {
    const baseUrl = await getApiBase()

    streamSse('/generate_chapter', data, {
      tolerateIncompleteWhenHasContent: true,
      onPayload: payload => {
        if (payload.prompt) {
          publishPromptData(payload.prompt)
        } else if (payload.content) {
          onChunk?.(payload.content)
        } else if (payload.done) {
          return true
        }
      },
      onDone: () => {
        onDone?.()
      },
      onError: message => {
        onError?.(message)
      }
    }).catch(err => {
      onError?.(err.message)
    })
  },

  generateSync: async (data: any) => {
    const response = await requestRaw('/generate_chapter_sync', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`生成请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  },

  optimize: async (data: any) => {
    const response = await requestRaw('/optimize_chapter', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`优化请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  },

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

  // CP4.5：previewAgenticBeats 已下线（合并闸门 planApi.preview 取代）

  clarifyOutline: async (data: any, abortSignal?: AbortSignal) => {
    // 大纲澄清需要调用 LLM，设置 5 分钟超时
    const response = await requestRaw(
      '/clarify-outline',
      {
        method: 'POST',
        body: JSON.stringify(data),
        signal: abortSignal
      },
      300000
    )

    if (!response.ok) {
      throw new Error(`大纲澄清请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  },

  /**
   * Agentic 章节生成（V4.0 默认使用双轨对抗架构）
   * @param useLegacyMode - 是否使用传统单轨模式（默认 false，使用双轨）
   */
  streamAgentic: async (
    data: any,
    callbacks: {
      onEvent?: (event: string, data: any) => void
      onChunk?: (chunk: string) => void
      onDone?: (result: any) => void
      onError?: (error: string) => void
    },
    endpoint = '/generate_chapter_agentic',
    useLegacyMode = false,
    signal?: AbortSignal
  ) => {
    // V4.0 默认使用双轨模式，除非显式指定使用传统模式
    if (!useLegacyMode && data.chapter_id) {
      return streamDualTrackFn(data.chapter_id, data, callbacks, signal)
    }
    let hasCompleted = false

    streamSse(endpoint, data, {
      onPayload: payload => {
        if (payload.prompt) {
          publishPromptData(payload.prompt)
        }

        if (payload.event) {
          callbacks.onEvent?.(payload.event, payload)

          if (payload.event === 'TEXT_CHUNK' && payload.content) {
            callbacks.onChunk?.(payload.content)
          } else if (payload.event === 'DONE') {
            hasCompleted = true
            callbacks.onDone?.({
              passed: payload.passed,
              iterations: payload.iterations,
              revision_count: payload.revision_count,
              metrics: payload.metrics
            })
            return true
          }
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
      }
    }, signal).catch(err => {
      if (!hasCompleted) {
        callbacks.onError?.(err.message)
      }
    })
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

  critiqueChapter: async (data: { chapter_content: string; chapter_title?: string }) => {
    const response = await requestRaw('/critique_chapter', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`主编指导请求失败: ${response.status} ${response.statusText}`)
    }

    return await response.json()
  },

  /**
   * V4.0 双轨生成 - 流式输出
   * 使用双轨对抗架构生成章节，包含短文生成和对抗校对
   */
  streamDualTrack: async (
    chapterId: string,
    data: any,
    callbacks: {
      onEvent?: (event: string, data: any) => void
      onChunk?: (chunk: string) => void
      onDone?: (result: any) => void
      onError?: (error: string) => void
    },
    signal?: AbortSignal
  ) => {
    return streamDualTrackFn(chapterId, data, callbacks, signal)
  }

  // CP4.5：generateDualTrackSimple 已下线（后端端点已删除，无前端调用方）
}

export const systemApi = {
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
  PlanPreviewResponse,
  PlanConfirmRequest,
  StyleCard,
  StyleExtractResponse,
  AuthorSample,
  AuthorSampleSearchHit,
  CostReport,
  QualityReport,
} from '../../../types'

/**
 * 章节规划 API（合并闸门，蓝图 §4.4.2 + decisions U3c）。
 *
 * 业务流程：
 *   preview() → 用户编辑章节卡+节拍 → confirm() → 触发 /generate-chapter（CP4.5 重命名）
 */
export const planApi = {
  /** 联合预览：生成/复用章节卡 + 节拍。
   *  首次调用 editedCardFields 留空 → AI 生成（2 次 LLM，5-15s）
   *  重规划 editedCardFields 非空 → 用用户版本生成新节拍（1 次 LLM）
   */
  preview: async (
    chapterId: string,
    editedCardFields?: Record<string, any> | null,
  ): Promise<PlanPreviewResponse> => {
    return requestJson(
      `/chapters/${chapterId}/plan`,
      {
        method: 'POST',
        body: JSON.stringify({ edited_card_fields: editedCardFields || null }),
      },
      600000,  // 10 分钟超时（联合预览耗时长）
    )
  },

  /** 单次确认：写 chapter_card + beats 到 DB，status=confirmed。 */
  confirm: async (
    chapterId: string,
    payload: PlanConfirmRequest,
  ): Promise<any> => {
    return requestJson(
      `/chapters/${chapterId}/plan/confirm`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    )
  },
}

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

  /** 重新触发本章双层审计（代码级 + LLM 级），返回新报告。 */
  rerun: async (chapterId: string, runId?: string): Promise<QualityReport> => {
    const query = runId ? `?run_id=${runId}` : ''
    return requestJson(`/chapters/${chapterId}/quality-report/rerun${query}`, {
      method: 'POST',
    })
  },
}
