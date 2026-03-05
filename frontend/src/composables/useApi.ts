const API_BASE = '/api'

let cachedPort: number | null = null

// 尝试从 URL 参数获取后端端口（Electron 注入）
try {
  const urlParams = new URLSearchParams(window.location.search)
  const portParam = urlParams.get('backendPort')
  if (portParam && portParam !== 'null' && portParam !== 'undefined') {
    const port = parseInt(portParam, 10)
    if (!isNaN(port) && port > 0) {
      cachedPort = port
      console.log(`✅ 从 URL 参数获取到后端端口: ${cachedPort}`)
    }
  }
} catch (e) {
  console.warn('解析 URL 参数失败', e)
}

async function getBackendPort(): Promise<number> {
  if (cachedPort) return cachedPort
  
  try {
    const portRes = await fetch('/api/port')
    if (portRes.ok) {
      const data = await portRes.json()
      if (data.port) {
        cachedPort = data.port
        return cachedPort
      }
    }
  } catch (e) {
    console.warn('获取后端端口失败，使用默认端口')
  }
  
  cachedPort = 8002
  return 8002
}

async function getApiBase(): Promise<string> {
  const isDevServer = window.location.port !== '' && [5173, 5174, 5175, 5176, 5177].includes(parseInt(window.location.port))
  
  if (isDevServer) {
    const port = await getBackendPort()
    return `http://127.0.0.1:${port}/api`
  }
  
  return API_BASE
}

interface FetchOptions {
  method?: string
  headers?: Record<string, string>
  body?: string
}

let apiBasePromise: Promise<string> | null = null

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

async function fetchApi(url: string, options: FetchOptions = {}) {
  if (!apiBasePromise) {
    apiBasePromise = getApiBase()
  }
  const baseUrl = await apiBasePromise
  
  const fetchOptions: RequestInit = {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    }
  }
  
  if (options.method) fetchOptions.method = options.method
  if (options.body) fetchOptions.body = options.body
  
  const response = await fetch(`${baseUrl}${url}`, fetchOptions)
  
  // 检查 Content-Type 是否为 JSON
  const contentType = response.headers.get('content-type')
  if (contentType && contentType.includes('text/html')) {
    const text = await response.text()
    // 如果返回的是 HTML（可能是 404 页或 index.html），抛出更明确的错误
    console.error(`API 请求返回了 HTML 而不是 JSON。URL: ${baseUrl}${url}`, text.substring(0, 200))
    throw new Error('API 服务异常，返回了 HTML 页面。这通常是因为后端服务未重启或路由配置错误。请重启后端服务。')
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(error.detail || '请求失败')
  }
  
  if (response.status === 204) {
    return null
  }
  
  return response.json()
}

export const bookApi = {
  getAll: () => fetchApi('/books'),
  get: (id) => fetchApi(`/books/${id}`),
  create: (data) => fetchApi('/books', { method: 'POST', body: JSON.stringify(data) }),
  update: (id, data) => fetchApi(`/books/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id) => fetchApi(`/books/${id}`, { method: 'DELETE' }),
  getWorldview: (id) => fetchApi(`/books/${id}/worldview`),
  updateWorldview: (id, data) => fetchApi(`/books/${id}/worldview`, { method: 'PATCH', body: JSON.stringify(data) })
}

export const characterApi = {
  getAll: (bookId) => {
    const url = bookId ? `/books/${bookId}/characters` : '/characters'
    return fetchApi(url)
  },
  get: (id) => fetchApi(`/characters/${id}`),
  create: (data) => fetchApi('/characters', { method: 'POST', body: JSON.stringify(data) }),
  update: (id, data) => fetchApi(`/characters/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id) => fetchApi(`/characters/${id}`, { method: 'DELETE' }),
  updateDynamicState: (id, data) => fetchApi(`/characters/${id}/update-dynamic-state`, { method: 'POST', body: JSON.stringify(data) })
}

export const chapterApi = {
  getAll: (bookId) => {
    const url = bookId ? `/books/${bookId}/chapters` : '/chapters'
    return fetchApi(url)
  },
  get: (id) => fetchApi(`/chapters/${id}`),
  create: (data) => fetchApi(`/books/${data.book_id}/chapters`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id, data) => fetchApi(`/chapters/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id) => fetchApi(`/chapters/${id}`, { method: 'DELETE' }),
  getEntities: (chapterId) => fetchApi(`/chapters/${chapterId}/entities`),
  updateEntities: (chapterId, entityIds) => fetchApi(`/chapters/${chapterId}/entities`, { method: 'PUT', body: JSON.stringify(entityIds) }),
  publish: (chapterId, data) => fetchApi(`/chapters/${chapterId}/publish`, { method: 'PATCH', body: JSON.stringify(data || {}) }),
  generateEmbedding: (chapterId, apiConfig) => fetchApi(`/chapters/${chapterId}/generate-embedding`, { method: 'POST', body: JSON.stringify(apiConfig || {}) })
}

export const relationshipApi = {
  getAll: (bookId) => {
    const url = bookId ? `/relationships?book_id=${bookId}` : '/relationships'
    return fetchApi(url)
  },
  create: (data) => fetchApi('/relationships', { method: 'POST', body: JSON.stringify(data) }),
  update: (id, data) => fetchApi(`/relationships/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id) => fetchApi(`/relationships/${id}`, { method: 'DELETE' })
}

export const mapApi = {
  getLocations(bookId: string) {
    return fetchApi(`/books/${bookId}/locations`)
  },
  createLocation(bookId: string, data: any) {
    return fetchApi(`/books/${bookId}/locations`, {
      method: 'POST',
      body: JSON.stringify({ ...data, book_id: bookId })
    })
  },
  updateLocation(id: string, data: any) {
    return fetchApi(`/locations/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    })
  },
  deleteLocation(id: string) {
    return fetchApi(`/locations/${id}`, {
      method: 'DELETE'
    })
  },
  getChapterLocations(chapterId: string) {
    return fetchApi(`/chapters/${chapterId}/locations`)
  },
  addLocationToChapter(chapterId: string, locationId: string) {
    return fetchApi(`/chapters/${chapterId}/locations`, {
      method: 'POST',
      body: JSON.stringify({ location_id: locationId })
    })
  },
  removeLocationFromChapter(chapterId: string, locationId: string) {
    return fetchApi(`/chapters/${chapterId}/locations/${locationId}`, {
      method: 'DELETE'
    })
  }
}

export const generateApi = {
  stream: async (data, onChunk, onDone, onError) => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.stream: 开始请求', { baseUrl, chapter_id: data.chapter_id })
    
    fetch(`${baseUrl}/generate_chapter`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).then(response => {
      console.log('[DEBUG] generateApi.stream: 收到响应', { status: response.status, ok: response.ok, statusText: response.statusText })
      
      if (!response.ok) {
        throw new Error(`生成请求失败: ${response.status} ${response.statusText}`)
      }
      
      const reader = response.body?.getReader()
      if (!reader) {
        console.error('[DEBUG] generateApi.stream: 无法获取 reader')
        onError?.('无法读取响应')
        return
      }
      
      const decoder = new TextDecoder()
      let buffer = ''
      let ended = false
      let hasContent = false
      
      const finalize = () => {
        if (ended) return
        ended = true
        reader.cancel().catch(() => {})
        onDone?.()
      }
      
      function read() {
        reader.read().then(({ done, value }) => {
          console.log('[DEBUG] generateApi.stream: read()', { done, valueLength: value?.length })
          
          if (done) {
            finalize()
            return
          }
          
          const chunk = decoder.decode(value, { stream: true })
          console.log('[DEBUG] generateApi.stream: 解码 chunk', { chunkLength: chunk.length })
          
          buffer += chunk
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                console.log('[DEBUG] generateApi.stream: 收到数据', { hasContent: !!data.content, hasError: !!data.error, hasDone: !!data.done, hasPrompt: !!data.prompt })
                if (data.prompt) {
                  publishPromptData(data.prompt)
                } else if (data.content) {
                  hasContent = true
                  onChunk?.(data.content)
                } else if (data.error) {
                  ended = true
                  reader.cancel().catch(() => {})
                  onError?.(data.error)
                  return
                } else if (data.done) {
                  finalize()
                  return
                }
              } catch (e) {
                console.error('[DEBUG] generateApi.stream: JSON 解析错误', e)
              }
            }
          }
          
          read()
        }).catch(err => {
          console.error('[DEBUG] generateApi.stream: read() 错误', err)
          
          if (ended) return
          const message = err?.message || ''
          if (hasContent && message.includes('ERR_INCOMPLETE_CHUNKED_ENCODING')) {
            console.log('[DEBUG] generateApi.stream: 检测到 ERR_INCOMPLETE_CHUNKED_ENCODING 但已有内容，视为完成')
            finalize()
            return
          }
          if (hasContent && message.toLowerCase().includes('networkerror')) {
            console.log('[DEBUG] generateApi.stream: 检测到 networkerror 但已有内容，视为完成')
            finalize()
            return
          }
          onError?.(message)
        })
      }
      
      read()
    }).catch(err => {
      console.error('[DEBUG] generateApi.stream: fetch 错误', err)
      onError?.(err.message)
    })
  },
  
  generateSync: async (data) => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.generateSync: 开始请求', { baseUrl, chapter_id: data.chapter_id })
    
    const response = await fetch(`${baseUrl}/generate_chapter_sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
    
    if (!response.ok) {
      throw new Error(`生成请求失败: ${response.status} ${response.statusText}`)
    }
    
    return await response.json()
  },

  previewAgenticBeats: async (data) => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.previewAgenticBeats: 开始请求', { baseUrl, chapter_id: data.chapter_id })

    const response = await fetch(`${baseUrl}/generate_chapter_agentic_preview_beats`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`节拍预览请求失败: ${response.status} ${response.statusText}`)
    }

    return await response.json()
  },

  streamAgentic: async (data, callbacks: {
    onEvent?: (event: string, data: any) => void,
    onChunk?: (chunk: string) => void,
    onDone?: (result: any) => void,
    onError?: (error: string) => void
  }, endpoint = '/generate_chapter_agentic') => {
    const baseUrl = await getApiBase()
    console.log('[DEBUG] generateApi.streamAgentic: 开始请求', { baseUrl, chapter_id: data.chapter_id })
    
    fetch(`${baseUrl}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).then(response => {
      console.log('[DEBUG] generateApi.streamAgentic: 收到响应', { status: response.status, ok: response.ok, statusText: response.statusText })
      
      if (!response.ok) {
        throw new Error(`生成请求失败: ${response.status} ${response.statusText}`)
      }
      
      const reader = response.body?.getReader()
      if (!reader) {
        console.error('[DEBUG] generateApi.streamAgentic: 无法获取 reader')
        callbacks.onError?.('无法读取响应')
        return
      }
      
      const decoder = new TextDecoder()
      let buffer = ''
      let ended = false
      
      const finalize = () => {
        if (ended) return
        ended = true
        reader.cancel().catch(() => {})
      }
      
      function read() {
        reader.read().then(({ done, value }) => {
          console.log('[DEBUG] generateApi.streamAgentic: read()', { done, valueLength: value?.length })
          
          if (done) {
            finalize()
            return
          }
          
          const chunk = decoder.decode(value, { stream: true })
          console.log('[DEBUG] generateApi.streamAgentic: 解码 chunk', { chunkLength: chunk.length })
          
          buffer += chunk
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                console.log('[DEBUG] generateApi.streamAgentic: 收到数据', { event: data.event, hasContent: !!data.content, hasError: !!data.error, hasDone: !!data.done })
                if (data.prompt) {
                  publishPromptData(data.prompt)
                }
                
                if (data.error) {
                  ended = true
                  reader.cancel().catch(() => {})
                  callbacks.onError?.(data.error)
                  return
                }
                
                if (data.event) {
                  callbacks.onEvent?.(data.event, data)
                  
                  if (data.event === 'TEXT_CHUNK' && data.content) {
                    callbacks.onChunk?.(data.content)
                  } else if (data.event === 'DONE') {
                    callbacks.onDone?.({
                      passed: data.passed,
                      iterations: data.iterations,
                      revision_count: data.revision_count
                    })
                    finalize()
                    return
                  }
                }
              } catch (e) {
                console.error('[DEBUG] generateApi.streamAgentic: JSON 解析错误', e)
              }
            }
          }
          
          read()
        }).catch(err => {
          console.error('[DEBUG] generateApi.streamAgentic: read() 错误', err)
          if (ended) return
          callbacks.onError?.(err?.message || '未知错误')
        })
      }
      
      read()
    }).catch(err => {
      console.error('[DEBUG] generateApi.streamAgentic: fetch 错误', err)
      callbacks.onError?.(err.message)
    })
  }
}
