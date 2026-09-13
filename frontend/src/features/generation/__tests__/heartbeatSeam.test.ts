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
import { sparkParts, setSparkParts, sparkDockVisible, sparkSticky, setSparkSticky } from '../composables/useSparkDock'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { ghostActive } from '../composables/useGhostDraft'
import { assistEnabled } from '../composables/useAssistEnabled'
import { thinkingPhase } from '../composables/useThinkingIndicator'

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
    // 思考指示器取坐标用（setThinkingPhase → updateThinkingPos）；无 dom 字段
    // 时布局跟随器自动跳过 ResizeObserver，node 环境安全
    view: { coordsAtPos: () => ({ bottom: 100, left: 50 }) },
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
  thinkingPhase.value = 'idle'
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

  it('半句静音清舱无条件执行：dock_muted=true 时 sticky 态不再保留旧件（2026-09-08 僵尸零件修复）', async () => {
    chapterEditorHandle.value = mockEditor('他握紧扳手。')
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse([
      { key: 'landing:a', kind: 'action', icon: '👤', text: '他把书按进内袋', direction: '环境', source: 'landing', note: '接着刚才那句往下写' },
    ]) as any)
    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)
    expect(sparkParts.value.length).toBe(1)

    // 模拟缝合后 sticky 态（08-28 连续吸附流）——旧实现此态半句不清舱，
    // 旧件「幽灵挂载」被作者误读为门禁未生效
    setSparkSticky()
    heartbeat.mockReset()
    heartbeat.mockResolvedValue({ ...okResponse(), dock_muted: true } as any)
    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)

    expect(sparkParts.value).toEqual([])          // 零件彻底清空，杜绝幽灵挂载
    expect(sparkDockVisible.value).toBe(false)    // 舱隐藏（hideSparkDock 一并清 sticky）
    expect(sparkSticky.value).toBe(false)
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

  it('Tab 重复生成：summonParts(true) 带 force_refresh 上行，普通取件不带（2026-09-09）', async () => {
    chapterEditorHandle.value = mockEditor('他握紧扳手。')
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockReset()
    heartbeat.mockResolvedValue(okResponse() as any)

    assist.summonParts(true)    // 舱在屏再按 Tab = 换一批（强制重算）
    await vi.advanceTimersByTimeAsync(0)
    expect((heartbeat.mock.calls[0]?.[1] as any).force_refresh).toBe(true)

    assist.summonParts()        // 普通取件（无缓存首唤）
    await vi.advanceTimersByTimeAsync(0)
    expect((heartbeat.mock.calls[1]?.[1] as any).force_refresh).toBe(false)
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

describe('接缝四：思考指示器只随显式点名亮（2026-09-10 停顿绿点退役）', () => {
  /**
   * 背景自动弹出全线退役（2026-09-09 Tab 唯一入口）后，停顿心跳照发
   * （感知/走向卡/保鲜不中断），但旧链路仍在停顿档发送时点亮光标处的
   * 薄荷绿脉冲点——舱永远不会自己来，作者坐等无果被当成故障。
   * 绿点自此只服务显式动作（Tab 点名/Space 续写/burst/点火/细纲扩写）。
   */
  it('长时间停顿：停顿心跳照发（感知不中断），思考指示器不亮', async () => {
    chapterEditorHandle.value = mockEditor('他握紧扳手。')
    const assist = useAdaptiveAssist(makeOpts())
    assist.mount()
    const onUpdate = (chapterEditorHandle.value as any).on.mock.calls.find((c: any[]) => c[0] === 'update')?.[1] as any
    heartbeat.mockResolvedValue(okResponse([
      { key: 'landing:a', kind: 'action', icon: '👤', text: '他把书按进内袋', source: 'landing' },
    ]) as any)

    onUpdate()                              // 打字武装计时器（活跃 3s + 停顿 4s）
    await vi.advanceTimersByTimeAsync(4000) // 越过两档

    const pauseCall = heartbeat.mock.calls.find((c: any[]) => c[1]?.paused_ms >= 4000)
    expect(pauseCall).toBeTruthy()           // 停顿心跳照发（后台感知不中断）
    expect(thinkingPhase.value).toBe('idle') // 绿点不亮：舱不会自己来，不承诺等待
  })

  it('停顿 2s 的等待预览灰点一并退役（不再有任何停顿预告）', async () => {
    chapterEditorHandle.value = mockEditor('他握紧扳手。')
    const assist = useAdaptiveAssist(makeOpts())
    assist.mount()
    const onUpdate = (chapterEditorHandle.value as any).on.mock.calls.find((c: any[]) => c[0] === 'update')?.[1] as any
    heartbeat.mockResolvedValue(okResponse() as any)

    onUpdate()
    await vi.advanceTimersByTimeAsync(2000) // 旧预览态时点（停顿 2s 亮灰点）

    expect(thinkingPhase.value).toBe('idle')
  })

  it('Tab 点名：summoned 心跳亮思考指示器，空手而归后灯灭（等待反馈保留）', async () => {
    chapterEditorHandle.value = mockEditor('他握紧扳手。')
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse() as any)

    assist.summonParts()
    expect(thinkingPhase.value).toBe('perceiving')  // 发送即亮（作者点名要件）
    await vi.advanceTimersByTimeAsync(0)

    expect(thinkingPhase.value).toBe('idle')        // 空响应 → 等待结束灯灭
  })

  it('点名撞上在飞后台生发：挂起等待期由点名自己亮灯（后台不亮后不能零反馈）', async () => {
    chapterEditorHandle.value = mockEditor('他握紧扳手。')
    const assist = useAdaptiveAssist(makeOpts())
    assist.mount()
    const onUpdate = (chapterEditorHandle.value as any).on.mock.calls.find((c: any[]) => c[0] === 'update')?.[1] as any
    heartbeat.mockResolvedValue(okResponse() as any)
    onUpdate()
    await vi.advanceTimersByTimeAsync(3000)  // 活跃档先发出并落地

    let resolveBg!: (v: any) => void
    heartbeat.mockImplementationOnce(() => new Promise((r) => { resolveBg = r }))
    await vi.advanceTimersByTimeAsync(1000)  // 停顿档发出（在飞挂起）
    expect(thinkingPhase.value).toBe('idle') // 后台停顿生发不亮灯

    assist.summonParts()                     // Tab 点名：撞在飞 → 转挂起
    expect(thinkingPhase.value).toBe('perceiving')

    resolveBg(okResponse() as any)           // 后台响应空手落地 → 补发 summoned
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(0)
    expect(heartbeat).toHaveBeenCalledTimes(3)  // 活跃 + 停顿 + 挂起补发
    expect(thinkingPhase.value).toBe('idle')    // 补发仍空 → 灯灭
  })
})

describe('接缝三：FIM 中插桥接取源（2026-09-09「卡片接着文末写」事故）', () => {
  /**
   * 桥接编辑器替身：光标停在空段（插入点），前后都有已写正文。
   * textBetween 按 flat 串切片模拟——pos 之前=前文，pos 之后=后文。
   */
  function bridgeEditor(pre: string, suffix: string) {
    const flat = pre + '\n\n' + suffix
    const pos = pre.length
    return {
      on: vi.fn(),
      off: vi.fn(),
      state: {
        doc: {
          textContent: flat.replace(/\n/g, ''),
          content: { size: flat.length },
          descendants: vi.fn(),
          textBetween: (from: number, to: number) =>
            flat.slice(Math.max(0, from), Math.max(0, to)),
        },
        selection: {
          $from: {
            parent: { textContent: '' },   // 插入点=空段
            pos,
            end: () => pos,
            start: () => pos,
          },
        },
      },
    } as any
  }

  it('桥接态 recent_text=光标前窗口（含前文、不含后文）——不再发空串触发后端文档末尾回退', async () => {
    const editor = bridgeEditor(
      '“这样啊，那你路上当心点。”王叔咳了两声。林尘背上包出门。',
      '林尘来到村子约莫一个星期了。醒来时躺在稻草堆里。',
    )
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse() as any)

    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)

    const call = heartbeat.mock.calls[0]?.[1] as any
    expect(call.recent_text).toContain('王叔咳了两声')      // 锚定光标前文
    expect(call.recent_text).not.toContain('稻草堆')         // 后文不混入「当前段落」
    expect(call.suffix_anchor).toContain('稻草堆')           // 后文走锚块（双端边界）
  })

  it('普通态（光标后无正文）零变化：recent_text 仍取光标段', async () => {
    const editor = bridgeEditor('他握紧扳手。', '')   // 光标在文尾：无后文=普通续写
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse() as any)

    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)

    const call = heartbeat.mock.calls[0]?.[1] as any
    expect(call.suffix_anchor).toBe('')
    // 光标段（空段）原样发空串——后端按既有口径回退（文尾场景下画布尾即正确上下文）
    expect(call.recent_text).toBe('')
  })

  it('2026-09-13 事故回归：省略号不再截断后文锚——物证完整上行', async () => {
    // 旧版「截到第 2 个句末标点」：省略号「……」是两个 U+2026 字符，一个
    // 省略号吃光两次配额，锚截在「咳咳…」处，「巷子里没灯」的物证没进锚。
    const suffix = '“这样啊，那你路上当心点，这天晚了，咳咳……”王叔弓着腰咳嗽了几声。巷子里没灯，只有谁家窗纸透出一点黄。'
    const editor = bridgeEditor('“不用不用。”林尘回头笑了笑。', suffix)
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse() as any)

    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)

    const call = heartbeat.mock.calls[0]?.[1] as any
    expect(call.suffix_anchor).toContain('咳咳……')
    expect(call.suffix_anchor).toContain('巷子里没灯')
  })

  it('超 300 字的后文回退窗内最后句末标点截断（结尾干净、不数句）', async () => {
    const suffix = '他数着路灯往前走，影子被拉长又缩短。'.repeat(30)  // 450 字
    const editor = bridgeEditor('前文一句。', suffix)
    chapterEditorHandle.value = editor
    const assist = useAdaptiveAssist(makeOpts())
    heartbeat.mockResolvedValue(okResponse() as any)

    assist.summonParts()
    await vi.advanceTimersByTimeAsync(0)

    const call = heartbeat.mock.calls[0]?.[1] as any
    const anchor = call.suffix_anchor as string
    expect(anchor.length).toBeLessThanOrEqual(300)
    expect('。！？…'.includes(anchor[anchor.length - 1])).toBe(true)
    expect(anchor).toContain('他数着路灯往前走')
  })
})
