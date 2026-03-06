import { getApiBase } from './base'

export interface FetchOptions {
  method?: string
  headers?: Record<string, string>
  body?: string
}

function createRequestInit(options: FetchOptions): RequestInit {
  const requestInit: RequestInit = {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    }
  }

  if (options.method) {
    requestInit.method = options.method
  }

  if (options.body) {
    requestInit.body = options.body
  }

  return requestInit
}

export async function requestJson(path: string, options: FetchOptions = {}) {
  const baseUrl = await getApiBase()
  const response = await fetch(`${baseUrl}${path}`, createRequestInit(options))

  const contentType = response.headers.get('content-type')
  if (contentType && contentType.includes('text/html')) {
    const text = await response.text()
    console.error(`API 请求返回了 HTML 而不是 JSON。URL: ${baseUrl}${path}`, text.substring(0, 200))
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

export async function requestRaw(path: string, options: FetchOptions = {}): Promise<Response> {
  const baseUrl = await getApiBase()
  return fetch(`${baseUrl}${path}`, createRequestInit(options))
}
