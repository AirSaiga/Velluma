import { ref } from 'vue'
import type { Toast, ToastType } from '../components/Toast.vue'

/**
 * 全局 Toast 队列（UX 重构地基 00 期 §5.3 治理）：
 * - 堆叠上限 3 条：push 前逐出最旧的可逐出者（优先 info/success，上限绝对）；
 * - 1500ms 同文去重：同 message+type 重复 push 不新增，重置既有条计时器（治连点双 Toast）；
 * - 计时器句柄 Map 持有，逐出/移除时清定时器；
 * - 时序/时长/action(s) 契约不变（撤销胶囊、理由条不受影响）。
 */
const toasts = ref<Toast[]>([])
let nextId = 0
const timers = new Map<number, ReturnType<typeof setTimeout>>()
const lastPushAt = new Map<string, number>()

const MAX_VISIBLE = 3
const DEDUPE_WINDOW_MS = 1500

const typeDurations: Record<ToastType, number> = {
  success: 4000,
  error: 6000,
  warning: 5000,
  info: 4000
}

export interface ToastAction {
  label: string
  onClick: () => void
}

function pruneDedupeLog(now: number) {
  for (const [key, ts] of lastPushAt) {
    if (now - ts >= DEDUPE_WINDOW_MS) lastPushAt.delete(key)
  }
}

function scheduleRemoval(id: number, duration: number) {
  const timer = setTimeout(() => removeToast(id), duration)
  timers.set(id, timer)
}

/** 逐出最旧的可逐出者：优先无动作按钮的（撤销胶囊/理由条带 action，逐出=截断
 *  作者的 undo 窗口，与「action 契约不变」承诺相悖——2026-09-07 审计修复），
 *  候选内再按 info/success → warning → error，全部带动作时才动最旧的一条。 */
function evictOldest() {
  const plain = toasts.value.filter((t) => !t.action && !(t.actions && t.actions.length))
  const pool = plain.length > 0 ? plain : toasts.value
  const preference: ToastType[] = ['info', 'success', 'warning', 'error']
  for (const type of preference) {
    const victim = pool.find((t) => t.type === type)
    if (victim) {
      removeToast(victim.id)
      return
    }
  }
  if (pool.length > 0) removeToast(pool[0].id)
}

const removeToast = (id: number) => {
  const index = toasts.value.findIndex(t => t.id === id)
  if (index !== -1) {
    toasts.value.splice(index, 1)
  }
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer)
    timers.delete(id)
  }
}

export function useToast() {
  /** 显示 toast；action（可选）渲染为可点按钮——点击即执行并关掉 toast（S4 撤销胶囊基础）。
   *  actions（可选，学着闭嘴）渲染为多动作按钮组，与 action 可同时存在（互不影响）。
   *  返回 toast id（重复展示去重时返回既有条 id）。 */
  const showToast = (
    message: string,
    type: ToastType = 'info',
    duration?: number,
    action?: ToastAction,
    actions?: ToastAction[],
  ): number => {
    const now = Date.now()
    pruneDedupeLog(now)

    // 同文去重：重置既有条计时器，不新增
    const key = `${type}|${message}`
    const last = lastPushAt.get(key)
    if (last !== undefined && now - last < DEDUPE_WINDOW_MS) {
      const existing = [...toasts.value].reverse().find((t) => t.type === type && t.message === message)
      if (existing) {
        const timer = timers.get(existing.id)
        if (timer) clearTimeout(timer)
        scheduleRemoval(existing.id, duration ?? typeDurations[type])
        lastPushAt.set(key, now)
        return existing.id
      }
    }

    // 堆叠上限（绝对）
    while (toasts.value.length >= MAX_VISIBLE) evictOldest()

    const id = nextId++
    toasts.value.push({ id, message, type, action, actions })
    lastPushAt.set(key, now)
    scheduleRemoval(id, duration ?? typeDurations[type])
    return id
  }

  return {
    toasts,
    showToast,
    removeToast
  }
}
