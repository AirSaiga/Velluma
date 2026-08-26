/**
 * 全书通读编排（2026-08-25 战略定稿「系统自己去读」的存量通读首秀）。
 *
 * 两阶段（严格保序：事件抽取需要实体打底，无人可认则无话可记）：
 *   阶段 A「认人」：逐章 read-entities（只产草稿不落库）→ 汇总去重 → 作者批量
 *     过目勾选 → 确认才建实体/地点（实体建设永远是作者动作）；
 *   阶段 B「记事」：逐章 auto-read → 事件候选进收件箱（物理隔离，作者 ✓ 才转正）。
 *
 * 幂等：后端按章内容哈希跳过重读，中断后重跑只补未读的章。
 * 可中断：章间检查取消标志（单章 LLM 调用不可中断，最多多跑一章）。
 */
import { computed, ref } from 'vue'
import { chapterApi } from '../../../services/api/domain'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import { worldApi } from '../../../services/api/domain/world.api'

export type ReadBookPhase = 'idle' | 'entities' | 'review' | 'events' | 'done' | 'error'

export interface EntityCandidate {
  name: string
  /** emergent 原始类型：character|item|skill|org */
  type: string
  description: string
  /** 汇总时命中章数（排序用——出场多的排前） */
  mentions: number
  checked: boolean
}

export interface LocationCandidate {
  name: string
  description: string
  mentions: number
  checked: boolean
}

const MIN_CHAPTER_TEXT = 100 // 与后端 AUTO_READ_MIN_TEXT 同阈值（前端预筛少发请求）

/** emergent 类型 → world 实体类型（world 只有三类；item/skill 归资产） */
function toEntityType(t: string): 'character' | 'faction' | 'asset' {
  if (t === 'character') return 'character'
  if (t === 'org') return 'faction'
  return 'asset'
}

function normalizeName(n: string): string {
  return (n || '').replace(/\s+/g, '')
}

export function useReadBook() {
  const phase = ref<ReadBookPhase>('idle')
  const progress = ref<{ done: number; total: number; label: string } | null>(null)
  const entityCandidates = ref<EntityCandidate[]>([])
  const locationCandidates = ref<LocationCandidate[]>([])
  const createdEntities = ref(0)
  const createdCandidates = ref(0)
  const skippedCount = ref(0)
  const errorMsg = ref('')
  /** 建设期忙碌闸 + 进度（防连点，2026-08-26 实测事故） */
  const creating = ref(false)
  const createProgress = ref<{ done: number; total: number } | null>(null)
  let cancelled = false

  const reviewCount = computed(() =>
    entityCandidates.value.filter((c) => c.checked).length
    + locationCandidates.value.filter((c) => c.checked).length,
  )

  function reset() {
    phase.value = 'idle'
    progress.value = null
    entityCandidates.value = []
    locationCandidates.value = []
    createdEntities.value = 0
    createdCandidates.value = 0
    skippedCount.value = 0
    errorMsg.value = ''
    creating.value = false
    createProgress.value = null
    cancelled = false
  }

  function cancel() {
    cancelled = true
  }

  /** 阶段 A：逐章抽实体候选并汇总（按规范化名去重，同名合并计数）。 */
  async function start(bookId: string) {
    reset()
    phase.value = 'entities'
    let chapters: any[] = []
    try {
      chapters = (await chapterApi.getAll(bookId)) || []
    } catch {
      errorMsg.value = '章节列表读取失败'
      phase.value = 'error'
      return
    }
    const targets = chapters
      .filter((c) => (c.content_text || '').length >= MIN_CHAPTER_TEXT)
      .sort((a, b) => (a.chapter_number || 0) - (b.chapter_number || 0))
    if (!targets.length) {
      errorMsg.value = '这本书还没有可读的章节'
      phase.value = 'error'
      return
    }

    await extractAll(targets, false)
    // 重跑死局保险（2026-08-25 实测）：全部章节因哈希幂等跳过且零产出——
    // 说明此前读过但 review 状态丢了（刷新/中断）；若世界仍零实体，
    // 候选从未被确认落库，自动带 force 重抽一次（预算闸不豁免）。
    if (!entityCandidates.value.length && !locationCandidates.value.length && !cancelled) {
      let existing: any[] = []
      try {
        existing = await worldApi.listEntities(bookId)
      } catch { /* 查询失败按有实体处理，不重抽 */ }
      if (!existing.length) {
        skippedCount.value = 0
        await extractAll(targets, true)
      }
    }
    progress.value = null
    if (phase.value === 'entities') phase.value = 'review'
  }

  async function extractAll(targets: any[], force: boolean) {
    const entMap = new Map<string, EntityCandidate>()
    const locMap = new Map<string, LocationCandidate>()
    for (let i = 0; i < targets.length; i++) {
      if (cancelled) { phase.value = 'idle'; return }
      const ch = targets[i]
      progress.value = { done: i + 1, total: targets.length, label: ch.title || `第${ch.chapter_number}章` }
      try {
        const r = await adaptiveApi.readEntities(ch.id, force)
        if (!r.ran) { if (r.skipped) skippedCount.value++; continue }
        for (const e of r.entities || []) {
          const key = normalizeName(e.name)
          if (!key) continue
          const hit = entMap.get(key)
          if (hit) hit.mentions++
          else entMap.set(key, {
            name: String(e.name).trim(), type: e.type || 'character',
            description: e.description || '', mentions: 1, checked: true,
          })
        }
        for (const l of r.locations || []) {
          const key = normalizeName(l.name)
          if (!key) continue
          const hit = locMap.get(key)
          if (hit) hit.mentions++
          else locMap.set(key, {
            name: String(l.name).trim(), description: l.description || '',
            mentions: 1, checked: true,
          })
        }
      } catch {
        skippedCount.value++ // 单章失败不阻塞整批（下一章继续）
      }
    }
    entityCandidates.value = [...entMap.values()].sort((a, b) => b.mentions - a.mentions)
    locationCandidates.value = [...locMap.values()].sort((a, b) => b.mentions - a.mentions)
  }

  /** 作者确认勾选 → 建实体/地点（此处才落库）→ 自动接阶段 B。
   *  忙碌闸（2026-08-26 实测事故：连点 14 次建出 14 份同名实体）——
   *  建设期间重复点击直接忽略；进度外露给模态禁用按钮用。 */
  async function confirmEntities(bookId: string) {
    if (creating.value || cancelled) return
    creating.value = true
    const ents = entityCandidates.value.filter((x) => x.checked)
    const locs = locationCandidates.value.filter((x) => x.checked)
    const total = ents.length + locs.length
    let done = 0
    createProgress.value = { done: 0, total }
    try {
      for (const c of ents) {
        try {
          await worldApi.createEntity(bookId, {
            entity_type: toEntityType(c.type),
            name: c.name,
            intro: c.description,
          })
          createdEntities.value++
        } catch { /* 单个失败不阻塞（服务端幂等闸兜重名） */ }
        createProgress.value = { done: ++done, total }
      }
      for (const l of locs) {
        try {
          await worldApi.createLocation(bookId, { name: l.name, intro: l.description })
          createdEntities.value++
        } catch { /* 同上 */ }
        createProgress.value = { done: ++done, total }
      }
    } finally {
      creating.value = false
      createProgress.value = null
    }
    if (!cancelled) await runEvents(bookId)
  }

  /** 阶段 B：逐章 auto-read，事件候选进收件箱。 */
  async function runEvents(bookId: string) {
    phase.value = 'events'
    let chapters: any[] = []
    try {
      chapters = (await chapterApi.getAll(bookId)) || []
    } catch {
      errorMsg.value = '章节列表读取失败'
      phase.value = 'error'
      return
    }
    const targets = chapters
      .filter((c) => (c.content_text || '').length >= MIN_CHAPTER_TEXT)
      .sort((a, b) => (a.chapter_number || 0) - (b.chapter_number || 0))
    for (let i = 0; i < targets.length; i++) {
      if (cancelled) { phase.value = 'idle'; return }
      const ch = targets[i]
      progress.value = { done: i + 1, total: targets.length, label: ch.title || `第${ch.chapter_number}章` }
      try {
        const r = await adaptiveApi.autoRead(ch.id)
        // 跳过也要计账（2026-08-26 审计修复）：阶段 B 曾把 skipped 整个丢弃——
        // 额度用完/间隔未到时完成页谎报「读完了、0 条」；与阶段 A 同口径计入跳过数
        if (r.ran) createdCandidates.value += r.created || 0
        else if (r.skipped) skippedCount.value++
      } catch { /* 单章失败不阻塞 */ }
    }
    progress.value = null
    phase.value = 'done'
  }

  return {
    phase, progress, entityCandidates, locationCandidates,
    createdEntities, createdCandidates, skippedCount, errorMsg, reviewCount,
    creating, createProgress,
    start, confirmEntities, runEvents, cancel, reset,
  }
}
