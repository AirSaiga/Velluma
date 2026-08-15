/**
 * HTML 富文本 → 纯文本 / 字数统计工具（UX 修复：字数口径统一）。
 *
 * 章节 content_text 是 TipTap getHTML() 产物（含 <p>/mark 等标签），
 * 直接取 .length 会把标签计入字数（章节越长虚高越多）。
 * 统一走「剥标签 → 去空白 → 计字符」口径（中文写作惯例按字符计）。
 */

/** 剥掉 HTML 标签取纯文本（DOM 解析，实体如 &nbsp; 会正确还原为空格）。 */
export function stripHtmlToText(html: string): string {
  if (!html) return ''
  if (!/<[a-z][\s\S]*>/i.test(html)) return html
  const div = document.createElement('div')
  div.innerHTML = html
  return div.textContent || ''
}

/** 章节正文字数：剥标签后去除全部空白字符的字符数。 */
export function countChapterWords(html: string): number {
  return stripHtmlToText(html).replace(/\s+/g, '').length
}
