/**
 * 章级谋篇·软脉络状态（P1.4 M1，docs/chapter-planning-spine.md）。
 *
 * 模块级单例（同 useWorldSlice 模式）：WorkspaceView（复合谋篇卡）与
 * InspectorPanel（副驾谋篇 tab）共享同一份 spine 状态。
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
  type SpineProgress,
} from '../../../services/api/domain/adaptive.api'
import { logCollabEvent } from '../../../composables/useCollabTelemetry'

export const spine = ref<ChapterSpine | null>(null)
export const spineSuggestions = ref<SpineSuggestion | null>(null)
export const spineSuggesting = ref(false)
export const spineLoaded = ref(false)
/** 心跳带回的谋篇进度（P1.4 M2：感知带进度行数据源；无脉络为 null） */
export const spineProgress = ref<SpineProgress | null>(null)
/** 走向卡小签点击 → 高亮对应锚点（SpinePanel 闪烁；2s 自动清） */
export const highlightAnchorId = ref<string | null>(null)

export function flashAnchor(id: string) {
  highlightAnchorId.value = id
  setTimeout(() => { if (highlightAnchorId.value === id) highlightAnchorId.value = null }, 2000)
}

/** 心跳进度回写本地 spine（状态只前进；触发一次无害的防抖保存保持双端一致） */
export function applySpineProgress(p: SpineProgress | null | undefined) {
  spineProgress.value = p || null
  if (!p || !spine.value?.anchors) return
  const byId = new Map(p.anchors.map((a) => [a.id, a.status]))
  spine.value.anchors = spine.value.anchors.map((a) => ({
    ...a,
    status: byId.get(a.id) === 'hit' && a.status === 'pending' ? 'hit' : a.status,
  }))
}

let currentChapterId: string | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null
let suppressAutosave = false

export function useChapterSpine() {
  async function load(chapterId: string) {
    // 切章竞态保险一：撤销在途防抖定时器——否则旧回调闭包携带 A 章 spine，
    // 而 save() 读「此刻」currentChapterId（已切到 B），A 数据会整包写到 B 章。
    // 设计取舍：不在切章前 flush 旧章在途编辑，丢弃 <2s 编辑是最小代价
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
    currentChapterId = chapterId
    spine.value = null
    spineSuggestions.value = null
    spineProgress.value = null
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
    // 切章竞态保险一（与 load 同款）：卸载前撤销在途防抖定时器
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
    currentChapterId = null
    spine.value = null
    spineSuggestions.value = null
    spineProgress.value = null
    suppressAutosave = true
  }

  async function save(patch: { intent?: ChapterSpine['intent'] | null; anchors?: SpineAnchor[] | null }) {
    if (!currentChapterId) return
    // 发请求前快照：watcher 传的 {...val} 是浅拷贝但深层同引用，序列化一致，
    // 回包后与本地整对象比对即可判断深层是否被再次编辑（意图输入/心跳回写 hit）
    const sent = JSON.stringify(patch)
    try {
      const r = await adaptiveApi.patchSpine(currentChapterId, patch)
      suppressAutosave = true
      // 仅当本地未被再次修改时才接受服务器值，防 PATCH 往返期间在途编辑被
      // 整包替换静默回滚；r.spine=null（后端「全空归 null」契约）直接赋值——
      // removeAnchor 主动清库传的是局部 patch {anchors:[]}，与本地整对象序列化
      // 天然不等，靠 null 直赋兜底（本地随即也置 null，语义一致）
      if (r.spine === null || (spine.value && JSON.stringify(spine.value) === sent)) {
        spine.value = r.spine
      }
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

  async function removeAnchor(id: string) {
    const s = spine.value
    if (!s?.anchors) return
    s.anchors = s.anchors.filter((a) => a.id !== id)
    if (!s.intent?.text && !s.anchors.length) {
      // 删空且无意图 → 置 null 前主动清库：watcher 对 !val 早退，不主动 save
      // 则服务端旧 spine 永久残留（后端「全空归 null」契约落 null）。
      // 保存失败也照旧本地置 null——本地清空优先，重载复活与现状同，不额外处理
      await save({ anchors: [] }).catch(() => {})
      spine.value = null  // 全空 = 无脉络
    }
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
    // 切章竞态保险二：捕获调度时的章 id，回调发现已切章则丢弃过期闭包
    // （load/unload 的 clearTimeout 是第一道；此为兜底，防绕过两者的路径）
    const cid = currentChapterId
    saveTimer = setTimeout(() => {
      saveTimer = null
      if (currentChapterId !== cid) return
      // 防抖路径静默吞异常（422 时无 unhandled rejection）；
      // adoptSuggestion/removeAnchor 等显式调用方的 throw 语义不变
      void save({ ...val }).catch(() => {})
    }, 2000)
  }, { deep: true })

  return {
    spine, spineSuggestions, spineSuggesting, spineLoaded, spineProgress, highlightAnchorId,
    load, unload, save, suggest, adoptSuggestion, discardSuggestions,
    setIntent, addAnchor, updateAnchor, removeAnchor,
  }
}
