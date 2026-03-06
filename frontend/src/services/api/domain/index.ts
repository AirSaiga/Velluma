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
    requestJson(`/books/${id}/worldview`, { method: 'PATCH', body: JSON.stringify(data) })
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
    requestJson(`/chapters/${chapterId}/generate-embedding`, { method: 'POST', body: JSON.stringify(apiConfig || {}) })
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
  stream: async (data: any, onChunk?: (chunk: string) => void, onDone?: () => void, onError?: (error: string) => void) => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.stream: 开始请求', { baseUrl, chapter_id: data.chapter_id })

    streamSse('/generate_chapter', data, {
      tolerateIncompleteWhenHasContent: true,
      onPayload: payload => {
        console.log('[DEBUG] generateApi.stream: 收到数据', {
          hasContent: !!payload.content,
          hasError: !!payload.error,
          hasDone: !!payload.done,
          hasPrompt: !!payload.prompt
        })
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
      console.error('[DEBUG] generateApi.stream: fetch 错误', err)
      onError?.(err.message)
    })
  },

  generateSync: async (data: any) => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.generateSync: 开始请求', { baseUrl, chapter_id: data.chapter_id })

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

  previewAgenticBeats: async (data: any) => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.previewAgenticBeats: 开始请求', { baseUrl, chapter_id: data.chapter_id })

    const response = await requestRaw('/generate_chapter_agentic_preview_beats', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`节拍预览请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  },

  streamAgentic: async (
    data: any,
    callbacks: {
      onEvent?: (event: string, data: any) => void
      onChunk?: (chunk: string) => void
      onDone?: (result: any) => void
      onError?: (error: string) => void
    },
    endpoint = '/generate_chapter_agentic'
  ) => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.streamAgentic: 开始请求', { baseUrl, chapter_id: data.chapter_id })

    let hasCompleted = false

    streamSse(endpoint, data, {
      onPayload: payload => {
        console.log('[DEBUG] generateApi.streamAgentic: 收到数据', {
          event: payload.event,
          hasContent: !!payload.content,
          hasError: !!payload.error,
          hasDone: !!payload.done
        })

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
          console.warn('[DEBUG] generateApi.streamAgentic: 流意外结束，未收到 DONE 事件')
          callbacks.onError?.('生成过程意外中断，未收到完成信号')
        }
      },
      onError: message => {
        hasCompleted = true
        callbacks.onError?.(message)
      }
    }).catch(err => {
      console.error('[DEBUG] generateApi.streamAgentic: fetch 错误', err)
      if (!hasCompleted) {
        callbacks.onError?.(err.message)
      }
    })
  }
}
