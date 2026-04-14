import { requestRaw } from '../transport'

export interface StreamSseHandlers {
  onPayload?: (payload: any) => void | boolean
  onDone?: () => void
  onError?: (message: string) => void
  tolerateIncompleteWhenHasContent?: boolean
}

export async function streamSse(
  endpoint: string,
  data: any,
  handlers: StreamSseHandlers = {},
  signal?: AbortSignal
): Promise<void> {
  const response = await requestRaw(endpoint, {
    method: 'POST',
    body: JSON.stringify(data),
    signal
  })

  if (!response.ok) {
    throw new Error(`生成请求失败: ${response.status} ${response.statusText}`)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    handlers.onError?.('无法读取响应')
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
    handlers.onDone?.()
  }

  const read = () => {
    reader
      .read()
      .then(({ done, value }) => {
        if (done) {
          finalize()
          return
        }

        const chunk = decoder.decode(value, { stream: true })
        buffer += chunk
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue

          try {
            const payload = JSON.parse(line.slice(6))
            if (payload.content) {
              hasContent = true
            }
            if (payload.error) {
              ended = true
              reader.cancel().catch(() => {})
              handlers.onError?.(payload.error)
              return
            }

            const shouldFinalize = handlers.onPayload?.(payload)
            if (shouldFinalize) {
              finalize()
              return
            }
          } catch (e) {
            console.error('streamSse JSON 解析错误', e)
          }
        }

        read()
      })
      .catch(err => {
        if (ended) return
        const message = err?.message || ''
        if (
          handlers.tolerateIncompleteWhenHasContent &&
          hasContent &&
          (message.includes('ERR_INCOMPLETE_CHUNKED_ENCODING') ||
            message.toLowerCase().includes('networkerror'))
        ) {
          finalize()
          return
        }
        handlers.onError?.(message || '未知错误')
      })
  }

  read()
}
