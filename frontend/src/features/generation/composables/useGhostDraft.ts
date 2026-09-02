import { ref, computed } from 'vue'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { noHistory } from '../../chapter-editor/noHistory'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'
import { useToast } from '../../../composables/useToast'
import type { GhostWarning } from '../../../services/api/domain/adaptive.api'

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
 * - C1 快检疑点（P5 §5.1）：GHOST_DONE 帧的 warnings 存 ghostWarnings，
 *   在屏时感知带停靠区出「N 处疑点」行；采纳时 toast 一句提醒。
 *   红线：只提示不拦截，采纳永远可用（§9「提示不拦截」）。
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
/** C1 上屏前快检疑点（GHOST_DONE 到达时由 useAdaptiveAssist 灌入；随生命周期重置） */
export const ghostWarnings = ref<GhostWarning[]>([])

// ---- 呈现平面洗层状态（三平面分权 P1，2026-08-29）----
/** 洗层命中清单 + 原稿快照（GHOST_DONE 灌入；随生命周期重置；空 hits=未触发） */
export interface GhostWashPayload {
  hits: Array<{ pattern: string; span: string; replaced: boolean; alternative: string }>
  original_text: string
}
export const ghostWash = ref<GhostWashPayload>({ hits: [], original_text: '' })

/** P5 回流 meta：本发幽灵的对齐令牌 + 注入样本 id（采纳/蒸发埋点携带） */
let _lastGhostMeta: { token: string; sampleIds: string[] } | null = null

/** 快检 kind → 人话短标签（toast 汇总 + 停靠区明细共用一张词表） */
const WARNING_KIND_LABELS: Record<GhostWarning['kind'], string> = {
  dead_speak: '死者开口',
  canon_leak: '疑似泄底',
  secret_leak: '私有设定外泄',
  // 二期扩（约束治理 2026-09-02）
  cliche_hit: '禁忌词',
  out_of_scene: '人物不在场',
  location_jump: '地点穿越',
  quality_breaker: '自动修正暂停',
}

/** kind → 人话标签（未登记 kind 回退原串——repaired chip 与汇总共用） */
export function warningKindLabel(kind: string): string {
  return (WARNING_KIND_LABELS as Record<string, string>)[kind] || kind
}

/** 二期返修环结果（GHOST_DONE 增量字段）：自动修正了 N 处硬伤 */
export const ghostRepaired = ref<{ count: number; kinds: string[]; action: string } | null>(null)
/** 拒稿熔断开启（自动修正连续失败转为仅提示）——感知带指示数据源 */
export const ghostBreakerOpen = ref(false)

/** GHOST_DONE 帧到达时灌入返修环结果（useAdaptiveAssist 调用；随 begin 重置）。 */
export function setGhostRepaired(
  repaired?: { count: number; kinds: string[]; action: string },
  breakerOpen?: boolean,
): void {
  ghostRepaired.value = repaired && repaired.count > 0 ? repaired : null
  ghostBreakerOpen.value = breakerOpen === true
}

/**
 * 疑点汇总话术（纯函数，单测锁定）：
 * 「已采纳，含 2 处疑点：死者开口、疑似泄底（×2 表示该类命中数）」；
 * 空列表返回空串（调用方据此静默）。
 */
export function summarizeGhostWarnings(warnings: GhostWarning[]): string {
  if (!warnings.length) return ''
  const counts = new Map<string, number>()
  for (const w of warnings) {
    const label = WARNING_KIND_LABELS[w.kind] || w.kind
    counts.set(label, (counts.get(label) || 0) + 1)
  }
  const parts = [...counts.entries()].map(([label, n]) => (n > 1 ? `${label}×${n}` : label))
  return `已采纳，含 ${warnings.length} 处疑点：${parts.join('、')}（可忽略，仅供参照）`
}

/** GHOST_DONE 帧到达时灌入快检疑点（useAdaptiveAssist 调用；随 begin/evaporate/commit 重置）。 */
export function setGhostWarnings(warnings: GhostWarning[]): void {
  ghostWarnings.value = Array.isArray(warnings) ? warnings : []
}

/** GHOST_DONE 帧到达时灌入洗层结果与回流 meta（useAdaptiveAssist 调用）。 */
export function setGhostWash(
  wash?: { hits?: Array<{ pattern: string; span: string; replaced: boolean; alternative: string }>; original_text?: string },
  meta?: { token?: string; sampleIds?: string[] },
): void {
  ghostWash.value = {
    hits: Array.isArray(wash?.hits) ? wash!.hits! : [],
    original_text: wash?.original_text || '',
  }
  _lastGhostMeta = meta?.token ? { token: meta.token, sampleIds: meta.sampleIds || [] } : null
}

/**
 * 「用原稿」（P1 可逆学习）：把幽灵区内容重灌为洗前原稿（保留 ghost mark、
 * 隔离撤销栈）。作者明示保留被洗掉的词——调用方随后应对每个 replaced 命中
 * 调 wash-prefer-original（blocker 降 warning，一次肯定胜过三次否定）。
 */
export function useGhostOriginal(): boolean {
  const original = ghostWash.value.original_text
  if (!original) return false
  const editor = chapterEditorHandle.value
  const range = findGhostRange()
  if (!editor || !range) return false
  const paras = original.split(/\n\n+/).filter((p) => p.trim())
  const blocks = paras.length > 1
    ? paras.map((p) => ({
        type: 'paragraph',
        content: [{ type: 'text', text: p, marks: [editor.schema.marks.ghostDraft.create()] }],
      }))
    : [{ type: 'paragraph', content: [{ type: 'text', text: original, marks: [editor.schema.marks.ghostDraft.create()] }] }]
  editor.chain()
    .command(noHistory)
    .deleteRange({ from: range.from, to: range.to })
    .insertContentAt(range.from, blocks)
    .run()
  ghostOriginal.value = original  // dirty 基准同步（原稿即新的“未修改态”）
  return true
}

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
  ghostWarnings.value = []
  ghostWash.value = { hits: [], original_text: '' }
  ghostRepaired.value = null
  ghostBreakerOpen.value = false
  ghostAnchorPos = anchorPos ?? null
  ghostActive.value = true
}

/**
 * 二期质量拒稿逃生舱（约束治理 2026-09-02）：后端返修/切除均未通过、幽灵
 * 不上屏时，作者可裁决「仍以疑点提示上屏」——被拒原稿以普通幽灵形态灌回
 * （Enter 采纳/Esc 蒸发同契约；疑点清单由调用方随 setGhostWarnings 附）。
 */
export function materializeRejectedGhost(
  text: string,
  source: Exclude<GhostSource, null> = 'stitch',
): void {
  if (!text) return
  beginGhost(source)
  appendGhost(text)
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
    ghostWarnings.value = []
  ghostWash.value = { hits: [], original_text: '' }
    return ''
  }
  // P5 回流（2026-08-29）：meta（token/样本 id）+ 正文随采纳事件落账——
  // sample_prior 据此派生采纳先验；文风页「AI 采纳收样本」池读正文
  dispatchCollabEvent('ghost_adopt', {
    source: ghostSource.value,
    ghost_token: _lastGhostMeta?.token || '',
    sample_ids: _lastGhostMeta?.sampleIds || [],
    wash_hits: ghostWash.value.hits.length,
    text: editor.state.doc.textBetween(range.from, range.to, '\n\n').slice(0, 400),
  })
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
  // C1 快检疑点：采纳落正文时一句 toast 提醒（只提示不拦截——采纳已完成）。
  // 疑点随快检在 GHOST_DONE 灌入；作者可能已微调幽灵文本，话术按「参照」口径。
  const adoptedWarnings = ghostWarnings.value
  ghostActive.value = false
  ghostSource.value = null
  ghostAnchorPos = null
  ghostWarnings.value = []
  ghostWash.value = { hits: [], original_text: '' }
  const summary = summarizeGhostWarnings(adoptedWarnings)
  if (summary) {
    const { showToast } = useToast()
    showToast(summary, 'warning')
  }
  return text
}

/** Esc 蒸发：连节点删除幽灵区，零痕迹（恢复作者最原始的每一个字）。 */
export function evaporateGhost(): void {
  const editor = chapterEditorHandle.value
  const range = findGhostRange()
  if (editor && range) {
    const source = ghostSource.value
    dispatchCollabEvent('ghost_discard', {
      source,
      ghost_token: _lastGhostMeta?.token || '',
      sample_ids: _lastGhostMeta?.sampleIds || [],
    })
    // 失败理由埋点（2026-08-25 实测主线「失败分类学」）：先取文本再删——
    // ≥30 字的蒸发才问（琐碎蒸发多是试键/误触，问了也是噪声）；
    // 可点可无视 8s 自灭，零打扰红线；理由枚举见 InsightsView COLLAB_KIND_LABELS。
    const discardedText = editor.state.doc.textBetween(range.from, range.to, '\n\n')
    editor.chain().command(noHistory).deleteRange({ from: range.from, to: range.to }).run()
    if (discardedText.trim().length >= 30) {
      const mk = (reason: string, label: string) => ({
        label,
        onClick: () => dispatchCollabEvent('ghost_discard_reason', { source, reason }),
      })
      useToast().showToast(
        '幽灵已蒸发——点个原因，帮我学会少写这种',
        'info',
        8000,
        undefined,
        [
          mk('misfit', '接错了'),
          mk('not_my_voice', '不像我'),
          mk('pacing', '节奏不对'),
          mk('other', '其他'),
        ],
      )
    }
  }
  ghostActive.value = false
  ghostSource.value = null
  ghostOriginal.value = ''
  ghostDegraded.value = false
  ghostWarnings.value = []
  ghostWash.value = { hits: [], original_text: '' }
  ghostAnchorPos = null
}

/**
 * 幽灵死亡收割（2026-08-29 手动删除事故）：
 * 作者用退格/选删亲手删光幽灵文本（而非 Esc 蒸发）时，文档里已无
 * ghostDraft 节点，但 ghostActive 仍为真——僵尸态吃掉 Tab（结构闸
 * 「ghostActive 只吞不唤」）、禁掉 Space（spaceActive 判 !ghostActive）、
 * 卡住 authorLane 在 ghostStitching、sticky 卡舱恢复等不到落沿。
 * 编辑器每次文档事务后调用（RichTextEditor onUpdate）：状态说有幽灵而
 * 文档扫不到 → 按「作者亲手蒸发」收尾——埋 ghost_discard 供学习回流
 * （作者已用删除表达拒绝，不弹理由 toast 问第二遍），文档已干净不再删。
 * 部分删除/改词不触发（mark 仍在 = 幽灵还活着，走 ghostDirty 微调语义）。
 */
export function reapGhostIfDead(): void {
  if (!ghostActive.value) return
  if (findGhostRange()) return
  dispatchCollabEvent('ghost_discard', {
    source: ghostSource.value,
    ghost_token: _lastGhostMeta?.token || '',
    sample_ids: _lastGhostMeta?.sampleIds || [],
  })
  ghostActive.value = false
  ghostSource.value = null
  ghostOriginal.value = ''
  ghostDegraded.value = false
  ghostWarnings.value = []
  ghostWash.value = { hits: [], original_text: '' }
  ghostAnchorPos = null
}

export function useGhostDraft() {
  return {
    ghostActive,
    ghostSource,
    ghostOriginal,
    ghostDegraded,
    ghostDirty,
    ghostWarnings,
    setGhostWarnings,
    summarizeGhostWarnings,
    beginGhost,
    appendGhost,
    ghostText,
    commitGhost,
    evaporateGhost,
    reapGhostIfDead,
    findGhostRange,
  }
}
