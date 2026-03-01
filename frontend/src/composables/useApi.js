/**
 * API 调用封装
 * 提供 Entity、Beat 和 Config 的 CRUD 操作
 */

const API_BASE = '/api'

/**
 * 通用 fetch 封装
 */
async function fetchApi(url, options = {}) {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  })
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(error.detail || '请求失败')
  }
  
  return response.json()
}

/**
 * Entity API
 */
export const entityApi = {
  // 获取所有实体
  getAll: () => fetchApi('/entities'),
  
  // 获取单个实体
  get: (id) => fetchApi(`/entities/${id}`),
  
  // 创建实体
  create: (data) => fetchApi('/entities', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  
  // 更新实体
  update: (id, data) => fetchApi(`/entities/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  }),
  
  // 删除实体
  delete: (id) => fetchApi(`/entities/${id}`, {
    method: 'DELETE'
  })
}

/**
 * Beat API
 */
export const beatApi = {
  // 获取所有节拍
  getAll: () => fetchApi('/beats'),
  
  // 获取单个节拍
  get: (id) => fetchApi(`/beats/${id}`),
  
  // 创建节拍
  create: (data) => fetchApi('/beats', {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  
  // 更新节拍
  update: (id, data) => fetchApi(`/beats/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  }),
  
  // 删除节拍
  delete: (id) => fetchApi(`/beats/${id}`, {
    method: 'DELETE'
  })
}

/**
 * Config API
 */
export const configApi = {
  // 获取配置
  get: () => fetchApi('/config'),
  
  // 更新配置
  update: (data) => fetchApi('/config', {
    method: 'POST',
    body: JSON.stringify(data)
  })
}

/**
 * 生成 API (流式)
 */
export const generateApi = {
  /**
   * 流式生成文本
   * @param {Object} data - 生成请求数据
   * @param {Function} onChunk - 接收文本片段的回调
   * @param {Function} onDone - 生成完成的回调
   * @param {Function} onError - 错误的回调
   */
  stream: (data, onChunk, onDone, onError) => {
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
      
      const reader = response.body.getReader()
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
