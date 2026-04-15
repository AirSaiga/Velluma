import { chapterApi } from '../../../services/api'
import type { Chapter } from '../../../types'

export function useChapterManager(options: {
  currentBookId: { value: string | null }
  chapters: { value: Chapter[] }
  selectedChapterId: { value: string | null }
  sortedChapters: { value: Chapter[] }
  showToast: (message: string, type?: string) => void
  showConfirm: (options: { title: string; message: string; warning?: string }) => Promise<boolean>
}) {
  const { currentBookId, chapters, selectedChapterId, sortedChapters, showToast, showConfirm } = options

  async function createChapter(data: Partial<Chapter>) {
    if (!currentBookId.value) {
      showToast('请先创建或选择一本书籍', 'warning')
      return
    }
    try {
      const newChapter = await chapterApi.create({
        ...data,
        book_id: currentBookId.value
      })
      chapters.value.push(newChapter)
      selectedChapterId.value = newChapter.id
      return newChapter
    } catch (error: any) {
      showToast('创建失败: ' + error.message, 'error')
    }
  }

  async function createChapterFromOutlinePanel() {
    const maxNumber = chapters.value.length > 0
      ? Math.max(...chapters.value.map(c => c.chapter_number))
      : 0
    await createChapter({
      chapter_number: maxNumber + 1,
      chapter_name: `第${maxNumber + 1}章`,
      title: '',
      outline_text: '',
      content_text: '',
      status: 'draft'
    })
  }

  async function updateChapter(id: string, data: any) {
    let retries = 3
    while (retries >= 0) {
      try {
        const { character_ids, ...chapterData } = data

        if (Object.keys(chapterData).length > 0) {
          const updated = await chapterApi.update(id, chapterData)
          const index = chapters.value.findIndex(c => c.id === id)
          if (index !== -1) {
            chapters.value[index] = { ...chapters.value[index], ...updated }
          }
        }

        if (character_ids !== undefined) {
          await chapterApi.updateEntities(id, character_ids)
          const index = chapters.value.findIndex(c => c.id === id)
          if (index !== -1) {
            chapters.value[index].character_ids = character_ids
          }
        }
        break
      } catch (error: any) {
        const isNetworkError = error.message.includes('Failed to fetch') || error.message.toLowerCase().includes('network error')
        if (isNetworkError && retries > 0) {
          console.warn(`更新失败，正在重试 (${retries}次剩余)...`, error)
          retries--
          await new Promise(resolve => setTimeout(resolve, 1000))
          continue
        }

        showToast('更新失败: ' + error.message, 'error')
        break
      }
    }
  }

  async function deleteChapter(id: string) {
    const target = chapters.value.find((c) => c.id === id)
    const ok = await showConfirm({ title: '确认删除', message: `确定要删除"${target?.title || '该章节'}"吗？` })
    if (!ok) return
    try {
      await chapterApi.delete(id)
      chapters.value = chapters.value.filter(c => c.id !== id)
      if (selectedChapterId.value === id) {
        selectedChapterId.value = sortedChapters.value[0]?.id || null
      }
    } catch (error: any) {
      showToast('删除失败: ' + error.message, 'error')
    }
  }

  async function generateChapterEmbedding(id: string) {
    const target = chapters.value.find((c) => c.id === id)
    if (!target?.summary) {
      showToast('该章节暂无摘要，请先发布章节生成摘要', 'warning')
      return
    }
    try {
      const result = await chapterApi.generateEmbedding(id)
      showToast(`向量生成成功！维度: ${result.vector_dim}`, 'success')
    } catch (error: any) {
      showToast('生成失败: ' + error.message, 'error')
    }
  }

  return {
    createChapter,
    createChapterFromOutlinePanel,
    updateChapter,
    deleteChapter,
    generateChapterEmbedding
  }
}
