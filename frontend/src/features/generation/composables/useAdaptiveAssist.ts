/**
 * NLE-ADF 3.0 自适应辅助层（心跳模式）。
 *
 * 两种心跳：
 * - 活跃心跳（防抖 3s）：作者活动后发，让后端感知正文推进、跑意图反推/变化检测。
 *   不带 paused_ms（作者在写，不是卡住）。
 * - 停顿心跳（停顿 4s + 光标段尾）：作者卡住时发，带 paused_ms=4000，
 *   触发后端 dock_generator 生发挂件。响应里带 dock_parts → 注入 Spark Dock。
 *
 * 时序协调：
 * - Spark Dock 自身的 4s 停顿门控（useSparkDock）负责"何时弹出"
 * - 停顿心跳负责"让后端在停顿时生成挂件"
 * - 两者都基于 4s 停顿，但 Spark Dock 弹出要求 sparkParts 非空——
 *   所以停顿心跳必须先于/同时于 Spark Dock 弹出完成。
 * - 实现：编辑器活动重置两个计时器（活跃心跳 3s + 停顿心跳 4s），
 *   停顿心跳跑完后 sparkParts 已就绪，Spark Dock 此时弹出即有内容。
 */
import { watch, ref, type Ref } from 'vue'
import { adaptiveApi, type HeartbeatResult, type FinishReport, type SettleResult, type DirectionCard } from '../../../services/api/domain/adaptive.api'
import { logCollabEvent } from '../../../composables/useCollabTelemetry'
import { applySpineProgress, spine } from '../../workspace/composables/useChapterSpine'
import {
  ghostActive, beginGhost, appendGhost, evaporateGhost, setGhostWarnings, setGhostWash,
} from './useGhostDraft'
import { setSparkParts, showSparkDock, hideSparkDock, sparkDockVisible, sparkSticky, type SparkPart } from './useSparkDock'
import { setBeatCards } from './useBeatDock'
import { setThinkingPhase, hideThinking } from './useThinkingIndicator'
import { assistEnabled } from './useAssistEnabled'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { findOutlineNotes } from '../../../extensions/OutlineNoteNode'

/** 细纲胶囊「落笔扩写」事件（OutlineNoteChip 派发，本层监听编排） */
const OUTLINE_EXPAND_EVENT = 'velluma:outline-expand'

/** P3-1（C5）「世界发现」跳过事件：settle/finish 带回原因 → 收件箱空态一句提示 */
const SCOUT_SKIPPED_EVENT = 'velluma:scout-skipped'

/**
 * 最近一次失败的辅助组件（P3-1/C5：心跳带回，per-chapter 后端内存态）。
 * 模块级单例（同 useChapterSpine 模式）——InspectorPanel「AI 视角」直接读；
 * 空 = 一切正常，UI 整块不渲染。
 */
export interface ComponentErrorInfo { component: string; ts: number; error: string }
export const componentErrors = ref<ComponentErrorInfo[]>([])
export function setComponentErrors(raw?: Record<string, { ts: number; error: string }> | null | undefined) {
  componentErrors.value = Object.entries(raw || {}).map(([component, v]) => ({
    component,
    ts: Number(v?.ts) || 0,
    error: String(v?.error || ''),
  }))
}

/** P3-4（C6）：把 settle/finish 带回的「世界发现」跳过原因广播给收件箱空态（null = 清除） */
function notifyScoutSkipped(reason?: string | null) {
  window.dispatchEvent(new CustomEvent(SCOUT_SKIPPED_EVENT, { detail: { reason: reason || null } }))
}

const ACTIVE_HEARTBEAT_MS = 3000   // 活跃心跳防抖
const PAUSE_HEARTBEAT_MS = 4000    // 停顿心跳（与 Spark Dock 弹出门控对齐）
const PREVIEW_DELAY_MS = 2000      // 思考指示器预览态延迟（停顿 2s 即显示淡灰点）

// ---- 句子级闸门的前端镜像（与后端 paragraph_source.ends_mid_sentence 同判据）----
// 半句悬停时停顿心跳必然被后端静音（dock_muted）——等待/感知灯不该为一个
// 设计上不会兑现的承诺亮起：实测「绿点亮一下立马消失」被作者当成断线。
// 空段=段界不判半句（与后端 2026-08-25 审计口径一致，勿回退）。
const _SENTENCE_TERMINALS = new Set('。！？!?…‥．。”」』）)'.split(''))

function _endsMidSentence(text: string): boolean {
  const t = (text || '').replace(/\s+$/, '')
  return !!t && !_SENTENCE_TERMINALS.has(t[t.length - 1])
}

interface AdaptiveAssistOptions {
  getChapterId: () => string | null
  getOutline: () => string  // 章节大纲（WorkspaceView 注入 selectedChapter.outline_text）
  suggestionsRef: Ref<any[]>
  planSuggestionsRef: Ref<any | null>
  dynamicBeatsRef: Ref<Array<{ beat_id: string; text: string; word_count: number; settled_at: number }>>
  aiLaneRef: Ref<string>
  authorLaneRef: Ref<string>
  /** 完稿审计报告（finishChapter 写入，InspectorPanel 渲染） */
  finishReportRef: Ref<FinishReport | null>
  /** 沉淀抽取结果（settleCurrent 写入：涌现实体 + 冲突，InspectorPanel 渲染） */
  settleResultRef: Ref<SettleResult | null>
  /** 显式动作失败上报（续写/沉淀/完稿/点火）——此前全线静默，作者操作无反馈 */
  reportError?: (msg: string) => void
  /** 后台心跳中断上报（warning 级；只报一次防刷屏，恢复后重置） */
  reportWarn?: (msg: string) => void
  /** A5d 沉淀产出候选事件（settle 抽出 N 条待确认）——宿主 toast 直达收件箱 */
  onCandidatesCreated?: (count: number) => void
}

export function useAdaptiveAssist(opts: AdaptiveAssistOptions) {
  let _activeTimer: ReturnType<typeof setTimeout> | null = null
  let _pauseTimer: ReturnType<typeof setTimeout> | null = null
  let _previewTimer: ReturnType<typeof setTimeout> | null = null
  let _lastActiveTs = 0
  let _continueAbort: AbortController | null = null
  let _heartbeatFailedOnce = false
  let _summonInFlight = false  // Tab 即点取件在飞标记（连按不叠加 LLM 调用）
  // 心跳在飞去重（2026-08-27 Tab 实测事故）：生发档（停顿/召唤）要跑 2~7s LLM，
  // 期间打字武装的活跃档计时器照常触发，其快速响应带着 dock_muted 清舱 +
  // hideThinking + 状态翻 dormant，把作者正盯着等的绿点半路杀掉——绿点消失到
  // 舱弹出之间 3~5s 零反馈，作者以为断线。两道闸：发送侧在飞让路 + 响应侧
  // 生发档在飞时活跃档响应只更数据不动反馈态。
  let _activeHeartbeatInFlight = false
  let _generationHeartbeatsInFlight = 0
  // Tab 点名挂起（2026-08-28 修复：点名撞上在飞生发档时此前被静默吞掉——
  // 作者按 Tab 毫无反应，要等 2~7s 再按一次才灵，体感「Tab 有时灵有时不灵」。
  // 现转挂起：在飞生发响应带回的零件即点名所得，响应落地直接弹舱兑现）
  let _summonPending = false
  // 埋点去重签名（P0-3）：心跳重复返回同一批卡/零件不重复计「亮出」
  let _lastCardSig = ''
  let _lastDockSig = ''
  // 感知上下文快照（2026-08-29 感知常驻拍板）：每次编辑器活动时记下
  // {章, 段文本, 字数, 段尾}——写作台卸载（切到世界页/文风页等）后 pending
  // 计时器照发心跳，用快照代替已卸载的编辑器读数，切页前的最后一次感知
  // 不因页面切换静默夭折；快照带章号，切章后旧快照作废不串章
  let _lastCtx: { chapterId: string; recentText: string; wordCount: number; cursorAtEnd: boolean } | null = null

  // ---- 编辑器活动：重置三个计时器 + 隐藏思考指示器 ----
  function _onEditorActivity() {
    if (!assistEnabled.value) return  // AI 辅助关闭（纯手写模式）：心跳/思考点全停
    _lastActiveTs = Date.now()
    // 感知上下文快照：卸载后 pending 心跳的数据源（感知常驻，2026-08-29）
    const chId = opts.getChapterId()
    const ed = chapterEditorHandle.value
    if (chId && ed) {
      const $from = ed.state.selection.$from
      _lastCtx = {
        chapterId: chId,
        recentText: $from.parent.textContent,
        wordCount: ed.state.doc.textContent.length,
        cursorAtEnd: $from.pos >= $from.end() - 1,
      }
    }
    // 作者重新动笔 → 立即隐藏思考点（任何 pending 计时器随之清掉）
    hideThinking()
    // 预览计时器：2s 后若无新活动 → 显示淡灰「等待中」点（预示即将凑近）
    if (_previewTimer) clearTimeout(_previewTimer)
    _previewTimer = setTimeout(() => {
      // 仅 composing 态 + 光标在段尾才预览（段中编辑/选词不算停顿思考）
      if (opts.authorLaneRef.value === 'composing' && _isCursorAtParagraphEnd()) {
        // 半句不预告：闸门下停顿心跳必空手而归，灰点是许愿不兑现
        if (!_endsMidSentence(_recentText500())) setThinkingPhase('waiting')
      }
    }, PREVIEW_DELAY_MS)
    // 活跃心跳：3s 后发（让后端感知正文推进）
    if (_activeTimer) clearTimeout(_activeTimer)
    _activeTimer = setTimeout(() => { void _sendHeartbeat(0) }, ACTIVE_HEARTBEAT_MS)
    // 停顿心跳：4s 后发（若期间无新活动，作者卡住了）
    if (_pauseTimer) clearTimeout(_pauseTimer)
    _pauseTimer = setTimeout(() => {
      // 仅光标在段尾才算卡壳（段中修改不算）
      if (_isCursorAtParagraphEnd()) {
        // 有缓存零件先秒弹（上次心跳存货），心跳在后台刷新零件；无缓存则等
        // 响应带回再弹（响应侧有活状态守卫）——LLM 延迟退出唤醒关键路径。
        // showSparkDock 自守：无零件/非 composing/幽灵在屏时静默 no-op。
        // 秒弹同吃半句闸门（2026-08-28 修复）：光标段尾但句子未写完时，心跳
        // 响应必带 dock_muted 清舱——秒弹先亮再被收掉 = 舱一闪即隐（预览灰点
        // 有此闸，秒弹漏了，口径对齐；心跳照发，感知带数据照常带回）
        if (!_endsMidSentence(_recentText500())) showSparkDock()
        void _sendHeartbeat(Date.now() - _lastActiveTs)
      }
    }, PAUSE_HEARTBEAT_MS)
  }

  function _isCursorAtParagraphEnd(): boolean {
    const editor = chapterEditorHandle.value
    if (!editor) return false
    const { $from } = editor.state.selection
    return $from.pos >= $from.end() - 1
  }

  /** 与后端同源的光标段文本——心跳发送的 recent_text 就是它的前 500 字 */
  function _recentText500(): string {
    const editor = chapterEditorHandle.value
    if (!editor) return ''
    return editor.state.selection.$from.parent.textContent.slice(0, 500)
  }

  async function _sendHeartbeat(pausedMs: number, flags?: { summoned?: boolean; _summonRetry?: boolean }) {
    const chapterId = opts.getChapterId()
    if (!chapterId) return
    if (opts.authorLaneRef.value !== 'composing') return
    if (ghostActive.value) return  // 幽灵在屏时暂停心跳
    const generationTier = pausedMs >= PAUSE_HEARTBEAT_MS
    // 发送侧在飞让路（2026-08-28 修正为与注释一致的两档统一闸）：生发档在飞时
    // 新心跳一律不发——活跃档冗余（生发响应同样带回走向卡/感知带全量快照），
    // 且活跃档快响应曾半路杀绿点（响应侧守卫兜过，但请求本身白烧）；Tab 点名
    // 例外转挂起：_summonPending 由在飞生发响应兑现，不再石沉大海。
    if (_generationHeartbeatsInFlight > 0) {
      if (flags?.summoned) _summonPending = true
      return
    }
    if (!generationTier && _activeHeartbeatInFlight) return
    const sendTs = _lastActiveTs  // 活动纪元：响应回来时比对，识别「发送后作者已动笔」

    const editor = chapterEditorHandle.value
    let wordCount = 0
    let recentText = ''
    let cursorAtEnd = false
    const segmentCount = opts.dynamicBeatsRef.value.length
    if (editor) {
      wordCount = editor.state.doc.textContent.length
      const $from = editor.state.selection.$from
      recentText = $from.parent.textContent
      cursorAtEnd = $from.pos >= $from.end() - 1
    } else if (_lastCtx && _lastCtx.chapterId === chapterId) {
      // 感知常驻（2026-08-29 用户拍板「无论切到哪都不停感知」）：写作台已
      // 卸载（作者在看世界页/文风页等）时 pending 计时器照发，用最近一次
      // 活动的快照代替已卸载的编辑器读数——切页前的停顿感知跑完、结果进
      // 世界模型缓存，回台后停顿秒弹直接可用。快照带章号：切章后旧快照
      // 作废（不拿旧章的段文本去感知新章）
      wordCount = _lastCtx.wordCount
      recentText = _lastCtx.recentText
      cursorAtEnd = _lastCtx.cursorAtEnd
    } else {
      return  // 无编辑器也无同章快照（卸载后从未活动过/已切章）：无从感知
    }
    const outlineText = opts.getOutline() || ''
    const hasOutline = outlineText.trim().length > 0

    // 仅停顿档切「感知中」：活跃档是后台探查（走向卡缓存/感知带），不该让顶栏
    // 状态闪烁——它 0.3s 后就被自家响应改写，作者只看到标签乱跳（2026-08-27 实测）
    // 半句静音轮不亮灯：闸门会让本轮必空手而归——绿点亮一下就灭比不亮更伤
    //（实测被当成断线）。心跳照发：感知带/世界保鲜数据照常带回。Tab 点名豁免。
    if (pausedMs >= PAUSE_HEARTBEAT_MS && (flags?.summoned || !_endsMidSentence(recentText.slice(0, 500)))) {
      opts.aiLaneRef.value = 'perceiving'
      // 停顿心跳发出 → 切强态（后端开始算 dock_generator，让用户看到「AI 正在读」）
      setThinkingPhase('perceiving')
    }
    _activeHeartbeatInFlight = true
    if (generationTier) _generationHeartbeatsInFlight += 1
    try {
      const result: HeartbeatResult = await adaptiveApi.heartbeat(chapterId, {
        word_count: wordCount,
        segment_count: segmentCount,
        paused_ms: pausedMs,
        // Tab 显式召唤时光标未必在段尾，但「作者点名要零件」本身就是好时机——
        // 后端 dock_generator 以段尾为生发闸，召唤一律放行（零件锚定段落文本不受影响）；
        // summoned 同时豁免句子级闸门（半句悬停时自然停顿不推零件，点名要则给）
        cursor_at_paragraph_end: flags?.summoned ? true : cursorAtEnd,
        has_outline: hasOutline,
        outline_text: outlineText,
        recent_text: recentText.slice(0, 500),
        summoned: !!flags?.summoned,
      })

      // 章节纪元守卫（2026-08-29 错章零件修复）：发送后切章 → 本响应是旧章的
      // 感知产物，落舱会污染新章（旧章零件被新章停顿秒弹错弹；生发档在飞还
      // 压住新章的刷新心跳，污染窗口=旧章 LLM 全程延迟）。直接丢弃——finally
      // 照常清在飞计数，不落任何数据
      if (chapterId !== opts.getChapterId()) return

      // 挂件 → Spark Dock（停顿心跳会带 dock_parts；活跃心跳通常空）
      // 句子级闸门信号（2026-08-26）：半句悬停时后端回 dock_muted=true——
      // 清舱收卡把「闭嘴」执行到端上。此前只清响应不清前端，旧件（上轮缓存/
      // 章节恢复兜底）一直躺在舱里，作者正写感想半句时卡照样在屏（实测事故）。
      // Tab 点名走 summoned 心跳重取，清舱无损失。
      // 生发档仍在飞（含活跃档先发慢归竞态）→ 本响应只更数据不动反馈态：
      // 清舱/hideThinking/状态翻 dormant 都会杀掉作者正盯着等的绿点。
      const generationStillBusy = _generationHeartbeatsInFlight > (generationTier ? 1 : 0)
      // sticky 态豁免（2026-08-28）：作者缝合后显式留下的舱（连续吸附流），
      // 半句静音管「自动弹出新件」不管作者留下的舱——杀掉它等于打断连续缝合流
      if (result.dock_muted && !generationStillBusy && !sparkSticky.value) {
        setSparkParts([])
        hideSparkDock()
      }
      const parts: SparkPart[] = (result.dock_parts || []).map((p) => ({
        key: p.key,
        kind: (p.kind as any) || 'anchor',
        icon: p.icon || '✨',
        text: p.text,
        direction: p.direction as SparkPart['direction'],
        origin: p.origin === 'expectation' ? 'expectation' : undefined,
      }))
      if (parts.length) {
        setSparkParts(parts)
        // 弹舱看响应时刻的活状态，不用发送时刻的死快照：发送后作者重新动笔
        // （_lastActiveTs 被刷新）或光标已离段尾 → 只静默更新零件供 Tab 用，不弹——
        // 弹了也被下一个按键立刻收掉（2026-08-24 trace 实证：LLM 3~7s 延迟常使
        // 响应落在下一次打字进行中，舱一闪即隐）。Tab 显式召唤例外：点名要的零件，直接弹。
        const authorResumed = _lastActiveTs > sendTs
        if (flags?.summoned) {
          showSparkDock()
        } else if (
          pausedMs >= PAUSE_HEARTBEAT_MS
          && cursorAtEnd
          && !authorResumed
          && _isCursorAtParagraphEnd()
        ) {
          showSparkDock()
        }
      }
      // 挂起的 Tab 点名兑现（2026-08-28）：本轮生发响应的零件即点名所得，
      // 弹舱条件同召唤语义（点名要的直接弹，不受段尾/动笔守卫）。
      // 空响应补发（2026-08-29 Tab 失效修复）：在飞心跳被限流/慢端点拖到
      // 12s 超时空手而归时，兑现即死——此刻在飞计数即将归零（finally 在本
      // 响应处理后执行），延迟一拍补发真 summoned 心跳，其响应走召唤语义
      // 必弹；仅补一次（_summonRetry 防循环），再空则下一按 Tab 全新尝试。
      if (_summonPending) {
        _summonPending = false
        if (parts.length) {
          showSparkDock()
        } else if (!flags?._summonRetry) {
          setTimeout(() => {
            void _sendHeartbeat(PAUSE_HEARTBEAT_MS, { summoned: true, _summonRetry: true })
          }, 0)
        }
      }

      // 走向卡缓存（Ctrl+Space 走向卡舱的数据源；层 3 推测首 beat）
      // M3 作者声明岔路：临近的岔路锚点选项置顶为硬提示卡（朱色视觉权重，
      // 区别日常柔性建议）——作者选向即决岔，选后 WorkspaceView 清标记
      const nearBranches = (result.spine_progress as any)?.near_branches as
        | { id: string; text: string; options: string[] }[]
        | undefined
      const branchCards: DirectionCard[] = (nearBranches || []).flatMap((nb) =>
        nb.options.map((opt) => ({
          event: opt,
          anchors: [nb.text],
          serves_anchor: nb.id,
          is_branch: true,
        })),
      )
      setBeatCards([...branchCards, ...(result.direction_cards || [])])

      // 谋篇进度（P1.4 M2）：回写 useChapterSpine 单例（感知带进度行 + 本地锚点状态同步）
      applySpineProgress(result.spine_progress)

      // 埋点（P0-3 个人镜子）：亮出按卡集签名去重——「无视」= 亮出减采纳，离线可算
      const cardSig = (result.direction_cards || []).map((c) => c.event).join('|')
      if (cardSig && cardSig !== _lastCardSig) {
        logCollabEvent(chapterId, 'cards_delivered', {
          count: (result.direction_cards || []).length,
          encounter_count: (result.direction_cards || []).filter((c: any) => c.from_encounter).length,
        })
      }
      _lastCardSig = cardSig
      const dockSig = parts.map((p) => p.text).join('|')
      if (dockSig && dockSig !== _lastDockSig) {
        logCollabEvent(chapterId, 'dock_delivered', { count: parts.length })
      }
      _lastDockSig = dockSig

      // 意图建议 → planSuggestions
      if (result.intent_source !== 'none') {
        opts.planSuggestionsRef.value = {
          source: result.intent_source,
          arc: result.intent_arc,
          confidence: result.intent_confidence,
        }
      }

      // Canon 感知 → adaptiveSuggestions（写中右缘感知带数据源；canon_watch 产）
      opts.suggestionsRef.value = result.canon_hints || []

      // 世界切片保鲜：版本搭心跳便车，经事件解耦给 useWorldSlice（静默重取，红点提示）
      if (result.world_version) {
        window.dispatchEvent(new CustomEvent('velluma:world-version', {
          detail: { chapterId, version: result.world_version },
        }))
      }

      // P3-1（C5）：最近失败的辅助组件 → 「AI 视角」调试区（空即清——成功即清语义）
      setComponentErrors(result.last_component_errors)

      // P0-4 接线（2026-08-27 语义收紧）：suggesting ⇔ 卡片舱真实在屏。
      // 此前条件是 parts.length || direction_cards.length——走向卡由活跃档心跳
      //（3s，纯算法）提前带回且只进 Ctrl+Space 缓存不可见，顶栏便先亮「走向已备好」，
      // 卡片舱要等停顿档（4s）+ dock_generator LLM（2~7s）才弹，标签比舱早 3~8s，
      // 半句静音（dock_muted）时甚至永不弹——实测作者困惑「说备好了舱呢」。
      // 此刻 hide/show 都已执行完，sparkDockVisible 即最终事实：舱弹出来标签才亮，
      // 与舱同帧出现；只有隐形缓存（走向卡/静默收仓）时保持安静。
      // 生发档在飞时不动反馈态（绿点/顶栏状态归在飞的生发档所有）；纯数据
      // 更新（走向卡缓存/感知带/埋点）照常应用
      if (!generationStillBusy) {
        opts.aiLaneRef.value = sparkDockVisible.value ? 'suggesting' : 'dormant'
        // 心跳完成：有挂件→Dock 接管（指示器已在 visible 计算里被 sparkDockVisible 隐藏）；
        // 无挂件→直接隐藏指示器（后端判本段不够触发，别让脉冲点一直转）。
        // 感知常驻补充（2026-08-29）：作者不在写作台（编辑器已卸载）时无论有无
        // 挂件都清思考点——舱本来就看不见，留着 perceiving 相位回台后会误亮
        if (!parts.length || !chapterEditorHandle.value) hideThinking()
      }
      _heartbeatFailedOnce = false  // 连接恢复，允许下次中断再提示一次
    } catch (e: any) {
      // 失败响应同样不得越权杀生发档的等待反馈（await 抛错时上面的 busy 判断
      // 未执行，须现算；生发档自身失败时计数含自己在内，1>1 不成立=允许清理）
      if (_generationHeartbeatsInFlight <= (generationTier ? 1 : 0)) {
        opts.aiLaneRef.value = 'dormant'
        hideThinking()
      }
      // 后台心跳中断：warning 提示一次后静默（3-4s 周期，不能刷屏；写作本身不受影响）
      if (!_heartbeatFailedOnce) {
        _heartbeatFailedOnce = true
        opts.reportWarn?.('AI 辅助连接中断（不影响写作，恢复后自动重连）：' + (e?.message || '网络错误'))
      }
    } finally {
      _activeHeartbeatInFlight = false
      if (generationTier) _generationHeartbeatsInFlight -= 1
    }
  }

  // ---- 零件即点取件（Tab 显式召唤：无缓存零件时补一跳停顿级心跳）----
  function summonParts() {
    if (_summonInFlight) return  // 连按不叠加 LLM 调用
    if (ghostActive.value) return
    // Tab 点名 = 作者显式要件：拆掉打字武装的三只计时器——它们都会在召唤的
    // 2~7s LLM 等待期内触发（活跃档响应半路杀绿点、停顿档白烧一次生发、
    // 预览点降级闪烁），下一次打字会重新武装
    if (_activeTimer) { clearTimeout(_activeTimer); _activeTimer = null }
    if (_pauseTimer) { clearTimeout(_pauseTimer); _pauseTimer = null }
    if (_previewTimer) { clearTimeout(_previewTimer); _previewTimer = null }
    _summonInFlight = true
    // 借停顿档（paused_ms=4000）让后端同步跑 dock_generator；summoned 标记让
    // 响应侧跳过段尾/动笔守卫直接弹舱（作者点名要的零件）。期间思考点自动亮
    // （停顿档 setThinkingPhase('perceiving')），等待有反馈。
    void Promise.resolve(_sendHeartbeat(PAUSE_HEARTBEAT_MS, { summoned: true }))
      .finally(() => { _summonInFlight = false })
  }

  // ---- 续写：stitch-ghost SSE 灌幽灵草稿 ----
  function requestContinue(
    mode: 'stitch' | 'continue' = 'continue',
    pickedParts: Array<{ text: string; direction?: string }> = [],
  ) {
    const chapterId = opts.getChapterId()
    if (!chapterId) return
    const editor = chapterEditorHandle.value
    if (!editor || ghostActive.value) return
    const paraText = editor.state.selection.$from.parent.textContent
    let fragment = paraText.trim().slice(-200)
    // 光标在空段落（如正文末尾的空行）时，回退取编辑器最后一个非空段落作为 fragment
    if (!fragment) {
      const doc = editor.state.doc
      doc.descendants((node) => {
        if (node.isTextblock) {
          const t = node.textContent.trim()
          if (t) { fragment = t.slice(-200); return false }
        }
        return true
      })
    }
    if (!fragment) return
    const paraStart = editor.state.selection.$from.start()
    const rollingPrefix = editor.state.doc.textBetween(Math.max(0, paraStart - 200), paraStart, '\n\n')

    if (_continueAbort) _continueAbort.abort()
    _continueAbort = new AbortController()
    opts.aiLaneRef.value = 'assisting'
    // 立即显示"AI 正在生成"——不等 GHOST_START（后端 LLM 调用 2-5s，期间作者需要反馈）
    setThinkingPhase('perceiving')

    // 采纳方向回报：取首个有 direction 的 part，通知后端降权（负反馈）
    const adoptedDir = pickedParts.find((p) => p.direction)?.direction

    logCollabEvent(chapterId, 'ghost_request', { mode })
    adaptiveApi.stitchGhost(chapterId, {
      fragment, rolling_prefix: rollingPrefix, mode,
      picked_parts: pickedParts.map((p) => p.text),
      target_chars: mode === 'stitch' ? 120 : 200,
      adopted_direction: adoptedDir,
    }, {
      onStart: () => { beginGhost('stitch'); hideThinking() },
      onChunk: (delta) => appendGhost(delta),
      onDone: (result) => {
        // C1 快检疑点随 DONE 帧到达 → 幽灵草稿状态（感知带停靠区展示 + 采纳 toast）
        setGhostWarnings(result.warnings || [])
        // 呈现平面 P1/P5：洗层结果 + 回流 meta 随 GHOST_DONE 灌入幽灵状态
        setGhostWash(result.wash, { token: result.ghost_token, sampleIds: result.sample_ids })
        opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
      },
      onError: (message) => {
        evaporateGhost(); opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
        // 此前静默失败：作者按 Space 等几秒毫无反应，分不清没触发还是失败
        opts.reportError?.(message || 'AI 续写失败，请重试')
      },
    }, _continueAbort.signal)
  }

  // ---- 沉淀：锁死段落 ----
  async function settleCurrent(commit: boolean = false) {
    const chapterId = opts.getChapterId()
    if (!chapterId) return null
    hideThinking()  // 显式动作 → 隐藏指示器
    const editor = chapterEditorHandle.value
    if (!editor) return null
    logCollabEvent(chapterId, 'settle', { commit })
    const $from = editor.state.selection.$from
    let text = $from.parent.textContent.trim()
    if (!text) {
      text = editor.state.doc.textBetween(
        Math.max(0, editor.state.doc.content.size - 2000),
        editor.state.doc.content.size, '\n\n',
      ).trim()
    }
    if (!text) return null

    opts.aiLaneRef.value = 'digesting'
    // P0-4 接线：沉淀期间 authorLane=settling（此前枚举从未赋值）；结束回落 composing
    opts.authorLaneRef.value = 'settling'
    try {
      const result = await adaptiveApi.settle(chapterId, { text, commit })
      opts.dynamicBeatsRef.value = [...opts.dynamicBeatsRef.value, {
        beat_id: `DYN_${Date.now()}`,
        text: text.slice(0, 200),
        word_count: text.length,
        settled_at: Date.now(),
      }]
      // 涌现实体/冲突写入 ref（InspectorPanel 渲染——作者主权：冲突不自动改）
      opts.settleResultRef.value = result
      opts.aiLaneRef.value = 'dormant'
      if (opts.authorLaneRef.value === 'settling') opts.authorLaneRef.value = 'composing'
      // W4 候选回流：settle 可能抽出候选事件 → 切片/收件箱静默刷新
      window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
      // P3-4（C6）：无候选产出时带出「世界发现」跳过原因 → 收件箱空态提示
      notifyScoutSkipped(result?.scout_skipped?.reason)
      // A5d 沉淀直达：抽出候选时 toast 带「去确认」action 直达副驾收件箱
      const createdCount = Number(result?.candidates_created) || 0
      if (createdCount > 0) opts.onCandidatesCreated?.(createdCount)
      return result
    } catch (e: any) {
      opts.aiLaneRef.value = 'dormant'
      if (opts.authorLaneRef.value === 'settling') opts.authorLaneRef.value = 'composing'
      // 此前静默 return null：沉淀失败作者完全无感知
      opts.reportError?.('沉淀失败：' + (e?.message || '未知错误'))
      return null
    }
  }

  // ---- 段落级连写（burst）：走向卡驱动，幽灵草稿多段流式灌入 ----
  function requestBurst(card?: { event: string; anchors?: string[] } | null) {
    const chapterId = opts.getChapterId()
    if (!chapterId) return
    const editor = chapterEditorHandle.value
    if (!editor || ghostActive.value) return
    // fragment/rolling_prefix 构建与 requestContinue 相同，但衔接窗口更大（500 字）
    const paraText = editor.state.selection.$from.parent.textContent
    let fragment = paraText.trim().slice(-200)
    if (!fragment) {
      const doc = editor.state.doc
      doc.descendants((node) => {
        if (node.isTextblock) {
          const t = node.textContent.trim()
          if (t) { fragment = t.slice(-200); return false }
        }
        return true
      })
    }
    if (!fragment) return
    const paraStart = editor.state.selection.$from.start()
    const rollingPrefix = editor.state.doc.textBetween(Math.max(0, paraStart - 500), paraStart, '\n\n')

    // 走向卡 → beat_guidance 文本（event + 焦点 anchors）；无卡 = 自由发挥
    const guidance = card
      ? card.event + (card.anchors?.length ? `（焦点：${card.anchors.join('、')}）` : '')
      : ''

    if (_continueAbort) _continueAbort.abort()
    _continueAbort = new AbortController()
    opts.aiLaneRef.value = 'assisting'
    setThinkingPhase('perceiving')

    logCollabEvent(chapterId, 'card_burst', { event: card?.event || '', from_encounter: !!(card as any)?.from_encounter })
    adaptiveApi.stitchGhost(chapterId, {
      fragment, rolling_prefix: rollingPrefix, mode: 'burst',
      beat_guidance: guidance,
      target_chars: 700,
    }, {
      onStart: () => { beginGhost('stitch'); hideThinking() },
      onChunk: (delta) => appendGhost(delta),
      onDone: (result) => {
        setGhostWarnings(result.warnings || [])
        // 呈现平面 P1/P5：洗层结果 + 回流 meta 随 GHOST_DONE 灌入幽灵状态
        setGhostWash(result.wash, { token: result.ghost_token, sampleIds: result.sample_ids })
        opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
      },
      onError: (message) => {
        evaporateGhost(); opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
        // 此前静默失败：作者按 Space 等几秒毫无反应，分不清没触发还是失败
        opts.reportError?.(message || 'AI 续写失败，请重试')
      },
    }, _continueAbort.signal)
  }

  // ---- 点火（冷启动）：空章 + 大纲 → 开篇引子（幽灵草稿形态）----
  function requestOpening() {
    const chapterId = opts.getChapterId()
    if (!chapterId) return
    const editor = chapterEditorHandle.value
    if (!editor || ghostActive.value) return

    if (_continueAbort) _continueAbort.abort()
    _continueAbort = new AbortController()
    opts.aiLaneRef.value = 'assisting'
    setThinkingPhase('perceiving')

    logCollabEvent(chapterId, 'ignition')
    adaptiveApi.stitchGhost(chapterId, {
      fragment: '', rolling_prefix: '', mode: 'open',
      target_chars: 700,
    }, {
      onStart: () => { beginGhost('stitch'); hideThinking() },
      onChunk: (delta) => appendGhost(delta),
      onDone: (result) => {
        setGhostWarnings(result.warnings || [])
        // 呈现平面 P1/P5：洗层结果 + 回流 meta 随 GHOST_DONE 灌入幽灵状态
        setGhostWash(result.wash, { token: result.ghost_token, sampleIds: result.sample_ids })
        opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
      },
      onError: (message) => {
        evaporateGhost(); opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
        // 此前静默失败：作者按 Space 等几秒毫无反应，分不清没触发还是失败
        opts.reportError?.(message || 'AI 续写失败，请重试')
      },
    }, _continueAbort.signal)
  }

  // ---- 细纲扩写：胶囊速记 → 双端锚定的小段幽灵正文（mode='outline'）----
  function requestExpandOutline(noteId: string) {
    const chapterId = opts.getChapterId()
    if (!chapterId) return
    const editor = chapterEditorHandle.value
    if (!editor) return
    if (ghostActive.value) {
      opts.reportError?.('已有幽灵草稿在屏，先 Enter 定稿或 Esc 蒸发再扩写')
      return
    }
    const target = findOutlineNotes(editor).find((n) => n.id === noteId && n.note.trim())
    if (!target) return
    const note = target.note.trim()
    logCollabEvent(chapterId, 'capsule_expand', { note_id: noteId })

    // 双端缝合上下文：胶囊前正文尾 500 字 + 胶囊后正文头 300 字
    // （章末/回补段后无正文时 after 为空 → 后端退化为单端锚定）
    const noteEnd = target.pos + target.nodeSize
    const rollingPrefix = editor.state.doc
      .textBetween(Math.max(0, target.pos - 500), target.pos, '\n\n')
      .trim()
    const afterText = editor.state.doc
      .textBetween(noteEnd, Math.min(noteEnd + 300, editor.state.doc.content.size), '\n\n')
      .trim()

    // 目标字数：解析速记中「约N字」（clamp 100-800），缺省 400
    const m = /约?\s*(\d+)\s*字/.exec(note)
    const targetChars = m
      ? Math.min(800, Math.max(100, parseInt(m[1], 10) || 400))
      : 400

    // 扩写启动即塌缩：胶囊变钉 ⚑，幽灵从钉后长出。
    // setNodeMarkup 只改 attrs 不改节点尺寸 → noteEnd 锚点位置保持有效。
    editor.commands.collapseOutlineNote(noteId)

    // M3 三锚定：胶囊挂了锚点 → 锚点文本随扩写注入意图块（双端缝合+锚点意图）
    const servesAnchor = target.anchorId
      ? ((spine.value?.anchors || []).find((a) => a.id === target.anchorId && a.status !== 'dropped')?.text || '')
      : ''

    if (_continueAbort) _continueAbort.abort()
    _continueAbort = new AbortController()
    opts.aiLaneRef.value = 'assisting'
    setThinkingPhase('perceiving')

    adaptiveApi.stitchGhost(chapterId, {
      fragment: note,
      rolling_prefix: rollingPrefix,
      after_text: afterText,
      mode: 'outline',
      target_chars: targetChars,
      serves_anchor: servesAnchor,
    }, {
      onStart: () => { beginGhost('outline', false, noteEnd); hideThinking() },
      onChunk: (delta) => appendGhost(delta),
      onDone: (result) => {
        setGhostWarnings(result.warnings || [])
        // 呈现平面 P1/P5：洗层结果 + 回流 meta 随 GHOST_DONE 灌入幽灵状态
        setGhostWash(result.wash, { token: result.ghost_token, sampleIds: result.sample_ids })
        opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
      },
      onError: (message) => {
        evaporateGhost(); opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
        opts.reportError?.(message || '细纲扩写失败，请重试')
      },
    }, _continueAbort.signal)
  }

  // ---- 完稿 ----
  async function finishChapter() {
    const chapterId = opts.getChapterId()
    if (!chapterId) return null
    hideThinking()  // 显式动作 → 隐藏指示器
    opts.aiLaneRef.value = 'analyzing'
    logCollabEvent(chapterId, 'finish')
    try {
      const result = await adaptiveApi.finish(chapterId)
      // 审计报告写入 ref（InspectorPanel 渲染）
      opts.finishReportRef.value = result
      opts.aiLaneRef.value = 'dormant'
      // W4 候选回流：完稿整章抽取 → 切片/收件箱静默刷新
      window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
      // P3-4（C6）：无候选产出时带出「世界发现」跳过原因 → 收件箱空态提示
      notifyScoutSkipped(result?.scout_skipped?.reason)
      return result
    } catch (e: any) {
      opts.aiLaneRef.value = 'dormant'
      // 此前静默 return null：完稿按钮点了没反应
      opts.reportError?.('完稿审计失败：' + (e?.message || '未知错误'))
      return null
    }
  }

  // ---- 生命周期 ----
  /** 细纲胶囊「落笔扩写」事件入口（OutlineNoteChip 派发；门控 assistEnabled） */
  function _onOutlineExpand(e: Event) {
    if (!assistEnabled.value) {
      opts.reportWarn?.('AI 辅助已关闭，细纲扩写不可用（顶栏 ✨ 开关可开启）')
      return
    }
    const id = (e as CustomEvent).detail?.id
    if (typeof id === 'string' && id) requestExpandOutline(id)
  }

  function mount() {
    // 打字（update）与光标移动（selectionUpdate）都算活动——「点过去想一想」也是
    // 停顿场景；只挂 update 会让纯点击后的停顿不再武装计时器，心跳从此沉寂
    watch(chapterEditorHandle, (editor, prev) => {
      prev?.off('update', _onEditorActivity)
      prev?.off('selectionUpdate', _onEditorActivity)
      editor?.on('update', _onEditorActivity)
      editor?.on('selectionUpdate', _onEditorActivity)
    }, { immediate: true })
    window.addEventListener(OUTLINE_EXPAND_EVENT, _onOutlineExpand)
  }

  /**
   * 写作台卸载（切到世界页/文风页等）时的分离——感知常驻（2026-08-29 用户
   * 拍板「无论切到哪都不停掉感知，除非关闭应用」）：
   * - **保留**：三只计时器不清（pending 的活跃/停顿感知照常发出，用卸载前的
   *   上下文快照），舱内零件不清（回台秒弹直接用），思考点不灭（在飞感知
   *   跑完时响应侧自行归位）
   * - **解除**：编辑器活动监听（编辑器已卸载，新实例重挂）、细纲扩写事件、
   *   进行中的 stitch/扩写 SSE（幽灵灌入需要活编辑器，卸载后无法落笔）
   * 真正的全量停机只随应用关闭发生（进程销毁）。切章清舱由 WorkspaceView
   * 的章节 watch 负责（旧章零件是旧章上下文的产物）。
   */
  function detach() {
    if (_continueAbort) { _continueAbort.abort(); _continueAbort = null }
    const editor = chapterEditorHandle.value
    editor?.off('update', _onEditorActivity)
    editor?.off('selectionUpdate', _onEditorActivity)
    window.removeEventListener(OUTLINE_EXPAND_EVENT, _onOutlineExpand)
  }

  return { requestContinue, requestBurst, requestOpening, requestExpandOutline, settleCurrent, finishChapter, summonParts, mount, detach }
}
