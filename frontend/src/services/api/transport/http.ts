import { getApiBase } from './base'

export interface FetchOptions {
  method?: string
  headers?: Record<string, string>
  body?: string
  signal?: AbortSignal
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

  if (options.signal) {
    requestInit.signal = options.signal
  }

  return requestInit
}

export async function requestJson<T = any>(path: string, options: FetchOptions = {}, timeoutMs = 300000): Promise<T> {
  const baseUrl = await getApiBase()
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${baseUrl}${path}`, createRequestInit({
      ...options,
      signal: options.signal || controller.signal
    }))

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
      return null as T
    }

    return response.json() as Promise<T>
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`请求超时（${timeoutMs / 1000}秒），请检查网络或稍后重试`)
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
}

export async function requestRaw(path: string, options: FetchOptions = {}, timeoutMs = 300000): Promise<Response> {
  const baseUrl = await getApiBase()
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${baseUrl}${path}`, createRequestInit({
      ...options,
      signal: options.signal || controller.signal
    }))
    return response
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`请求超时（${timeoutMs / 1000}秒），请检查网络或稍后重试`)
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
}
