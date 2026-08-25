/**
 * 辅助层「学着闭嘴」静音清单 API（2026-08-25 战略定稿）。
 *
 * 端点 /books/{bookId}/assist-mutes（经 transport 自动加 /api 前缀）。
 * 静音集合由后端从行为数据派生（quiet_learning），此处只做读面与宽恕复位。
 */
import { requestJson } from '../transport'

export interface AssistMute {
  key: string
  label: string
  channel: 'inbox' | 'hint' | string
}

interface AssistMutesResponse {
  mutes: AssistMute[]
}

/** 当前生效的静音清单（失败返回空数组——静音面缺失不阻塞收件箱主功能）。 */
export async function getAssistMutes(bookId: string): Promise<AssistMute[]> {
  try {
    const res = await requestJson<AssistMutesResponse>(`/books/${bookId}/assist-mutes`)
    return res.mutes || []
  } catch {
    return []
  }
}

/** 宽恕复位某条静音（该键此前的拒绝记录一笔勾销）。返回复位后的清单。 */
export async function forgiveAssistMute(bookId: string, key: string): Promise<AssistMute[]> {
  const res = await requestJson<AssistMutesResponse>(`/books/${bookId}/assist-mutes/forgive`, {
    method: 'POST',
    body: JSON.stringify({ key }),
  })
  return res.mutes || []
}
