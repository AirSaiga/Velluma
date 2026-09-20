/**
 * 对拍口径：锁「备份预览解析/冲突判断/文件名」三件纯函数的契约——
 * 合法备份出完整摘要、坏文件收敛成 ok=false 人话原因（不抛）、
 * 同 ID 冲突判断、文件名sanitize。改 backupPreview.ts 先跑本文件。
 */
import { describe, expect, it } from 'vitest'
import {
  BACKUP_FORMAT,
  backupFileName,
  conflictsWithShelf,
  formatExportedAt,
  parseBackupPreview,
} from '../backupPreview'

function makeBackup(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    format: BACKUP_FORMAT,
    version: 1,
    exported_at: '2026-09-19T02:03:04+00:00',
    rows: {
      books: [{ id: 'b1', title: '灯塔与雾', genre: '悬疑' }],
      chapters: [{ id: 'c1' }, { id: 'c2' }],
    },
    ...overrides,
  })
}

describe('parseBackupPreview', () => {
  it('合法备份 → 完整摘要', () => {
    const p = parseBackupPreview(makeBackup())
    expect(p.ok).toBe(true)
    expect(p.bookId).toBe('b1')
    expect(p.title).toBe('灯塔与雾')
    expect(p.genre).toBe('悬疑')
    expect(p.chapterCount).toBe(2)
    expect(p.version).toBe(1)
    expect(p.exportedAt).toBe('2026-09-19T02:03:04+00:00')
  })

  it('无书名回落「未命名」、无题材空串、无章 0 章', () => {
    const p = parseBackupPreview(makeBackup({
      rows: { books: [{ id: 'b1' }] },
    }))
    expect(p.ok).toBe(true)
    expect(p.title).toBe('未命名')
    expect(p.genre).toBe('')
    expect(p.chapterCount).toBe(0)
  })

  it('坏 JSON → ok=false 不抛', () => {
    expect(parseBackupPreview('not json{').ok).toBe(false)
  })

  it('非备份格式标记 → 拒', () => {
    expect(parseBackupPreview('{"format":"other"}').ok).toBe(false)
    expect(parseBackupPreview('null').ok).toBe(false)
    expect(parseBackupPreview('[1,2]').ok).toBe(false)
  })

  it('版本缺失/非法 → 拒', () => {
    expect(parseBackupPreview(makeBackup({ version: 'x' })).ok).toBe(false)
    expect(parseBackupPreview(makeBackup({ version: 0 })).ok).toBe(false)
  })

  it('books 行缺失/为空/无 id → 拒', () => {
    expect(parseBackupPreview(makeBackup({ rows: {} })).ok).toBe(false)
    expect(parseBackupPreview(makeBackup({ rows: { books: [] } })).ok).toBe(false)
    expect(parseBackupPreview(makeBackup({ rows: { books: [{ title: '无 id' }] } })).ok).toBe(false)
  })
})

describe('conflictsWithShelf', () => {
  const ok = parseBackupPreview(makeBackup())

  it('书架有同 ID → true', () => {
    expect(conflictsWithShelf(ok, ['other', 'b1'])).toBe(true)
  })

  it('书架无同 ID → false；解析失败 → 恒 false', () => {
    expect(conflictsWithShelf(ok, ['other'])).toBe(false)
    expect(conflictsWithShelf(parseBackupPreview('bad'), ['b1'])).toBe(false)
  })
})

describe('backupFileName', () => {
  it('含书名/日期/扩展名；Windows 保留字符被替换', () => {
    const name = backupFileName('灯塔:"雾"/', new Date(2026, 8, 19, 14, 5))
    expect(name).toBe('灯塔__雾__-备份-20260919-1405.vellumabook')
    expect(name).not.toMatch(/[:*?"<>|\\\/]/)
  })

  it('空书名回落「未命名」；补零稳定两位', () => {
    expect(backupFileName('  ', new Date(2026, 0, 2, 3, 4))).toBe('未命名-备份-20260102-0304.vellumabook')
  })
})

describe('formatExportedAt', () => {
  it('ISO → 本地 YYYY-MM-DD HH:mm', () => {
    const d = new Date(2026, 8, 19, 9, 8)
    expect(formatExportedAt(d.toISOString())).toBe('2026-09-19 09:08')
  })

  it('空串空返回；解析失败原样透传', () => {
    expect(formatExportedAt('')).toBe('')
    expect(formatExportedAt('不是时间')).toBe('不是时间')
  })
})
