import { ref } from 'vue'
import { worldApi } from '../../../services/api/domain/world.api'
import type {
  SceneSlice,
  WorldEventCandidate,
  WorldVersion,
} from '../../../services/api/domain/world.api'

/**
 * 写作页「此刻此地」世界切片 store（模块级单例，docs/world-writing-bridge.md W1/W4）。
 *
 * 数据源 GET /world/scene-slice——与生成上下文（settings_bundle）共用同一份
 * 时间解析与事件推演，作者看到的在场 = AI 看到的在场。
 *
 * 保鲜三时机：
 * ① 章节切换：切片条组件 watch chapterId → load
 * ② 心跳携带版本：useAdaptiveAssist 经 velluma:world-version 事件分发 → 版本
 *    变化时静默重取（心跳三重门控下纯手写/阅读态无心跳，③ 是硬性兜底）
 * ③ 窗口重新聚焦：本模块自管监听（世界页与写作页双开时的同步）
 *
 * W4 候选回流：candidates（本章 pending 池）随 load 一并拉取；settle/finish 经
 * velluma:world-refresh 事件触发静默重取（收件箱出现「本章带来 N 处世界变化」）。
 *
 * 红点（updated）：静默重取后内容签名确有变化才亮，点击确认清除——「世界有更新」
 * 的提示不打断，只标记。
 */

export const WORLD_VERSION_EVENT = 'velluma:world-version'
export const WORLD_REFRESH_EVENT = 'velluma:world-refresh'
/** P3-4（C6）：settle/finish 带回的「世界发现」跳过原因（detail.reason 为 null 时清除） */
export const SCOUT_SKIPPED_EVENT = 'velluma:scout-skipped'

const slice = ref<SceneSlice | null>(null)
const candidates = ref<WorldEventCandidate[]>([])
const loading = ref(false)
const updated = ref(false)
/** 「世界发现」跳过原因（作者语言一句话；空 = 无提示，收件箱空态维持现状） */
const scoutSkipped = ref<string | null>(null)

let currentKey: { bookId: string; chapterId: string } | null = null
let listenersAttached = false

// 模块顶层直接挂监听（不进 attachListeners 的惰性挂载）：dispatch 时刻
// WorldSceneSlice 可能处于卸载态（副驾不在「此刻」tab），惰性挂载会丢事件
if (typeof window !== 'undefined') {
  window.addEventListener(SCOUT_SKIPPED_EVENT, (ev) => {
    const detail = (ev as CustomEvent<{ reason: string | null }>).detail
    scoutSkipped.value = detail?.reason || null
  })
}

/** 内容签名：变化才算「世界有更新」（版本号变化但内容等价不亮红点） */
function signature(s: SceneSlice): string {
  return [
    s.t,
    s.t_source,
    s.presence.map((p) => `${p.entity_id}:${p.alive}:${p.location_name}:${p.label}`).join('|'),
    s.scene?.location_id ?? '',
    s.foreshadows.map((f) => f.ledger_key).join('|'),
    s.expectations.map((e) => e.description).join('|'),
  ].join('~')
}

async function loadCandidates(bookId: string, chapterId: string) {
  // 竞态守卫（与 load 同口径，2026-09-17 补齐）：请求期间已切章 → 丢弃过期
  // 响应——此前 slice 有守卫而 candidates 没有，切章途中旧章候选会落地覆盖
  const reqKey = { bookId, chapterId }
  const stale = () => currentKey?.bookId !== reqKey.bookId || currentKey?.chapterId !== reqKey.chapterId
  try {
    const list = await worldApi.listCandidates(bookId, chapterId, 'pending')
    if (stale()) return
    candidates.value = list
  } catch {
    if (stale()) return
    candidates.value = [] // 收件箱缺席不影响切片本体
  }
}

async function load(bookId: string, chapterId: string, opts: { silent?: boolean } = {}) {
  if (!bookId || !chapterId) return
  const prevKey = currentKey
  currentKey = { bookId, chapterId }
  if (!opts.silent) loading.value = true
  try {
    const next = await worldApi.getSceneSlice(bookId, chapterId)
    // 竞态守卫：请求期间已切章 → 丢弃过期响应
    if (currentKey.bookId !== bookId || currentKey.chapterId !== chapterId) return
    // 签名只在同章内比较（遗留修：切章时 t_source/在场合法变化，不算「世界有更新」）
    const sameChapter = prevKey?.bookId === bookId && prevKey?.chapterId === chapterId
    const prevSig = slice.value && sameChapter ? signature(slice.value) : ''
    slice.value = next
    if (prevSig && signature(next) !== prevSig) updated.value = true
  } catch (e) {
    console.warn('[WorldSlice] 加载切片失败', e)
  } finally {
    loading.value = false
  }
  await loadCandidates(bookId, chapterId)
}

/** 心跳附带的世界版本（velluma:world-version 事件携带）→ 版本变化时静默重取 */
async function notifyVersion(chapterId: string, v: WorldVersion | null | undefined) {
  if (!v || !slice.value) return
  if (currentKey?.chapterId !== chapterId) return
  const cur = slice.value.version
  if (cur.events !== v.events || (cur.updated_at || null) !== (v.updated_at || null)) {
    await load(currentKey.bookId, chapterId, { silent: true })
  }
}

/** 切片条「改」入口：设置/清除本章叙事锚后立即重取（切片时刻随之变化） */
async function setNarrativeTime(bookId: string, chapterId: string, t: number | null) {
  await worldApi.setChapterAnchor(chapterId, t)
  await load(bookId, chapterId, { silent: true })
}

/** 本章场景钉（W5-lite）：钉定/取消后重取（「脚下」第一优先级） */
async function setScenePin(bookId: string, chapterId: string, locationId: string | null) {
  await worldApi.setScenePin(chapterId, locationId)
  await load(bookId, chapterId, { silent: true })
}

/** W4 ✓ 转正：返回创建的事件（撤销胶囊用 event.id 删除 + reopen）；
 *  C3 canon 候选分流建真相节点不建事件（event=null → 返回 null，调用方静默） */
async function acceptCandidate(
  bookId: string,
  candidateId: string,
): Promise<{ eventId: string; label: string } | null> {
  const r = await worldApi.acceptCandidate(bookId, candidateId)
  if (currentKey) await load(currentKey.bookId, currentKey.chapterId, { silent: true })
  if (!r.event) return null
  return { eventId: r.event.id, label: r.event.note || r.event.event_type }
}

/** W4 ✗ 丢弃 */
async function rejectCandidate(bookId: string, candidateId: string) {
  await worldApi.rejectCandidate(bookId, candidateId)
  if (currentKey) await loadCandidates(currentKey.bookId, currentKey.chapterId)
}

/** W4 撤销入账：单事务端点一步完成（02 修缮 P2b，删事件 + 回 pending 原子化；
 *  eventId 显式带上覆盖存量候选——draft.accepted_event_id 上线前的已采纳者） */
async function undoAccept(bookId: string, candidateId: string, eventId?: string) {
  await worldApi.undoAcceptCandidate(bookId, candidateId, { event_id: eventId || null })
  if (currentKey) await load(currentKey.bookId, currentKey.chapterId, { silent: true })
}

function acknowledgeUpdate() {
  updated.value = false
}

function attachListeners() {
  if (listenersAttached) return
  listenersAttached = true
  window.addEventListener('focus', () => {
    if (currentKey) void load(currentKey.bookId, currentKey.chapterId, { silent: true })
  })
  window.addEventListener(WORLD_VERSION_EVENT, (ev) => {
    const detail = (ev as CustomEvent<{ chapterId: string; version: WorldVersion }>).detail
    if (detail?.chapterId && detail.version) {
      void notifyVersion(detail.chapterId, detail.version)
    }
  })
  // settle/finish/速记入账/候选转正后的主动刷新（比心跳版本更快兑现）
  window.addEventListener(WORLD_REFRESH_EVENT, () => {
    if (currentKey) void load(currentKey.bookId, currentKey.chapterId, { silent: true })
  })
}

export function useWorldSlice() {
  attachListeners()
  return {
    slice,
    candidates,
    loading,
    updated,
    scoutSkipped,
    load,
    notifyVersion,
    setNarrativeTime,
    setScenePin,
    acceptCandidate,
    rejectCandidate,
    undoAccept,
    acknowledgeUpdate,
  }
}
