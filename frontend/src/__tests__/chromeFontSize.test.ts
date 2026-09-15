import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

/**
 * Chrome 无 <12px 对拍（06 §8-N1）：
 * 豁免面（古地图三容器/书封/预览 PRESETS）与纸面/编辑器作用域之外，
 * 所有 font-size 不得低于 12px（--text-xs 是全产品最低可读档，00 期 §2.1）。
 * 裸 px 与 <0.75rem 一并扫描；❦ 饰符（.empty-state::before）是装饰图形非文字，豁免。
 */

const SRC = join(__dirname, '..')
const EXEMPT_FILES = new Set([
  'WorldMap.vue',
  'WorldView.vue',
  'WorldTimeline.vue',
  'LibraryView.vue',
  'appearancePreviewPresets.ts',
])
const SKIP_DIRS = new Set(['__tests__', '_deprecated', 'node_modules'])

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) yield* walk(p)
    else if (/\.(vue|css)$/.test(name)) yield p
  }
}

const SUB12_RE = /font-size:\s*(1[01]px|0?\.[0-7][0-9]*rem)\s*;/

function findViolations(): string[] {
  const out: string[] = []
  for (const path of walk(SRC)) {
    const base = path.split(/[\\/]/).pop()!
    if (EXEMPT_FILES.has(base)) continue
    const text = readFileSync(path, 'utf-8')
    const lines = text.split('\n')
    let sel = ''
    for (let i = 0; i < lines.length; i++) {
      const s = lines[i].trim()
      if (s.endsWith('{') || (s.includes('{') && !s.startsWith('/*'))) {
        sel = s.slice(0, s.indexOf('{')).trim() || sel
      }
      if (!s.startsWith('font-size')) continue
      if (sel.includes('.empty-state::before')) continue
      if (sel.includes('.ProseMirror') || sel.includes('ghost-draft')) continue
      const m = SUB12_RE.exec(s)
      if (m) {
        // rem 值 ≥0.75rem（12px）不算违规
        const rem = /0\.([0-9]+)rem/.exec(m[1])
        if (rem && parseInt(rem[1], 10) >= 75) continue
        out.push(`${relative(SRC, path)}:${i + 1} [${sel.slice(0, 40)}] ${m[1]}`)
      }
    }
  }
  return out
}

describe('chrome 无 <12px（N1 对拍）', () => {
  it('豁免面/纸面之外不存在低于 12px 的字号', () => {
    const violations = findViolations()
    expect(violations).toEqual([])
  })
})
