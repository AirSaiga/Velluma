import { Extension, InputRule } from '@tiptap/core'
import type { Editor } from '@tiptap/core'
import { buildBlockTextMap } from './blockTextMap'

/**
 * 中文标点规范化（写作台排版基线，2026-09-10）。
 *
 * 治的是「中文小说正文里混着 ASCII 标点」——实测存量：19 章里 8 章用 `...`
 * 当省略号（渲染成基线小三点，与全角 `……` 的中线六点不是一回事），另有
 * 粘贴残留的半角逗号/句号。中文输入法在中文标点态下本就产全角，本模块是
 * 给「切到英文标点态」「从别处粘来」「AI 生成回灌」这三种情况兜底。
 *
 * 两个消费面共用同一套判据（单一权威，规则改这里一处即可）：
 * - 输入侧：ChineseTypography 扩展的 InputRules，作者打字即正（落库前就对了）；
 * - 批处理侧：normalizeDocumentPunctuation()，对既有正文一次性归一。
 *
 * **判据铁律：只在中日韩上下文里动手**（`宁漏勿误`）。前一位是中文/中文标点
 * 才认作「这是中文句子里的半角标点」。所以 `3.5`、`1,000`、`Mr. Smith`、
 * `Hello... world` 一律原样——它们的邻居是数字或拉丁字母，不是中文。
 */

/** 中日韩上下文类：汉字/假名 + CJK 标点（、。》《「」）+ 全角形式 + 弯引号/省略号 */
export const CJK_CONTEXT_CLASS =
  '\\u2018-\\u201f\\u2026\\u3000-\\u303f\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\ufe30-\\ufe4f\\uff00-\\uffef'

const CJK_RE = new RegExp(`[${CJK_CONTEXT_CLASS}]`)

/** 文本里是否含中文（智能引号规则的开关判据） */
export function hasCjk(text: string): boolean {
  return CJK_RE.test(text)
}

const CJK_CLASS = `[${CJK_CONTEXT_CLASS}]`

/** 半角 → 全角映射（前一位是中文才动） */
const HALF_TO_FULL: Record<string, string> = {
  ',': '，',
  ';': '；',
  ':': '：',
  '?': '？',
  '!': '！',
  '.': '。',
  '(': '（',
  ')': '）',
}

/** 全角标点的开/闭集合（空格清理判据） */
const OPEN_PUNCT = '（【《「『“'
const CLOSE_PUNCT = '，。！？；：、）】》」』”'

/** 一处替换：把块内文本 [start, end) 换成 text（位置=块内文本偏移，不是文档位置） */
export interface PunctEdit {
  start: number
  end: number
  text: string
}

/**
 * 纯函数：扫出全部标点归一替换（单一实现——`normalizeChinesePunctuation` 与
 * 文档批处理都从这里取判据，保证「打字即正」与「一键归一」结果逐字一致）。
 *
 * 逐字符单遍扫描而不是多遍正则替换：替换会改长度，多遍正则的位置在下一遍里
 * 就失真了，而批处理必须拿到精确的 [start,end) 才能映射回 ProseMirror 位置。
 */
export function punctuationEdits(text: string): PunctEdit[] {
  const edits: PunctEdit[] = []
  const cjk = (ch: string | undefined): boolean => !!ch && CJK_RE.test(ch)
  let i = 0

  while (i < text.length) {
    const ch = text[i]
    const prev = i > 0 ? text[i - 1] : ''

    // ① 点列：3 个及以上的 ASCII 句点/全角句号（中点被逐字转换后的混合形态也算）
    //    → 中文省略号 `……`。前一位或后一位是中文即认。
    if (ch === '.' || ch === '。') {
      let j = i
      while (j < text.length && (text[j] === '.' || text[j] === '。')) j += 1
      if (j - i >= 3 && (cjk(prev) || cjk(text[j]))) {
        edits.push({ start: i, end: j, text: '……' })
        i = j
        continue
      }
    }

    // ② 破折号：`--` → `——`（同省略号，认相邻中文）
    if (ch === '-') {
      let j = i
      while (j < text.length && text[j] === '-') j += 1
      if (j - i >= 2 && (cjk(prev) || cjk(text[j]))) {
        edits.push({ start: i, end: j, text: '——' })
        i = j
        continue
      }
    }

    // ③ 直引号成对 → 中文引号：只认同一行内成对、且引号里含中文的
    //    （英文引文/代码串原样；`don't` 这类单个撇号不成对，绝不误配）
    //    只给两个引号记账、**不跳过引号里的内容**——引号内的半角标点/省略号
    //    要由 ④① 在同一遍里接着收（跳过会让同一段文本第二遍才收敛，破坏幂等）
    if (ch === '"' || ch === "'") {
      const close = text.indexOf(ch, i + 1)
      const lineEnd = text.indexOf('\n', i + 1)
      if (close > i && (lineEnd === -1 || close < lineEnd)) {
        const inner = text.slice(i + 1, close)
        if (inner.length <= 200 && hasCjk(inner)) {
          edits.push({ start: i, end: i + 1, text: ch === '"' ? '“' : '‘' })
          edits.push({ start: close, end: close + 1, text: ch === '"' ? '”' : '’' })
        }
      }
    }

    // ④ 半角标点 → 全角（前一位是中文才动）。
    //    句号额外排除「前一位是 `。`」——否则 `...` 会逐字变成 `。。。` 而不是 `……`。
    if (cjk(prev) && HALF_TO_FULL[ch] && !(ch === '.' && prev === '。')) {
      edits.push({ start: i, end: i + 1, text: HALF_TO_FULL[ch] })
      i += 1
      continue
    }

    // ⑤ 全角标点两侧的 ASCII 空格（中文排版里恒为误敲）：闭合标点前 / 开启标点后
    if (ch === ' ' || ch === '\t') {
      let j = i
      while (j < text.length && (text[j] === ' ' || text[j] === '\t')) j += 1
      if (CLOSE_PUNCT.includes(text[j]) || OPEN_PUNCT.includes(prev)) {
        edits.push({ start: i, end: j, text: '' })
      }
      i = j
      continue
    }

    i += 1
  }

  // 契约：按位置升序返回（调用方靠它做「游标推进」的拼接）。
  // 引号规则会在处理左引号时顺手记下右引号的账，天然晚于引号内部的标点，
  // 所以这里必须显式排序——不排会让替换拼接错位（实测：`"好--就这?"` 被拼成
  // `“好--就这?”——就这？"`）。
  return edits.sort((a, b) => a.start - b.start)
}

/**
 * 纯函数：中文标点归一（幂等——同一段文本跑两遍结果一致）。
 * 逐字符 diff 的反面：这里走「替换清单」应用，长度变化不影响正确性。
 */
export function normalizeChinesePunctuation(input: string): string {
  if (!input) return input
  const edits = punctuationEdits(input)
  if (!edits.length) return input
  let out = ''
  let cursor = 0
  for (const edit of edits) {
    out += input.slice(cursor, edit.start) + edit.text
    cursor = edit.end
  }
  return out + input.slice(cursor)
}

/** 当前段落光标之前的文本（智能引号开/闭判定用；原子节点补 `\ufffc` 保位） */
function blockTextBefore(state: any): string {
  const $from = state.selection.$from
  if (!$from?.parent?.textBetween) return ''
  return $from.parent.textBetween(0, $from.parentOffset, undefined, '\ufffc')
}

/**
 * 输入规则集（打字即正）。
 *
 * 三条纪律：
 * - 正则**不加 `g` 标志**——InputRule 用 `regex.exec` 复用同一实例，带 `g` 会
 *   在多次调用间残留 lastIndex 导致漏匹配；
 * - 一律用**零宽后顾**而不是把前一个汉字纳入匹配——这样 range 只覆盖半角标点
 *   本身，替换不会重建前一个汉字的文本节点（不吞掉它的行内格式）；
 * - 中文输入法组合态由 TipTap 输入规则自带 `view.composing` 短路，不会打断选词。
 */
function buildRules(): InputRule[] {
  const insert = (text: string) => ({ state, range }: any) => {
    state.tr.insertText(text, range.from, range.to)
  }

  return [
    // 省略号：`...` 或已被逐字转成 `。。。` 的点列（≥3）都收成 `……`。
    // 逐字输入时第 1 个点会先被下面的句号规则收成 `。`，所以点列必须混合识别。
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS})[。.]{3,}$`), handler: insert('……') }),
    // 破折号：`--` → `——`
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS})-{2}$`), handler: insert('——') }),
    // 半角标点 → 全角（前一位是中文才动）。
    // 句号额外排除「前一位是 `。`」——否则 `...` 会逐字变成 `。。。` 而不是 `……`。
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS})(?<![。])\\.$`), handler: insert('。') }),
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS}),$`), handler: insert('，') }),
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS});$`), handler: insert('；') }),
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS}):$`), handler: insert('：') }),
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS})\\?$`), handler: insert('？') }),
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS})!$`), handler: insert('！') }),
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS})\\($`), handler: insert('（') }),
    new InputRule({ find: new RegExp(`(?<=${CJK_CLASS})\\)$`), handler: insert('）') }),
    // 直双引号 → 中文引号，靠段内「左引号数 > 右引号数」判断本次是开还是闭。
    // 纯英文段落（已有内容且一个汉字都没有）不碰——那里 `"` 就是英文字符。
    new InputRule({
      find: /"$/,
      handler: ({ state, range }) => {
        const before = blockTextBefore(state)
        if (before.trim() && !hasCjk(before)) return
        const opens = (before.match(/“/g) || []).length
        const closes = (before.match(/”/g) || []).length
        state.tr.insertText(opens > closes ? '”' : '“', range.from, range.to)
      },
    }),
  ]
}

export const ChineseTypography = Extension.create({
  name: 'chineseTypography',
  addInputRules() {
    return buildRules()
  },
})

export default ChineseTypography

// ============================================================
// 批处理侧：把既有正文一次性归一（⋯ 菜单「整理标点」，零 LLM / 零 API Key）
// ============================================================

/** 一处待执行的文档替换（位置=文档位置） */
export interface DocEdit {
  from: number
  to: number
  text: string
}

function collectBlockEdits(block: any, blockPos: number, out: DocEdit[]): void {
  // 幽灵草稿排除（未确认的 AI 中间态不属于正文）；@提及/细纲胶囊等原子节点同理占位挡开
  const { text, toDoc } = buildBlockTextMap(block, blockPos, { skipGhost: true })
  if (!text) return

  for (const edit of punctuationEdits(text)) {
    const from = toDoc(edit.start)
    const to = toDoc(edit.end, true)
    if (from == null || to == null) continue
    out.push({ from, to, text: edit.text })
  }
}

/**
 * 纯函数（无编辑器、无 DOM）：扫出整篇/选区里全部标点归一替换，返回**文档位置**。
 *
 * 块内文本整体拼装后再跑判据，是为了让规则看得见「跨文本节点的前一位」：
 * 行内格式（加粗/颜色残留）会把一句话切成多个文本节点，逐节点跑会漏掉
 * `好` | `...` 这种前一位在隔壁节点的情况。
 * 提成独立函数=可测（对拍 `__tests__/chineseTypography.test.ts` 的文档级用例）。
 */
export function collectPunctuationEdits(doc: any, from = 0, to = doc.content.size): DocEdit[] {
  const edits: DocEdit[] = []
  doc.nodesBetween(from, to, (node: any, pos: number) => {
    if (!node.isTextblock) return true
    collectBlockEdits(node, pos, edits)
    return false
  })
  return edits
}

/**
 * 对整篇（或选区）做中文标点归一，单事务提交（一次 Ctrl+Z 可整体反悔）。
 *
 * 替换保留命中处的行内格式（取 `doc.resolve(from).marks()`），不因为改了
 * 一个标点就把整句的加粗/斜体弄丢。
 */
export function normalizeDocumentPunctuation(
  editor: Editor,
  range?: { from: number; to: number },
): { edits: number; chars: number } {
  const { state } = editor
  const edits = collectPunctuationEdits(state.doc, range?.from ?? 0, range?.to)

  if (!edits.length) return { edits: 0, chars: 0 }

  // 倒序应用：后面的替换先落，前面记录的位置才不被位移污染
  const ordered = [...edits].sort((a, b) => b.from - a.from)
  const tr = state.tr
  let chars = 0
  for (const edit of ordered) {
    if (edit.from >= edit.to) continue
    // 保留命中处的行内格式；幽灵标记显式排除（防御编辑点恰在幽灵边界）
    const marks = state.doc.resolve(edit.from).marks().filter((m: any) => m.type.name !== 'ghostDraft')
    if (edit.text) {
      tr.replaceWith(edit.from, edit.to, editor.schema.text(edit.text, marks))
    } else {
      tr.delete(edit.from, edit.to)
    }
    chars += edit.to - edit.from
  }
  editor.view.dispatch(tr)
  return { edits: ordered.length, chars }
}
