import { InputRule, Node, mergeAttributes } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import AskNoteChip from './AskNoteChip.vue'

let _seq = 0
function _newId(): string {
  return `ask-${Date.now().toString(36)}-${++_seq}`
}

/**
 * 「问书」手势节点（04 下一阶段：行间手势速查）。
 *
 * 行内输入 `??` → 空问句胶囊（浮层输入问题）→ Enter 派发 velluma:ask-book
 * （编排归 WorkspaceView：调 /adaptive/ask-book 后经 velluma:ask-book-answer
 * 回投）→ 答案以幽灵式浅字浮现于行间：只读、不可采纳、不进正文，Esc 蒸发
 * ——与幽灵草稿同视觉语言，但无采纳语义（图书管理员不是合著者）。
 *
 * 生命周期契约（与细纲胶囊/幽灵一致）：会话级，存盘剥除——
 * useChapterEditorContainer.stripGhostDraftHtml 移除 [data-ask-note] 元素。
 * renderText 返回空串：word_count / settle / heartbeat 的提取天然跳过。
 */
export const AskNoteNode = Node.create({
  name: 'askNote',
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
      editing: {
        default: false,
      },
    }
  },

  parseHTML() {
    return [{ tag: 'span[data-ask-note]' }]
  },

  renderHTML({ node }) {
    return [
      'span',
      mergeAttributes({
        'data-ask-note': '',
        'data-id': node.attrs.id,
        class: 'ask-note',
      }),
    ]
  },

  renderText() {
    return ''
  },

  addNodeView() {
    return VueNodeViewRenderer(AskNoteChip)
  },

  addInputRules() {
    return [
      // 输入 ?? → 在光标处转出问句胶囊并打开浮层（与 [[ 细纲胶囊同族手势）。
      // 半角/全角两形态都认：chineseTypography 会把「前一位是中文」的半角 ?
      // 即时转成 ？——中文正文后作者实际打出的是「？？」（04 稿 §6 预警的
      // 手势冲突，施工核实即此；只认半角则手势在中文正文后永不触发）
      new InputRule({
        find: /[?？]{2}$/,
        handler: ({ range, chain }) => {
          chain()
            .insertContentAt(range, [
              { type: this.name, attrs: { id: _newId(), editing: true } },
              { type: 'text', text: ' ' },
            ])
            .run()
        },
      }),
    ]
  },
})

export default AskNoteNode
