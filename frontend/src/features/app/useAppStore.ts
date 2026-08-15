/**
 * 全局应用状态 store（V3.1 F1 新建）。
 *
 * 职责：聚合 useAppState + useBookManager + useChapterManager + useCharacterManager，
 * 通过 provide/inject 在整个应用共享，替代 AppContainer 内部多层 props 透传。
 *
 * 设计依据：规格 §11.1 "维持 composables（不引 Pinia），但约定会话单例 composable + 视图局部状态两层"。
 * 本 store 是"会话单例"——书籍/章节/角色列表等跨视图共享状态集中在这里；
 * 视图局部状态（如 Inspector 当前 tab、生成流程步骤）留在各视图自己的 composable。
 *
 * 使用方式：
 *   // AppShell 顶层 provide
 *   const store = useAppStore()
 *   provide(APP_STORE_KEY, store)
 *
 *   // 任意子组件 inject
 *   const store = inject(APP_STORE_KEY)!
 *   store.selectBook(bookId)
 */
import { ref, computed, provide, inject, type InjectionKey, type Ref, type ComputedRef } from 'vue'
import { bookApi, chapterApi, characterApi, relationshipApi } from '../../services/api'
import { worldApi } from '../../services/api/domain/world.api'
import { loadUiPrefs, saveUiPrefs, type UiPrefs } from '../../composables/useUiPrefs'
import type { Book, Chapter, Character, Relationship, ApiConfig } from '../../types'

// ============================================================
// 世界页数据源适配（M4：world 优先 / 旧表兜底，读时映射）
// 把 world 实体映射成旧 Character 形状塞进 store.characters——canon 高亮 /
// InspectorPanel / 灵感弹窗等下游零改动。世界页无实体返回 null（走旧表）。
// ============================================================
const _WORLD_PROFILE_FIELDS: Array<[string, string]> = [
  ['appearance', '外貌'],
  ['personality', '性格'],
  ['speech_style', '语言习惯'],
  ['goal', '目标'],
  ['background', '背景'],
]

function _worldStaticPrompt(entity: any): string {
  const props = entity?.props || {}
  const parts: string[] = []
  for (const [key, label] of _WORLD_PROFILE_FIELDS) {
    const v = String(props[key] || '').trim()
    if (v) parts.push(`${label}：${v}`)
  }
  const legacy = String(props.legacy_profile || '').trim()
  if (legacy) parts.push(legacy)
  return parts.join('\n')
}

async function _loadWorldCast(bookId: string): Promise<{ chars: any[]; rels: any[] } | null> {
  try {
    const ents = await worldApi.listEntities(bookId)
    if (!ents || ents.length === 0) return null
    const chars = ents
      .filter((e: any) => e.entity_type === 'character')
      .map((e: any) => ({
        id: e.id,
        name: e.name,
        aliases: e.aliases || [],
        importance_level: Math.max(1, Math.min(4, Math.ceil((e.importance || 1) / 2.5))),
        static_prompt: _worldStaticPrompt(e),
        dynamic_state: '',
        current_state: '',
        _world_sourced: true,
      }))
    const rels = await worldApi
      .listRelations(bookId)
      .then((list: any[]) => (list || []).map((r: any) => ({ ...r, _world_sourced: true })))
      .catch(() => [])
    return { chars, rels }
  } catch {
    return null // 世界页不可用/未迁移 → 旧表兜底
  }
}

const CURRENT_BOOK_STORAGE_KEY = 'velluma_current_book_id'

export interface AppStore {
  // 列表状态
  books: Ref<Book[]>
  chapters: Ref<Chapter[]>
  characters: Ref<Character[]>
  relationships: Ref<Relationship[]>
  // 当前选中
  currentBookId: Ref<string | null>
  selectedChapterId: Ref<string | null>
  currentBook: ComputedRef<Book | null>
  selectedChapter: ComputedRef<Chapter | null>
  sortedChapters: ComputedRef<Chapter[]>
  // 配置
  apiConfig: Ref<ApiConfig>
  uiPrefs: Ref<UiPrefs>
  loading: Ref<boolean>
  // 数据加载
  loadBooks: () => Promise<void>
  loadCurrentBookData: () => Promise<void>
  selectBook: (bookId: string | null) => void
  selectChapter: (chapterId: string | null) => void
  // 书籍管理
  createBook: (data: Partial<Book>) => Promise<Book | undefined>
  /** 按指定 id 更新书籍；若 id 为当前书则同步当前书状态 */
  updateBook: (bookId: string, data: Partial<Book>) => Promise<Book | undefined>
  deleteBook: (bookId: string) => Promise<void>
  // 章节管理
  createChapter: (data: Partial<Chapter>) => Promise<Chapter | undefined>
  updateChapter: (id: string, data: Partial<Chapter> & { character_ids?: string[] }) => Promise<void>
  deleteChapter: (id: string) => Promise<void>
  // 角色管理
  refreshCharacters: () => Promise<void>
  updateApiConfig: (data: Partial<ApiConfig>) => void
  updateUiPrefs: (partial: Partial<UiPrefs>) => void
}

export const APP_STORE_KEY: InjectionKey<AppStore> = Symbol('AppStore')

export function provideAppStore(): AppStore {
  const store = createAppStore()
  provide(APP_STORE_KEY, store)
  return store
}

export function useAppStore(): AppStore {
  const store = inject(APP_STORE_KEY)
  if (!store) {
    throw new Error('useAppStore 必须在 provideAppStore 之后调用（AppShell 内）')
  }
  return store
}

function createAppStore(): AppStore {
  const books = ref<Book[]>([])
  const currentBookId = ref<string | null>(null)
  const selectedChapterId = ref<string | null>(null)
  const characters = ref<Character[]>([])
  const chapters = ref<Chapter[]>([])
  const relationships = ref<Relationship[]>([])
  const apiConfig = ref<ApiConfig>(loadApiConfig())
  const uiPrefs = ref<UiPrefs>(loadUiPrefs())
  const loading = ref(false)

  const sortedChapters = computed<Chapter[]>(() =>
    [...chapters.value].sort((a, b) => a.chapter_number - b.chapter_number)
  )

  const currentBook = computed<Book | null>(() =>
    books.value.find((b) => b.id === currentBookId.value) || null
  )

  const selectedChapter = computed<Chapter | null>(() =>
    chapters.value.find((c) => c.id === selectedChapterId.value) || null
  )

  async function loadBooks() {
    try {
      books.value = await bookApi.getAll()
      if (books.value.length === 0) {
        currentBookId.value = null
        return
      }
      const savedBookId = localStorage.getItem(CURRENT_BOOK_STORAGE_KEY)
      const hasSavedBook = !!savedBookId && books.value.some((b) => b.id === savedBookId)
      const nextBookId = hasSavedBook ? savedBookId : books.value[0].id
      if (currentBookId.value !== nextBookId) {
        currentBookId.value = nextBookId
      }
      // 关键：设置 currentBookId 后必须加载该书数据（角色/章节/关系）。
      // 之前缺失此调用，导致直接打开 Bible 等视图时列表为空
      // （loadCurrentBookData 仅在 selectBook 切书时触发，同书场景不会走 selectBook）。
      await loadCurrentBookData()
    } catch (error) {
      console.error('[AppStore] 加载书籍失败:', error)
      // rethrow：调用方（AppShell/LibraryView 等）需感知失败弹提示——
      // 此前静默吞掉，用户把「加载失败」误判为「数据丢失（空书架）」
      throw error
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
      // 世界页优先（读时适配）；无世界数据 → 旧表（未迁移书行为不变）
      const worldCast = await _loadWorldCast(currentBookId.value)
      const [chars, chaps, rels] = await Promise.all([
        worldCast ? Promise.resolve(worldCast.chars) : characterApi.getAll(currentBookId.value),
        chapterApi.getAll(currentBookId.value),
        worldCast ? Promise.resolve(worldCast.rels) : relationshipApi.getAll(currentBookId.value),
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
      // 仅在未选中时默认选第一章（避免覆盖外部主动选择）
      if (!selectedChapterId.value || !chaptersWithEntities.some(c => c.id === selectedChapterId.value)) {
        selectedChapterId.value = chaptersWithEntities.length > 0
          ? [...chaptersWithEntities].sort((a, b) => a.chapter_number - b.chapter_number)[0].id
          : null
      }
    } catch (error) {
      console.error('[AppStore] 加载数据失败:', error)
      throw error  // 见 loadBooks：加载失败必须让调用方可感知
    } finally {
      loading.value = false
    }
  }

  function selectBook(bookId: string | null) {
    if (currentBookId.value === bookId) return
    currentBookId.value = bookId
    selectedChapterId.value = null
    if (bookId) {
      localStorage.setItem(CURRENT_BOOK_STORAGE_KEY, bookId)
    } else {
      localStorage.removeItem(CURRENT_BOOK_STORAGE_KEY)
    }
    loadCurrentBookData()
  }

  function selectChapter(chapterId: string | null) {
    selectedChapterId.value = chapterId
  }

  async function createBook(data: Partial<Book>) {
    try {
      const newBook = await bookApi.create(data as any)
      books.value.push(newBook)
      selectBook(newBook.id)
      return newBook
    } catch (error: any) {
      console.error('[AppStore] 创建书籍失败:', error)
      throw error
    }
  }

  async function updateBook(bookId: string, data: Partial<Book>) {
    if (!bookId) return
    try {
      const updated = await bookApi.update(bookId, data)
      // currentBook 由 books 派生，更新列表项即同步当前书状态
      const idx = books.value.findIndex((b) => b.id === bookId)
      if (idx !== -1) books.value[idx] = updated
      return updated
    } catch (error) {
      console.error('[AppStore] 更新书籍失败:', error)
      throw error
    }
  }

  async function deleteBook(bookId: string) {
    try {
      await bookApi.delete(bookId)
      books.value = books.value.filter((b) => b.id !== bookId)
      if (currentBookId.value === bookId) {
        selectBook(books.value[0]?.id ?? null)
      }
    } catch (error) {
      console.error('[AppStore] 删除书籍失败:', error)
      throw error
    }
  }

  async function createChapter(data: Partial<Chapter>) {
    if (!currentBookId.value) return
    try {
      const newChapter = await chapterApi.create({ ...data, book_id: currentBookId.value } as any)
      chapters.value.push(newChapter)
      selectedChapterId.value = newChapter.id
      return newChapter
    } catch (error: any) {
      console.error('[AppStore] 创建章节失败:', error)
      throw error
    }
  }

  async function updateChapter(id: string, data: Partial<Chapter> & { character_ids?: string[] }) {
    const { character_ids, ...chapterData } = data
    if (Object.keys(chapterData).length > 0) {
      const updated = await chapterApi.update(id, chapterData as any)
      const idx = chapters.value.findIndex((c) => c.id === id)
      if (idx !== -1) chapters.value[idx] = { ...chapters.value[idx], ...updated }
    }
    if (character_ids !== undefined) {
      await chapterApi.updateEntities(id, character_ids)
      const idx = chapters.value.findIndex((c) => c.id === id)
      if (idx !== -1) chapters.value[idx].character_ids = character_ids
    }
  }

  async function deleteChapter(id: string) {
    await chapterApi.delete(id)
    chapters.value = chapters.value.filter((c) => c.id !== id)
    if (selectedChapterId.value === id) {
      selectedChapterId.value = sortedChapters.value[0]?.id ?? null
    }
  }

  async function refreshCharacters() {
    if (!currentBookId.value) return
    try {
      const worldCast = await _loadWorldCast(currentBookId.value)
      characters.value = worldCast ? worldCast.chars : await characterApi.getAll(currentBookId.value)
    } catch (error) {
      console.error('[AppStore] 加载角色失败:', error)
      throw error  // 调用方（WorkspaceView）toast 提示
    }
  }

  function updateApiConfig(data: Partial<ApiConfig>) {
    apiConfig.value = { ...apiConfig.value, ...data }
    localStorage.setItem('velluma_api_config', JSON.stringify(apiConfig.value))
  }

  function updateUiPrefs(partial: Partial<UiPrefs>) {
    uiPrefs.value = { ...uiPrefs.value, ...partial }
    saveUiPrefs(uiPrefs.value)
  }

  return {
    books, chapters, characters, relationships,
    currentBookId, selectedChapterId, currentBook, selectedChapter, sortedChapters,
    apiConfig, uiPrefs, loading,
    loadBooks, loadCurrentBookData, selectBook, selectChapter,
    createBook, updateBook, deleteBook,
    createChapter, updateChapter, deleteChapter,
    refreshCharacters, updateApiConfig, updateUiPrefs,
  }
}

function loadApiConfig(): ApiConfig {
  try {
    const saved = localStorage.getItem('velluma_api_config')
    if (saved) return JSON.parse(saved)
  } catch {
    // 忽略解析失败
  }
  return {
    api_key: '',
    base_url: '',
    model: 'google/gemini-2.0-flash-001',
    reasoning_model: '',
    creative_model: '',
    proxy_enabled: true,
    proxy_url: '',
  }
}
