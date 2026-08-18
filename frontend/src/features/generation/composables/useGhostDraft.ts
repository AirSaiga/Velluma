import { ref, computed } from 'vue'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { noHistory } from '../../chapter-editor/noHistory'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'

/**
 * NLE-ADF 2.0 幽灵草稿控制器（useGhostDraft）。
 *
 * 管理文档中"待确认 AI 草稿"（GhostDraftMark 文本）的全生命周期：
 *   begin → append × N（SSE chunk 流式灌入）→ commit（Enter 锁死摘 mark）
 *         ↘ evaporate（Esc 蒸发连节点删除）
 *
 * 全局单例：同一时刻全文档至多一个幽灵区（交互契约——作者的注意力焦点唯一）。
 *
 * 关键设计：
 * - 幽灵区定位不缓存位置，每次扫描文档中带 ghostDraft mark 的文本节点
 *   （作者在幽灵区里改词/删字会让任何缓存位置漂移，扫描对编辑天然免疫）。
 * - dirty 检测：对比"流式灌入的原文"与"当前幽灵区文本"，判断作者是否微调过
 *   ——锁拍时 dirty 段走 lock_with_text，干净段走 pass（与既有裁决路由一致）。
 * - 多段落：代笔整段文本含 \n\n，拆成多个 paragraph 节点插入（每段文本挂 mark）。
 */

export type GhostSource = 'stitch' | 'render' | 'outline' | null

/** 当前是否存在幽灵草稿（响应式） */
export const ghostActive = ref(false)
/** 幽灵来源：stitch=微缝合 / render=整段代笔 / outline=细纲扩写 */
export const ghostSource = ref<GhostSource>(null)
/** 流式灌入的原文（dirty 检测基准） */
export const ghostOriginal = ref('')
/** 降级标记（代笔降级段 → 琥珀色幽灵） */
export const ghostDegraded = ref(false)

/**
 * 幽灵插入锚点（细纲扩写用）：null=跟随当前光标（默认，兼容旧行为），
 * 非 null=插到指定文档位置（细纲胶囊末尾）。仅在首 chunk 落文档前的
 * 窗口内有效——首 chunk 后 findGhostRange 接管定位，作者编辑天然免疫。
 */
let ghostAnchorPos: number | null = null

interface GhostRange {
  from: number
  to: number
}

/** 扫描文档，返回覆盖全部 ghostDraft 文本节点的范围（无则 null）。 */
function findGhostRange(): GhostRange | null {
  const editor = chapterEditorHandle.value
  if (!editor) return null
  let from = -1
  let to = -1
  editor.state.doc.descendants((node, pos) => {
    if (node.isText && node.marks.some((m) => m.type.name === 'ghostDraft')) {
      if (from === -1) from = pos
      to = pos + node.nodeSize
    }
    return true
  })
  return from === -1 ? null : { from, to }
}

/** 开始一段幽灵草稿（重置状态；首个 chunk 到达时才真正落文档）。
 *
 * anchorPos：可选插入锚点（细纲扩写传胶囊末尾位置）；不传则落当前光标。
 */
export function beginGhost(
  source: Exclude<GhostSource, null>,
  degraded = false,
  anchorPos?: number | null,
): void {
  // 防御：已有幽灵时先蒸发（正常流程不会叠加，异常重入不污染文档）
  if (ghostActive.value) evaporateGhost()
  ghostSource.value = source
  ghostOriginal.value = ''
  ghostDegraded.value = degraded
  ghostAnchorPos = anchorPos ?? null
  ghostActive.value = true
}

/** 向文档插入带 mark 的文本（单段内联追加或多段落块追加）。 */
function insertMarkedText(delta: string): void {
  const editor = chapterEditorHandle.value
  if (!editor) return
  const variant = ghostDegraded.value ? 'amber' : 'mint'
  const mark = { type: 'ghostDraft', attrs: { variant } }
  const range = findGhostRange()

  if (delta.includes('\n\n')) {
    // 多段落（代笔整段全量推送到达时）：首个段落并入当前幽灵段尾，
    // 后续段落作为新 paragraph 节点追加。
    const paras = delta.split(/\n\n+/)
    const blocks = paras
      .filter((p) => p.length > 0)
      .map((p) => ({
        type: 'paragraph',
        content: [{ type: 'text', text: p, marks: [mark] }],
      }))
    if (blocks.length === 0) return
    if (range) {
      // 既有幽灵区：块内容插到幽灵末尾段落之后
      const paraEnd = editor.state.doc.resolve(range.to).after()
      editor.chain().command(noHistory).insertContentAt(paraEnd, blocks).run()
    } else {
      const pos = ghostAnchorPos ?? editor.state.selection.from
      editor.chain().command(noHistory).insertContentAt(pos, blocks).run()
    }
    return
  }

  // 单段内联追加
  const content = { type: 'text', text: delta, marks: [mark] }
  if (range) {
    // range.to 位于最后一个幽灵文本节点之后、仍在段落内 → 内联插入
    editor.chain().command(noHistory).insertContentAt(range.to, content).run()
  } else {
    const pos = ghostAnchorPos ?? editor.state.selection.from
    editor.chain().command(noHistory).insertContentAt(pos, content).run()
  }
}

/**
 * 追加一个 SSE chunk 到幽灵区（打字机式生长的数据源）。
 * 首 chunk 在当前光标处落文档；后续 chunk 追加到幽灵区末尾。
 *
 * 实现：累积全部 delta 到 ghostOriginal，每次 chunk 到达时用完整文本
 * 替换整个幽灵区（而非逐 chunk 插入独立文本节点）。这样 ProseMirror 里
 * 始终保持最少的文本节点，避免"切得很碎"（每 6 字一个节点的碎片化）。
 */
export function appendGhost(delta: string): void {
  if (!ghostActive.value || !delta) return
  ghostOriginal.value += delta
  _replaceGhostText(ghostOriginal.value)
}

/**
 * 用完整文本替换整个幽灵区（删除旧幽灵 + 插入新完整文本，单次事务）。
 * 保持打字机视觉效果（文本逐渐变长），但内部只有最少的文本节点。
 */
function _replaceGhostText(fullText: string): void {
  const editor = chapterEditorHandle.value
  if (!editor) return
  const variant = ghostDegraded.value ? 'amber' : 'mint'
  const mark = { type: 'ghostDraft', attrs: { variant } }
  const range = findGhostRange()

  // 多段落：拆成 paragraph 块
  if (fullText.includes('\n\n')) {
    const paras = fullText.split(/\n\n+/).filter((p) => p.length > 0)
    const blocks = paras.map((p) => ({
      type: 'paragraph',
      content: [{ type: 'text', text: p, marks: [mark] }],
    }))
    if (range) {
      // 删除旧幽灵区，插入新完整内容（隔离撤销栈：流式逐 chunk 若入栈，
      // Ctrl+Z 会逐帧倒放打字机并可能复活幽灵区）
      editor.chain().command(noHistory).deleteRange({ from: range.from, to: range.to }).insertContentAt(range.from, blocks).run()
    } else {
      const pos = ghostAnchorPos ?? editor.state.selection.from
      editor.chain().command(noHistory).insertContentAt(pos, blocks).run()
    }
    return
  }

  // 单段：删除旧幽灵区，插入新完整文本（单个文本节点）
  if (range) {
    editor.chain().command(noHistory).deleteRange({ from: range.from, to: range.to }).insertContentAt(range.from, { type: 'text', text: fullText, marks: [mark] }).run()
  } else {
    const pos = ghostAnchorPos ?? editor.state.selection.from
    editor.chain().command(noHistory).insertContentAt(pos, { type: 'text', text: fullText, marks: [mark] }).run()
  }
}

/** 当前幽灵区文本（块间以 \n\n 连接，与纯文本正文格式一致）。 */
export function ghostText(): string {
  const editor = chapterEditorHandle.value
  if (!editor) return ''
  const range = findGhostRange()
  if (!range) return ''
  return editor.state.doc.textBetween(range.from, range.to, '\n\n')
}

/** 作者是否微调过幽灵草稿（决定锁定时走 lock_with_text 还是 pass）。 */
export const ghostDirty = computed(() => {
  if (!ghostActive.value) return false
  return ghostText().trim() !== ghostOriginal.value.trim()
})

/**
 * Enter 锁死：摘除幽灵区全部 mark（文字变回正文），返回定稿文本。
 * 光标移到定稿文本末尾，作者顺势继续写。
 * 锁死闪烁（设计稿 Step-Lock Flash）：摘 mark 后给定稿区短暂高亮脉冲
 * （复用 Highlight mark，350ms 后摘除）——作者明确感知"这段算数了"。
 */
export function commitGhost(): string {
  const editor = chapterEditorHandle.value
  const range = findGhostRange()
  if (!editor || !range) {
    ghostActive.value = false
    ghostSource.value = null
    return ''
  }
  dispatchCollabEvent('ghost_adopt', { source: ghostSource.value })
  const text = editor.state.doc.textBetween(range.from, range.to, '\n\n')
  editor
    .chain()
    .command(noHistory)
    .command(({ tr, state }) => {
      tr.removeMark(range.from, range.to, state.schema.marks.ghostDraft)
      return true
    })
    .setTextSelection(range.to)
    .run()
  // 锁死闪烁：薄荷绿高亮脉冲一次后摘除（350ms；作者继续打字位置漂移时
  // 摘除范围按原记录，Highlight 只影响底色、误摘无害）
  const flashFrom = range.from
  const flashTo = range.to
  editor
    .chain()
    .command(noHistory)
    .setTextSelection({ from: flashFrom, to: flashTo })
    .setHighlight({ color: 'rgba(52, 211, 153, 0.28)' })
    .setTextSelection(flashTo)
    .run()
  setTimeout(() => {
    const ed = chapterEditorHandle.value
    if (!ed) return
    const size = ed.state.doc.content.size
    ed.chain()
      .command(noHistory)
      .setTextSelection({ from: Math.min(flashFrom, size), to: Math.min(flashTo, size) })
      .unsetHighlight()
      .setTextSelection(Math.min(flashTo, size))
      .run()
  }, 350)
  ghostActive.value = false
  ghostSource.value = null
  ghostAnchorPos = null
  return text
}

/** Esc 蒸发：连节点删除幽灵区，零痕迹（恢复作者最原始的每一个字）。 */
export function evaporateGhost(): void {
  const editor = chapterEditorHandle.value
  const range = findGhostRange()
  if (editor && range) {
    dispatchCollabEvent('ghost_discard', { source: ghostSource.value })
    editor.chain().command(noHistory).deleteRange({ from: range.from, to: range.to }).run()
  }
  ghostActive.value = false
  ghostSource.value = null
  ghostOriginal.value = ''
  ghostDegraded.value = false
  ghostAnchorPos = null
}

export function useGhostDraft() {
  return {
    ghostActive,
    ghostSource,
    ghostOriginal,
    ghostDegraded,
    ghostDirty,
    beginGhost,
    appendGhost,
    ghostText,
    commitGhost,
    evaporateGhost,
    findGhostRange,
  }
}
