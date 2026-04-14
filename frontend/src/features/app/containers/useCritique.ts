import { ref } from 'vue'
import { generateApi } from '../../../services/api'
import type { Chapter, ApiConfig } from '../../../types'

export function useCritique(options: {
  selectedChapter: { value: Chapter | null }
  apiConfig: { value: ApiConfig }
  showToast: (message: string, type?: string) => void
  setActiveFloatingTab: (tab: string | null) => void
  setRightPanelExpanded: (expanded: boolean) => void
}) {
  const { selectedChapter, apiConfig, showToast, setActiveFloatingTab, setRightPanelExpanded } = options

  const critiqueResult = ref<any>(null)
  const critiqueLoading = ref(false)

  async function handleRequestCritique(content: string) {
    if (!content) return
    if (content.length < 10) {
      showToast('章节内容太短，无法进行审阅（至少10个字）', 'warning')
      return
    }

    setActiveFloatingTab('critique')
    setRightPanelExpanded(true)
    critiqueLoading.value = true
    critiqueResult.value = null

    try {
      const result = await generateApi.critiqueChapter({
        chapter_content: content,
        chapter_title: selectedChapter.value?.title || '',
        api_key: apiConfig.value.api_key,
        base_url: apiConfig.value.base_url,
        model: apiConfig.value.reasoning_model || apiConfig.value.model
      })
      critiqueResult.value = result
    } catch (error: any) {
      showToast('获取指导失败: ' + (error.message || '未知错误'), 'error')
    } finally {
      critiqueLoading.value = false
    }
  }

  function handleJumpToCritique(comment: any) {
    // 由 AppContainer 通过 chapterEditorRef 处理
    // 这里仅作为占位，实际在 AppContainer 中保留 chapterEditorRef 调用
  }

  function handleCloseCritique() {
    critiqueResult.value = null
  }

  return {
    critiqueResult,
    critiqueLoading,
    handleRequestCritique,
    handleJumpToCritique,
    handleCloseCritique
  }
}
