import { describe, it, expect } from 'vitest'
import { ensurePinyin, matchesQuery } from '../pinyinMatch'

// 二期拼音检索：懒加载前后两种行为都要锁——退化路径（子串）是常态首屏，
// 拼音路径在引擎到位后生效。用例顺序有意安排：先退化后加载。

describe('pinyinMatch 拼音检索', () => {
  it('空查询恒真 / 子串匹配（引擎未就绪的常态行为）', () => {
    expect(matchesQuery('', '任意文本')).toBe(true)
    expect(matchesQuery('林尘', '林尘序章生活的村庄')).toBe(true)
    expect(matchesQuery('村庄', '林尘序章生活的村庄')).toBe(true)
    expect(matchesQuery('不存在', '林尘序章生活的村庄')).toBe(false)
    // null/undefined 字段跳过不抛
    expect(matchesQuery('林尘', null, undefined, '林尘')).toBe(true)
  })

  it('拼音就绪后：全拼/首字母/部分音节/中位命中、多字段任一命中、未命中仍为假', async () => {
    await ensurePinyin()
    expect(matchesQuery('linchen', '林尘')).toBe(true)            // 全拼
    expect(matchesQuery('lc', '林尘')).toBe(true)                 // 首字母
    expect(matchesQuery('linc', '林尘')).toBe(true)               // 部分音节
    expect(matchesQuery('cunzhuang', '林尘序章生活的村庄')).toBe(true) // 中位命中（村庄）
    expect(matchesQuery('bjys', '北京要塞')).toBe(true)           // 多字首字母缩写
    expect(matchesQuery('beijing', null, '北京要塞')).toBe(true)  // 第二字段命中
    expect(matchesQuery('林c', '林尘')).toBe(true)                // 中文+拼音混输
    expect(matchesQuery('LINCHEN', '林尘')).toBe(true)            // 大小写不敏感
    expect(matchesQuery('xyzq', '林尘')).toBe(false)              // 未命中
  })
})
