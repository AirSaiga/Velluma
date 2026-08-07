/**
 * 降级原因字典（前后端对齐）。
 *
 * 职责：把后端 downgrade.py / bsadf_workflow.py 产出的英文 reason 枚举
 * 映射成作者可读的中文，供 StoryboardPanel / GenerationStepper
 * 等处共用，避免文案分散与手动同步。
 *
 * 后端实际 reason 取值来源：
 * - 步进中（BEAT_RENDER_READY.degraded / BEAT_DOWNGRADED）：
 *   downgrade.py:_classify_downgrade_reason 产出 ai_smell / gate_fail /
 *   coverage_fail / llm_error 四类
 * - 完成态（COMPLETE.degraded_beats）/ 轮询兜底（stepping-run/state）：
 *   bsadf_workflow.py:1467 与 routes/bsadf.py:1368 重建时硬编码 render_degraded
 *   （卡快照不保留原始 reason，故用通用值）
 *
 * 其中 gate_fail 在后端实际覆盖三类（downgrade.py:246-251）：
 *   segment_loop_duplicate（剧情回路/与前段重复）、
 *   pov_absent（POV 角色名缺失）、
 *   已死亡/离场（角色状态矛盾）。
 * 故文案需点明这三类，而非笼统的"质检未通过"。
 */
export const DEGRADED_REASON_LABEL: Record<string, string> = {
  ai_smell: 'AI 腔过重',
  coverage_fail: '必现画面覆盖不足',
  gate_fail: '质检未通过（剧情重复 / 角色状态冲突 / 视角缺失）',
  llm_error: '模型调用错误',
  render_degraded: '渲染降级',
}

/**
 * 把降级 reason 映射为中文；未知 reason 原样返回（兜底，不丢失信息）。
 *
 * 用法：`formatDegradedReason(ev.reason)`
 */
export function formatDegradedReason(reason: string | undefined | null): string {
  if (!reason) return '渲染降级'
  return DEGRADED_REASON_LABEL[reason] || reason
}
