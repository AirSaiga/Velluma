/**
 * 章节正文本地草稿兜底（UX 修复：断网/关窗/保存失败不丢稿）。
 *
 * 模式复刻 useGenerationSession 的 localStorage 快照（velluma:gensess:）：
 * 编辑器防抖窗口内即写本地（不等落库），落库成功后清除，失败保留待恢复。
 * 全部读写 try/catch 静默容错——草稿是保险丝，绝不能反过来炸掉主流程。
 *
 * 生命周期：
 *   打字 → saveChapterDraft（剥幽灵后）→ 防抖落库成功 → clearChapterDraft
 *   落库失败/关窗 → 草稿残留 → 下次进章 → WorkspaceView 弹恢复确认
 */

const DRAFT_PREFIX = 'velluma:draft:'
const DRAFT_VERSION = 1

export interface ChapterDraft {
  v: number
  content: string
  savedAt: number
}

export function saveChapterDraft(chapterId: string, content: string): void {
  try {
    const draft: ChapterDraft = { v: DRAFT_VERSION, content, savedAt: Date.now() }
    localStorage.setItem(DRAFT_PREFIX + chapterId, JSON.stringify(draft))
  } catch {
    // localStorage 满/隐私模式等：静默放弃兜底，不影响编辑
  }
}

export function loadChapterDraft(chapterId: string): ChapterDraft | null {
  try {
    const raw = localStorage.getItem(DRAFT_PREFIX + chapterId)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed?.v !== DRAFT_VERSION || typeof parsed.content !== 'string') return null
    return parsed as ChapterDraft
  } catch {
    return null
  }
}

export function clearChapterDraft(chapterId: string): void {
  try {
    localStorage.removeItem(DRAFT_PREFIX + chapterId)
  } catch {
    // 静默
  }
}
