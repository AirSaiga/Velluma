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

/**
 * 发起原始 fetch 请求（用于 SSE 流式响应）。
 *
 * @param timeoutMs 总超时（毫秒）。设为 0 表示不设总超时——适用于 SSE 流，
 *   因流的生命周期可能远超普通请求（章节生成可达数分钟）。
 *   设为 0 时仅保留调用方传入的 signal（如用户主动 cancel），
 *   连接保活由后端心跳 + 前端 cancel 共同负责。
 *   默认 300000（300s）保持向后兼容。
 */
export async function requestRaw(path: string, options: FetchOptions = {}, timeoutMs = 300000): Promise<Response> {
  const baseUrl = await getApiBase()

  // timeoutMs=0：流式响应不限总时长，不创建超时 controller（避免误杀长耗时流）
  const controller = timeoutMs > 0 ? new AbortController() : null
  const timeoutId = controller ? setTimeout(() => controller.abort(), timeoutMs) : null

  try {
    const response = await fetch(`${baseUrl}${path}`, createRequestInit({
      ...options,
      signal: options.signal || (controller?.signal)
    }))
    return response
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      // 仅当超时 controller 触发时给出超时文案；用户主动 cancel（options.signal）不应被当作"超时"
      if (timeoutId && controller?.signal.aborted) {
        throw new Error(`请求超时（${timeoutMs / 1000}秒），请检查网络或稍后重试`)
      }
      // 用户主动取消：原样抛出 AbortError，让上层（streamSse/cancel）处理
      throw error
    }
    throw error
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }
}
