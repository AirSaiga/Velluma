import { afterEach, describe, expect, it, vi } from 'vitest'
import { countChapterWords, escapeHtml, stripHtmlToText } from '../htmlText'

/**
 * vitest 为 node 环境无 DOM（vitest.config.js 注释：engine 层纯 TS）。
 * 纯函数面（快路径/escapeHtml/纯文本字数）直接测；
 * 标签路径用受控 document stub 验证「走 DOM 解析而非正则」的调用协议。
 */

describe('stripHtmlToText', () => {
  it('空输入 → 空串', () => {
    expect(stripHtmlToText('')).toBe('')
  })

  it('无标签文本直返（不触碰 DOM）', () => {
    expect(stripHtmlToText('山月不知心底事。')).toBe('山月不知心底事。')
  })

  it('含标签文本走 DOM 解析（node 环境用受控 stub）', () => {
    const div = {
      _html: '',
      set innerHTML(v: string) {
        this._html = v
      },
      get textContent() {
        // 模拟浏览器解析：剥标签、实体还原（与被测函数解耦的独立实现）
        return this._html
          .replace(/<[^>]+>/g, '')
          .replace(/&nbsp;/g, ' ')
      },
    }
    vi.stubGlobal('document', { createElement: () => div })
    try {
      expect(stripHtmlToText('<p>他推门。</p><p>风雪&nbsp;扑面。</p>')).toBe('他推门。风雪 扑面。')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

describe('countChapterWords', () => {
  it('纯文本：去空白后的字符数（中文按字符计）', () => {
    expect(countChapterWords('山月不知心底事')).toBe(7)
    expect(countChapterWords('山 月 不 知')).toBe(4)
  })

  it('空输入 → 0', () => {
    expect(countChapterWords('')).toBe(0)
  })

  it('标签字符不计入（字数口径统一红线）', () => {
    // 2026-09-17 起为纯正则快路径（不再 DOM 解析）：长章字数重算不再抖主线程
    expect(countChapterWords('<p>正文字数</p>')).toBe(4)
    expect(countChapterWords('<p>他推门。</p><p><strong>风雪</strong>扑面。</p>')).toBe(9)
  })

  it('常见实体按解码后字符计（快路径与 DOM 精确路径口径一致）', () => {
    expect(countChapterWords('A&amp;B')).toBe(3)
    expect(countChapterWords('「&quot;q&quot;」')).toBe(5) // 引号解码后是真实字符，照计
    expect(countChapterWords('他&nbsp;们')).toBe(2) // nbsp 属空白，去掉
  })
})

describe('escapeHtml', () => {
  it('四类敏感字符实体化', () => {
    expect(escapeHtml('<script a="b">&')).toBe('&lt;script a=&quot;b&quot;&gt;&amp;')
  })

  it('普通中文原样', () => {
    expect(escapeHtml('山月不知')).toBe('山月不知')
  })

  it('null/undefined → 空串（拼 tooltip 的最小防线）', () => {
    expect(escapeHtml(null)).toBe('')
    expect(escapeHtml(undefined)).toBe('')
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})
