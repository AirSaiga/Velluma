import { describe, it, expect, beforeEach } from 'vitest'
import { useDeaiPairMark, DEAI_BAD_MAX_CHARS } from '../useDeaiPairMark'

// 模块级单例——每个用例前清干净
const { pendingBad, markBad, markGood, clearPending } = useDeaiPairMark()

const BAD = '综上所述，本次改版显著提升了页面加载速度，为后续增长夯实了基础。'
const GOOD = '这轮改版后，页面加载快了不少，后面的增长也有底了。'

describe('deai 训练对配对状态机', () => {
  beforeEach(() => clearPending())

  it('记改前：暂存文本并给出下一步指引', () => {
    const r = markBad(BAD, 'bk1')
    expect(r.ok).toBe(true)
    expect(pendingBad.value?.text).toBe(BAD)
    expect(pendingBad.value?.bookKey).toBe('bk1')
  })

  it('记改前：空文本与超 100 字契约窗拒绝', () => {
    expect(markBad('   ', 'bk1').ok).toBe(false)
    const over = markBad('字'.repeat(DEAI_BAD_MAX_CHARS + 1), 'bk1')
    expect(over.ok).toBe(false)
    expect(over.message).toContain(String(DEAI_BAD_MAX_CHARS))
    expect(pendingBad.value).toBeNull()
  })

  it('记改后：无暂存时给出流程指引', () => {
    const r = markGood(GOOD, 'bk1')
    expect(r.ok).toBe(false)
    expect(r.message).toContain('记改前')
  })

  it('记改后：配对成功且不清 pending（提交成功才由调用方清）', () => {
    markBad(BAD, 'bk1')
    const r = markGood(GOOD, 'bk1')
    expect(r.ok).toBe(true)
    expect(r.bad).toBe(BAD)
    expect(pendingBad.value).not.toBeNull()
  })

  it('记改后：换书作废并清空暂存', () => {
    markBad(BAD, 'bk1')
    const r = markGood(GOOD, 'bk2')
    expect(r.ok).toBe(false)
    expect(r.message).toContain('另一本书')
    expect(pendingBad.value).toBeNull()
  })

  it('记改后：改后文本为空拒绝', () => {
    markBad(BAD, 'bk1')
    expect(markGood('  ', 'bk1').ok).toBe(false)
  })

  it('重复记改前 = 覆盖旧暂存（重新选段场景）', () => {
    markBad(BAD, 'bk1')
    markBad('另一段原文。', 'bk1')
    const r = markGood('另一段改后。', 'bk1')
    expect(r.bad).toBe('另一段原文。')
  })
})
