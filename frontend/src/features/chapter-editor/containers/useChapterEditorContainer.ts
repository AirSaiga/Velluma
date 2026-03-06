import { computed, ref } from 'vue'
import { useChapterGenerator } from '../../../composables/useChapterGenerator'
import { useToast } from '../../../composables/useToast'
import { chapterApi, generateApi, publishPromptData } from '../../../services/api'
import {
  AGENTIC_DEFAULTS,
  AGENTIC_FIELD_CONFIG,
  AGENTIC_GROUPS,
  buildAgenticPayload,
  getAgenticFieldFeedback,
  normalizeAgenticForm,
  validateAgenticForm
} from '../../../composables/useAgenticConfig'
import type { AgenticFormState, Chapter, Character, ConfirmedStoryBeat, GenerateChapterAgenticPayload, PacingStyle } from '../../../types'

interface ApiConfig {
  api_key: string
  base_url: string
  model: string
}

export interface ChapterEditorContainerProps {
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  metaCollapsed?: boolean
}

type ChapterEditorEmit = (event: string, ...args: any[]) => void

interface BeatEditorState {
  position: number
  beat_id?: string
  summary: string
  location?: string
  pov_character?: string
  action_summary?: string
  worldbuilding_instruction?: string
  openingState: string
  stoppingState: string
  forbiddenEventsText: string
  word_count_target: number
  target_words: number
  hook_ids: string[]
}

const TENSION_LEVEL_MIN = 1
const TENSION_LEVEL_MAX = 10
const DEFAULT_TENSION_LEVEL = 5
const DEFAULT_PACING_STYLE: PacingStyle = 'balanced'
const pacingStyleOptions: Array<{ value: PacingStyle; label: string }> = [
  { value: 'slow_burn', label: '慢热推进' },
  { value: 'balanced', label: '平衡节奏' },
  { value: 'fast_paced', label: '快节奏推进' }
]
const beatFieldMap = {
  openingState: 'entry_state',
  stoppingState: 'exit_state',
  forbiddenEventsText: 'red_lines'
} as const

export function useChapterEditorContainer(props: ChapterEditorContainerProps, emit: ChapterEditorEmit) {
  const { isGenerating, generatedText, error, workflowState, startGeneration, startAgenticGeneration, optimizeChapter, reset } = useChapterGenerator()
  const { showToast } = useToast()

  const isPublishing = ref(false)
  const publishError = ref<string | null>(null)
  const showPublishModal = ref(false)
  const showAgenticSettingsModal = ref(false)
  const showBeatReviewModal = ref(false)
  const characterUpdates = ref<Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>>([])
  const chapterSummary = ref<string | null>(null)
  const beatPreviewLoading = ref(false)
  const beatPreviewError = ref('')
  const previewBeats = ref<BeatEditorState[]>([])
  const pendingAgenticPayload = ref<GenerateChapterAgenticPayload | null>(null)
  const pendingClearEditorOnConfirm = ref(false)
  
  // 生成完成提示弹窗状态
  const showCompletionModal = ref(false)
  const completionMessage = ref('')
  const completionTitle = ref('')

  const agenticForm = ref<AgenticFormState>({ ...AGENTIC_DEFAULTS })
  const wordCountMin = ref(500)
  const wordCountMax = ref(10000)
  const isStreamMode = ref(true)
  const isAgenticMode = ref(true)
  const formError = ref('')

  const isEditorDisabled = computed(() => isGenerating.value || isPublishing.value || beatPreviewLoading.value)
  const isLoadingOverlay = computed(() => (isGenerating.value && isAgenticMode.value) || beatPreviewLoading.value || isPublishing.value)
  const selectedChapter = computed(() => props.selectedChapter)
  const agenticValidation = computed(() => validateAgenticForm(agenticForm.value))
  const agenticFieldFeedback = computed(() => getAgenticFieldFeedback(agenticForm.value))
  const agenticGroupFields = computed(() => ({
    generation: ['word_count'] as Array<keyof AgenticFormState>,
    memory: ['rag_top_k', 'rag_alpha', 'rag_beta', 'rag_gamma', 'rag_lambda'] as Array<keyof AgenticFormState>,
    workflow: ['max_iterations'] as Array<keyof AgenticFormState>
  }))
  const hasFieldFeedback = computed(() => Object.values(agenticFieldFeedback.value).some(Boolean))
  const firstFieldFeedback = computed(() => Object.values(agenticFieldFeedback.value).find(Boolean) || '')

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
  const canSubmitAgentic = computed(() => agenticValidation.value.errors.length === 0 && !hasFieldFeedback.value)
  const ragWeightTotal = computed(() => {
    const sum = agenticForm.value.rag_alpha + agenticForm.value.rag_beta + agenticForm.value.rag_gamma
    return Math.round(sum * 1000) / 1000
  })

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

  function normalizeTensionLevel(value: unknown, fallback = DEFAULT_TENSION_LEVEL) {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return fallback
    const rounded = Math.round(numeric)
    return Math.max(TENSION_LEVEL_MIN, Math.min(TENSION_LEVEL_MAX, rounded))
  }

  function normalizePacingStyle(value: unknown, fallback: PacingStyle = DEFAULT_PACING_STYLE): PacingStyle {
    if (value === 'slow_burn' || value === 'balanced' || value === 'fast_paced') {
      return value
    }
    return fallback
  }

  function getTensionLevelValue() {
    return normalizeTensionLevel(selectedChapter.value?.tension_level, DEFAULT_TENSION_LEVEL)
  }

  function getPacingStyleValue() {
    return normalizePacingStyle(selectedChapter.value?.pacing_style, DEFAULT_PACING_STYLE)
  }

  function handleTensionLevelInput(event: Event) {
    const target = event.target as HTMLInputElement
    updateChapter({ tension_level: normalizeTensionLevel(target.value, getTensionLevelValue()) })
  }

  function handlePacingStyleInput(event: Event) {
    const target = event.target as HTMLSelectElement
    updateChapter({ pacing_style: normalizePacingStyle(target.value, getPacingStyleValue()) })
  }

  let metaUpdateTimeout: ReturnType<typeof setTimeout> | undefined
  function scheduleMetaUpdate(updates: Record<string, any>) {
    clearTimeout(metaUpdateTimeout)
    metaUpdateTimeout = setTimeout(() => {
      updateChapter(updates)
    }, 500)
  }

  async function publishChapter() {
    if (!selectedChapter.value) return

    if (selectedChapter.value.status === 'published') {
      if (confirm('本章已发布，确定要取消发布吗？')) {
        try {
          isPublishing.value = true
          publishError.value = null
          await chapterApi.update(selectedChapter.value.id, { status: 'draft' })
          emit('update-chapter', selectedChapter.value.id, { status: 'draft' })
          showToast('已取消发布', 'success')
        } catch (err: any) {
          publishError.value = err.message
          showToast('取消发布失败: ' + err.message, 'error')
        } finally {
          isPublishing.value = false
        }
      }
      return
    }

    if (!props.apiConfig.api_key) {
      showToast('请先在设置中配置 API Key 以启用角色动态状态更新功能', 'warning')
    }

    if (confirm('确定要发布本章吗？发布后将会自动更新涉及角色的动态状态。')) {
      try {
        isPublishing.value = true
        publishError.value = null
        const result = await chapterApi.publish(selectedChapter.value.id, {
          api_key: props.apiConfig.api_key || undefined,
          base_url: props.apiConfig.base_url || undefined,
          model: props.apiConfig.model || 'gpt-4o-mini'
        })
        emit('update-chapter', selectedChapter.value.id, { status: 'published' })
        emit('refresh-characters')
        characterUpdates.value = result.character_updates || []
        if (result.summary) {
          chapterSummary.value = result.summary
          emit('update-chapter', selectedChapter.value.id, { summary: result.summary })
        }
        showPublishModal.value = true
      } catch (err: any) {
        publishError.value = err.message
        showToast('发布失败: ' + err.message, 'error')
      } finally {
        isPublishing.value = false
      }
    }
  }

  function closePublishModal() {
    showPublishModal.value = false
    characterUpdates.value = []
    chapterSummary.value = null
  }

  function openAgenticSettingsModal() {
    if (!isAgenticMode.value || isGenerating.value) return
    showAgenticSettingsModal.value = true
  }

  function closeAgenticSettingsModal() {
    showAgenticSettingsModal.value = false
  }

  function closeBeatReviewModal() {
    showBeatReviewModal.value = false
    beatPreviewError.value = ''
    previewBeats.value = []
    pendingAgenticPayload.value = null
    pendingClearEditorOnConfirm.value = false
  }

  async function previewBeatsForReview(payload: GenerateChapterAgenticPayload, clearEditorOnConfirm: boolean) {
    beatPreviewLoading.value = true
    beatPreviewError.value = ''
    try {
      const result = await generateApi.previewAgenticBeats(payload)
      const beats = Array.isArray(result?.beats) ? result.beats : []
      if (!beats.length) {
        throw new Error('未生成可用节拍，请调整大纲后重试')
      }
      previewBeats.value = beats.map((beat: ConfirmedStoryBeat) => ({
        position: Number(beat.position) || 1,
        beat_id: beat.beat_id,
        summary: String(beat.summary || '').trim(),
        location: beat.location,
        pov_character: beat.pov_character,
        action_summary: beat.action_summary,
        worldbuilding_instruction: beat.worldbuilding_instruction,
        openingState: String(beat[beatFieldMap.openingState] || '').trim(),
        stoppingState: String(beat[beatFieldMap.stoppingState] || '').trim(),
        forbiddenEventsText: Array.isArray(beat[beatFieldMap.forbiddenEventsText])
          ? beat[beatFieldMap.forbiddenEventsText].join('\n')
          : '',
        word_count_target: Math.max(0, Number(beat.word_count_target) || 0),
        target_words: Math.max(0, Number(beat.target_words) || 0),
        hook_ids: Array.isArray(beat.hook_ids) ? beat.hook_ids.filter(Boolean) : []
      }))
      pendingAgenticPayload.value = payload
      pendingClearEditorOnConfirm.value = clearEditorOnConfirm
      showBeatReviewModal.value = true
    } catch (err) {
      beatPreviewError.value = (err as Error).message || '节拍预览失败'
      showToast('节拍预览失败: ' + beatPreviewError.value, 'error')
    } finally {
      beatPreviewLoading.value = false
    }
  }

  function getBeatHookLabel(beat: Pick<BeatEditorState, 'hook_ids'>) {
    if (!Array.isArray(beat.hook_ids) || beat.hook_ids.length === 0) return '无'
    return beat.hook_ids.join(' / ')
  }

  const isFormatting = ref(false)

  async function handleFormatText(text: string) {
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
        model: props.apiConfig.model || 'google/gemini-2.0-flash-001'
      })
      
      if (formatted_text && editorRef.value) {
        // 将返回的文本按行分割，构建 Tiptap JSON 结构以确保正确分段
        // 1. 按换行符分割（兼容 \n, \r\n）
        // 2. 过滤掉空行
        // 3. 构造 paragraph 节点
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

        // 使用 setContent 替换编辑器内容
        editorRef.value.editor.commands.setContent(jsonContent)
      }
    } catch (e: any) {
      console.error('Format text failed', e)
      showToast('格式整理失败: ' + e.message, 'error')
    } finally {
      isFormatting.value = false
    }
  }

  const editorRef = ref<any>(null)
  function setEditorRef(editor: any) {
    editorRef.value = editor
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

  function confirmBeatsAndGenerate() {
    if (!pendingAgenticPayload.value || previewBeats.value.length === 0) {
      showToast('当前没有可用节拍，请重新生成', 'warning')
      return
    }
    if (pendingClearEditorOnConfirm.value && editorRef.value) {
      editorRef.value.clearContent()
    }
    const payload = {
      ...pendingAgenticPayload.value,
      beats: previewBeats.value.map((beat) => {
        const redLines = beat.forbiddenEventsText
          .split(/\r?\n|[,，]/)
          .map((item) => item.trim())
          .filter(Boolean)
        return {
          position: Math.max(1, Math.round(Number(beat.position) || 1)),
          beat_id: beat.beat_id,
          summary: beat.summary.trim() || `节拍${beat.position}`,
          location: beat.location,
          pov_character: beat.pov_character,
          action_summary: beat.action_summary,
          worldbuilding_instruction: beat.worldbuilding_instruction,
          [beatFieldMap.openingState]: beat.openingState.trim() || undefined,
          [beatFieldMap.stoppingState]: beat.stoppingState.trim() || undefined,
          [beatFieldMap.forbiddenEventsText]: redLines,
          word_count_target: Math.max(0, Math.round(Number(beat.word_count_target) || 0)),
          target_words: Math.max(0, Math.round(Number(beat.target_words) || 0)),
          hook_ids: Array.isArray(beat.hook_ids) ? beat.hook_ids.filter(Boolean) : []
        } as ConfirmedStoryBeat
      })
    }
    closeBeatReviewModal()
    reset()
    formError.value = ''
    generateStartTime = Date.now()
    startAgenticGeneration(payload, {
      onEvent: (event, data) => {
        console.log('[Workflow Event]', event, data)
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
        const statusMsg = result.passed
          ? `本章正文生成完成！审查通过，共重写 ${result.revision_count} 次 (${durationText}${topStageText}${aggregateStageText}${llmText})`
          : `本章正文生成完成！已达成最大迭代次数，共重写 ${result.revision_count} 次 (${durationText}${topStageText}${aggregateStageText}${llmText})`
        openCompletionModal('生成完成', statusMsg)
      }
    }, '/generate_chapter_agentic_with_beats')
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
    if (!isAgenticMode.value && !props.apiConfig.api_key) {
      showToast('请先配置 API Key', 'warning')
      return
    }

    const editor = editorRef.value?.editor
    const editorContent = editor ? editor.getText().trim() : ''
    const hasEditorContent = Boolean(editorContent)
    if (hasEditorContent && !confirm('当前章节已有内容，生成新内容将覆盖原有内容。是否继续？')) {
      return
    }

    const requestData = {
      chapter_id: selectedChapter.value.id,
      api_key: props.apiConfig.api_key,
      base_url: props.apiConfig.base_url || undefined,
      model: props.apiConfig.model,
      word_count: agenticForm.value.word_count
    }

    if (isAgenticMode.value) {
      const rawFeedback = getAgenticFieldFeedback(agenticForm.value)
      const firstFeedback = Object.values(rawFeedback).find(Boolean)
      if (firstFeedback) {
        formError.value = firstFeedback
        showToast(formError.value, 'warning')
        return
      }
      const { payload, errors } = buildAgenticPayload({
        chapterId: selectedChapter.value.id,
        apiConfig: props.apiConfig,
        form: agenticForm.value
      })
      agenticForm.value = normalizeAgenticForm(agenticForm.value)
      if (!payload) {
        formError.value = errors[0] || '表单参数不合法'
        showToast(formError.value, 'warning')
        return
      }
      await previewBeatsForReview(payload, hasEditorContent)
      return
    }

    if (isStreamMode.value) {
      reset()
      formError.value = ''
      generateStartTime = Date.now()
      if (hasEditorContent && editorRef.value) {
        editorRef.value.clearContent()
      }
      startGeneration(requestData, (chunk) => {
        if (editorRef.value) {
          editorRef.value.insertContent(chunk)
        }
      }, () => {
        if (editorRef.value) {
          editorRef.value.flushBuffer()
        }
        syncGeneratedContentToChapter()
        openCompletionModal('生成完成', `本章正文生成完成！(${getDurationText()})`)
      })
      return
    }

    reset()
    formError.value = ''
    generateStartTime = Date.now()
    if (hasEditorContent && editorRef.value) {
      editorRef.value.clearContent()
    }
    isGenerating.value = true
    try {
      const result = await generateApi.generateSync(requestData)
      publishPromptData(result.prompt)
      if (editorRef.value && result.content) {
        editorRef.value.clearContent()
        editorRef.value.insertContent(result.content)
      }
      openCompletionModal('生成完成', `本章正文生成完成！(${getDurationText()})`)
    } catch (err) {
      showToast('生成失败: ' + (err as Error).message, 'error')
    } finally {
      isGenerating.value = false
    }
  }

  function normalizeAgenticField() {
    const before = getAgenticFieldFeedback(agenticForm.value)
    agenticForm.value = normalizeAgenticForm(agenticForm.value)
    if (Object.keys(before).length > 0) {
      formError.value = '检测到无效输入，已自动恢复为有效值'
    } else if (!hasFieldFeedback.value) {
      formError.value = ''
    }
  }

  function restoreAgenticDefaults() {
    agenticForm.value = { ...AGENTIC_DEFAULTS }
    formError.value = ''
  }

  function restoreAgenticField(field: keyof AgenticFormState) {
    agenticForm.value = {
      ...agenticForm.value,
      [field]: AGENTIC_DEFAULTS[field]
    }
    formError.value = ''
  }

  function getAgenticFieldValue(field: keyof AgenticFormState) {
    return agenticForm.value[field]
  }

  function setAgenticFieldValue(field: keyof AgenticFormState, event: Event) {
    const target = event.target as HTMLInputElement
    const nextValue = Number(target.value)
    agenticForm.value = {
      ...agenticForm.value,
      [field]: nextValue
    }
  }

  function getAgenticFieldInputType(field: keyof AgenticFormState) {
    if (field === 'word_count' || field === 'max_iterations' || field === 'rag_top_k') {
      return 'number'
    }
    return 'number'
  }

  function getAgenticFieldStep(field: keyof AgenticFormState) {
    if (field === 'word_count') return 100
    if (field === 'max_iterations' || field === 'rag_top_k') return 1
    return 0.01
  }

  function getAgenticFieldMin(field: keyof AgenticFormState) {
    if (field === 'word_count') return 500
    if (field === 'max_iterations' || field === 'rag_top_k') return 1
    return 0
  }

  function getAgenticFieldMax(field: keyof AgenticFormState) {
    if (field === 'word_count') return 10000
    if (field === 'max_iterations') return 5
    if (field === 'rag_top_k') return 20
    if (field === 'rag_alpha' || field === 'rag_beta' || field === 'rag_gamma') return 1
    return undefined
  }

  function getAgenticFieldFeedbackText(field: keyof AgenticFormState) {
    return agenticFieldFeedback.value[field] || ''
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

  function setWordCount(value: number) {
    agenticForm.value = {
      ...agenticForm.value,
      word_count: value
    }
  }

  async function handleOptimize() {
    if (!selectedChapter.value || !optimizationFeedback.value.trim() || isGenerating.value) return
    try {
      const optimizedContent = await optimizeChapter({
        chapter_id: selectedChapter.value.id,
        optimization_feedback: optimizationFeedback.value,
        word_count: agenticForm.value.word_count,
        api_key: props.apiConfig.api_key,
        base_url: props.apiConfig.base_url,
        model: props.apiConfig.model
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

  return {
    AGENTIC_FIELD_CONFIG,
    AGENTIC_GROUPS,
    showCompletionModal: showCompletionModal,
    completionMessage: completionMessage,
    completionTitle: completionTitle,
    closeCompletionModal,
    agenticForm,
    agenticGroupFields,
    agenticValidation,
    agenticFieldFeedback,
    beatPreviewError,
    beatPreviewLoading,
    canSubmitAgentic,
    chapterSummary,
    characterUpdates,
    closeAgenticSettingsModal,
    closeBeatReviewModal,
    closePublishModal,
    confirmBeatsAndGenerate,
    error,
    firstFieldFeedback,
    formError,
    generatedText,
    getAgenticFieldFeedbackText,
    getAgenticFieldInputType,
    getAgenticFieldMax,
    getAgenticFieldMin,
    getAgenticFieldStep,
    getAgenticFieldValue,
    getBeatHookLabel,
    getMetaCollapsedLabel,
    getPacingStyleValue,
    getTensionLevelValue,
    getWorkflowStageLabel,
    handlePacingStyleInput,
    handleContentUpdate,
    handleFormatText,
    handleOptimize,
    handleOutlineInput,
    handleTensionLevelInput,
    handleTitleInput,
    inspirationActiveCharacterIds,
    isAgenticMode,
    isCharacterSelected,
    isEditorDisabled,
    isFormatting,
    isGenerating,
    isLoadingOverlay,
    isPublishing,
    isStreamMode,
    localMetaCollapsed,
    normalizeAgenticField,
    openAgenticSettingsModal,
    openInspirationModal,
    optimizationFeedback,
    pacingStyleOptions,
    previewBeats,
    publishChapter,
    ragWeightTotal,
    restoreAgenticDefaults,
    restoreAgenticField,
    selectedChapter,
    setAgenticFieldValue,
    setEditorRef,
    setOptimizationFeedback,
    setWordCount,
    showAgenticSettingsModal,
    showBeatReviewModal,
    showInspirationModal,
    showPublishModal,
    startGenerate,
    toggleAgenticMode,
    toggleCharacter,
    toggleMetaCollapsed,
    toggleStreamMode,
    wordCountMax,
    wordCountMin,
    workflowState,
    handleApplyInspirationToOutline,
    closeInspirationModal
  }
}
