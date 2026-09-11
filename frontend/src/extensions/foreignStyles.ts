/**
 * 外来行内样式净化（写作台，2026-09-10）。
 *
 * 病灶实测：从网页/Word/别处粘进正文的 `<span style="color: rgb(43, 45, 49)">`
 * 会作为 textStyle 标记留在文档里（存量章节里就有）——浅色主题下是深灰，
 * **深色主题下就是深色纸面上的深色字，直接读不出来**，而作者按遍主题开关
 * 都找不到原因（样式在正文里，不在主题里）。
 *
 * 两个入口共用同一张清单（单一权威）：
 * - 粘贴侧：`transformPastedHTML` 里剥掉（治未病——不让外来色进文档）；
 * - 存量侧：「清除外来样式」命令剥掉对应标记（治已病——正文里已有的）。
 *
 * 只剥「描述长相」的属性，粗体/斜体/下划线/删除线/上下标是作者的排版意图，
 * 一律保留。
 */

/** 会被剥掉的行内样式属性（长相类：颜色/底色/字体族字号/行距字距/阴影） */
export const FOREIGN_STYLE_PROPS = new Set([
  'color',
  'background',
  'background-color',
  'background-image',
  'font-family',
  'font-size',
  'line-height',
  'letter-spacing',
  'text-shadow',
])

/**
 * 纯函数：过滤一段 `style` 声明串，只留非外来属性（返回空串即整条属性可摘）。
 * 拆分为独立纯函数是为了可测——DOM 那层没法在 node 环境的单测里跑。
 */
export function scrubStyleDeclarations(raw: string): string {
  if (!raw) return ''
  const kept: string[] = []
  for (const part of raw.split(';')) {
    const decl = part.trim()
    if (!decl) continue
    const colon = decl.indexOf(':')
    // 没有冒号的不是声明（畸形残留）——一律丢弃，不留垃圾在 style 里
    if (colon === -1) continue
    const prop = decl.slice(0, colon).trim().toLowerCase()
    if (!prop || FOREIGN_STYLE_PROPS.has(prop)) continue
    kept.push(decl)
  }
  return kept.join('; ')
}

/**
 * 剥掉一段 HTML 里的外来行内样式（粘贴钩子用）。
 * 无 `style` 属性时零成本原样返回——粘贴主路径不做无谓的 DOM 解析。
 */
export function stripForeignInlineStyles(html: string): string {
  if (!html || !/style\s*=/i.test(html)) return html
  if (typeof DOMParser === 'undefined') return html
  const doc = new DOMParser().parseFromString(html, 'text/html')
  doc.querySelectorAll('[style]').forEach((el) => {
    const kept = scrubStyleDeclarations(el.getAttribute('style') || '')
    if (kept) el.setAttribute('style', kept)
    else el.removeAttribute('style')
  })
  return doc.body.innerHTML
}

/** 「清除外来样式」命令要摘的标记（与 FOREIGN_STYLE_PROPS 同源：textStyle 装颜色/字体，highlight 装底色） */
export const FOREIGN_MARK_NAMES = ['textStyle', 'highlight'] as const
