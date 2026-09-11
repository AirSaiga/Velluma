/**
 * 文本块 → 扁平纯文本 + 偏移映射（写作台编辑器基础设施，2026-09-10）。
 *
 * 「按字符串判据改文档」这件事的共同底座：标点归一（chineseTypography）与
 * 查找替换（editorFind）都要先把一个段落拍平成一段可跑字符串规则的文本，
 * 再把字符串上的偏移映射回 ProseMirror 文档位置。两处各写一份必然走形，
 * 这里收成单一权威。
 *
 * 两条契约：
 * - 行内格式（加粗/颜色残留）会把一句话切成多个文本节点，所以**按块整体拼装**，
 *   规则才看得见「前一位在隔壁节点」的情况；
 * - 原子节点（@提及/细纲胶囊）与（可选）幽灵草稿以 `\ufffc` 占位：既保住
 *   偏移映射，又让跨过它们的匹配天然失效（宁漏勿误——绝不对原子内部动手）。
 */

export interface TextSpan {
  /** 块内文本偏移起点 */
  textStart: number
  /** 块内文本偏移终点（不含） */
  textEnd: number
  /** 对应的文档位置 */
  docStart: number
}

export interface BlockTextMap {
  text: string
  spans: TextSpan[]
  /** 块内文本偏移 → 文档位置；落到占位/映射之外返回 null */
  toDoc: (offset: number, endBias?: boolean) => number | null
}

/**
 * @param block    文本块节点（paragraph/heading/…）
 * @param blockPos 该节点在文档中的起始位置
 * @param skipGhost 幽灵草稿（未确认的 AI 中间态）是否排除在可改文本之外
 *                  ——标点归一=排除（不属于正文），查找=包含（屏幕上看得见）
 */
export function buildBlockTextMap(
  block: any,
  blockPos: number,
  opts: { skipGhost?: boolean } = {},
): BlockTextMap {
  const spans: TextSpan[] = []
  let text = ''

  block.forEach((child: any, offset: number) => {
    if (!child.isText) {
      text += '\ufffc'
      return
    }
    if (opts.skipGhost && child.marks.some((m: any) => m.type.name === 'ghostDraft')) {
      text += '\ufffc'
      return
    }
    spans.push({ textStart: text.length, textEnd: text.length + child.text.length, docStart: blockPos + 1 + offset })
    text += child.text
  })

  const toDoc = (offset: number, endBias = false): number | null => {
    for (const s of spans) {
      const hit = endBias
        ? offset > s.textStart && offset <= s.textEnd
        : offset >= s.textStart && offset < s.textEnd
      if (hit) return s.docStart + (offset - s.textStart)
    }
    return null
  }

  return { text, spans, toDoc }
}
