import { ref } from 'vue'
import { chapterApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import type { Chapter } from '../../../types'

export function useChapterPublisher(
  emit: (event: 'update-chapter' | 'refresh-characters', ...args: any[]) => void
) {
  const { showToast } = useToast()
  const { show: showConfirm } = useConfirmDialog()

  const isPublishing = ref(false)
  const publishError = ref<string | null>(null)
  const showPublishModal = ref(false)
  const characterUpdates = ref<Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>>([])
  const characterExtraction = ref<any>(null)
  const chapterSummary = ref<string | null>(null)

  async function publishChapter(
    selectedChapter: Chapter | null,
    apiConfig: { api_key?: string; base_url?: string; reasoning_model?: string; model?: string; proxy_enabled?: boolean; proxy_url?: string }
  ) {
    if (!selectedChapter) return

    if (selectedChapter.status === 'published') {
      const ok = await showConfirm({
        title: '确认取消发布',
        message: '本章已发布，确定要取消发布吗？'
      })
      if (!ok) return
      try {
        isPublishing.value = true
        publishError.value = null
        await chapterApi.update(selectedChapter.id, { status: 'draft' })
        emit('update-chapter', selectedChapter.id, { status: 'draft' })
        showToast('已取消发布', 'success')
      } catch (err: any) {
        publishError.value = err.message
        showToast('取消发布失败: ' + err.message, 'error')
      } finally {
        isPublishing.value = false
      }
      return
    }

    if (!apiConfig.api_key) {
      showToast('请先在设置中配置 API Key 以启用角色动态状态更新功能', 'warning')
    }

    const ok = await showConfirm({
      title: '确认发布',
      message: '确定要发布本章吗？发布后将会自动更新涉及角色的动态状态。',
      warning: '发布后会自动分析章节内容并更新角色动态状态'
    })
    if (!ok) return

    try {
      isPublishing.value = true
      publishError.value = null
      const result = await chapterApi.publish(selectedChapter.id, {
        api_key: apiConfig.api_key || undefined,
        base_url: apiConfig.base_url || undefined,
        model: apiConfig.reasoning_model || apiConfig.model || 'gpt-4o-mini',
        proxy_enabled: apiConfig.proxy_enabled !== false,
        proxy_url: apiConfig.proxy_url || undefined
      })
      emit('update-chapter', selectedChapter.id, { status: 'published' })
      emit('refresh-characters')
      characterUpdates.value = result.character_updates || []
      characterExtraction.value = result.character_extraction || null
      if (result.summary) {
        chapterSummary.value = result.summary
        emit('update-chapter', selectedChapter.id, { summary: result.summary })
      }
      showPublishModal.value = true
    } catch (err: any) {
      publishError.value = err.message
      showToast('发布失败: ' + err.message, 'error')
    } finally {
      isPublishing.value = false
    }
  }

  function closePublishModal() {
    showPublishModal.value = false
    characterUpdates.value = []
    characterExtraction.value = null
    chapterSummary.value = null
  }

  function resetOnChapterChange() {
    characterUpdates.value = []
    characterExtraction.value = null
    chapterSummary.value = null
  }

  return {
    isPublishing,
    publishError,
    showPublishModal,
    characterUpdates,
    characterExtraction,
    chapterSummary,
    publishChapter,
    closePublishModal,
    resetOnChapterChange
  }
}
