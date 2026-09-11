import { Extension } from '@tiptap/core'
import type { Editor } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { buildBlockTextMap } from './blockTextMap'

/**
 * 写作台查找/替换（2026-09-10，Ctrl+F）。
 *
 * 为什么值得单独做：小说改稿的高频动作是「统一称呼/改人名/查重复用词」——
 * 此前全工程没有查找，作者只能肉眼翻章。
 *
 * 三层分工：
 * - 本模块：ProseMirror 插件（搜索态 + 命中高亮装饰）与纯判据（命中扫描）；
 * - useEditorFind：状态机（当前命中/上下条/替换/全部替换）；
 * - EditorFindBar.vue：条状 UI（纸面右上浮出，Esc 收）。
 *
 * 纪律：
 * - 装饰是**纯视图层**（Decoration）——不入库、不进撤销栈、不改 getHTML；
 * - 不跨段落匹配（块内扫描）：跨段的"命中"在小说里没有意义，且跨块区间会把
 *   段落标记卷进替换；
 * - 未确认的幽灵草稿**参与查找**（屏幕上看得见就该找得到），但绝不因查找被改写
 *   ——替换走 collectDocMatches 的同一份位置，幽灵文本也在其中；作者真要改幽灵
 *   是他的自由（幽灵本来就是可编辑的中间态）。
 */

export interface FindSearchState {
  term: string
  caseSensitive: boolean
  activeIndex: number
}

export const EDITOR_FIND_KEY = new PluginKey<FindSearchState>('editorFind')

export interface DocMatch {
  from: number
  to: number
}

/** 纯函数：单段文本里的全部命中（返回 [start, end) 偏移） */
export function findTextMatches(text: string, term: string, caseSensitive = false): Array<[number, number]> {
  const out: Array<[number, number]> = []
  if (!text || !term) return out
  const haystack = caseSensitive ? text : text.toLowerCase()
  const needle = caseSensitive ? term : term.toLowerCase()
  let cursor = 0
  while (cursor <= haystack.length - needle.length) {
    const hit = haystack.indexOf(needle, cursor)
    if (hit === -1) break
    out.push([hit, hit + needle.length])
    cursor = hit + needle.length
  }
  return out
}

/**
 * 文档内全部命中（逐文本块扫描，返回文档位置；块内偏移 → 文档位置走共享映射）。
 * 幽灵草稿参与（屏幕上看得见即算），原子节点以占位挡住（不给 @提及内部做匹配）。
 */
export function collectDocMatches(doc: any, term: string, caseSensitive = false): DocMatch[] {
  const out: DocMatch[] = []
  if (!term) return out
  doc.descendants((node: any, pos: number) => {
    if (!node.isTextblock) return true
    const { text, toDoc } = buildBlockTextMap(node, pos)
    for (const [start, end] of findTextMatches(text, term, caseSensitive)) {
      const from = toDoc(start)
      const to = toDoc(end, true)
      if (from != null && to != null) out.push({ from, to })
    }
    return false
  })
  return out
}

function buildDecorations(doc: any, search: FindSearchState): DecorationSet {
  if (!search.term) return DecorationSet.empty
  const matches = collectDocMatches(doc, search.term, search.caseSensitive)
  if (!matches.length) return DecorationSet.empty
  const active = Math.max(0, Math.min(search.activeIndex, matches.length - 1))
  return DecorationSet.create(
    doc,
    matches.map((m, i) =>
      Decoration.inline(m.from, m.to, {
        class: i === active ? 'editor-find-match editor-find-match--active' : 'editor-find-match',
      }),
    ),
  )
}

/** 推送搜索态（只带 meta 的事务——docChanged=false，不进撤销栈）。 */
export function setFindSearch(editor: Editor, patch: Partial<FindSearchState>): void {
  editor.view.dispatch(editor.state.tr.setMeta(EDITOR_FIND_KEY, patch))
}

/** 读取搜索态（条组件与快捷键共用；无插件时返回空态）。 */
export function readFindSearch(editor: Editor | null | undefined): FindSearchState {
  const state = editor?.state ? EDITOR_FIND_KEY.getState(editor.state) : null
  return state || { term: '', caseSensitive: false, activeIndex: 0 }
}

export const EditorFind = Extension.create({
  name: 'editorFind',

  addProseMirrorPlugins() {
    return [
      new Plugin<FindSearchState>({
        key: EDITOR_FIND_KEY,
        state: {
          init: () => ({ term: '', caseSensitive: false, activeIndex: 0 }),
          apply(tr, value) {
            const meta = tr.getMeta(EDITOR_FIND_KEY) as Partial<FindSearchState> | undefined
            return meta ? { ...value, ...meta } : value
          },
        },
        props: {
          decorations(state) {
            const search = EDITOR_FIND_KEY.getState(state)
            // 未搜索时零成本短路：不扫文档、不建装饰集
            return search?.term ? buildDecorations(state.doc, search) : DecorationSet.empty
          },
        },
      }),
    ]
  },
})

export default EditorFind
