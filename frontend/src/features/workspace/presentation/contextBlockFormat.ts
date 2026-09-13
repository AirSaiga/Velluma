// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Velluma Contributors
/**
 * 「AI 此刻读到的」块正文保字排版解析器（docs/design/ux-redesign/09-ai-view-redesign.md §5）。
 *
 * 块 content 是后端 render_system_blocks 的字面 prompt 文本（与真实注入逐字
 * 同源）。本模块把它解析成可排版的节点树——红线：除结构标记（行首 #/##、
 * 行首 "- "、场景行 ｜ 分隔符、缩进空白、换行）转为排版结构外，其余任何
 * 字符不增不删不改写；内联标记（【…】〔…〕）只做样式包裹，字符原样保留。
 *
 * 解析器行级保守：只认确定形态，任何不确定的行落到 plain 节点（衬线原样
 * 渲染）；「原文」开关是逐字核对的逃生舱。形态清单以后端实测产出为准：
 * knowledge_plane.py（场景 ｜ 行 / 实体 - 行 + 缩进档案体 / 注：尾注 /
 * 【此刻·切记】recency 钉）、adaptive_prompts.py（# 块头 / 示范 N 样本）、
 * consistency.py（## 段头 / "  → " 写作指令行）。
 */

// ===== 段分组（§2.2：沿真实注入序切段，不重排） =====

export type SegmentId = 'fact' | 'guard' | 'style' | 'other'

export const SEGMENT_TITLES: Record<SegmentId, string> = {
  fact: '事实与设定',
  guard: '约束与记忆',
  style: '文风与笔感',
  other: '其他',
}

/** 段内显示序（=注入序的段切分）；未映射 key 落 other 兜底 */
export const SEGMENT_ORDER: SegmentId[] = ['fact', 'guard', 'style', 'other']

const SEGMENT_OF_KEY: Record<string, SegmentId> = {
  scene: 'fact',
  warm: 'fact',
  entities: 'fact',
  proper_nouns: 'fact',
  canon: 'fact',
  secrets: 'fact',
  worldview: 'fact',
  relations: 'fact',
  negative: 'guard',
  echoes: 'guard',
  spatial: 'guard',
  style_positive: 'style',
  author_samples: 'style',
  anti_pseudo_sensory: 'style',
}

export function segmentOfKey(key: string): SegmentId {
  return SEGMENT_OF_KEY[key] ?? 'other'
}

// ===== 来源文案人话化（§7 文案表；后端零改动，前端映射） =====

const SOURCE_OVERRIDES: Record<string, string> = {
  世界实体: '世界页 · 实体',
  章级绑定: '章节旧表（未接世界页）',
  '打算 tab · spine（章内冻结）': '打算 tab（章内不变）',
  '真相层（含私有）': '真相账本（含私有）',
  '文风样本库 · 对话场景优先': '文风样本库 · 优先对话段',
  '场景钉 + 叙事时刻': '场景钉 + 时间锚',
}

/** 知识平面前缀（entities 块专属）在展示层剥掉，尾巴单独映射 */
const KG_PREFIX = '知识平面 · '

export function friendlySource(source: string): string {
  const s = (source || '').trim()
  if (s.startsWith(KG_PREFIX)) {
    const tail = s.slice(KG_PREFIX.length)
    if (tail === '世界实体') return '世界页 · 实体档案'
    if (tail === '章级绑定') return '章节旧表（未接世界页）'
    return s
  }
  return SOURCE_OVERRIDES[s] ?? s
}

// ===== 行内标记切分（【…】〔…〕 → mark span；字符原样保留） =====

export interface InlineSpan {
  text: string
  mark?: boolean
}

const INLINE_MARK_RE = /〔[^〕]*〕|【[^】]*】/g

export function inlineParse(text: string): InlineSpan[] {
  const spans: InlineSpan[] = []
  let last = 0
  for (const m of text.matchAll(INLINE_MARK_RE)) {
    const idx = m.index ?? 0
    if (idx > last) spans.push({ text: text.slice(last, idx) })
    spans.push({ text: m[0], mark: true })
    last = idx + m[0].length
  }
  if (last < text.length) spans.push({ text: text.slice(last) })
  return spans.length ? spans : [{ text }]
}

/** mark 的语义着色档：在场=ok / 死亡=danger / 此刻=中性 / 其余（示范编号等）=中性弱 */
export type MarkTone = 'present' | 'dead' | 'moment' | 'neutral'

export function markTone(text: string): MarkTone {
  if (text.startsWith('〔在场〕')) return 'present'
  if (text.startsWith('【已死亡') || text.startsWith('【已死')) return 'dead'
  if (text.startsWith('【此刻')) return 'moment'
  return 'neutral'
}

// ===== 行级节点解析（§5.2 规则表 + 施工批注 #2 补充形态） =====

export type BlockNode =
  /** "# 标题" / "## 标题" 弱小节标题（# 标记丢弃，标题字符保留） */
  | { type: 'heading'; text: string }
  /** "- xxx" 列表项（- 标记丢弃） */
  | { type: 'item'; text: string }
  /** 列表项后的缩进续行（档案体 / "→ 写作指令"；缩进丢弃） */
  | { type: 'profile'; text: string }
  /** "注：xxx" 尾注（整行保留） */
  | { type: 'note'; text: string }
  /** "k：v" 键值行（：分隔符丢弃，k/v 字符保留） */
  | { type: 'kv'; k: string; v: string }
  /** "【示范 N】" 样本编号行（整行保留） */
  | { type: 'sample'; text: string }
  /** 兜底原样行（衬线渲染；施工批注 #1：不用等宽） */
  | { type: 'plain'; text: string }

const HEADING_RE = /^#{1,2} (.+)$/
const ITEM_RE = /^- (.+)$/
const SAMPLE_RE = /^【示范 \d+】$/
const PROFILE_RE = /^[ \t]+(.+)$/
const NOTE_RE = /^注：.+/
const RECENT_PIN_RE = /^【此刻·切记】(.*)$/
const PIPE_RE = /^[^：]+：.*$/
const KV_RE = /^([^，。；、！？"”,.;:!?—]{1,12})：(.+)$/

export function parseBlockContent(content: string, blockKey = ''): BlockNode[] {
  const src = (content || '').replace(/^[ \t\r\n]+/, '').replace(/\s+$/, '')
  if (!src) return []
  const nodes: BlockNode[] = []
  let afterItem = false
  for (const rawLine of src.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line.trim()) continue // 空行 = 块间/条目间结构间隔
    let m: RegExpMatchArray | null
    if ((m = line.match(HEADING_RE))) {
      nodes.push({ type: 'heading', text: m[1] })
      afterItem = false
    } else if ((m = line.match(SAMPLE_RE))) {
      nodes.push({ type: 'sample', text: m[0] })
      afterItem = false
    } else if ((m = line.match(ITEM_RE))) {
      nodes.push({ type: 'item', text: m[1] })
      afterItem = true
    } else if (afterItem && (m = line.match(PROFILE_RE))) {
      nodes.push({ type: 'profile', text: m[1] })
    } else if (line.match(NOTE_RE)) {
      nodes.push({ type: 'note', text: line })
      afterItem = false
    } else if ((m = line.match(RECENT_PIN_RE))) {
      // recency 钉：前缀【此刻·切记】并入首段 k（字符零丢弃），其余段各自 kv
      pushPipedSegments(nodes, m[0])
      afterItem = false
    } else if (blockKey === 'scene' && line.match(PIPE_RE)) {
      // 场景身份行：按 ｜ 切段，每段 k：v
      pushPipedSegments(nodes, line)
      afterItem = false
    } else if ((m = line.match(KV_RE))) {
      nodes.push({ type: 'kv', k: m[1], v: m[2] })
      afterItem = false
    } else {
      nodes.push({ type: 'plain', text: line })
      afterItem = false
    }
  }
  return nodes
}

/** ｜ 切段 → 每段 k：v 或 plain；首段若带【此刻·切记】前缀则并入 k */
function pushPipedSegments(nodes: BlockNode[], line: string): void {
  const pinMatch = line.match(RECENT_PIN_RE)
  const pinPrefix = pinMatch ? '【此刻·切记】' : ''
  const body = pinMatch ? pinMatch[1] : line
  const segments = body.split('｜')
  segments.forEach((seg, i) => {
    const withPrefix = i === 0 ? pinPrefix + seg : seg
    const kv = withPrefix.match(KV_RE) || withPrefix.match(PIPE_RE)
    if (kv) {
      const idx = withPrefix.indexOf('：')
      nodes.push({ type: 'kv', k: withPrefix.slice(0, idx), v: withPrefix.slice(idx + 1) })
    } else if (seg.trim()) {
      nodes.push({ type: 'plain', text: withPrefix })
    }
  })
}

// ===== 保字不变式（§5.5 测试契约；生产侧不消费，测试侧对拍用） =====

/** 节点树摊平成纯文本（丢的全是结构标记对应的字符） */
export function flattenNodes(nodes: BlockNode[]): string {
  return nodes
    .map((n) => (n.type === 'kv' ? n.k + n.v : n.text))
    .join('')
}

/** 不变式归一：去空白 + 去结构标记（行首 #/##、"- "、缩进）+ 去 ｜/： 分隔符 */
export function normalizeForInvariant(text: string): string {
  return text
    .split('\n')
    .map((l) => l.replace(/^[ \t]+/, '').replace(/^#{1,2} /, '').replace(/^- /, ''))
    .join('')
    .replace(/[｜：\s]/g, '')
}
