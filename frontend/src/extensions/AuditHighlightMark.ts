import { Mark, mergeAttributes } from '@tiptap/core'

/**
 * 审校问题高亮 mark（V3.1 F4 新增）。
 *
 * 审校问题点击定位的临时高亮（黄色闪烁后淡出）。
 *
 * 用途：用户在 Inspector 审校 tab 点击某条 finding 时，
 * 编辑器滚动到对应 offset 并临时高亮该区间，2.5s 后自动清除。
 */
export interface AuditHighlightMarkOptions {
  HTMLAttributes: Record<string, any>
}

export const AuditHighlightMark = Mark.create<AuditHighlightMarkOptions>({
  name: 'auditHighlight',

  addOptions() {
    return {
      HTMLAttributes: {},
    }
  },

  parseHTML() {
    return [
      { tag: 'mark.audit-highlight' },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'mark',
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, { class: 'audit-highlight' }),
      0,
    ]
  },
})
