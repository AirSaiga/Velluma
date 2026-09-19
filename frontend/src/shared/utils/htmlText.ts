/**
 * HTML 富文本 → 纯文本 / 字数统计工具（UX 修复：字数口径统一）。
 *
 * 章节 content_text 是 TipTap getHTML() 产物（含 <p>/mark 等标签），
 * 直接取 .length 会把标签计入字数（章节越长虚高越多）。
 * 统一走「剥标签 → 去空白 → 计字符」口径（中文写作惯例按字符计）。
 */

/** 剥掉 HTML 标签取纯文本（DOM 解析，实体如 &nbsp; 会正确还原为空格）。
 * 精确路径：草稿一致性比对等「结果必须逐字符可靠」的场景用这个。 */
export function stripHtmlToText(html: string): string {
  if (!html) return ''
  if (!/<[a-z][\s\S]*>/i.test(html)) return html
  const div = document.createElement('div')
  div.innerHTML = html
  return div.textContent || ''
}

/** 章节正文字数：剥标签后去除全部空白字符的字符数。
 * 快路径纯正则（2026-09-17）：此前整章 innerHTML DOM 解析在写作台每次落库后
 * 字数重算、书架页当前书卡片每渲染都对全书 N 章各解析一遍，长章/多章时主线程
 * 抖动。字数口径只关心字符数——TipTap 产物是良构 HTML 子集，五种常见实体
 * 解码后计字符（&nbsp; 反正是空白、随 \s 一并去掉；草稿比对仍走 DOM 精确路径）。 */
export function countChapterWords(html: string): number {
  if (!html) return 0
  const text = html
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&amp;/gi, '&')
  return text.replace(/\s+/g, '').length
}

/** HTML 注入转义（popup/tooltip 拼 HTML 时的最小防线：& < > " 四字符实体化）。 */
export function escapeHtml(s: unknown): string {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string,
  )
}
