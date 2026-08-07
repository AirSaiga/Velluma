import { Mark } from '@tiptap/core'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    ghostDraft: {
      /** 给选区/后续输入挂幽灵草稿标记 */
      setGhostDraft: () => ReturnType
      /** 摘除幽灵草稿标记（Enter 锁死 = 变回正文） */
      unsetGhostDraft: () => ReturnType
    }
  }
}

/**
 * NLE-ADF 2.0 幽灵草稿 Mark（Ghost Draft）。
 *
 * AI 微缝合/整段代笔吐出的"待确认草稿"：以真实文本插入文档（作者可直接改
 * 1~2 个词——提案第 5 步的微调整合），薄荷绿底色 + 呼吸微光标识临时态。
 *   - Enter 锁死：摘除 mark，文字变回正文（实现见 useGhostDraft.commitGhost）
 *   - Esc 蒸发：连节点删除，零痕迹（useGhostDraft.evaporateGhost）
 *
 * 为什么用 Mark 而不是 Decoration：Decoration 不可编辑不可选中，违背
 * "作者微调后再锁死"的交互契约。Mark 文本天然可编辑/可选中/可删。
 *
 * 历史参考：extensions/ 下曾有 AuditHighlightMark（审计高亮，已删），同机制。
 */
export const GhostDraftMark = Mark.create({
  name: 'ghostDraft',

  // 边界不延续：幽灵区末尾继续打字是作者正文（不带 mark），
  // 锁死/蒸发边界因此永远清晰；mark 内部编辑（改词）仍继承 mark。
  inclusive: false,

  addAttributes() {
    return {
      // mint=微缝合/正常代笔；amber=降级段代笔（质量警示，呼应 degraded 语义）
      variant: {
        default: 'mint',
        parseHTML: (element) => element.getAttribute('data-variant') || 'mint',
        renderHTML: (attributes) => ({ 'data-variant': attributes.variant }),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'span[data-ghost-draft]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'span',
      {
        'data-ghost-draft': '',
        class: `ghost-draft ghost-draft--${HTMLAttributes.variant || 'mint'}`,
      },
      0,
    ]
  },

  addCommands() {
    return {
      setGhostDraft:
        () =>
        ({ commands }) =>
          commands.setMark(this.name),
      unsetGhostDraft:
        () =>
        ({ commands }) =>
          commands.unsetMark(this.name),
    }
  },
})

export default GhostDraftMark
