/**
 * 协作埋点事件总线（零依赖——展示组件可安全 import，不触及 services 层）。
 * 05 瘦身后仅机制事件走此路（hint_dismiss / ghost_adopt / ghost_discard /
 * ghost_discard_reason）；词表与消费方见 adaptive/events.py 模块头。
 */

export type CollabDetail = Record<string, unknown>

/** 展示组件通路：派发 DOM 事件（由 WorkspaceView 的监听统一转发后端）。 */
export function dispatchCollabEvent(kind: string, detail: CollabDetail = {}): void {
  window.dispatchEvent(new CustomEvent('velluma:collab-event', { detail: { kind, detail } }))
}
