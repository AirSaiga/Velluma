/**
 * 程序化文档变更的撤销栈隔离（UX 修复：恢复 Ctrl+Z 的配套措施）。
 *
 * 编辑器已开启原生 history（Ctrl+Z 撤销/重做）。但 AI/系统发起的程序化变更
 * ——幽灵草稿流式灌入、外部回流 setContent、切章强制覆盖、划轨回拨、选区优化 diff——
 * 若进撤销栈，Ctrl+Z 会逐帧"倒放打字机"，甚至把上一章内容灌进新章文档（串章事故）。
 *
 * prosemirror-history 原生约定：tr.getMeta('addToHistory') === false 的事务不入栈。
 * TipTap v2 未封装该通道，此处以自定义 command 补齐。
 *
 * 用法（chain 共享同一 tr，插入链中任一位置即可）：
 *   editor.chain().command(noHistory).insertContentAt(pos, blocks).run()
 *
 * 注意：用户主权变更（打字、清脂、格式整理、mention 插入）不要打标——
 * 可撤销正是需求（见 shared/utils/defat.ts 顶部注释"Ctrl+Z 可整体撤销"）。
 */

interface TrLike {
  setMeta: (key: string, value: unknown) => unknown
}

/** chain 内打标：本事务不进撤销栈。直接传给 .command() 使用。 */
export function noHistory({ tr }: { tr: TrLike }): boolean {
  tr.setMeta('addToHistory', false)
  return true
}

/** setContent 且不进撤销栈（切章/外部回流/生成预览流式专用）。 */
export function setContentNoHistory(editor: any, content: any, emitUpdate = false): void {
  editor.chain().command(noHistory).setContent(content, emitUpdate).run()
}
