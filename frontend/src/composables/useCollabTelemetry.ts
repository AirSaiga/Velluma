/**
 * 协作交互埋点（roadmap P0-3，本地 jsonl 零上报——个人镜子，非增长分析）。
 *
 * `logCollabEvent`：composables / 容器用（持有 chapterId 时直接记，fire-and-forget）。
 * 展示组件请用 `collabEventBus.ts` 的 dispatchCollabEvent（零依赖，WorkspaceView 桥接）。
 */

import { adaptiveApi } from '../services/api/domain/adaptive.api'

export type CollabDetail = Record<string, unknown>

/** 直接通路：记事件（失败静默——埋点绝不阻塞写作）。 */
export function logCollabEvent(
  chapterId: string | null | undefined,
  kind: string,
  detail: CollabDetail = {},
): void {
  if (!chapterId) return
  try {
    void adaptiveApi.logCollabEvent(chapterId, kind, detail).catch(() => {})
  } catch {
    /* 静默 */
  }
}
