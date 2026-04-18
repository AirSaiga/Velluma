import { ref, computed, watch } from 'vue'
import { bookApi, characterApi, chapterApi, relationshipApi } from '../../../services/api'
import { loadUiPrefs, type UiPrefs } from '../../../composables/useUiPrefs'
import type { Book, Chapter, Character, Relationship, ApiConfig } from '../../../types'

const CURRENT_BOOK_STORAGE_KEY = 'velluma_current_book_id'

export function useAppState() {
  const books = ref<Book[]>([])
  const currentBookId = ref<string | null>(null)
  const selectedChapterId = ref<string | null>(null)
  const characters = ref<Character[]>([])
  const chapters = ref<Chapter[]>([])
  const relationships = ref<Relationship[]>([])
  const apiConfig = ref<ApiConfig>({
    api_key: '',
    base_url: '',
    model: 'google/gemini-2.0-flash-001',
    reasoning_model: '',
    creative_model: '',
    proxy_enabled: true,
    proxy_url: ''
  })
  const uiPrefs = ref<UiPrefs>(loadUiPrefs())
  const loading = ref(false)

  const sortedChapters = computed<Chapter[]>(() => {
    return [...chapters.value].sort((a, b) => a.chapter_number - b.chapter_number)
  })

  const currentBook = computed<Book | null>(() => {
    return books.value.find((b) => b.id === currentBookId.value) || null
  })

  const selectedChapter = computed<Chapter | null>(() => {
    return chapters.value.find((c) => c.id === selectedChapterId.value) || null
  })

  async function loadBooks() {
    try {
      books.value = await bookApi.getAll()
      if (books.value.length === 0) {
        currentBookId.value = null
        return
      }

      const savedBookId = localStorage.getItem(CURRENT_BOOK_STORAGE_KEY)
      const hasSavedBook = !!savedBookId && books.value.some(book => book.id === savedBookId)
      const nextBookId = hasSavedBook ? savedBookId : books.value[0].id

      if (currentBookId.value !== nextBookId) {
        currentBookId.value = nextBookId
      }
    } catch (error: any) {
      console.error('加载书籍失败:', error)
    }
  }

  async function loadCurrentBookData() {
    if (!currentBookId.value) {
      characters.value = []
      chapters.value = []
      relationships.value = []
      selectedChapterId.value = null
      return
    }

    loading.value = true
    try {
      const [chars, chaps, rels] = await Promise.all([
        characterApi.getAll(currentBookId.value),
        chapterApi.getAll(currentBookId.value),
        relationshipApi.getAll(currentBookId.value)
      ])
      characters.value = chars
      relationships.value = rels

      const chaptersWithEntities = await Promise.all(
        chaps.map(async (chapter: Chapter) => {
          try {
            const entityData = await chapterApi.getEntities(chapter.id)
            return { ...chapter, character_ids: entityData.entity_ids || [] }
          } catch {
            return { ...chapter, character_ids: [] }
          }
        })
      )
      chapters.value = chaptersWithEntities
      selectedChapterId.value = chaptersWithEntities.length > 0
        ? [...chaptersWithEntities].sort((a, b) => a.chapter_number - b.chapter_number)[0].id
        : null
    } catch (error: any) {
      console.error('加载数据失败:', error)
    } finally {
      loading.value = false
    }
  }

  watch(chapters, (list) => {
    if (list.length === 0) {
      selectedChapterId.value = null
      return
    }
    const hasSelected = !!selectedChapterId.value && list.some((c) => c.id === selectedChapterId.value)
    if (!hasSelected) {
      selectedChapterId.value = sortedChapters.value[0].id
    }
  }, { deep: true })

  watch(currentBookId, (newBookId) => {
    if (newBookId) {
      localStorage.setItem(CURRENT_BOOK_STORAGE_KEY, newBookId)
    } else {
      localStorage.removeItem(CURRENT_BOOK_STORAGE_KEY)
    }
    loadCurrentBookData()
  })

  function updateApiConfig(data: Partial<ApiConfig>) {
    apiConfig.value = { ...apiConfig.value, ...data }
    localStorage.setItem('velluma_api_config', JSON.stringify(apiConfig.value))
  }

  return {
    books,
    currentBookId,
    selectedChapterId,
    characters,
    chapters,
    relationships,
    apiConfig,
    uiPrefs,
    loading,
    sortedChapters,
    currentBook,
    selectedChapter,
    loadBooks,
    loadCurrentBookData,
    updateApiConfig
  }
}
