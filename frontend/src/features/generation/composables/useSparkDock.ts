import { ref, computed, watch, nextTick } from 'vue'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { ghostActive, ghostEndReason } from './useGhostDraft'
import { followEditorLayout } from './editorLayoutFollower'

/**
 * NLE-ADF 灵感悬浮舱（Spark Dock）状态控制器。
 *
 * 定位：灵感提示 + 补写入口——降低作者写作难度。
 * 作者停顿卡壳时，卡片舱在光标下方淡入 3~4 个【镜头特写挂件】，
 * 作者吸附挂件 → Space 微缝合（AI 基于挂件指引流式续写，幽灵草稿形态）。
 *
 * 挂件是具体的物理画面碎片（"老烟按发电机的血手"/"咬平齿的废管钳"），
 * 不是角色名罗列，也不是抽象建议。来源是后端 dock_generator 对
 * recent_text + projections + 设定(nutrients/hard_constraints) 的 LLM 生发。
 *
 * 交互：
 * - 停顿 4s（光标段尾）或 Tab → 挂件浮现
 * - 数字键 1~4 → 吸附到意图栏（可多选）
 * - Space（吸附栏有挂件时）→ 微缝合补写（session 处理）
 * - Esc → 关 Dock / 清吸附栏 / 取消 sticky
 *
 * Sticky 机制（NLE-ADF 3.0）：缝合触发后舱不消失，进入 sticky 态——
 * 作者继续打字/光标移动/ghost 出现都不会隐藏它，便于连续吸附多件缝合。
 * sticky 在以下情况退出：Esc 关舱 / 切章 / unmount / hideSparkDock 强制调用。
 */

export interface SparkPart {
  /** 去重键（source:文本） */
  key: string
  kind: 'anchor' | 'carrier' | 'character' | 'asset'
  icon: string
  /** 挂件文本：6 字以内的镜头特写词（"老烟的血手"/"咬平齿的管钳"），非角色名 */
  text: string
  /** NLE-ADF 3.0 叙事方向（主线/伏笔/刻画/环境/关系）——分析面元数据，2026-08-29 起不再上屏 */
  direction?: '主线' | '伏笔' | '刻画' | '环境' | '关系'
  /** 来源标记：'expectation' = 期待账本衍生件（分析面；前端以 echo note 取代旧「期待」tag） */
  origin?: 'expectation'
  /**
   * 功能槽位（2026-08-29「不知所云」重构）：作者必须能看懂「选这枚会发生什么」——
   * landing=接着写（作者最后一句的物理落点）/ toward_beat=通往大纲就近节拍 /
   * echo=呼应前情或读者期待 / ambient=纯氛围（留白）。旧缓存零件无此字段按 ambient。
   */
  source?: 'landing' | 'toward_beat' | 'echo' | 'ambient'
  /** 出处短语（后端按注入素材拼装，≤16 字：「通往「领物资」」「读者在等：书的来历」） */
  note?: string
}

/** 槽位展示序（landing 首位；无 source 的旧零件沉底） */
const SOURCE_ORDER: Record<NonNullable<SparkPart['source']>, number> = {
  landing: 0,
  toward_beat: 1,
  echo: 2,
  ambient: 3,
}

export const sparkDockVisible = ref(false)
export const sparkDockPos = ref({ top: 0, left: 0 })
export const attachedParts = ref<SparkPart[]>([])

/**
 * 行间推挤锚位（2026-09-09 布局重构）：卡舱从 fixed 浮层改为 ProseMirror
 * WidgetDecoration——锚=光标所在段之后的文档位置（$from.after()），由
 * extensions/InlineDock.ts 消费立装饰。像素位 sparkDockPos 仍维护
 * （BeatCardDock/幽灵三条回落锚在用），但卡舱自身不再消费它。
 */
export const sparkAnchorPos = ref<number | null>(null)

/**
 * Sticky 态：缝合触发后置 true，舱持续显示不被打字活动隐藏，
 * 让作者连续吸附多件缝合。Esc 关舱 / 切章 / unmount 退出。
 *
 * ⚠ 2026-08-28 排查发现：setSparkSticky 曾全工程零调用（死代码）——缝合后
 * 舱即被 hideSparkDock 永久收走，"连续吸附多件缝合"从未生效。现复活：
 * 缝合触发时 setSparkSticky + stashSparkDock（藏舱让位幽灵），幽灵落定
 * （蒸发/失败回弹；Enter 采纳自第二冲程 2026-09-09 起不回弹——采纳即写完）
 * 由下方 watch 自动 restore——打字不再收舱。
 */
export const sparkSticky = ref(false)

// ---- 临时在场通行证（2026-09-09 涌现角色闭环）----
// 后端 onstage 把正文高频未建档人名（明姐类）发为 is_guest；心跳响应带
// onstage_guests 名单 → 舱底出「录入档案」直达入口，建档后自动转正
export const sparkGuests = ref<string[]>([])

export function setSparkGuests(names: string[]): void {
  sparkGuests.value = [...new Set((names || []).filter(Boolean))].slice(0, 2)
}

// ---- 建档往返（guest return trip）----
// 跨路由保存/恢复光标：SPA 内模块级单例最可靠（无序列化、无 origin 漂移——
// localStorage 起源不稳的教训在案）；pos 为 ProseMirror 绝对位置，恢复时按
// 文档长度钳位（离开期间的自动保存可能改变文档长度）
export interface GuestReturnTrip {
  chapterId: string
  pos: number
  paraHead: string  // 光标段前 20 字指纹（防内容漂移后错位——校验失败退文档尾）
}

let _guestReturn: GuestReturnTrip | null = null

export function stashGuestReturn(chapterId: string, pos: number, paraHead: string): void {
  _guestReturn = { chapterId, pos, paraHead: (paraHead || '').slice(0, 20) }
}

export function takeGuestReturn(): GuestReturnTrip | null {
  const t = _guestReturn
  _guestReturn = null
  return t
}

/**
 * 卡片舱自动弹出总开关（2026-09-09 用户拍板「先关闭」）：false=停顿秒弹/
 * 响应侧自动弹/幽灵落定回弹全部退役——卡片舱唯一入口是 Tab 主动唤醒
 * （且每次 Tab 都强制重算）。置回 true 可整体恢复三条自动弹出路径。
 */
export const SPARK_DOCK_AUTO_POPUP = false

const _baseParts = ref<SparkPart[]>([])
const _extraParts = ref<SparkPart[]>([])

/** 展示挂件 = 基础件 + 兜底件（去重，上限 4，槽位序——「接着写」恒居首位）。基础件来自后端 LLM 生发。 */
export const sparkParts = computed<SparkPart[]>(() => {
  const merged: SparkPart[] = []
  for (const part of [..._baseParts.value, ..._extraParts.value]) {
    if (!merged.some((m) => m.key === part.key)) merged.push(part)
  }
  return merged
    .slice(0, 6)
    .sort((a, b) => (SOURCE_ORDER[a.source ?? 'ambient'] ?? 3) - (SOURCE_ORDER[b.source ?? 'ambient'] ?? 3))
    .slice(0, 4)
})

/** 可展示门（session 注入：创作态/composing + 无幽灵 + 非缝合中） */
let _canShow: () => boolean = () => false
let _pauseTimer: ReturnType<typeof setTimeout> | null = null

export function setSparkDockGate(fn: () => boolean): void {
  _canShow = fn
}

/** 注入后端 LLM 生发的灵感碎片（由 useAdaptiveAssist 停顿心跳后注入） */
export function setSparkParts(parts: SparkPart[]): void {
  _baseParts.value = parts
}

/**
 * 注入额外挂件（章级兜底，现仅用于切章清空）。
 * 角色名兜底件已废弃——与"镜头碎片"定位冲突。
 */
export function setExtraSparkParts(parts: SparkPart[]): void {
  _extraParts.value = parts
}

/** 触发 sticky（缝合后调用）：舱持续显示，不被打字活动隐藏 */
export function setSparkSticky(): void {
  sparkSticky.value = true
}

/**
 * 藏舱让位幽灵（缝合触发时调用）：视觉上隐藏（避免与幽灵草稿重叠混乱），
 * 但保留 sticky 态——幽灵落定后 restoreSparkDock 自动弹回，连续吸附不断流。
 * 与 hideSparkDock 的区别：hide 是完全退出（清 sticky），stash 是暂避。
 */
export function stashSparkDock(): void {
  sparkDockVisible.value = false
  sparkSelectedIndex.value = -1
}

/** 幽灵落定（Enter 定稿 / Esc 蒸发 / 出错回滚）后的自动回弹：sticky 态即弹回。 */
export function restoreSparkDock(): void {
  if (!sparkSticky.value) return
  showSparkDock()
}

// 幽灵生命周期 ↔ sticky 回弹：幽灵消失且 sticky 在，舱自动弹回（零件缓存仍在）。
// nextTick 推迟：本 watch 在模块加载时注册，先于 session 的 authorLane 回写
// watch 执行——不推迟的话弹舱时闸门还停在 ghostStitching，回弹被静默吞掉。
// 门禁由 showSparkDock 自守。
// 回弹分流（第二冲程 2026-09-09 实测拍板）：Enter 采纳（ghostEndReason='commit'）
// 不回弹——采纳=这一瞬已写完，弹回是打扰（08-28 的「连续吸附」语义随数字键
// 直开单镜头而退役）；蒸发/收尸/失败回弹——镜头不对，换一枚正好要舱。Tab
// 随时可再唤，无损失。
if (SPARK_DOCK_AUTO_POPUP) {
  watch(ghostActive, (active, prev) => {
    if (!active && prev) nextTick(() => {
      if (ghostEndReason.value === 'commit') return
      restoreSparkDock()
    })
  })
}

/**
 * 计算光标下方的浮舱定位（Spark Dock / Beat Dock 共用）。
 * 光标下方 8px；left 对齐当前文本块起始（与正文同栏缩进）。失败返回 null。
 */
export function computeCursorDockPos(): { top: number; left: number } | null {
  const editor = chapterEditorHandle.value
  if (!editor) return null
  try {
    const { $from } = editor.state.selection
    const cursorCoords = editor.view.coordsAtPos($from.pos)
    const blockStartCoords = editor.view.coordsAtPos($from.start())
    return {
      top: cursorCoords.bottom + 8,
      left: Math.max(16, blockStartCoords.left),
    }
  } catch {
    return null
  }
}

function _positionDockAtCursor(): boolean {
  const pos = computeCursorDockPos()
  if (!pos) return false
  sparkDockPos.value = pos
  return true
}

/** 行间锚取位（2026-09-09）：锚=光标段之后（$from.after()）——WidgetDecoration 立在此处 */
function _anchorAtCursor(): boolean {
  const editor = chapterEditorHandle.value
  if (!editor) return false
  try {
    sparkAnchorPos.value = editor.state.selection.$from.after()
    return true
  } catch {
    return false
  }
}

// ============================================================
// 布局跟随（2026-08-28 错位修复）：舱可见期间跟随滚动/回流/光标重定位
// ============================================================
// sparkDockPos 此前只在弹出时算一次——感知带出现挤动编辑区、滚动都会让
// fixed 定位的舱漂离正文。可见期间挂 followEditorLayout，隐藏即卸；
// 编辑器热换（切章）重挂。
let _unfollowDock: (() => void) | null = null

function _syncDockPos(): void {
  if (sparkDockVisible.value) _positionDockAtCursor()
}

watch(sparkDockVisible, (visible) => {
  if (visible && !_unfollowDock) _unfollowDock = followEditorLayout(_syncDockPos)
  else if (!visible && _unfollowDock) { _unfollowDock(); _unfollowDock = null }
})

watch(chapterEditorHandle, () => {
  if (_unfollowDock) { _unfollowDock(); _unfollowDock = null }
  if (sparkDockVisible.value) _unfollowDock = followEditorLayout(_syncDockPos)
})

/** 主动唤起（Tab）或停顿心跳驱动（useAdaptiveAssist 调用）共用的展示入口 */
export function showSparkDock(): void {
  if (!_canShow()) return
  if (!sparkParts.value.length) return
  if (!_anchorAtCursor()) return
  _positionDockAtCursor()   // 像素位仍维护（BeatCardDock/幽灵回落锚消费）
  sparkSelectedIndex.value = -1  // 每次弹出重置浏览选中
  sparkDockVisible.value = true
}

export function hideSparkDock(): void {
  sparkSticky.value = false   // 显式隐藏同时取消 sticky
  sparkDockVisible.value = false
  sparkSelectedIndex.value = -1
}

export function clearAttachedParts(): void {
  attachedParts.value = []
}

/** 数字键吸附：把第 index 个挂件收入意图栏（去重）；返回是否消费该按键 */
export function attachSparkPart(index: number): boolean {
  if (!sparkDockVisible.value) return false
  const part = sparkParts.value[index]
  if (!part) return false
  if (!attachedParts.value.some((p) => p.key === part.key)) {
    attachedParts.value = [...attachedParts.value, part]
  }
  return true
}

/**
 * ↑↓ 浏览选中索引（纯视觉高亮，不影响吸附——吸附仍数字键 1~4 / 鼠标点击）。
 * 竖排带内：方向键浏览碎片，数字键/点击吸附。
 */
export const sparkSelectedIndex = ref(-1)

/** ↑↓ 移动选中（循环）；Dock 未开 / 无碎片 / sticky 态返回 false（让作者用 ↑↓ 移光标）。 */
export function moveSparkSelection(delta: number): boolean {
  if (!sparkDockVisible.value || sparkParts.value.length === 0) return false
  if (sparkSticky.value) return false  // sticky 态放行（连续缝合时作者要编辑移光标）
  const n = sparkParts.value.length
  sparkSelectedIndex.value = (sparkSelectedIndex.value + delta + n) % n
  return true
}

export function resetSparkSelection(): void {
  sparkSelectedIndex.value = -1
}

/**
 * 编辑器活动（打字/动光标）：隐藏 Dock——但 sticky 态除外。
 *
 * NLE-ADF 3.0：sticky 态下打字/光标移动不隐藏舱（缝合后保留，便于连续启发）。
 * 非 sticky 态（首次弹出等停顿）打字即隐藏（作者继续写，不需要灵感）。
 * 自动弹出由 useAdaptiveAssist 停顿心跳（4s + 段尾）拿到后端挂件后触发，
 * 本模块只管：打字隐藏（sticky 除外）+ Tab 主动唤起 + 数字吸附。
 */
function _onEditorActivity(): void {
  if (sparkSticky.value) {
    // sticky 态：跟随光标重定位，但不隐藏。行间锚按段落粒度跟随（非每键）
    // ——光标段变了才换锚，打字不抖、不逐键重建装饰
    if (sparkDockVisible.value) {
      _positionDockAtCursor()
      try {
        const after = chapterEditorHandle.value?.state.selection.$from.after()
        if (after != null && after !== sparkAnchorPos.value) sparkAnchorPos.value = after
      } catch { /* 段边界取不到则保持旧锚 */ }
    }
    return
  }
  hideSparkDock()
}

watch(
  chapterEditorHandle,
  (editor, prev) => {
    prev?.off('update', _onEditorActivity)
    prev?.off('selectionUpdate', _onEditorActivity)
    editor?.on('update', _onEditorActivity)
    editor?.on('selectionUpdate', _onEditorActivity)
  },
  { immediate: true },
)

export function useSparkDock() {
  return {
    sparkDockVisible,
    sparkDockPos,
    sparkParts,
    attachedParts,
    sparkSelectedIndex,
    sparkSticky,
    setSparkDockGate,
    setSparkParts,
    setExtraSparkParts,
    showSparkDock,
    hideSparkDock,
    stashSparkDock,
    restoreSparkDock,
    clearAttachedParts,
    attachSparkPart,
    moveSparkSelection,
    resetSparkSelection,
    setSparkSticky,
    sparkGuests, setSparkGuests, stashGuestReturn, takeGuestReturn,
  }
}
