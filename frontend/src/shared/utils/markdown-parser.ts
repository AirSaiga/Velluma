/**
 * Markdown → HTML 解析纯函数（Markdown 导入功能专用）。
 *
 * 职责：将 .md 文件内容转为 TipTap StarterKit 可原生渲染的 HTML。
 * 业务场景：批量导入 .md 章节时，前端读取文件 → 调用本函数 → HTML 写入 content_text。
 *
 * 设计要点：
 * - html: false —— 禁止 .md 内嵌原始 HTML，防止注入（markdown-it 会转义为文本）
 * - breaks: true —— 单 \n → <br>，贴合小说写作的细段落习惯
 * - 预处理剥离图片/链接 URL（TipTap StarterKit 无对应节点，保留 alt 文本）
 *
 * 依赖项：markdown-it
 */
import MarkdownIt from 'markdown-it'

const mdInstance = new MarkdownIt({
  html: false, // 禁止原始 HTML 嵌入（安全）
  breaks: true, // 单换行 → <br>
  linkify: true, // 自动识别 URL
  typographer: false, // 不转换智能引号（中文小说需保留原标点）
})

/**
 * 移除 TipTap StarterKit 不支持的 Markdown 语法（图片、链接 URL）。
 * 保留替代文字/链接文字，仅丢弃目标地址。
 */
function stripUnsupportedSyntax(md: string): string {
  // 图片：![alt](url) → alt（保留替代文字，若无 alt 则移除整段）
  let out = md.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
  // 链接：[text](url) → text（保留文字，丢 URL）
  out = out.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
  return out
}

/**
 * 将 Markdown 字符串转为 HTML。
 *
 * 处理链：移除 BOM → 统一换行 → 剥离不支持语法 → markdown-it 渲染。
 *
 * Args:
 *   markdown: .md 文件的原始文本内容
 *
 * Returns:
 *   可被 TipTap setContent() 直接消费的 HTML 字符串
 */
export function markdownToHtml(markdown: string): string {
  if (!markdown) return ''
  const cleaned = stripUnsupportedSyntax(markdown)
    .replace(/^\uFEFF/, '') // 移除 BOM
    .replace(/\r\n/g, '\n') // 统一换行
  return mdInstance.render(cleaned).trim()
}

/**
 * 从 HTML 中提取纯文本并计算字数（用于预览表格的字数列）。
 *
 * Args:
 *   html: markdownToHtml 的输出
 *
 * Returns:
 *   去除标签后的纯文本长度
 */
export function htmlPlainTextLength(html: string): number {
  if (!html) return 0
  return html.replace(/<[^>]+>/g, '').replace(/\s/g, '').length
}

/**
 * 从文件名推断章节名。
 *
 * 规则：去掉扩展名 → 去掉前导数字和常见分隔符（- _ 空格）→ 返回剩余文字。
 * 示例：'01-序幕.md' → '序幕'；'第二章 相遇.md' → '第二章 相遇'；'notes.md' → 'notes'
 *
 * Args:
 *   fileName: 原始文件名（含扩展名）
 *
 * Returns:
 *   推断出的章节名
 */
export function inferChapterName(fileName: string): string {
  // 去扩展名
  const baseName = fileName.replace(/\.(md|markdown|MD|Markdown)$/i, '')
  // 去前导数字 + 分隔符（如 "01-"、"01_"、"01 "）
  const stripped = baseName.replace(/^\d+\s*[-_\]\)\.\s]+\s*/, '')
  return stripped.trim() || baseName.trim()
}

/** splitMarkdownByH1 返回的单个分片 */
export interface MarkdownSection {
  /** 从一级标题提取的标题文字（无 # 前缀） */
  title: string
  /** 该分片的 Markdown 正文（含 # 标题行，可直接传给 markdownToHtml） */
  markdown: string
}

/** parseChapterHeading 返回的解析结果 */
export interface ChapterHeadingParse {
  /** 从标题中提取的章节号（如 "第3章" → 3）；提取不到则为 null */
  number: number | null
  /** 去掉章节号前缀后的标题文字；无前缀则为原标题 */
  name: string
}

/**
 * 从 H1 标题文字中解析章节号与章节名。
 *
 * 支持的中文/阿拉伯数字章节号格式（含可选空格/分隔符）：
 *   "第一章 序幕"     → { number: 1, name: "序幕" }
 *   "第3章  山雨欲来"  → { number: 3, name: "山雨欲来" }
 *   "第二十三章 相遇" → { number: 23, name: "相遇" }
 *   "第123章"         → { number: 123, name: "" }
 *   "序幕"            → { number: null, name: "序幕" }
 *
 * Args:
 *   heading: H1 标题文字（已去掉 # 前缀，可含首尾空白）
 *
 * Returns:
 *   { number, name }
 */
export function parseChapterHeading(heading: string): ChapterHeadingParse {
  const trimmed = heading.trim()
  if (!trimmed) return { number: null, name: '' }

  // 中文数字 → 阿拉伯数字
  const CN_DIGIT: Record<string, number> = {
    零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5,
    六: 6, 七: 7, 八: 8, 九: 9,
  }
  // 复合：十=10, 二十=20...; 百/千同理。逐字符解析。
  function cnToNumber(s: string): number {
    let total = 0
    let current = 0
    for (const ch of s) {
      if (ch === '十') {
        total += (current || 1) * 10
        current = 0
      } else if (ch === '百') {
        total += (current || 1) * 100
        current = 0
      } else if (ch === '千') {
        total += (current || 1) * 1000
        current = 0
      } else if (ch in CN_DIGIT) {
        current = CN_DIGIT[ch]
      }
    }
    return total + current
  }

  // 匹配 "第<数字>章"，数字可为阿拉伯（1-9999）或中文（一/二.../二十三）
  // 后跟可选分隔符（空格、: ：. 、）和剩余标题文字
  // 匹配阿拉伯数字：第1章 / 第 12 章
  const arMatch = trimmed.match(/^第\s*(\d{1,4})\s*章\s*[:：.、\s]*(.*)$/)
  if (arMatch) {
    return { number: parseInt(arMatch[1], 10), name: arMatch[2].trim() }
  }
  // 匹配中文数字：第一章 / 第二十三章 / 第一百零五章
  const cnMatch = trimmed.match(/^第\s*([零〇一二两三四五六七八九十百千]+)\s*章\s*[:：.、\s]*(.*)$/)
  if (cnMatch) {
    const num = cnToNumber(cnMatch[1])
    if (num > 0) return { number: num, name: cnMatch[2].trim() }
  }

  // 无章节号前缀
  return { number: null, name: trimmed }
}

/**
 * 按一级标题（`#`）拆分 Markdown 文本为多个章节分片。
 *
 * 规则：
 * - 仅匹配行首恰好一个 `#` 后跟空格的标题（`# 标题`），不匹配 `##`/`###` 等多级标题
 * - 每个分片的 markdown **不含**标题行本身，仅含标题之后到下一个标题之前的正文
 * - 第一个 # 之前的内容（前言/元信息）**丢弃**（不并入任何章节）
 * - 无任何 # 标题时返回单个分片（markdown=原文，title=空串，由调用方回退到文件名）
 *
 * Args:
 *   markdown: 已去 BOM/统一换行的原始 Markdown 文本
 *
 * Returns:
 *   分片数组（至少 1 个元素）
 */
export function splitMarkdownByH1(markdown: string): MarkdownSection[] {
  const lines = markdown.split('\n')
  // 匹配行首恰好一个 # 后跟空格：# 标题（不匹配 ## 标题）
  const H1_RE = /^#\s+(.+?)\s*$/

  const sections: { title: string; lines: string[] }[] = []
  let current: { title: string; lines: string[] } | null = null

  for (const line of lines) {
    const match = line.match(H1_RE)
    if (match) {
      // 命中新的 H1：收尾当前分片，开启新分片（lines 从空开始，不含标题行）
      current = { title: match[1], lines: [] }
      sections.push(current)
    } else if (current) {
      // 标题后的正文行，追加到当前分片（不含标题本身）
      current.lines.push(line)
    }
    // 第一个 H1 之前的行（前言）直接跳过，不并入任何章节
  }

  // 无任何 H1：原文整体作为一个分片（title 为空，调用方回退到文件名）
  if (sections.length === 0) {
    return [{ title: '', markdown: markdown.trim() }]
  }

  return sections.map((s) => ({
    title: s.title,
    markdown: s.lines.join('\n').trim(),
  }))
}
