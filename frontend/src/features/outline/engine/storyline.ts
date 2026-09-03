/**
 * 故事线俯视板纯函数（大纲板方案 A，2026-09-03）。
 *
 * 章号轴上的伏笔弧线 / 锚点进度 / 真相揭示分组的全部排布判据。
 * 输入输出均为纯数据（不碰 services 层类型，对拍单测 __tests__/storyline.test.ts）。
 * 世界页时间轴的弧线带（ArcBand）按「世界时间」排布；本模块按「章号」排布——
 * 两根轴正交：时间轴管设定事实的世界时间，故事线管叙事节奏。
 */

// ===== 输入形状（与 services 层契约对齐的本地子集）=====

/** spine 锚点的最小形状（status: pending 未兑现 / hit 已兑现 / dropped 放弃） */
export interface StorylineAnchor {
  id: string
  text: string
  status: 'pending' | 'hit' | 'dropped'
}

export interface StorylineSpine {
  intent?: { text: string } | null
  anchors?: StorylineAnchor[] | null
}

/** 伏笔账本的最小形状（PlotLedgerEntry 子集） */
export interface StorylineLedger {
  id: string
  content: string
  status: 'open' | 'closed' | 'dropped'
  /** 埋设章号（created_at_chapter）；null = 无章锚 */
  plantedChapter?: number | null
  /** 回收章节 ID（resolved_in_chapter_id）；null = 未回收 */
  resolvedChapterId?: string | null
}

/** 真相节点的最小形状（CanonNode 子集） */
export interface StorylineCanonNode {
  label: string
  visibility: string
  expected_reveal_chapter?: number | null
}

// ===== 锚点进度 =====

export interface AnchorProgress {
  /** 已兑现数 */
  done: number
  /** 有效总数（dropped 不计） */
  total: number
}

/** 打算锚点进度：dropped 剔除，hit 计兑现。无锚点返回 0/0（调用方按 total>0 决定显示）。 */
export function anchorProgress(spine: StorylineSpine | null | undefined): AnchorProgress {
  const anchors = spine?.anchors ?? []
  let done = 0
  let total = 0
  for (const a of anchors) {
    if (!a || a.status === 'dropped') continue
    total += 1
    if (a.status === 'hit') done += 1
  }
  return { done, total }
}

/** 打算一句话（intent.text 去首尾空白；空 spine 返回空串）。 */
export function spineIntentText(spine: StorylineSpine | null | undefined): string {
  return (spine?.intent?.text ?? '').trim()
}

// ===== 伏笔弧线 =====

export interface StorylineArc {
  id: string
  content: string
  /** 埋设章号（已校验存在于章列表） */
  fromN: number
  /** 回收章号；null = 悬空（open 未收，画到轴右缘渐隐） */
  toN: number | null
  resolved: boolean
}

/**
 * 伏笔账本 → 章号轴弧线集。
 *
 * 剔除规则（与 ArcBand「无世界锚不在弧线带」同纪律）：
 * - dropped 剔除；
 * - 无埋设章号（plantedChapter 空/不在章列表）剔除——起笔无处安放；
 * - closed 但回收章 ID 解析不到章号（章节已删）剔除——终点无处安放，不做悬空假画。
 */
export function buildStoryArcs(
  ledgers: StorylineLedger[],
  chapterNumberById: Map<string, number>,
  validNumbers: Set<number>,
): StorylineArc[] {
  const out: StorylineArc[] = []
  for (const l of ledgers) {
    if (!l || l.status === 'dropped') continue
    const fromN = l.plantedChapter ?? null
    if (fromN == null || !validNumbers.has(fromN)) continue
    if (l.status === 'closed') {
      const toN = l.resolvedChapterId ? chapterNumberById.get(l.resolvedChapterId) ?? null : null
      if (toN == null || !validNumbers.has(toN)) continue
      out.push({ id: l.id, content: l.content, fromN, toN, resolved: true })
    } else {
      out.push({ id: l.id, content: l.content, fromN, toN: null, resolved: false })
    }
  }
  return out
}

// ===== 弧线分道（同 world 时间轴 assignRows 的区间装道判据，章号版）=====

export interface LanedArc extends StorylineArc {
  /** 弧线水平区间（章索引，含端点） */
  start: number
  end: number
  /** 道号（0 起，重叠弧线自上而下堆叠） */
  lane: number
}

/**
 * 弧线按章索引区间贪心分道：区间 [start,end] 找第一条「最后一条弧线 end 更小」的道，
 * 找不到开新道。悬空弧线 end = lastIdx（画到右缘）。
 * 输入只需 arcs + 章号→索引映射；输出已按 start 升序稳定排列。
 */
export function assignArcLanes(
  arcs: StorylineArc[],
  indexOfNumber: Map<number, number>,
  lastIdx: number,
): LanedArc[] {
  const placed: LanedArc[] = arcs
    .map((a) => {
      const i = indexOfNumber.get(a.fromN)
      if (i == null) return null
      const j = a.toN != null ? indexOfNumber.get(a.toN) : lastIdx
      if (j == null) return null
      return { ...a, start: Math.min(i, j), end: Math.max(i, j), lane: 0 }
    })
    .filter((x): x is LanedArc => x != null)
    .sort((a, b) => a.start - b.start || a.end - b.end)
  const laneEnds: number[] = []
  for (const arc of placed) {
    let lane = laneEnds.findIndex((e) => e < arc.start)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(arc.end)
    } else {
      laneEnds[lane] = arc.end
    }
    arc.lane = lane
  }
  return placed
}

// ===== 章节刻上的伏笔记号（埋/收计数）=====

export interface ChapterMarks {
  planted: number
  resolved: number
}

/** 每章的伏笔埋/收计数（只统计画进弧线的有效伏笔；dropped 与无锚不计）。 */
export function chapterMarks(arcs: StorylineArc[], n: number): ChapterMarks {
  let planted = 0
  let resolved = 0
  for (const a of arcs) {
    if (a.fromN === n) planted += 1
    if (a.toN === n) resolved += 1
  }
  return { planted, resolved }
}

// ===== 真相揭示分组 =====

/**
 * 真相节点按「计划揭示章号」分组——只有 秘密/半露（visibility !== 'public'）
 * 且带 expected_reveal_chapter 的条目才构成朱点（与时间轴 C3 揭示投影同语义）。
 */
export function groupReveals(nodes: StorylineCanonNode[]): Map<number, string[]> {
  const out = new Map<number, string[]>()
  for (const nd of nodes) {
    if (!nd || nd.visibility === 'public') continue
    const n = nd.expected_reveal_chapter
    if (n == null || !Number.isFinite(n)) continue
    const list = out.get(n)
    if (list) list.push(nd.label)
    else out.set(n, [nd.label])
  }
  return out
}

// ===== 张力曲线样本（章号对齐 + 数值夹取）=====

export interface StorylineTensionSample {
  n: number
  /** 0..10（越界夹取；读者镜像口径） */
  tension: number
  payoff: boolean
}

/** 张力样本按章列表过滤（画不到的章号剔除）+ 数值夹取 0..10。 */
export function alignTensionSamples(
  samples: Array<{ chapter_number: number; overall_tension: number; is_payoff_chapter?: boolean }>,
  validNumbers: Set<number>,
): StorylineTensionSample[] {
  const out: StorylineTensionSample[] = []
  for (const s of samples) {
    if (!s || !validNumbers.has(s.chapter_number)) continue
    const t = Number(s.overall_tension)
    if (!Number.isFinite(t)) continue
    out.push({
      n: s.chapter_number,
      tension: Math.max(0, Math.min(10, t)),
      payoff: !!s.is_payoff_chapter,
    })
  }
  return out.sort((a, b) => a.n - b.n)
}
