/**
 * 章级谋篇·软脉络状态（P1.4 M1，docs/chapter-planning-spine.md）。
 *
 * 模块级单例（同 useWorldSlice 模式）：WorkspaceView（复合谋篇卡）与
 * InspectorPanel（副驾章节 tab 谋篇区）共享同一份 spine 状态。
 *
 * 度优先的实现：意图一句话可空；锚点硬上限 5（超限后端 422 劝阻，本地
 * 也拦一道）；2s 防抖自动保存（文风页同款契约）；无脉络 → spine=null，
 * 相关 UI 静默缺席（D-3）。切章重载。
 */
import { ref, watch } from 'vue'
import {
  adaptiveApi,
  type ChapterSpine,
  type SpineAnchor,
  type SpineSuggestion,
} from '../../../services/api/domain/adaptive.api'
import { logCollabEvent } from '../../../composables/useCollabTelemetry'

export const spine = ref<ChapterSpine | null>(null)
export const spineSuggestions = ref<SpineSuggestion | null>(null)
export const spineSuggesting = ref(false)
export const spineLoaded = ref(false)

let currentChapterId: string | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null
let suppressAutosave = false

export function useChapterSpine() {
  async function load(chapterId: string) {
    currentChapterId = chapterId
    spine.value = null
    spineSuggestions.value = null
    spineLoaded.value = false
    suppressAutosave = true
    try {
      const r = await adaptiveApi.getSpine(chapterId)
      if (currentChapterId === chapterId) spine.value = r.spine
    } catch {
      /* 静默——谋篇缺席不影响写作 */
    } finally {
      spineLoaded.value = true
      suppressAutosave = false
    }
  }

  function unload() {
    currentChapterId = null
    spine.value = null
    spineSuggestions.value = null
    suppressAutosave = true
  }

  async function save(patch: { intent?: ChapterSpine['intent'] | null; anchors?: SpineAnchor[] | null }) {
    if (!currentChapterId) return
    try {
      const r = await adaptiveApi.patchSpine(currentChapterId, patch)
      suppressAutosave = true
      spine.value = r.spine
      // nextTick 后恢复自动保存（赋值本身不该再触发一轮）
      setTimeout(() => { suppressAutosave = false }, 0)
    } catch (e: any) {
      // 422 劝阻文案直接冒给调用方 UI；其它静默（谋篇保存失败不打断写作）
      if (e?.status === 422 || /422|锚点/.test(e?.message || '')) throw e
    }
  }

  /** 建议收下（D-4：此刻才落库）；mode 决定收意图还是锚点 */
  async function adoptSuggestion(part: 'intent' | 'anchors' | 'all') {
    const s = spineSuggestions.value
    if (!s) return
    const cur = spine.value || {}
    const patch: { intent?: ChapterSpine['intent']; anchors?: SpineAnchor[] } = {}
    if ((part === 'intent' || part === 'all') && s.intent) {
      patch.intent = { text: s.intent, source: 'ai' }
    }
    if (part === 'anchors' || part === 'all') {
      const existing = cur.anchors || []
      const room = Math.max(0, 5 - existing.length)
      patch.anchors = [
        ...existing,
        ...s.anchors.slice(0, room).map((text, i) => ({
          id: `ai_${Date.now()}_${i}`,
          text,
          source: 'ai' as const,
          status: 'pending' as const,
        })),
      ]
    }
    logCollabEvent(currentChapterId, 'spine_suggest_adopt', { part })
    await save(patch)
  }

  function discardSuggestions() {
    spineSuggestions.value = null
    logCollabEvent(currentChapterId, 'spine_suggest_discard')
  }

  // ---- 就地编辑动作（直接改 spine.value → 2s 防抖自动保存） ----

  function _ensure(): ChapterSpine {
    if (!spine.value) spine.value = { anchors: [] }
    if (!spine.value.anchors) spine.value.anchors = []
    return spine.value
  }

  function setIntent(text: string) {
    const s = _ensure()
    s.intent = { text: text.trim().slice(0, 60), source: s.intent?.source || 'author' }
    logCollabEvent(currentChapterId, 'spine_intent_set')
  }

  function addAnchor(text: string) {
    const s = _ensure()
    if (s.anchors!.length >= 5) return
    s.anchors = [...s.anchors!, {
      id: `a_${Date.now()}`,
      text: text.trim().slice(0, 12),
      source: 'author',
      status: 'pending',
    }]
    logCollabEvent(currentChapterId, 'spine_anchor_add')
  }

  function updateAnchor(id: string, patch: Partial<SpineAnchor>) {
    const s = spine.value
    if (!s?.anchors) return
    s.anchors = s.anchors.map((a) => (a.id === id ? { ...a, ...patch } : a))
    if (patch.status === 'dropped') logCollabEvent(currentChapterId, 'spine_anchor_drop')
  }

  function removeAnchor(id: string) {
    const s = spine.value
    if (!s?.anchors) return
    s.anchors = s.anchors.filter((a) => a.id !== id)
    if (!s.intent?.text && !s.anchors.length) spine.value = null  // 全空 = 无脉络
    logCollabEvent(currentChapterId, 'spine_anchor_remove')
  }

  async function suggest() {
    if (!currentChapterId || spineSuggesting.value) return
    spineSuggesting.value = true
    logCollabEvent(currentChapterId, 'spine_suggest')
    try {
      spineSuggestions.value = await adaptiveApi.spineSuggest(currentChapterId)
    } catch {
      spineSuggestions.value = null
    } finally {
      spineSuggesting.value = false
    }
  }

  // ---- 2s 防抖自动保存（加载/保存期间抑制） ----
  watch(spine, (val) => {
    if (suppressAutosave || !currentChapterId || !val) return
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => {
      saveTimer = null
      void save({ ...val })
    }, 2000)
  }, { deep: true })

  return {
    spine, spineSuggestions, spineSuggesting, spineLoaded,
    load, unload, save, suggest, adoptSuggestion, discardSuggestions,
    setIntent, addAnchor, updateAnchor, removeAnchor,
  }
}
