/**
 * 心跳接缝对拍（2026-08-30 审计修复护栏）。
 *
 * 两起接缝事故的回归锁——两侧各自有测试、接缝本身无对拍，是两案的共性根因：
 * 1. 槽位贯通：后端 _finalize_parts 产 source/note、路由原样透传，但心跳
 *    映射的对象字面量漏拷这两字段——SparkDock 副行恒「○ 纯画面 · 不牵动
 *    剧情」，landing/echo 的后果短语从未上屏（SparkPart.optional → vue-tsc 零报）。
 * 2. 感知常驻：停顿计时器回调把 _sendHeartbeat 整段包在光标闸里，编辑器
 *    卸载（切页）后 _isCursorAtParagraphEnd 恒 false——切页后的 pending
 *    停顿感知整段挡死，_lastCtx 快照形同虚设（只剩活跃档可达）。
 *
 * node 环境（无 jsdom）：adaptive.api 整模块桩掉（heartbeat 可控响应 +
 * logCollabEvent 静默），window 以最小桩替代（mount 的事件监听）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'

vi.mock('../../../services/api/domain/adaptive.api', () => ({
  adaptiveApi: {
    heartbeat: vi.fn(),
    logCollabEvent: vi.fn(),
    stitchGhost: vi.fn(),
  },
}))

// OutlineNoteNode → OutlineNoteChip.vue：vitest node 环境无 vue 插件，
// 桩掉组件本体（本测试不渲染节点视图，只消费 findOutlineNotes 纯函数）
vi.mock('../../../extensions/OutlineNoteChip.vue', () => ({ default: {} }))

import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import { useAdaptiveAssist } from '../composables/useAdaptiveAssist'
import { sparkParts, setSparkParts } from '../composables/useSparkDock'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { ghostActive } from '../composables/useGhostDraft'
import { assistEnabled } from '../composables/useAssistEnabled'

const heartbeat = vi.mocked(adaptiveApi.heartbeat)

/** 心跳响应的最小可用形状（走真实 _sendHeartbeat 响应侧全链路） */
function okResponse(dockParts: any[] = []) {
  return {
    dock_parts: dockParts,
    direction_cards: [],
    intent_source: 'none',
    intent_arc: '',
    intent_confidence: 0,
    fact_count: 0,
    total_words: 0,
    activated: [],
    signals: [],
    canon_hints: [],
  }
}

/** 段尾编辑器替身：$from.parent.textContent / doc.textContent / $from.end() */
function mockEditor(paragraphText: string, atEnd = true) {
  const end = 10 + paragraphText.length
  return {
    on: vi.fn(),
    off: vi.fn(),
    state: {
      doc: {
        textContent: 'x'.repeat(200) + paragraphText,
        descendants: vi.fn(),  // 细纲胶囊收集（意图入舱批次）——替身无胶囊
      },
      selection: {
        $from: {
          parent: { textContent: paragraphText },
          pos: atEnd ? end - 1 : end - 5,
          end: () => end,
        },
      },
    },
  } as any
}

function makeOpts(chapterId = 'ch-seam') {
  return {
    getChapterId: () => chapterId,
    getOutline: () => '',
    suggestionsRef: ref<any[]>([]),
    planSuggestionsRef: ref<any>(null),
    dynamicBeatsRef: ref<any[]>([]),
    aiLaneRef: ref<string>('dormant'),
    authorLaneRef: ref<string>('composing'),
    finishReportRef: ref<any>(null),
    settleResultRef: ref<any>(null),
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('window', {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })
  heartbeat.mockReset()
  assistEnabled.value = true
  ghostActive.value = false
  setSparkParts([])
  chapterEditorHandle.value = null
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('接缝一：dock 零件 source/note 贯通（副行数据不丢）', () => {
  it('心跳响应带 source/note → sparkParts 原样保留', async () => {
    chapterEditorHandle.value = mockEditor('他握紧扳手。')
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse([
      { key: 'landing:a', kind: 'action', icon: '👤', text: '他把书按进内袋', direction: '环境', source: 'landing', note: '接着刚才那句往下写' },
      { key: 'echo:b', kind: 'action', icon: '👤', text: '扳手砸中铁屑', direction: '环境', source: 'echo', note: '顺笔带出前情：第三章·扳手' },
      { key: 'ambient:c', kind: 'scene', icon: '⚙️', text: '灰光浮尘', direction: '环境', source: 'ambient' },
    ]) as any)

    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)

    const landing = sparkParts.value.find((p) => p.key === 'landing:a')
    const echo = sparkParts.value.find((p) => p.key === 'echo:b')
    const ambient = sparkParts.value.find((p) => p.key === 'ambient:c')
    expect(landing?.source).toBe('landing')
    expect(landing?.note).toBe('接着刚才那句往下写')
    expect(echo?.source).toBe('echo')
    expect(echo?.note).toBe('顺笔带出前情：第三章·扳手')
    expect(ambient?.source).toBe('ambient')
    expect(ambient?.note).toBeUndefined()
  })

  it('细纲胶囊速记随心跳上行（意图反推素材；无胶囊传空数组）', async () => {
    const editor = mockEditor('他握紧扳手。') as any
    // 替身植入两枚胶囊节点（一枚空 note 被过滤）
    editor.state.doc.descendants = (cb: any) => {
      cb({ type: { name: 'outlineNote' }, attrs: { note: ' 让他先忍住，下班才爆发 ' } })
      cb({ type: { name: 'outlineNote' }, attrs: { note: '  ' } })
      cb({ type: { name: 'paragraph' }, attrs: {} })
      return true
    }
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse() as any)

    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)

    const call = heartbeat.mock.calls[0]?.[1] as any
    expect(call.outline_notes).toEqual(['让他先忍住，下班才爆发'])
  })

  it('零件槽位随 stitch 请求上行（双轨契约选档信号，与 picked_parts 同序）', () => {
    const editor = mockEditor('他握紧扳手。') as any
    // requestContinue 需要的两件套：$from.start() 与 doc.textBetween()
    editor.state.selection.$from.start = () => 10
    editor.state.doc.textBetween = () => '前文尾巴'
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())

    assist.requestContinue('stitch', [
      { text: '灰光浮尘', slot: 'ambient' },
      { text: '他把书按进内袋', slot: 'landing' },
    ])

    const call = vi.mocked(adaptiveApi.stitchGhost).mock.calls[0]?.[1] as any
    expect(call.picked_parts).toEqual(['灰光浮尘', '他把书按进内袋'])
    expect(call.picked_slots).toEqual(['ambient', 'landing'])
  })
})

describe('接缝二：感知常驻——切页后停顿档心跳照发', () => {
  /** 打字 → 切页（编辑器卸载）的最小剧场；返回武装完毕的 assist */
  function typeThenLeavePage(assist: ReturnType<typeof useAdaptiveAssist>, editor: any) {
    assist.mount()
    const onUpdate = editor.on.mock.calls.find((c: any[]) => c[0] === 'update')?.[1] as any
    expect(onUpdate).toBeTruthy()
    onUpdate()                      // 作者打字：武装计时器 + 记 _lastCtx 快照
    chapterEditorHandle.value = null  // 切页：RichTextEditor onBeforeUnmount 置空句柄
  }

  it('编辑器卸载后 pending 停顿心跳用快照段尾判据照发（paused_ms=4000，recent_text 来自快照）', async () => {
    const editor = mockEditor('他握紧扳手。')
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())
    typeThenLeavePage(assist, editor)

    heartbeat.mockResolvedValue(okResponse() as any)
    await vi.advanceTimersByTimeAsync(4000)

    const pauseCall = heartbeat.mock.calls.find((c: any[]) => c[1]?.paused_ms >= 4000)
    expect(pauseCall).toBeTruthy()
    expect((pauseCall![1] as any).recent_text).toContain('他握紧扳手')
  })

  it('快照记的是段中（非段尾）→ 卸载后停顿心跳不发（段中修改不算卡壳）', async () => {
    const editor = mockEditor('他握紧扳手。', false)  // 光标在段中
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())
    typeThenLeavePage(assist, editor)

    heartbeat.mockResolvedValue(okResponse() as any)
    await vi.advanceTimersByTimeAsync(4000)

    expect(heartbeat.mock.calls.every((c: any[]) => (c[1]?.paused_ms ?? 0) < 4000)).toBe(true)
  })

  it('切章后旧章快照作废：停顿/活跃档都不拿旧章段文本感知新章', async () => {
    const editor = mockEditor('他握紧扳手。')
    chapterEditorHandle.value = editor
    const opts = makeOpts('ch-old')
    const assist = useAdaptiveAssist(opts)
    typeThenLeavePage(assist, editor)
    opts.getChapterId = () => 'ch-new'   // 切章

    heartbeat.mockResolvedValue(okResponse() as any)
    await vi.advanceTimersByTimeAsync(4000)

    expect(heartbeat).not.toHaveBeenCalled()
  })
})
