import { InputRule, Node, mergeAttributes } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import OutlineNoteChip from './OutlineNoteChip.vue'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    outlineNote: {
      /** 在光标/选区处插入细纲胶囊（选区文本自动转为速记） */
      insertOutlineNote: (note?: string) => ReturnType
      /** 按 id 塌缩细纲为钉子（扩写启动时由辅助层调用） */
      collapseOutlineNote: (id: string) => ReturnType
    }
  }
}

let _seq = 0
function _newId(): string {
  return `on-${Date.now().toString(36)}-${++_seq}`
}

export interface OutlineNoteRef {
  id: string
  note: string
  collapsed: boolean
  pos: number
  nodeSize: number
}

/** 扫描文档中全部细纲胶囊（辅助层定位用；不缓存位置，免疫编辑漂移）。 */
export function findOutlineNotes(editor: any): OutlineNoteRef[] {
  const out: OutlineNoteRef[] = []
  if (!editor?.state?.doc) return out
  editor.state.doc.descendants((node: any, pos: number) => {
    if (node.type.name === 'outlineNote') {
      out.push({
        id: String(node.attrs.id || ''),
        note: String(node.attrs.note || ''),
        collapsed: !!node.attrs.collapsed,
        pos,
        nodeSize: node.nodeSize,
      })
    }
    return true
  })
  return out
}

/**
 * 「细纲」胶囊节点（NLE-ADF 3.0 细纲扩写）。
 *
 * 作者亲笔的剧情速记（如「打一架，她退缩，约300字」）以行内胶囊形态嵌在
 * 正文中；点开浮层编辑、按「落笔扩写」后由 AI 结合前后正文与设定库扩写成
 * 小段幽灵正文（编排见 useAdaptiveAssist 的 velluma:outline-expand 监听）。
 * 扩写启动时塌缩为小钉 ⚑，点开可改速记再扩写。
 *
 * 生命周期契约（与幽灵草稿一致）：会话级，存盘剥除——
 * useChapterEditorContainer.stripGhostDraftHtml 会移除 [data-outline-note]
 * 元素（含速记文本），数据库与 localStorage 草稿永远只有正文。
 *
 * renderText 返回空串：word_count / settle / heartbeat 的 textBetween
 * 天然跳过胶囊，不污染正文提取。
 */
export const OutlineNoteNode = Node.create({
  name: 'outlineNote',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: false,
  draggable: false,

  addAttributes() {
    return {
      id: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-id') || '',
      },
      note: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-note') || '',
      },
      collapsed: {
        default: false,
        parseHTML: (element) => element.hasAttribute('data-collapsed'),
      },
      // 瞬态：新建/插入时置 true，NodeView 据此自动打开浮层（不入 HTML）
      editing: {
        default: false,
      },
    }
  },

  parseHTML() {
    return [{ tag: 'span[data-outline-note]' }]
  },

  renderHTML({ node }) {
    return [
      'span',
      mergeAttributes({
        'data-outline-note': '',
        'data-id': node.attrs.id,
        'data-note': node.attrs.note,
        ...(node.attrs.collapsed ? { 'data-collapsed': '' } : {}),
        class: 'outline-note' + (node.attrs.collapsed ? ' outline-note--collapsed' : ''),
      }),
    ]
  },

  renderText() {
    return ''
  },

  addNodeView() {
    return VueNodeViewRenderer(OutlineNoteChip)
  },

  addCommands() {
    return {
      insertOutlineNote:
        (note?: string) =>
        ({ chain, state }) => {
          const { from, to, empty } = state.selection
          const seed =
            note !== undefined && note !== null
              ? note
              : empty
                ? ''
                : state.doc.textBetween(from, to, '\n\n')
          chain()
            .insertContentAt(
              { from, to },
              [
                { type: this.name, attrs: { id: _newId(), note: seed, collapsed: false, editing: true } },
                { type: 'text', text: ' ' },
              ],
            )
            .run()
          return true
        },
      collapseOutlineNote:
        (id: string) =>
        ({ state, tr, dispatch }) => {
          let target: { pos: number; node: any } | null = null
          state.doc.descendants((node: any, pos: number) => {
            if (node.type.name === this.name && node.attrs.id === id) {
              target = { pos, node }
              return false
            }
            return true
          })
          if (!target) return false
          if (dispatch) {
            tr.setNodeMarkup((target as { pos: number; node: any }).pos, undefined, {
              ...(target as { pos: number; node: any }).node.attrs,
              collapsed: true,
              editing: false,
            })
          }
          return true
        },
    }
  },

  addInputRules() {
    return [
      // 输入 [[ → 在光标处转出空细纲胶囊并打开浮层（Alt+O 的零鼠标等价物）
      new InputRule({
        find: /\[\[$/,
        handler: ({ range, chain }) => {
          chain()
            .insertContentAt(range, [
              { type: this.name, attrs: { id: _newId(), note: '', collapsed: false, editing: true } },
              { type: 'text', text: ' ' },
            ])
            .run()
        },
      }),
    ]
  },
})

export default OutlineNoteNode
