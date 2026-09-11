/**
 * 约束治理二期前端透出测试（2026-09-02）。
 *
 * 覆盖三件：
 * 1. 新 warning kind 人话映射（out_of_scene/location_jump/quality_breaker/
 *    cliche_hit）——GhostWarningsBar 的 KIND_META、useGhostDraft 的
 *    WARNING_KIND_LABELS 与汇总话术共用口径；未登记 kind 回退原串不炸；
 * 2. setGhostRepaired 状态灌入纪律：count>0 才亮条，beginGhost 重置；
 * 3. materializeRejectedGhost 逃生舱：拒稿原稿以普通幽灵形态灌回
 *    （ghostActive + ghostOriginal 累积 + 编辑器收到带 ghostDraft mark 的插入）。
 *
 * node 环境（无 jsdom）：collabEventBus 桩掉（真实实现走 window）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../../composables/collabEventBus', () => ({
  dispatchCollabEvent: vi.fn(),
}))

import {
  ghostActive,
  ghostOriginal,
  ghostRepaired,
  ghostBreakerOpen,
  beginGhost,
  evaporateGhost,
  setGhostRepaired,
  materializeRejectedGhost,
  summarizeGhostWarnings,
  warningKindLabel,
} from '../composables/useGhostDraft'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import type { GhostWarning } from '../../../services/api/domain/adaptive.api'

/** 最小编辑器替身：无幽灵节点；记录 insertContentAt 收到的内容。 */
function mockEditor() {
  const inserted: any[] = []
  const editor = {
    state: {
      doc: {
        descendants(_cb: (node: any, pos: number) => void) {
          return true // 空文档——无 ghostDraft 节点 → findGhostRange 返 null
        },
      },
      selection: { from: 5 },
    },
    chain() {
      const self: any = {
        command: () => self,
        deleteRange: () => self,
        insertContentAt: (_pos: number, content: any) => {
          inserted.push(content)
          return self
        },
        run: () => true,
      }
      return self
    },
  } as any
  return { editor, inserted }
}

let insertedRef: any[] = []

beforeEach(() => {
  const { editor, inserted } = mockEditor()
  chapterEditorHandle.value = editor
  insertedRef = inserted
  if (ghostActive.value) evaporateGhost()
  ghostRepaired.value = null
  ghostBreakerOpen.value = false
})

describe('warningKindLabel（二期新 kind 人话映射）', () => {
  it('四个新 kind 全部有人话标签', () => {
    expect(warningKindLabel('out_of_scene')).toBe('人物不在场')
    expect(warningKindLabel('location_jump')).toBe('地点跳变')
    expect(warningKindLabel('quality_breaker')).toBe('自动修正暂停')
    expect(warningKindLabel('cliche_hit')).toBe('禁忌词')
  })

  it('旧三类标签不回归', () => {
    expect(warningKindLabel('dead_speak')).toBe('死者开口')
    expect(warningKindLabel('canon_leak')).toBe('秘密穿帮')
    expect(warningKindLabel('secret_leak')).toBe('秘密外泄')
  })

  it('未登记 kind 回退原串（后端新增枚举不炸前端）', () => {
    expect(warningKindLabel('future_kind')).toBe('future_kind')
  })

  it('抢拍（09-03 live 出生即返修资格）有人话标签', () => {
    expect(warningKindLabel('beat_rush')).toBe('抢拍')
  })
})

describe('summarizeGhostWarnings 二期 kind 进汇总话术', () => {
  it('跳变两类按人话标签汇总', () => {
    const s = summarizeGhostWarnings([
      { kind: 'out_of_scene', span_text: '流光', message: 'x' },
      { kind: 'location_jump', span_text: '北岸要塞', message: 'y' },
    ] as GhostWarning[])
    expect(s).toBe('已采纳，含 2 处疑点：人物不在场、地点跳变（只是提醒，可不管）')
  })
})

describe('setGhostRepaired（返修环结果灌入）', () => {
  it('count>0 亮条 + 熔断旗标', () => {
    setGhostRepaired({ count: 2, kinds: ['canon_leak'], action: 'repaired' }, false)
    expect(ghostRepaired.value).toEqual({ count: 2, kinds: ['canon_leak'], action: 'repaired' })
    expect(ghostBreakerOpen.value).toBe(false)
  })

  it('items 逐条明细随车透传（09-08 作者可见性：点开看修了什么）', () => {
    const items: GhostWarning[] = [
      { kind: 'canon_leak', span_text: '皇室遗孤', message: '疑似泄底：正文直接写出了真相层私有标签「皇室遗孤」' },
    ]
    setGhostRepaired({ count: 1, kinds: ['canon_leak'], action: 'repaired', items }, false)
    expect(ghostRepaired.value?.items).toEqual(items)
  })

  it('count=0 / 缺字段 → 不亮条；breaker_open=true 亮熔断', () => {
    setGhostRepaired({ count: 0, kinds: [], action: 'repaired' }, true)
    expect(ghostRepaired.value).toBeNull()
    expect(ghostBreakerOpen.value).toBe(true)
  })

  it('undefined 全空 → 双态归零（无返修帧的常态路径）', () => {
    setGhostRepaired({ count: 1, kinds: ['canon_leak'], action: 'excised' }, true)
    setGhostRepaired(undefined, undefined)
    expect(ghostRepaired.value).toBeNull()
    expect(ghostBreakerOpen.value).toBe(false)
  })

  it('beginGhost 重置（下一发幽灵不戴上一发的修正条）', () => {
    setGhostRepaired({ count: 1, kinds: ['canon_leak'], action: 'repaired' }, true)
    beginGhost('stitch')
    expect(ghostRepaired.value).toBeNull()
    expect(ghostBreakerOpen.value).toBe(false)
  })
})

describe('materializeRejectedGhost（拒稿逃生舱）', () => {
  it('空文本静默不动作（防御位）', () => {
    materializeRejectedGhost('')
    expect(ghostActive.value).toBe(false)
  })

  it('拒稿原稿灌回为普通幽灵：状态激活 + 原文累积 + 带 ghostDraft mark 落文档', () => {
    materializeRejectedGhost('被拒的原稿文本。')
    expect(ghostActive.value).toBe(true)
    expect(ghostOriginal.value).toBe('被拒的原稿文本。')
    expect(insertedRef.length).toBe(1)
    const content = insertedRef[0]
    expect(content.text).toBe('被拒的原稿文本。')
    expect(content.marks[0].type).toBe('ghostDraft')
  })

  it('灌回后可再蒸发（Enter/Esc 同契约的蒸发半边）', () => {
    materializeRejectedGhost('被拒的原稿文本。')
    evaporateGhost()
    expect(ghostActive.value).toBe(false)
  })
})
