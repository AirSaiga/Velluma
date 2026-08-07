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
import { watch, type Ref } from 'vue'
import { adaptiveApi, type HeartbeatResult, type FinishReport, type SettleResult } from '../../../services/api/domain/adaptive.api'
import {
  ghostActive, beginGhost, appendGhost, evaporateGhost,
} from './useGhostDraft'
import { setSparkParts, showSparkDock, type SparkPart } from './useSparkDock'
import { setThinkingPhase, hideThinking } from './useThinkingIndicator'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'

const ACTIVE_HEARTBEAT_MS = 3000   // 活跃心跳防抖
const PAUSE_HEARTBEAT_MS = 4000    // 停顿心跳（与 Spark Dock 弹出门控对齐）
const PREVIEW_DELAY_MS = 2000      // 思考指示器预览态延迟（停顿 2s 即显示淡灰点）

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
}

export function useAdaptiveAssist(opts: AdaptiveAssistOptions) {
  let _activeTimer: ReturnType<typeof setTimeout> | null = null
  let _pauseTimer: ReturnType<typeof setTimeout> | null = null
  let _previewTimer: ReturnType<typeof setTimeout> | null = null
  let _lastActiveTs = 0
  let _heartbeatAbort: AbortController | null = null
  let _continueAbort: AbortController | null = null

  // ---- 编辑器活动：重置三个计时器 + 隐藏思考指示器 ----
  function _onEditorActivity() {
    _lastActiveTs = Date.now()
    // 作者重新动笔 → 立即隐藏思考点（任何 pending 计时器随之清掉）
    hideThinking()
    // 预览计时器：2s 后若无新活动 → 显示淡灰「等待中」点（预示即将凑近）
    if (_previewTimer) clearTimeout(_previewTimer)
    _previewTimer = setTimeout(() => {
      // 仅 composing 态 + 光标在段尾才预览（段中编辑/选词不算停顿思考）
      if (opts.authorLaneRef.value === 'composing' && _isCursorAtParagraphEnd()) {
        setThinkingPhase('waiting')
      }
    }, PREVIEW_DELAY_MS)
    // 活跃心跳：3s 后发（让后端感知正文推进）
    if (_activeTimer) clearTimeout(_activeTimer)
    _activeTimer = setTimeout(() => { void _sendHeartbeat(0) }, ACTIVE_HEARTBEAT_MS)
    // 停顿心跳：4s 后发（若期间无新活动，作者卡住了）
    if (_pauseTimer) clearTimeout(_pauseTimer)
    _pauseTimer = setTimeout(() => {
      // 仅光标在段尾才发停顿心跳（段中修改不算卡壳）
      if (_isCursorAtParagraphEnd()) {
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

  async function _sendHeartbeat(pausedMs: number) {
    const chapterId = opts.getChapterId()
    if (!chapterId) return
    if (opts.authorLaneRef.value !== 'composing') return
    if (ghostActive.value) return  // 幽灵在屏时暂停心跳

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
    }
    const outlineText = opts.getOutline() || ''
    const hasOutline = outlineText.trim().length > 0

    if (_heartbeatAbort) _heartbeatAbort.abort()
    _heartbeatAbort = new AbortController()

    opts.aiLaneRef.value = pausedMs >= PAUSE_HEARTBEAT_MS ? 'perceiving' : 'perceiving'
    // 停顿心跳发出 → 切强态（后端开始算 dock_generator，让用户看到「AI 正在读」）
    if (pausedMs >= PAUSE_HEARTBEAT_MS) {
      setThinkingPhase('perceiving')
    }
    try {
      const result: HeartbeatResult = await adaptiveApi.heartbeat(chapterId, {
        word_count: wordCount,
        segment_count: segmentCount,
        paused_ms: pausedMs,
        cursor_at_paragraph_end: cursorAtEnd,
        has_outline: hasOutline,
        outline_text: outlineText,
        recent_text: recentText.slice(0, 500),
      })
      if (_heartbeatAbort.signal.aborted) return

      // 挂件 → Spark Dock（停顿心跳会带 dock_parts；活跃心跳通常空）
      const parts: SparkPart[] = (result.dock_parts || []).map((p) => ({
        key: p.key,
        kind: (p.kind as any) || 'anchor',
        icon: p.icon || '✨',
        text: p.text,
        direction: p.direction as SparkPart['direction'],
      }))
      if (parts.length) {
        setSparkParts(parts)
        // 停顿心跳且光标在段尾 → 触发 Dock 弹出（此时 sparkParts 已就绪，不会空舱）
        if (pausedMs >= PAUSE_HEARTBEAT_MS && cursorAtEnd) {
          showSparkDock()
        }
      }

      // 意图建议 → planSuggestions
      if (result.intent_source !== 'none') {
        opts.planSuggestionsRef.value = {
          source: result.intent_source,
          arc: result.intent_arc,
          confidence: result.intent_confidence,
        }
      }

      opts.aiLaneRef.value = 'dormant'
      // 心跳完成：有挂件→Dock 接管（指示器已在 visible 计算里被 sparkDockVisible 隐藏）；
      // 无挂件→直接隐藏指示器（后端判本段不够触发，别让脉冲点一直转）
      if (!parts.length) hideThinking()
    } catch (e: any) {
      if (_heartbeatAbort?.signal.aborted) return
      opts.aiLaneRef.value = 'dormant'
      hideThinking()
    }
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

    adaptiveApi.stitchGhost(chapterId, {
      fragment, rolling_prefix: rollingPrefix, mode,
      picked_parts: pickedParts.map((p) => p.text),
      target_chars: mode === 'stitch' ? 120 : 200,
      adopted_direction: adoptedDir,
    }, {
      onStart: () => { beginGhost('stitch'); hideThinking() },
      onChunk: (delta) => appendGhost(delta),
      onDone: () => {
        opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
      },
      onError: () => {
        evaporateGhost(); opts.aiLaneRef.value = 'dormant'; _continueAbort = null
        hideThinking()
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
      return result
    } catch {
      opts.aiLaneRef.value = 'dormant'
      return null
    }
  }

  // ---- 完稿 ----
  async function finishChapter() {
    const chapterId = opts.getChapterId()
    if (!chapterId) return null
    hideThinking()  // 显式动作 → 隐藏指示器
    opts.aiLaneRef.value = 'analyzing'
    try {
      const result = await adaptiveApi.finish(chapterId)
      // 审计报告写入 ref（InspectorPanel 渲染）
      opts.finishReportRef.value = result
      opts.aiLaneRef.value = 'dormant'
      return result
    } catch {
      opts.aiLaneRef.value = 'dormant'
      return null
    }
  }

  // ---- 生命周期 ----
  function mount() {
    watch(chapterEditorHandle, (editor, prev) => {
      prev?.off('update', _onEditorActivity)
      editor?.on('update', _onEditorActivity)
    }, { immediate: true })
  }

  function unmount() {
    if (_activeTimer) { clearTimeout(_activeTimer); _activeTimer = null }
    if (_pauseTimer) { clearTimeout(_pauseTimer); _pauseTimer = null }
    if (_previewTimer) { clearTimeout(_previewTimer); _previewTimer = null }
    if (_heartbeatAbort) { _heartbeatAbort.abort(); _heartbeatAbort = null }
    if (_continueAbort) { _continueAbort.abort(); _continueAbort = null }
    const editor = chapterEditorHandle.value
    editor?.off('update', _onEditorActivity)
    setSparkParts([])
    hideThinking()
  }

  return { requestContinue, settleCurrent, finishChapter, mount, unmount }
}
