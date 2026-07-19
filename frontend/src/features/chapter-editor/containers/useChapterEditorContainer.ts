import { computed, ref, watch } from 'vue'
import { useChapterGenerator } from '../../../composables/useChapterGenerator'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { chapterApi, generateApi } from '../../../services/api'
import type { ApiConfig, Chapter, Character, GenerateChapterAgenticPayloadWithBeats, BeatEditorItem } from '../../../types'
import { useIntentDrivenConfig, buildAgenticPayloadFromIntent } from '../../intent-driven/useIntentDrivenConfig'
import { useBeatPreview } from './useBeatPreview'
import { useOutlineClarification } from './useOutlineClarification'
import { useChapterPublisher } from './useChapterPublisher'
import { useChapterAssets } from './useChapterAssets'

export interface ChapterEditorContainerProps {
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  metaCollapsed?: boolean
  // CP4.5：skip_plan_gate 兼容开关已移除
}

type ChapterEditorEmit = (event: 'update-chapter' | 'update-meta-collapsed' | 'refresh-characters' | 'editor-entity-focus' | 'request-critique' | 'intent-generate' | 'intent-save', ...args: any[]) => void

export function useChapterEditorContainer(props: ChapterEditorContainerProps, emit: ChapterEditorEmit) {
  const { isGenerating, generatedText, error, workflowState, startAgenticGeneration, optimizeChapter, reset, cancelGeneration } = useChapterGenerator()
  const { showToast } = useToast()
  const { show: showConfirm } = useConfirmDialog()
  const { reset: resetIntentDrivenConfig, wordCount: intentWordCount } = useIntentDrivenConfig()

  const beatPreview = useBeatPreview()
  const outlineClarification = useOutlineClarification()
  const publisher = useChapterPublisher(emit)
  const assets = useChapterAssets()

  const showAgenticSettingsModal = ref(false)
  const chapterSummary = computed(() => publisher.chapterSummary.value)

  // 生成完成提示弹窗状态
  const showCompletionModal = ref(false)
  const completionMessage = ref('')
  const completionTitle = ref('')

  const isStreamMode = ref(true)
  const isAgenticMode = ref(true)
  const formError = ref('')

  // 保存状态反馈
  type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
  const saveStatus = ref<SaveStatus>('idle')
  const lastSavedAt = ref<Date | null>(null)
  let saveStatusTimer: ReturnType<typeof setTimeout> | undefined

  const isEditorDisabled = computed(() => isGenerating.value || publisher.isPublishing.value || beatPreview.beatPreviewLoading.value || outlineClarification.isClarifyingOutline.value)
  const isLoadingOverlay = computed(() => (isGenerating.value && isAgenticMode.value) || beatPreview.beatPreviewLoading.value || publisher.isPublishing.value || outlineClarification.isClarifyingOutline.value)
  const selectedChapter = computed(() => props.selectedChapter)

  function openCompletionModal(title: string, message: string) {
    completionTitle.value = title
    completionMessage.value = message
    showCompletionModal.value = true
  }

  function closeCompletionModal() {
    showCompletionModal.value = false
    completionMessage.value = ''
    completionTitle.value = ''
  }

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

  function handleOutlineInput(e: Event) {
    const target = e.target as HTMLTextAreaElement
    scheduleMetaUpdate({ outline_text: target.value })
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

  async function handleApplyClarification(newOutlineText: string) {
    updateChapter({ outline_text: newOutlineText })
    outlineClarification.closeClarificationModal()

    if (beatPreview.pendingAgenticPayload.value) {
      await beatPreview.previewBeatsForReview(
        beatPreview.pendingAgenticPayload.value,
        beatPreview.pendingClearEditorOnConfirm.value
      )
    }
  }

  function openAgenticSettingsModal() {
    if (!isAgenticMode.value || isGenerating.value) return
    showAgenticSettingsModal.value = true
  }

  function closeAgenticSettingsModal() {
    showAgenticSettingsModal.value = false
  }

  function resetAgenticSettings() {
    resetIntentDrivenConfig()
  }

  const isFormatting = ref(false)
  const editorRef = ref<any>(null)
  function setEditorRef(editor: any) {
    editorRef.value = editor
  }

  function scrollToCritique(comment: any) {
    if (!editorRef.value || !comment) return
    if (comment.exact_quote && editorRef.value.scrollToCritiqueByQuote) {
      editorRef.value.scrollToCritiqueByQuote(comment.exact_quote)
    } else {
      const commentId = comment.id || comment._id
      if (commentId && editorRef.value.scrollToCritiqueById) {
        editorRef.value.scrollToCritiqueById(commentId)
      }
    }
  }

  function syncGeneratedContentToChapter() {
    const html = editorRef.value?.editor?.getHTML?.()
    if (!html || typeof html !== 'string') return
    updateChapter({ content_text: html, draft_text: html })
  }

  let generateStartTime = 0
  function getDurationText() {
    const duration = (Date.now() - generateStartTime) / 1000
    return `耗时 ${duration.toFixed(1)} 秒`
  }

  async function confirmBeatsAndGenerate() {
    const payloadBase = beatPreview.buildConfirmedBeatsPayload()
    if (!payloadBase) {
      showToast('当前没有可用节拍，请重新生成', 'warning')
      return
    }
    if (beatPreview.pendingClearEditorOnConfirm.value && editorRef.value) {
      editorRef.value.clearContent()
    }
    const payload: GenerateChapterAgenticPayloadWithBeats = {
      ...beatPreview.pendingAgenticPayload.value!,
      beats: payloadBase.beats
    }

    const savedPayload: GenerateChapterAgenticPayloadWithBeats = { ...payload }

    // CP2.5b：合并闸门——先调 plan/confirm 写入 DB（status=confirmed）
    // CP4.5：skip_plan_gate 兼容开关已移除，confirm 为必经路径
    // 后端 /generate-chapter 硬要求 chapter_card.status=confirmed
    const confirmOk = await beatPreview.confirmPlan()
    if (!confirmOk) {
      showToast('章节卡确认失败，已中止生成', 'error')
      return
    }

    beatPreview.closeBeatReviewModal()
    reset()
    formError.value = ''
    generateStartTime = Date.now()

    const chapterId = savedPayload.chapter_id || selectedChapter.value?.id
    if (!chapterId) {
      showToast('章节 ID 缺失，请重试', 'error')
      return
    }

    const dualTrackPayload = {
      ...savedPayload,
      chapter_id: chapterId,
      beats: savedPayload.beats || []
    }

    startAgenticGeneration(dualTrackPayload, {
      onEvent: (event, data) => {
        console.log('[Workflow Event]', event, data)
        if (event === 'DONE' && data.debug_history && (window as any).electronAPI) {
          (window as any).electronAPI.send('prompt-data', data.debug_history)
        }
      },
      onChunk: (chunk) => {
        if (editorRef.value) {
          editorRef.value.insertContent(chunk)
        }
      },
      onComplete: (result) => {
        if (editorRef.value) {
          editorRef.value.flushBuffer()
        }
        if (result.text) {
          if (editorRef.value) {
            editorRef.value.clearContent()
            editorRef.value.insertContent(result.text)
          }
        }
        syncGeneratedContentToChapter()
        const durationText = getDurationText()
        const metrics = result?.metrics
        const topStages = Array.isArray(metrics?.top_stage_seconds) ? metrics.top_stage_seconds.slice(0, 3) : []
        const aggregateStages = Array.isArray(metrics?.aggregate_stage_seconds) ? metrics.aggregate_stage_seconds.slice(0, 2) : []
        const topStageText = topStages.length
          ? `；墙钟主要耗时：${topStages.map((item: any) => `${item.stage} ${Number(item.seconds || 0).toFixed(1)}s`).join('，')}`
          : ''
        const aggregateStageText = aggregateStages.length
          ? `；并发累计：${aggregateStages.map((item: any) => `${item.stage} ${Number(item.seconds || 0).toFixed(1)}s`).join('，')}`
          : ''
        const llmCalls = Number(metrics?.llm?.calls || 0)
        const llmFailures = Number(metrics?.llm?.failures || 0)
        const llmText = llmCalls > 0 ? `；LLM调用 ${llmCalls} 次（失败 ${llmFailures} 次）` : ''
        const revisionCount = result.revision_count ?? result.iterations ?? 0
        const statusMsg = result.passed
          ? `本章正文生成完成！审查通过，共重写 ${revisionCount} 次 (${durationText}${topStageText}${aggregateStageText}${llmText})`
          : `本章正文生成完成！已达成最大迭代次数，共重写 ${revisionCount} 次 (${durationText}${topStageText}${aggregateStageText}${llmText})`
        openCompletionModal('生成完成', statusMsg)
      }
    }, `/chapters/${chapterId}/generate-chapter`)
  }

  function toggleCharacter(charId: string) {
    if (!selectedChapter.value) return
    const currentIds = selectedChapter.value.character_ids || []
    const newCharacterIds = currentIds.includes(charId)
      ? currentIds.filter(id => id !== charId)
      : [...currentIds, charId]
    updateChapter({ character_ids: newCharacterIds })
    chapterApi.updateEntities(selectedChapter.value.id, newCharacterIds).catch(err => {
      console.error('更新章节角色关联失败:', err)
    })
  }

  async function startGenerate() {
    if (!selectedChapter.value) {
      showToast('请先选择章节', 'warning')
      return
    }
    if (!props.apiConfig.api_key) {
      showToast('请先配置 API Key', 'warning')
      return
    }

    const editor = editorRef.value?.editor
    const editorContent = editor ? editor.getText().trim() : ''
    const hasEditorContent = Boolean(editorContent)
    if (hasEditorContent) {
      const ok = await showConfirm({
        title: '确认覆盖',
        message: '当前章节已有内容，生成新内容将覆盖原有内容。是否继续？',
        warning: '原有内容将被完全替换'
      })
      if (!ok) return
    }

    const chapter = selectedChapter.value as any
    const { payload, errors } = buildAgenticPayloadFromIntent({
      chapterId: chapter.id,
      apiConfig: props.apiConfig,
      chapterData: chapter ? {
        creative_intents: chapter.creative_intents,
        chapter_goals: chapter.chapter_goals,
        selected_plan_type: chapter.selected_plan_type,
        user_overrides: chapter.user_overrides,
        word_count: chapter.word_count,
        author_intent: chapter.author_intent
      } : undefined
    })

    if (!payload) {
      formError.value = errors[0] || '请先配置智能生成设置'
      showToast(formError.value, 'warning')
      return
    }

    beatPreview.pendingAgenticPayload.value = payload
    beatPreview.pendingClearEditorOnConfirm.value = hasEditorContent
    // CP4.5：skip_plan_gate 兼容开关已移除（不再透传到 payload）

    const clarifyResult = await outlineClarification.checkOutlineClarification(chapter, {
      api_key: props.apiConfig.api_key,
      base_url: props.apiConfig.base_url,
      reasoning_model: props.apiConfig.reasoning_model,
      model: props.apiConfig.model
    })

    if (clarifyResult.shouldIntercept) {
      return
    }

    await beatPreview.previewBeatsForReview(payload, hasEditorContent)
  }

  let updateTimeout: ReturnType<typeof setTimeout> | undefined
  function handleContentUpdate(content: string) {
    if (isGenerating.value) {
      return
    }
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

  function getWorkflowStageLabel() {
    switch (workflowState.value.currentEvent) {
      case 'ASSEMBLING_CONTEXT':
        return '组装上下文'
      case 'PLANNING':
        return '规划节拍'
      case 'DRAFTING':
        return '起草'
      case 'SCENE_INTENT':
        return '拆解场景意图'
      case 'STITCHING':
        return '统稿拼接'
      case 'REVIEWING':
        return '审阅'
      case 'REFINING':
        return '重写优化'
      case 'SKETCH_GENERATION':
        return '生成速写骨架'
      case 'SKETCH_DONE':
        return '速写骨架完成'
      case 'FINAL_TEXT_STREAM':
        return '输出正文'
      case 'TEXT_CHUNK':
        return '写入中'
      case 'DONE':
        return '完成'
      default:
        return '处理中'
    }
  }

  function isCharacterSelected(charId: string) {
    return selectedChapter.value?.character_ids?.includes(charId) || false
  }

  const optimizationFeedback = ref('')
  function setOptimizationFeedback(value: string) {
    optimizationFeedback.value = value
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

  function handleApplyInspirationToOutline(content: string) {
    if (!selectedChapter.value) return
    const currentOutline = selectedChapter.value.outline_text || ''
    const newOutline = currentOutline ? `${currentOutline}\n${content}` : content
    scheduleMetaUpdate({ outline_text: newOutline })
  }

  function toggleAgenticMode() {
    isAgenticMode.value = !isAgenticMode.value
  }

  function toggleStreamMode() {
    isStreamMode.value = !isStreamMode.value
  }

  async function handleOptimize() {
    if (!selectedChapter.value || !optimizationFeedback.value.trim() || isGenerating.value) return
    try {
      const optimizedContent = await optimizeChapter({
        chapter_id: selectedChapter.value.id,
        optimization_feedback: optimizationFeedback.value,
        word_count: intentWordCount.value,
        api_key: props.apiConfig.api_key,
        base_url: props.apiConfig.base_url,
        model: props.apiConfig.reasoning_model || props.apiConfig.model
      })
      if (optimizedContent) {
        updateChapter({
          content_text: optimizedContent,
          draft_text: optimizedContent
        })
        optimizationFeedback.value = ''
      }
    } catch (e) {
      console.error('Optimization failed', e)
    }
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
        api_key: props.apiConfig.api_key,
        base_url: props.apiConfig.base_url,
        model: props.apiConfig.reasoning_model || props.apiConfig.model || 'google/gemini-2.0-flash-001'
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
        workflowState.value = null
        isGenerating.value = false
        beatPreview.closeBeatReviewModal()
      }
    }
  )

  assets.watchChapterAssets(() => props.selectedChapter)

  return {
    toggleAsset: (assetId: string) => assets.toggleAsset(props.selectedChapter, assetId),
    isAssetSelected: assets.isAssetSelected,
    showCompletionModal,
    completionMessage,
    completionTitle,
    closeCompletionModal,
    beatPreviewError: beatPreview.beatPreviewError,
    beatPreviewLoading: beatPreview.beatPreviewLoading,
    // CP2.5b：合并闸门——章节卡 + 重规划
    chapterCard: beatPreview.chapterCard,
    planDegraded: beatPreview.planDegraded,
    regenerateBeatsWithEditedCard: beatPreview.regenerateBeatsWithEditedCard,
    chapterSummary,
    characterUpdates: publisher.characterUpdates,
    characterExtraction: publisher.characterExtraction,
    closeAgenticSettingsModal,
    closeBeatReviewModal: beatPreview.closeBeatReviewModal,
    closePublishModal: publisher.closePublishModal,
    confirmBeatsAndGenerate,
    error,
    formError,
    generatedText,
    getBeatHookLabel: beatPreview.getBeatHookLabel,
    getMetaCollapsedLabel,
    getWorkflowStageLabel,
    handleContentUpdate,
    handleEditorEntityFocus,
    handleFormatText,
    handleOptimize,
    handlePartialOptimize,
    handleOutlineInput,
    handleAssetsSchemaInput,
    handleTitleInput,
    inspirationActiveCharacterIds,
    isAgenticMode,
    isCharacterSelected,
    isEditorDisabled,
    isFormatting,
    isGenerating,
    isLoadingOverlay,
    isPublishing: publisher.isPublishing,
    isStreamMode,
    localMetaCollapsed,
    openAgenticSettingsModal,
    openInspirationModal,
    optimizationFeedback,
    previewBeats: beatPreview.previewBeats,
    anchorPov: ref<string | null>(null),
    publishChapter: () => publisher.publishChapter(props.selectedChapter, props.apiConfig),
    selectedChapter,
    setEditorRef,
    scrollToCritique,
    setOptimizationFeedback,
    showAgenticSettingsModal,
    showBeatReviewModal: beatPreview.showBeatReviewModal,
    showInspirationModal,
    showPublishModal: publisher.showPublishModal,
    showClarificationModal: outlineClarification.showClarificationModal,
    clarificationResult: outlineClarification.clarificationResult,
    isClarifyingOutline: outlineClarification.isClarifyingOutline,
    closeClarificationModal: outlineClarification.closeClarificationModal,
    handleApplyClarification,
    handleSubmitClarificationAnswers: (answers: { questionId: string; answer: string }[], originalOutline: string) =>
      outlineClarification.handleSubmitClarificationAnswers(
        answers,
        originalOutline,
        props.selectedChapter,
        {
          api_key: props.apiConfig.api_key,
          base_url: props.apiConfig.base_url,
          reasoning_model: props.apiConfig.reasoning_model,
          model: props.apiConfig.model
        },
        handleApplyClarification
      ),
    startGenerate,
    toggleAgenticMode,
    toggleCharacter,
    toggleMetaCollapsed,
    toggleStreamMode,
    workflowState,
    handleApplyInspirationToOutline,
    closeInspirationModal,
    cancelGeneration,
    saveStatus,
    lastSavedAt,
    updatePreviewBeats: (beats: BeatEditorItem[]) => {
      beatPreview.previewBeats.value = beats
    }
  }
}
