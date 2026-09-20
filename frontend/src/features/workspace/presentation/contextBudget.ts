/**
 * 预算占用条纯函数（P5 A3b · docs/reports/foundation-hardening.md §4.2）。
 *
 * 「AI 此刻所见」预览每块的占用条数据换算——纯展示计算，无组件依赖，
 * 供 ContextPreviewSection.vue 渲染与 __tests__/contextBudget.test.ts 锁定。
 * 占用比 = chars / budget_chars（该块配额=后端 budget.BLOCK_CHAR_BUDGETS
 * 常量上限）；>90% 变色（预算吃紧的调参信号）。
 */

/** 占用百分比（0-100，封顶 100；配额缺失/非法 → 0=不显示条） */
export function budgetFillPercent(chars: number, budget: number): number {
  if (!Number.isFinite(chars) || !Number.isFinite(budget) || budget <= 0 || chars <= 0) {
    return 0
  }
  return Math.min(100, (chars / budget) * 100)
}

/** 是否吃紧（占用比 > 90% 变色的阈值） */
export function isBudgetHot(chars: number, budget: number): boolean {
  if (!Number.isFinite(chars) || !Number.isFinite(budget) || budget <= 0) {
    return false
  }
  return chars / budget > 0.9
}
