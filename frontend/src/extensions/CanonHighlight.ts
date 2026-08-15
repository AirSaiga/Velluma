import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import type { Editor } from '@tiptap/vue-3'

export interface CanonTerm {
  /** 要标记的词（角色名 / 伏笔标签） */
  text: string
  /** 着色类型：character 角色 / hook 伏笔 */
  kind: 'character' | 'hook' | 'contradiction'
}

const canonHighlightKey = new PluginKey('canonHighlight')

/**
 * NLE-ADF 3.0 Canon 词高亮（Decoration，纯视图不入库）。
 *
 * 正文里角色名 / 伏笔词下加虚线小标（canon-mark--character / canon-mark--hook），
 * 提示作者「这里有 Canon 设定」。轻标记，不浮层、不盖字、不入 getHTML。
 *
 * 为什么用 Decoration 而非 Mark：Mark 会进文档 schema、影响 getHTML/落库；
 * Decoration 是纯视图层，作者保存的正文干净（标记只在他屏幕上显示）。
 *
 * 词表经 setCanonTerms 更新（dispatch 带 meta 的空 tr 触发 plugin state
 * 更新 → decorations 重算）。外部 watch 词表来源（角色名/伏笔词）变化时调用。
 */
export const CanonHighlight = Extension.create({
  name: 'canonHighlight',

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: canonHighlightKey,
        state: {
          init() {
            return { terms: [] as CanonTerm[] }
          },
          apply(tr, value) {
            const meta = tr.getMeta(canonHighlightKey)
            if (meta && Array.isArray(meta.terms)) return { terms: meta.terms }
            return value
          },
        },
        props: {
          decorations(state) {
            const pluginState = canonHighlightKey.getState(state)
            const terms = pluginState?.terms || []
            if (terms.length === 0) return DecorationSet.empty
            // 预处理：过滤掉过短词（<2 字易误命中），去重
            const valid = terms.filter((t) => t.text && t.text.length >= 2)
            if (valid.length === 0) return DecorationSet.empty
            const decos: Decoration[] = []
            const contradictionTexts = valid
              .filter((t) => t.kind === 'contradiction')
              .map((t) => t.text)
            state.doc.descendants((node, pos) => {
              if (node.isText && node.text) {
                // inline 词标记（角色/伏笔/矛盾）
                const text = node.text
                for (const t of valid) {
                  let idx = text.indexOf(t.text)
                  while (idx !== -1) {
                    decos.push(
                      Decoration.inline(pos + idx, pos + idx + t.text.length, {
                        class: `canon-mark canon-mark--${t.kind}`,
                      }),
                    )
                    idx = text.indexOf(t.text, idx + t.text.length)
                  }
                }
              } else if (node.isTextblock && contradictionTexts.length) {
                // 段落级：含矛盾词的段加左缘条（Decoration.node）
                const paraText = node.textContent
                if (contradictionTexts.some((ct) => ct && paraText.includes(ct))) {
                  decos.push(
                    Decoration.node(pos, pos + node.nodeSize, {
                      class: 'canon-para--contradiction',
                    }),
                  )
                }
              }
              return true
            })
            return DecorationSet.create(state.doc, decos)
          },
        },
      }),
    ]
  },
})

/**
 * 更新 Canon 高亮词表（外部 watch 调用）。
 *
 * 词表变化不会自动触发 ProseMirror 重算 decorations——需 dispatch 一个带 meta
 * 的空 tr，plugin apply 读 meta 更新 state，decorations 据此重算。
 */
export function setCanonTerms(editor: Editor | null, terms: CanonTerm[]): void {
  if (!editor) return
  const tr = editor.view.state.tr
  tr.setMeta(canonHighlightKey, { terms })
  editor.view.dispatch(tr)
}

export default CanonHighlight
