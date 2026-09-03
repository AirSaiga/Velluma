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
  // SSE 流不限总时长（timeoutMs=0）：章节生成可能数分钟，
  // 由后端心跳（每 15s 注释帧）保活 + 用户主动 cancel 控制，避免前端误杀长流。
  const response = await requestRaw(endpoint, {
    method: 'POST',
    body: JSON.stringify(data),
    signal
  }, 0)

  if (!response.ok) {
    // 提取 FastAPI 错误体的 detail（与 http.ts requestJson 的归一化对齐）——
    // 此前只拼英文 statusText，后端在 body 里给的友好说明（配额/参数错误等）被整个丢弃
    let detail = ''
    try {
      const body = await response.json()
      detail = body?.detail || ''
    } catch { /* 非 JSON 错误体忽略 */ }
    throw new Error(detail || `生成请求失败: ${response.status} ${response.statusText}`)
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
  // JSON 解析失败计数：偶发坏帧可跳过，连续失败说明协议被破坏，应显式报错而非静默吞掉
  let parseErrors = 0

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

        // 包一层 try-catch：任何解析/回调异常都不能打断递归 read()，
        // 否则流会静默死掉（后端还在跑但前端不再读，表现为"进度断掉"）
        try {
          const chunk = decoder.decode(value, { stream: true })
          buffer += chunk
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue

            try {
              const payload = JSON.parse(line.slice(6))
              // 全量日志：追踪每个到达前端的 payload（诊断 SSE 事件丢失）
              if (payload.event && payload.event !== 'HEARTBEAT') {
                console.log('[streamSse] 收到', payload.event, payload.current ? (payload.current + '/' + payload.total) : '')
              }
              // HEARTBEAT 帧直接忽略（保活用，不触发任何业务回调）
              if (payload.event === 'HEARTBEAT') {
                continue
              }
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
              // 连续失败计数（2026-09-04 修复：原累计不清零——「连续 5 帧坏帧
              // 断流」实为「累计 5 帧断流」，长流偶发坏帧会误杀健康流）
              parseErrors += 1
              if (parseErrors >= 5 && !ended) {
                ended = true
                reader.cancel().catch(() => {})
                handlers.onError?.('数据流解析失败：收到连续无效帧，请重试')
                return
              }
            }
          }
          // 有成功解析的帧 → 计数归零（恢复「连续」语义）
          parseErrors = 0
        } catch (e) {
          // 业务回调（onPayload）抛异常不应中断流读取
          console.error('[streamSse] chunk 处理异常（不中断流）', e)
        }

        // 递归继续读（关键：任何情况下都必须调 read()，否则流静默死亡）
        read()
      })
      .catch(err => {
        if (ended) return
        // 主动 abort（如 advanceBeat 中止旧流）不是错误——静默结束，
        // 否则 AbortError 会被当成生成失败把 stage 砸成 error（中止竞态）
        if (signal?.aborted) return
        const message = err?.message || ''
        console.error('[streamSse] read .catch 异常', message, err)
        if (
          handlers.tolerateIncompleteWhenHasContent &&
          hasContent &&
          (message.includes('ERR_INCOMPLETE_CHUNKED_ENCODING') ||
            message.toLowerCase().includes('networkerror'))
        ) {
          finalize()
          return
        }
        console.error('[streamSse] read 异常', message)
        handlers.onError?.(message || '未知错误')
      })
  }

  read()
}
