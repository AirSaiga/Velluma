import { ref, watch } from 'vue'
import { assetApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import type { Chapter } from '../../../types'

export function useChapterAssets() {
  const { showToast } = useToast()

  const selectedAssetIds = ref<string[]>([])

  async function toggleAsset(chapter: Chapter | null, assetId: string) {
    if (!chapter) return
    const ids = [...selectedAssetIds.value]
    const index = ids.indexOf(assetId)
    if (index === -1) {
      ids.push(assetId)
    } else {
      ids.splice(index, 1)
    }
    selectedAssetIds.value = ids

    try {
      await assetApi.updateChapterAssets(chapter.id, ids)
      showToast('章节关键道具更新成功', 'success')
    } catch (err: any) {
      showToast('章节关键道具更新失败: ' + err.message, 'error')
      // 失败回滚
      const oldIndex = selectedAssetIds.value.indexOf(assetId)
      if (oldIndex === -1) {
        selectedAssetIds.value.push(assetId)
      } else {
        selectedAssetIds.value.splice(oldIndex, 1)
      }
    }
  }

  function isAssetSelected(assetId: string) {
    return selectedAssetIds.value.includes(assetId)
  }

  function resetAssets() {
    selectedAssetIds.value = []
  }

  function watchChapterAssets(selectedChapterRef: () => Chapter | null) {
    return watch(
      selectedChapterRef,
      async (newChapter, oldChapter) => {
        if (newChapter?.id !== oldChapter?.id) {
          if (newChapter) {
            try {
              const assets = await assetApi.getChapterAssets(newChapter.id)
              selectedAssetIds.value = assets.map(a => a.asset_id)
            } catch (err) {
              console.error('Failed to load chapter assets:', err)
              selectedAssetIds.value = []
            }
          } else {
            selectedAssetIds.value = []
          }
        }
      },
      { immediate: true }
    )
  }

  return {
    selectedAssetIds,
    toggleAsset,
    isAssetSelected,
    resetAssets,
    watchChapterAssets
  }
}
