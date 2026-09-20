/**
 * 书籍备份文件的预览解析（纯函数，不触网）。
 *
 * 职责：把 .vellumabook 备份 JSON 文本解析成「给作者看的摘要」——
 * 书名/题材/章数/导出时间，以及与书架现状的冲突判断。后端在导入时
 * 会再校验一遍（这里是预览，不是闸门）。
 */

export const BACKUP_FORMAT = 'velluma.book-backup'

export interface BackupPreview {
  ok: boolean
  /** ok=false 时给作者看的原因 */
  error?: string
  bookId?: string
  title?: string
  genre?: string
  chapterCount?: number
  /** 导出时间（ISO 原文） */
  exportedAt?: string
  /** 备份格式版本 */
  version?: number
}

/** 解析备份文件文本 → 预览摘要；任何不对都收敛成 ok=false + 人话原因 */
export function parseBackupPreview(text: string): BackupPreview {
  let data: any
  try {
    data = JSON.parse(text)
  } catch {
    return { ok: false, error: '这不是有效的 JSON 文件' }
  }
  if (!data || typeof data !== 'object' || data.format !== BACKUP_FORMAT) {
    return { ok: false, error: '这不是一份 Velluma 书籍备份文件' }
  }
  if (typeof data.version !== 'number' || data.version < 1) {
    return { ok: false, error: '备份文件版本信息缺失' }
  }
  const bookRows = data.rows?.books
  if (!Array.isArray(bookRows) || bookRows.length !== 1) {
    return { ok: false, error: '备份里缺少书籍数据' }
  }
  const book = bookRows[0] || {}
  if (!book.id) {
    return { ok: false, error: '备份里缺少书籍数据' }
  }
  return {
    ok: true,
    bookId: String(book.id),
    title: book.title || '未命名',
    genre: book.genre || '',
    chapterCount: Array.isArray(data.rows?.chapters) ? data.rows.chapters.length : 0,
    exportedAt: typeof data.exported_at === 'string' ? data.exported_at : '',
    version: data.version,
  }
}

/** 书架里已有同 ID 书（还原=原样放回，重复还原会被拒） */
export function conflictsWithShelf(preview: BackupPreview, shelfBookIds: string[]): boolean {
  return preview.ok === true && shelfBookIds.includes(preview.bookId as string)
}

/** 备份落盘文件名：{书名}-备份-{YYYYMMDD-HHmm}.vellumabook */
export function backupFileName(title: string, now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
  const safeTitle = title.replace(/[\\/:*?"<>|]/g, '_').trim() || '未命名'
  return `${safeTitle}-备份-${stamp}.vellumabook`
}

/** 导出时间人话化（ISO → 本地「YYYY-MM-DD HH:mm」；解析失败原样返回） */
export function formatExportedAt(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
