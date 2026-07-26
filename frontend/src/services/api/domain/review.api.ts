/**
 * 审阅/质量重跑 API。
 *
 * 封装后端已存在但此前前端未暴露的能力：
 * - POST /api/chapters/{id}/quality-report/rerun  重新触发双层质量审计
 * - POST /api/critique_chapter                    毒舌编辑视角的章节审阅
 */
import { requestJson } from '../transport'
import type { QualityReport } from '../../../types'

/** 审阅条目（对应后端 CritiqueItem）。 */
export interface CritiqueItem {
  exact_quote: string
  type: string
  reader_feeling: string
  suggestion: string
}

/** 审阅响应（对应后端 CritiqueResponse）。 */
export interface CritiqueResponse {
  comments: CritiqueItem[]
  overall_praise: string
}

export const reviewApi = {
  /** 重新触发本章双层质量审计（代码级 + LLM 级），返回新报告。 */
  rerunQualityReport: (chapterId: string, runId?: string): Promise<QualityReport> => {
    const query = runId ? `?run_id=${runId}` : ''
    return requestJson(`/chapters/${chapterId}/quality-report/rerun${query}`, {
      method: 'POST',
    })
  },

  /** 毒舌编辑审阅：纯文本输入，无需数据库上下文。 */
  critiqueChapter: (chapterContent: string, chapterTitle?: string): Promise<CritiqueResponse> =>
    requestJson('/critique_chapter', {
      method: 'POST',
      body: JSON.stringify({
        chapter_content: chapterContent,
        chapter_title: chapterTitle ?? null,
      }),
    }),
}
