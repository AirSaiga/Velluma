/**
 * 章节落库冲刷协调：编辑器 1s 防抖保存 ↔ 「读库前必须最新」的后端动作（完稿体检等）。
 *
 * 背景：编辑器内容落库走 1s 防抖（useChapterEditorContainer.handleContentUpdate），
 * 而完稿体检以库内正文为审计对象。若防抖窗口内发枪，审计读到缺末尾的旧稿——
 * 屏上的最后一句没进库，残句检查会把完整句误报成「没写完的句子」。
 *
 * 本模块以单例注册处解耦四层组件链（WorkspaceView → ChapterEditor →
 * ChapterEditorContainer → useChapterEditorContainer）：容器登记冲刷回调，
 * WorkspaceView 登记在飞保存 Promise；消费方先 flush() 同步触发挂起保存，
 * 再 await settled() 等写库返回，保证发枪时 库内正文 = 屏上正文。
 */

let _flush: (() => void) | null = null
/** 在飞保存 Promise（最近一次 handleUpdateChapter；失败态已吞——此处只协调时序，报错归保存路径自己 toast） */
let _inflight: Promise<unknown> = Promise.resolve()

/** 容器挂载时登记、卸载时注销（null） */
export function registerPendingSaveFlush(fn: (() => void) | null): void {
  _flush = fn
}

/** WorkspaceView.handleUpdateChapter 登记在飞写库 */
export function trackChapterSave(p: Promise<unknown>): void {
  _inflight = p.catch(() => {})
}

/** 立即冲刷挂起的防抖保存（同步触发 emit；写库异步完成，配 awaitPendingSaveSettled） */
export function flushPendingChapterSave(): void {
  _flush?.()
}

/** 等待在飞写库返回（无在飞保存时立即返回） */
export async function awaitPendingSaveSettled(): Promise<void> {
  await _inflight
}
