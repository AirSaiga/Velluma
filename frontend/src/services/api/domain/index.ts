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
  generateEmbedding: (chapterId: string, apiConfig: any) =>
    requestJson(`/chapters/${chapterId}/generate-embedding`, { method: 'POST', body: JSON.stringify(apiConfig || {}) }),
  testCharacterExtraction: (data: { chapter_content: string; api_key: string; base_url?: string; model?: string }) =>
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
  }
) {
  let hasCompleted = false

  streamSse(`/chapters/${chapterId}/generate-dual-track`, data, {
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

  previewAgenticBeats: async (data: any, abortSignal?: AbortSignal) => {
    // 节拍预览需要调用 LLM，设置 5 分钟超时
    const response = await requestRaw(
      '/generate_chapter_agentic_preview_beats',
      {
        method: 'POST',
        body: JSON.stringify(data),
        signal: abortSignal
      },
      300000
    )

    if (!response.ok) {
      throw new Error(`节拍预览请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  },

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
   * Agentic 章节生成（V3.5 默认使用双轨对抗架构）
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
    useLegacyMode = false
  ) => {
    // V3.5 默认使用双轨模式，除非显式指定使用传统模式
    if (!useLegacyMode && data.chapter_id) {
      return streamDualTrackFn(data.chapter_id, data, callbacks)
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
    }).catch(err => {
      if (!hasCompleted) {
        callbacks.onError?.(err.message)
      }
    })
  },

  formatText: async (data: { text: string; api_key?: string; base_url?: string; model?: string }) => {
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
    temperature: number
    api_key: string
    base_url?: string
    model?: string
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

  critiqueChapter: async (data: any) => {
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
   * V3.5 双轨生成 - 流式输出
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
    }
  ) => {
    return streamDualTrackFn(chapterId, data, callbacks)
  },

  /**
   * V3.5 双轨生成 - 非流式（简化版）
   */
  generateDualTrackSimple: async (chapterId: string, data: any) => {
    const response = await requestRaw(`/chapters/${chapterId}/generate-dual-track-simple`, {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`双轨生成请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  }
}

export const systemApi = {
  getProxyConfig: () => requestJson('/system/proxy'),
  updateProxyConfig: (config: { enabled: boolean; url: string }) => 
    requestJson('/system/proxy', { method: 'PUT', body: JSON.stringify(config) }),
  
  /**
   * 测试模型连接
   * @param config 模型配置，包含 api_key, base_url, model, reasoning_enabled, reasoning_effort
   * @returns 测试结果，包含连接状态和推理模式支持信息
   */
  testModel: async (config: {
    api_key: string
    base_url?: string
    model: string
    reasoning_enabled?: boolean
    reasoning_effort?: string
  }): Promise<{
    success: boolean
    message: string
    model_info?: { model: string; base_url: string }
    reasoning_supported?: boolean
    reasoning_message?: string
    response_time_ms?: number
  }> => {
    return requestJson('/system/test-model', {
      method: 'POST',
      body: JSON.stringify(config)
    })
  }
}
