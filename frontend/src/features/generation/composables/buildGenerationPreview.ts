/**
 * 生成预览 HTML 构建器（渲染文并入正文编辑框）。
 *
 * 职责：生成/步进进行中，把各段渲染文构建为带段隔离的 HTML，灌入正文编辑器
 * （只读预览）；完成后返回 null，编辑器回落显示章节正文。
 *
 * 段隔离语义：按 beatSlots 顺序遍历，每段一个「h4 状态标头 + 若干 p 正文 + hr 分隔」
 * 区块。重渲某段时 session 会清/重写该段 key，本函数每次全量重建，由
 * RichTextEditor 的 modelValue watcher setContent 实现该段的原子替换。
 *
 * 实现约束：TipTap schema 会丢弃未知 class，故段状态用文字符号（🔒/⏎/⟳/·）表达；
 * h4/hr/p 均为 StarterKit 原生节点，setContent 可安全解析。文本必须转义 & < >。
 */
import type { GenerationSession } from './useGenerationSession'

/** 文本转义（小说正文可能含 & < >，直接插 HTML 会破坏结构） */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/** 段正文 → 段落 HTML（与 RichTextEditor.normalizeToHtml 的纯文本规则一致） */
function textToParagraphs(text: string): string {
  return text
    .split(/\n\n+/)
    .map(p => p.trim())
    .filter(Boolean)
    .map(p => `<p>${escapeHtml(p).replace(/\n/g, '')}</p>`)
    .join('')
}

/**
 * 从预览 HTML 中提取指定段的正文（主编辑器直改的回读通道）。
 *
 * 结构约定：`<h4>段 N · 状态</h4><p>…</p>…` 段块间以 `<hr>` 分隔。
 * 作者在主编辑器里的每次输入都产出整篇预览 HTML，本函数按段标头定位、
 * 收集到下一个 `<hr>` 为止的兄弟节点文本，以 \n\n 连接（与 textToParagraphs
 * 的拆分规则互逆，保证回写后 rebuild 稳定）。
 *
 * 返回 null = 段标头未找到（作者误删 h4 等病态情况）——调用方跳过本次同步，
 * 绝不把整篇稿子写进一个段。
 */
export function extractSegmentTextFromPreviewHtml(html: string, segmentIndex: number): string | null {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const marker = `段 ${segmentIndex + 1} ·`
  const h = Array.from(doc.body.querySelectorAll('h4'))
    .find(el => (el.textContent || '').trim().startsWith(marker))
  if (!h) return null
  const paras: string[] = []
  let node = h.nextElementSibling
  while (node && node.tagName !== 'HR') {
    paras.push(node.textContent || '')
    node = node.nextElementSibling
  }
  return paras.join('\n\n')
}

export function buildGenerationPreviewHtml(session: GenerationSession): string | null {
  const stage = session.stage.value
  // 待命/完成：编辑器显示章节正文（完成时 handleGenerated 已把终稿写库）
  if (stage === 'idle' || stage === 'done') return null

  const slots = session.beatSlots.value
  const segs = session.segmentTexts.value
  const progress = session.renderProgress.value
  const degradedIds = new Set(session.degradedBeats.value.map(d => d.beat_id))

  // BS-ADF 段隔离预览（Track A/B 渲染中 / NLE-ADF 步进）。
  // 门控：段文本（步进/批量定稿块）或渲染进度（批量 BEAT_RENDER_PROGRESS）
  // 任一就位即亮——渲染一开始就显示全部段占位块，不再等首段定稿。
  // Track B beat_pending 编辑卡阶段两者皆空，不预览（编辑器保持可编辑）。
  if (slots.length > 0 && (Object.keys(segs).length > 0 || progress.length > 0)) {
    const locked = session.lockedBeatIds.value
    const readyId = session.readyBeatId.value
    const renderingId = session.renderingBeatId.value
    // 岔路门挂起段（beat_branch_choosing）：段标给明确状态而非落兜底「待渲染」
    const branchPendingId = stage === 'beat_branch_choosing'
      ? session.branchChoicePending.value?.beat_id
      : null
    // 降级就绪段：渲染即降级，就绪态等待作者手写/跳过（区别于「已降级」的历史段）
    const readyDegraded = session.readyBeatDegraded.value
    const progressByBeat = new Map(progress.map(p => [p.beat_id, p]))
    const blocks: string[] = []
    for (const slot of slots) {
      const p = progressByBeat.get(slot.beat_id)
      const isReadyDegraded = readyId === slot.beat_id && !!readyDegraded
        && (!readyDegraded.beat_id || readyDegraded.beat_id === slot.beat_id)
      const status =
        locked.has(slot.beat_id) ? '✓ 已定稿' :
        isReadyDegraded ? '⚠ 渲染失败 · 待处理' :
        readyId === slot.beat_id ? (session.readySegmentDirty.value ? '⏎ 待推进 · ✎ 已修改' : '⏎ 待推进') :
        branchPendingId === slot.beat_id ? '⑂ 待选走向' :
        renderingId === slot.beat_id ? '⟳ 渲染中' :
        degradedIds.has(slot.beat_id) ? '⚠ 已降级' :
        p?.status === 'rendering' ? '⟳ 渲染中' :
        p?.status === 'rendered' ? `✓ 已渲染 · ${p.word_count} 字` :
        p?.status === 'skipped' ? '⊘ 已跳过' :
        '· 待渲染'
      const text = segs[slot.beat_id] || ''
      const body = text
        ? textToParagraphs(text)
        : isReadyDegraded
          ? '<p>（本段渲染失败：直接在上方写正文后点「接受」，或跳过本段）</p>'
          : degradedIds.has(slot.beat_id)
            ? '<p>（本段渲染失败，可事后定点重渲）</p>'
            : '<p>（待渲染）</p>'
      blocks.push(`<h4>段 ${slot.segment_index + 1} · ${status}</h4>${body}`)
    }
    return blocks.join('<hr>')
  }

  // ADF 整文流式：无段结构，直接预览流文本（RichTextEditor 侧归一化包 <p>）
  if (session.generating.value && session.streamText.value) {
    return session.streamText.value
  }

  // 其余阶段（Track B beat_pending 编辑卡等）：不预览
  return null
}
