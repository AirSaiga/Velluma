import { computed, ref, watch } from 'vue'
import { useToast } from '../../../composables/useToast'
import { chapterApi, generateApi } from '../../../services/api'
import { reviewApi, type CritiqueItem } from '../../../services/api/domain/review.api'
import type { ApiConfig, Chapter, Character } from '../../../types'
import { useChapterPublisher } from './useChapterPublisher'
import { useChapterAssets } from './useChapterAssets'

// V3.1 清理：旧双轨生成路径（startGenerate → 节拍预览弹窗 → 双轨 SSE）已移除。
// 章节生成统一由 generation 特性的 useGenerationSession（Inspector「本章」tab）驱动。
// 本容器只保留编辑器自身职责：内容编辑、发布、灵感、格式整理/选区优化、角色/资产勾选。
export interface ChapterEditorContainerProps {
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  metaCollapsed?: boolean
}

type ChapterEditorEmit = (event: 'update-chapter' | 'update-meta-collapsed' | 'refresh-characters' | 'editor-entity-focus', ...args: any[]) => void

export function useChapterEditorContainer(props: ChapterEditorContainerProps, emit: ChapterEditorEmit) {
  const { showToast } = useToast()

  const publisher = useChapterPublisher(emit)
  const assets = useChapterAssets()

  const chapterSummary = computed(() => publisher.chapterSummary.value)
  const isEditorDisabled = computed(() => publisher.isPublishing.value)
  const selectedChapter = computed(() => props.selectedChapter)

  function handleEditorEntityFocus(keyword: string) {
    emit('editor-entity-focus', keyword)
  }

  function updateChapter(updates: Record<string, any>) {
    if (!selectedChapter.value) return
    emit('update-chapter', selectedChapter.value.id, updates)
  }

  function handleTitleInput(e: Event) {
    const target = e.target as HTMLInputElement
    scheduleMetaUpdate({ title: target.value })
  }

  function handleAssetsSchemaInput(e: Event) {
    const target = e.target as HTMLTextAreaElement
    scheduleMetaUpdate({ chapter_assets_schema: target.value })
  }

  let metaUpdateTimeout: ReturnType<typeof setTimeout> | undefined
  function scheduleMetaUpdate(updates: Record<string, any>) {
    clearTimeout(metaUpdateTimeout)
    metaUpdateTimeout = setTimeout(() => {
      updateChapter(updates)
    }, 500)
  }

  // 保存状态反馈
  type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
  const saveStatus = ref<SaveStatus>('idle')
  const lastSavedAt = ref<Date | null>(null)

  const isFormatting = ref(false)
  const editorRef = ref<any>(null)
  function setEditorRef(editor: any) {
    editorRef.value = editor
  }

  /**
   * 滚动到指定字符偏移并临时高亮（V3.1 F4 审校问题点击定位）。
   * offset 来自审校 finding 的 [start, end] 字符偏移。
   */
  function scrollToOffset(offset: [number, number]) {
    if (!editorRef.value?.scrollToOffsetAndHighlight) return
    editorRef.value.scrollToOffsetAndHighlight(offset)
  }

  function toggleCharacter(charId: string) {
    if (!selectedChapter.value) return
    const chapterId = selectedChapter.value.id
    const currentIds = selectedChapter.value.character_ids || []
    const newCharacterIds = currentIds.includes(charId)
      ? currentIds.filter(id => id !== charId)
      : [...currentIds, charId]
    updateChapter({ character_ids: newCharacterIds })
    chapterApi.updateEntities(chapterId, newCharacterIds).catch(err => {
      console.error('更新章节角色关联失败:', err)
      // 失败不能静默：UI 勾选已变但实际未保存 → 提示 + 回滚勾选态
      showToast('更新章节角色关联失败：' + (err?.message || '未知错误'), 'error')
      if (selectedChapter.value?.id === chapterId) {
        updateChapter({ character_ids: currentIds })
      }
    })
  }

  let updateTimeout: ReturnType<typeof setTimeout> | undefined
  function handleContentUpdate(content: string) {
    clearTimeout(updateTimeout)
    updateTimeout = setTimeout(() => {
      updateChapter({ content_text: content, draft_text: content })
    }, 1000)
  }

  const localMetaCollapsed = ref(props.metaCollapsed ?? false)
  function toggleMetaCollapsed() {
    localMetaCollapsed.value = !localMetaCollapsed.value
    emit('update-meta-collapsed', localMetaCollapsed.value)
  }

  function getMetaCollapsedLabel() {
    return localMetaCollapsed.value ? '展开信息' : '收起信息'
  }

  function isCharacterSelected(charId: string) {
    return selectedChapter.value?.character_ids?.includes(charId) || false
  }

  const showInspirationModal = ref(false)
  const inspirationActiveCharacterIds = ref<string[]>([])

  function openInspirationModal() {
    if (!selectedChapter.value) return
    const charIds = props.characters
      .filter(char => selectedChapter.value?.character_ids?.includes(char.id))
      .map(char => char.id)
    inspirationActiveCharacterIds.value = charIds
    showInspirationModal.value = true
  }

  function closeInspirationModal() {
    showInspirationModal.value = false
  }

  // 章节审阅（POST /api/critique_chapter，毒舌编辑视角，纯文本无需 LLM Key 配置——走后端统一配置）
  const showCritiqueModal = ref(false)
  const critiqueLoading = ref(false)
  const critiqueComments = ref<CritiqueItem[]>([])
  const critiquePraise = ref('')

  async function openCritiqueModal() {
    const chapter = selectedChapter.value
    if (!chapter) return
    const content = (chapter.content_text || chapter.draft_text || '').trim()
    if (content.length < 10) {
      showToast('章节内容太少，无法审阅', 'warning')
      return
    }
    showCritiqueModal.value = true
    critiqueLoading.value = true
    critiqueComments.value = []
    critiquePraise.value = ''
    try {
      const result = await reviewApi.critiqueChapter(content, chapter.title || undefined)
      critiqueComments.value = result.comments || []
      critiquePraise.value = result.overall_praise || ''
    } catch (e: any) {
      console.error('章节审阅失败:', e)
      showCritiqueModal.value = false
      showToast('审阅失败：' + (e?.message || '未知错误'), 'error')
    } finally {
      critiqueLoading.value = false
    }
  }

  function closeCritiqueModal() {
    showCritiqueModal.value = false
  }

  function handleApplyInspirationToOutline(content: string) {
    if (!selectedChapter.value) return
    const currentOutline = selectedChapter.value.outline_text || ''
    const newOutline = currentOutline ? `${currentOutline}\n${content}` : content
    scheduleMetaUpdate({ outline_text: newOutline })
  }

  async function handlePartialOptimize(payload: { selection: any, instruction: string, mode?: string, tone?: string | null }) {
    if (!selectedChapter.value || !props.apiConfig.api_key) {
      showToast('请先配置 API Key', 'warning')
      return
    }

    isFormatting.value = true

    try {
      // CP4.1：透传 mode + tone 到后端（蓝图 §4.9）
      const requestBody: Record<string, any> = {
        chapter_id: selectedChapter.value.id,
        selected_text: payload.selection.text,
        context_before: payload.selection.contextBefore,
        context_after: payload.selection.contextAfter,
        user_instruction: payload.instruction,
        api_key: props.apiConfig.api_key,
        base_url: props.apiConfig.base_url,
        model: props.apiConfig.reasoning_model || props.apiConfig.model,
      }
      if (payload.mode) {
        requestBody.mode = payload.mode
      }
      if (payload.tone) {
        requestBody.tone = payload.tone
      }
      const { optimized_text } = await generateApi.optimizeSelection(requestBody)

      if (optimized_text && editorRef.value) {
        editorRef.value.applyOptimizationDiff(optimized_text)
        showToast('优化生成完成，请确认', 'success')
      } else {
        editorRef.value.resetOptimization()
        showToast('优化未返回有效结果', 'warning')
      }
    } catch (e: any) {
      console.error('Optimization failed', e)
      showToast('优化失败: ' + e.message, 'error')
      if (editorRef.value) {
        editorRef.value.resetOptimization()
      }
    } finally {
      isFormatting.value = false
    }
  }

  async function handleFormatText(payload: string | { text: string; selection?: { from: number; to: number } }) {
    const text = typeof payload === 'string' ? payload : payload.text
    const selection = typeof payload === 'string' ? undefined : payload.selection

    if (isFormatting.value || !text) return

    try {
      if (!props.apiConfig.api_key) {
        showToast('请先在设置中配置 API Key 以使用智能格式整理功能', 'warning')
        return
      }

      isFormatting.value = true
      const { formatted_text } = await generateApi.formatText({
        text,
      })

      if (formatted_text && editorRef.value) {
        const paragraphs = formatted_text
          .split(/\r?\n/)
          .filter((line: string) => line.trim().length > 0)

        const jsonContent = {
          type: 'doc',
          content: paragraphs.map((text: string) => ({
            type: 'paragraph',
            content: [{ type: 'text', text: text.trim() }]
          }))
        }

        if (selection) {
          editorRef.value.editor.commands.setTextSelection(selection)
          editorRef.value.editor.commands.insertContent(jsonContent)
        } else {
          editorRef.value.editor.commands.setContent(jsonContent)
        }
      }
    } catch (e: any) {
      console.error('Format text failed', e)
      showToast('格式整理失败: ' + e.message, 'error')
    } finally {
      isFormatting.value = false
    }
  }

  watch(
    () => props.selectedChapter,
    async (newChapter, oldChapter) => {
      if (newChapter?.id !== oldChapter?.id) {
        publisher.resetOnChapterChange()
      }
    }
  )

  assets.watchChapterAssets(() => props.selectedChapter)

  return {
    toggleAsset: (assetId: string) => assets.toggleAsset(props.selectedChapter, assetId),
    isAssetSelected: assets.isAssetSelected,
    chapterSummary,
    characterUpdates: publisher.characterUpdates,
    characterExtraction: publisher.characterExtraction,
    closePublishModal: publisher.closePublishModal,
    handleContentUpdate,
    handleEditorEntityFocus,
    handleFormatText,
    handlePartialOptimize,
    handleAssetsSchemaInput,
    handleTitleInput,
    inspirationActiveCharacterIds,
    isCharacterSelected,
    isEditorDisabled,
    isFormatting,
    isPublishing: publisher.isPublishing,
    localMetaCollapsed,
    openInspirationModal,
    showCritiqueModal,
    critiqueLoading,
    critiqueComments,
    critiquePraise,
    openCritiqueModal,
    closeCritiqueModal,
    anchorPov: ref<string | null>(null),
    publishChapter: () => publisher.publishChapter(props.selectedChapter, props.apiConfig),
    selectedChapter,
    setEditorRef,
    scrollToOffset,
    showInspirationModal,
    showPublishModal: publisher.showPublishModal,
    toggleCharacter,
    toggleMetaCollapsed,
    getMetaCollapsedLabel,
    handleApplyInspirationToOutline,
    closeInspirationModal,
    saveStatus,
    lastSavedAt,
  }
}
