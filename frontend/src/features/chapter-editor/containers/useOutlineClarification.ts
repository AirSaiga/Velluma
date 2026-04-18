import { ref } from 'vue'
import { generateApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import type { Chapter, ClarifyingQuestion } from '../../../types'

export function useOutlineClarification() {
  const { showToast } = useToast()

  const isClarifyingOutline = ref(false)
  const clarificationResult = ref<{
    is_ambiguous: boolean
    identified_issues?: string[]
    clarifying_questions?: ClarifyingQuestion[]
    clarification_suggestions?: string[]
    refined_text?: string
  } | null>(null)
  const showClarificationModal = ref(false)

  function closeClarificationModal() {
    showClarificationModal.value = false
    clarificationResult.value = null
  }

  async function checkOutlineClarification(
    chapter: Chapter,
    apiConfig: { api_key: string; base_url: string; reasoning_model?: string; model?: string }
  ) {
    const currentOutline = chapter.outline_text?.trim() || ''
    if (!currentOutline.length || currentOutline.length >= 200) {
      return { shouldIntercept: false as const }
    }

    isClarifyingOutline.value = true
    try {
      const clarifyRes = await generateApi.clarifyOutline({
        chapter_id: chapter.id,
        ambiguous_text: currentOutline,
        api_key: apiConfig.api_key,
        base_url: apiConfig.base_url,
        model: apiConfig.reasoning_model || apiConfig.model || 'gpt-4o-mini',
        author_intent: chapter.author_intent
      })

      if (
        clarifyRes.is_ambiguous &&
        (
          (clarifyRes.clarifying_questions && clarifyRes.clarifying_questions.length > 0) ||
          (clarifyRes.clarification_suggestions && clarifyRes.clarification_suggestions.length > 0)
        )
      ) {
        clarificationResult.value = clarifyRes
        showClarificationModal.value = true
        return { shouldIntercept: true as const }
      }
      return { shouldIntercept: false as const }
    } catch (err: any) {
      console.warn('大纲澄清失败，退回直接生成模式', err)
      return { shouldIntercept: false as const }
    } finally {
      isClarifyingOutline.value = false
    }
  }

  async function handleSubmitClarificationAnswers(
    answers: { questionId: string; answer: string }[],
    originalOutline: string,
    chapter: Chapter | null,
    apiConfig: { api_key: string; base_url: string; reasoning_model?: string; model?: string },
    onApply: (newOutlineText: string) => void | Promise<void>
  ) {
    if (!chapter) return

    isClarifyingOutline.value = true
    try {
      const userInstruction = answers.map(a => a.answer).join('\n')
      const previousIssues = clarificationResult.value?.identified_issues || []

      const clarifyRes = await generateApi.clarifyOutline({
        chapter_id: chapter.id,
        ambiguous_text: chapter.outline_text?.trim() || '',
        api_key: apiConfig.api_key,
        base_url: apiConfig.base_url,
        model: apiConfig.reasoning_model || apiConfig.model || 'gpt-4o-mini',
        author_intent: chapter.author_intent,
        user_instruction: userInstruction,
        previous_issues: previousIssues
      })

      clarificationResult.value = clarifyRes

      if (!clarifyRes.refined_text?.trim()) {
        await onApply(originalOutline)
      }
      // 如果返回了 refined_text，保持弹窗打开让用户看到修正后的大纲
    } catch (err: any) {
      console.warn('第二轮澄清请求失败，使用原始大纲', err)
      await onApply(originalOutline)
    } finally {
      isClarifyingOutline.value = false
    }
  }

  return {
    isClarifyingOutline,
    clarificationResult,
    showClarificationModal,
    closeClarificationModal,
    checkOutlineClarification,
    handleSubmitClarificationAnswers
  }
}
