/**
 * 预算占用条纯函数单测（P5 A3b · docs/reports/foundation-hardening.md §4.2）。
 *
 * 占用条是纯展示（无 @vue/test-utils，不写组件测试）；比例与变色阈值
 * 抽成纯函数在此锁定。阈值契约：>90% 变色（0.9 恰好不算吃紧）。
 */
import { describe, expect, it } from 'vitest'
import { budgetFillPercent, isBudgetHot } from '../presentation/contextBudget'

describe('budgetFillPercent', () => {
  it('常规比例换算为百分比', () => {
    expect(budgetFillPercent(500, 1000)).toBe(50)
    expect(budgetFillPercent(2500, 2500)).toBe(100)
  })

  it('超配额封顶 100（条不溢出轨道）', () => {
    expect(budgetFillPercent(3000, 1000)).toBe(100)
  })

  it('配额缺失/非法/零占用 → 0（不显示条）', () => {
    expect(budgetFillPercent(100, 0)).toBe(0)
    expect(budgetFillPercent(100, -5)).toBe(0)
    expect(budgetFillPercent(0, 1000)).toBe(0)
    expect(budgetFillPercent(NaN, 1000)).toBe(0)
    expect(budgetFillPercent(100, NaN)).toBe(0)
  })
})

describe('isBudgetHot', () => {
  it('占用比 > 90% 判吃紧', () => {
    expect(isBudgetHot(91, 100)).toBe(true)
    expect(isBudgetHot(100, 100)).toBe(true)
  })

  it('恰好 90% 不算吃紧（阈值是严格大于）', () => {
    expect(isBudgetHot(90, 100)).toBe(false)
    expect(isBudgetHot(89, 100)).toBe(false)
  })

  it('配额缺失/非法不误报', () => {
    expect(isBudgetHot(999, 0)).toBe(false)
    expect(isBudgetHot(999, -1)).toBe(false)
    expect(isBudgetHot(NaN, 100)).toBe(false)
  })
})
