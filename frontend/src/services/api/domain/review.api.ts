/**
 * 审阅/质量重跑 API。
 *
 * 封装后端已存在但此前前端未暴露的能力：
 * - POST /api/chapters/{id}/quality-report/rerun  重新触发双层质量审计
 *
 * （/api/critique_chapter 已于 2026-09-12 写后检查收敛批随 Refinery 拔除——
 * docs/post-writing-checks-audit.md：零上下文盲审 + 零观测 + 零采纳通道。）
 */
import { requestJson } from '../transport'
import type { QualityReport } from '../../../types'

export const reviewApi = {
  /** 重新触发本章双层质量审计（代码级 + LLM 级），返回新报告。 */
  rerunQualityReport: (chapterId: string, runId?: string): Promise<QualityReport> => {
    const query = runId ? `?run_id=${runId}` : ''
    return requestJson(`/chapters/${chapterId}/quality-report/rerun${query}`, {
      method: 'POST',
    })
  },
}
