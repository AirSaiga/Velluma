/**
 * API 调用封装
 * 提供 Entity、Beat 和 Config 的 CRUD 操作
 */

let API_BASE = '/api'
let API_PORT: number | null = null

/**
 * 初始化 API，获取后端端口号
 */
export async function initApi(): Promise<void> {
  try {
    const response = await fetch('/api/port')
    const data = await response.json() as { port: number }
    if (data.port) {
      API_PORT = data.port
      API_BASE = `http://localhost:${data.port}/api`
      console.log(`API 已初始化，端口: ${data.port}`)
    }
  } catch (e) {
    console.warn('无法获取端口号，使用默认相对路径')
  }
}

/**
 * 通用 fetch 封装
 */
async function fetchApi<T = any>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  })
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error((error as any).detail || '请求失败')
  }
  
  return response.json()
}

/**
 * Entity API
 */
export const entityApi = {
  getAll: () => fetchApi('/entities'),
  get: (id: string) => fetchApi(`/entities/${id}`),
  create: (data: any) => fetchApi('/entities', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  update: (id: string, data: any) => fetchApi(`/entities/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  }),
  delete: (id: string) => fetchApi(`/entities/${id}`, {
    method: 'DELETE'
  })
}

/**
 * Beat API
 */
export const beatApi = {
  getAll: () => fetchApi('/beats'),
  get: (id: string) => fetchApi(`/beats/${id}`),
  create: (data: any) => fetchApi('/beats', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  update: (id: string, data: any) => fetchApi(`/beats/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  }),
  delete: (id: string) => fetchApi(`/beats/${id}`, {
    method: 'DELETE'
  })
}

/**
 * Config API
 */
export const configApi = {
  get: () => fetchApi('/config'),
  update: (data: any) => fetchApi('/config', {
    method: 'POST',
    body: JSON.stringify(data)
  })
}

/**
 * 生成 API (流式)
 */
export const generateApi = {
  stream: (data: any, onChunk?: (chunk: string) => void, onDone?: () => void, onError?: (error: string) => void) => {
    fetch(`${API_BASE}/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    }).then(response => {
      if (!response.ok) {
        throw new Error('生成请求失败')
      }
      
      const reader = response.body?.getReader()
      if (!reader) {
        onError?.('无法读取响应')
        return
      }
      
      const decoder = new TextDecoder()
      
      function read() {
        reader.read().then(({ done, value }) => {
          if (done) {
            onDone?.()
            return
          }
          
          const chunk = decoder.decode(value, { stream: true })
          const lines = chunk.split('\n')
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.content) {
                  onChunk?.(data.content)
                } else if (data.error) {
                  onError?.(data.error)
                } else if (data.done) {
                  onDone?.()
                }
              } catch (e) {
                // 忽略解析错误
              }
            }
          }
          
          read()
        }).catch(err => {
          onError?.(err.message)
        })
      }
      
      read()
    }).catch(err => {
      onError?.(err.message)
    })
  }
}
