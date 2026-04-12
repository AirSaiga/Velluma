import { computed, ref, watch } from 'vue'
import { useChapterGenerator } from '../../../composables/useChapterGenerator'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { chapterApi, generateApi, publishPromptData, assetApi } from '../../../services/api'
import { buildAgenticPayload } from '../../../composables/useAgenticConfig'
import type { ApiConfig, Chapter, Character, ConfirmedStoryBeat, GenerateChapterAgenticPayload, ClarifyingQuestion, Asset, ChapterAsset } from '../../../types'
import { useIntentDrivenConfig, buildAgenticPayloadFromIntent } from '../../intent-driven/useIntentDrivenConfig'

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
  pov_mode: 'single' | 'ensemble' | 'omniscient'  // V3.6
  pov_characters: string[]                         // V3.6
  pov_aperture?: string                            // V3.5
  anchor_pov?: string
  original_actor?: string
  action_summary?: string
  worldbuilding_instruction?: string
  entry_state?: string                             // 后端原始字段
  exit_state?: string                              // 后端原始字段
  red_lines?: string[]                             // 后端原始字段
  openingState: string                             // 映射自 entry_state
  stoppingState: string                            // 映射自 exit_state
  forbiddenEventsText: string                      // 映射自 red_lines
  word_count_target: number
  target_words: number
  hook_ids: string[]
}

const beatFieldMap = {
  openingState: 'entry_state',
  stoppingState: 'exit_state',
  forbiddenEventsText: 'red_lines'
} as const

export function useChapterEditorContainer(props: ChapterEditorContainerProps, emit: ChapterEditorEmit) {
  const { isGenerating, generatedText, error, workflowState, startGeneration, startAgenticGeneration, optimizeChapter, reset } = useChapterGenerator()
  const { showToast } = useToast()
  const { show: showConfirm } = useConfirmDialog()

  const isPublishing = ref(false)
  const publishError = ref<string | null>(null)
  const showPublishModal = ref(false)
  const showAgenticSettingsModal = ref(false)
  const { reset: resetIntentDrivenConfig, wordCount: intentWordCount } = useIntentDrivenConfig()
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
  const anchorPov = ref<string | null>(null)
  const pendingAgenticPayload = ref<GenerateChapterAgenticPayload | null>(null)
  const pendingClearEditorOnConfirm = ref(false)
  
  // 新增大纲澄清相关状态
  const isClarifyingOutline = ref(false)
  const clarificationResult = ref<{
    is_ambiguous: boolean
    identified_issues?: string[]
    clarifying_questions?: ClarifyingQuestion[]
    clarification_suggestions?: string[]
    refined_text?: string
  } | null>(null)
  const showClarificationModal = ref(false)
  
  // 生成完成提示弹窗状态
  const showCompletionModal = ref(false)
  const completionMessage = ref('')
  const completionTitle = ref('')

  const isStreamMode = ref(true)
  const isAgenticMode = ref(true)
  const formError = ref('')

  const isEditorDisabled = computed(() => isGenerating.value || isPublishing.value || beatPreviewLoading.value || isClarifyingOutline.value)
  const isLoadingOverlay = computed(() => (isGenerating.value && isAgenticMode.value) || beatPreviewLoading.value || isPublishing.value || isClarifyingOutline.value)
  const selectedChapter = computed(() => props.selectedChapter)
  const selectedAssetIds = ref<string[]>([])

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

  async function publishChapter() {
    if (!selectedChapter.value) return

    if (selectedChapter.value.status === 'published') {
      const ok = await showConfirm({
        title: '确认取消发布',
        message: '本章已发布，确定要取消发布吗？'
      })
      if (!ok) return
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
      return
    }

    if (!props.apiConfig.api_key) {
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
      const result = await chapterApi.publish(selectedChapter.value.id, {
        api_key: props.apiConfig.api_key || undefined,
        base_url: props.apiConfig.base_url || undefined,
        model: props.apiConfig.reasoning_model || props.apiConfig.model || 'gpt-4o-mini',
        proxy_enabled: props.apiConfig.proxy_enabled !== false,
        proxy_url: props.apiConfig.proxy_url || undefined
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
    resetIntentDrivenConfig()
  }

  function closeBeatReviewModal() {
    showBeatReviewModal.value = false
    beatPreviewError.value = ''
    previewBeats.value = []
    pendingAgenticPayload.value = null
    pendingClearEditorOnConfirm.value = false
    // 取消进行中的预览请求
    if (previewAbortController) {
      previewAbortController.abort()
      previewAbortController = null
    }
  }

  function closeClarificationModal() {
    showClarificationModal.value = false
    clarificationResult.value = null
  }

  async function handleApplyClarification(newOutlineText: string) {
    if (selectedChapter.value && newOutlineText !== selectedChapter.value.outline_text) {
      try {
        await chapterApi.update(selectedChapter.value.id, { outline_text: newOutlineText })
        updateChapter({ outline_text: newOutlineText })
      } catch (err) {
        console.error('更新大纲失败:', err)
        showToast('大纲保存失败，生成可能使用旧版本大纲', 'warning')
      }
    } else {
      updateChapter({ outline_text: newOutlineText })
    }
    
    closeClarificationModal()
    
    // 如果还有等待生成的 Payload，则在更新大纲后直接触发生成
    if (pendingAgenticPayload.value) {
      // 从最新大纲构建新的 Payload (可选: 如果依赖最新状态，可重构生成 Payload 的逻辑)
      // 在这里直接拿着原本的 pendingAgenticPayload 继续走下去
      await previewBeatsForReview(pendingAgenticPayload.value, pendingClearEditorOnConfirm.value)
    }
  }

  // 新增：处理用户提交澄清答案（第二轮）
  async function handleSubmitClarificationAnswers(
    answers: { questionId: string, answer: string }[],
    originalOutline: string
  ) {
    const chapter = selectedChapter.value
    if (!chapter) return

    isClarifyingOutline.value = true
    try {
      // 构建 user_instruction：将用户的回答格式化为文本
      const userInstruction = answers.map(a => a.answer).join('\n')
      
      // 构建 previous_issues：从当前澄清结果中获取
      const previousIssues = clarificationResult.value?.identified_issues || []
      
      // 发送第二轮澄清请求
      const clarifyRes = await generateApi.clarifyOutline({
        chapter_id: chapter.id,
        ambiguous_text: chapter.outline_text?.trim() || '',
        api_key: props.apiConfig.api_key,
        base_url: props.apiConfig.base_url,
        model: props.apiConfig.reasoning_model || props.apiConfig.model || 'gpt-4o-mini',
        author_intent: chapter.author_intent,
        user_instruction: userInstruction,  // 用户的回答
        previous_issues: previousIssues     // 之前识别的问题
      })

      // 更新澄清结果（此时应该包含 refined_text）
      clarificationResult.value = clarifyRes
      
      // 如果后端返回了修正后的大纲，更新文本框
      if (clarifyRes.refined_text?.trim()) {
        // 保持弹窗打开，但更新 refined_text，让用户看到修正后的大纲
        // 用户可以选择继续修改或直接应用
      } else {
        // 如果没有返回 refined_text，直接应用原始大纲
        handleApplyClarification(chapter.outline_text || '')
      }
    } catch (err: any) {
      console.warn('第二轮澄清请求失败，使用原始大纲', err)
      // 失败时直接应用原始大纲
      handleApplyClarification(chapter.outline_text || '')
    } finally {
      isClarifyingOutline.value = false
    }
  }

  async function previewBeatsForReview(payload: GenerateChapterAgenticPayload, clearEditorOnConfirm: boolean) {
    // 取消之前的请求（如果有）
    if (previewAbortController) {
      previewAbortController.abort()
    }
    previewAbortController = new AbortController()

    beatPreviewLoading.value = true
    beatPreviewError.value = ''
    try {
      const result = await generateApi.previewAgenticBeats(payload, previewAbortController.signal)
      const beats = Array.isArray(result?.beats) ? result.beats : []
      if (!beats.length) {
        throw new Error('未生成可用节拍，请调整大纲后重试')
      }
      if (result.debug_prompt) {
        publishPromptData(result.debug_prompt)
      }
      previewBeats.value = beats.map((beat: ConfirmedStoryBeat) => ({
        position: Number(beat.position) || 1,
        beat_id: beat.beat_id,
        summary: String(beat.summary || '').trim(),
        location: beat.location,
        pov_character: beat.pov_character,
        pov_mode: (beat.pov_mode || 'single') as 'single' | 'ensemble' | 'omniscient',
        pov_characters: Array.isArray(beat.pov_characters) ? beat.pov_characters.filter(Boolean) : [],
        pov_aperture: beat.pov_aperture || undefined,
        action_summary: beat.action_summary,
        worldbuilding_instruction: beat.worldbuilding_instruction,
        entry_state: beat.entry_state,
        exit_state: beat.exit_state,
        red_lines: Array.isArray(beat.red_lines) ? beat.red_lines : [],
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
      if ((err as Error).name === 'AbortError') {
        // 用户主动取消，不显示错误
        return
      }
      beatPreviewError.value = (err as Error).message || '节拍预览失败'
      showToast('节拍预览失败: ' + beatPreviewError.value, 'error')
    } finally {
      beatPreviewLoading.value = false
      previewAbortController = null
    }
  }

  function getBeatHookLabel(beat: Pick<BeatEditorState, 'hook_ids'>) {
    if (!Array.isArray(beat.hook_ids) || beat.hook_ids.length === 0) return '无'
    return beat.hook_ids.join(' / ')
  }

  const isFormatting = ref(false)
  let previewAbortController: AbortController | null = null

  async function handleFormatText(payload: string | { text: string; selection?: { from: number; to: number } }) {
    const text = typeof payload === 'string' ? payload : payload.text
    const selection = typeof payload === 'string' ? undefined : payload.selection
    
    if (isFormatting.value || !text) return
    
    try {
      isFormatting.value = true
      const { formatted_text } = await generateApi.formatText({
        text,
        api_key: props.apiConfig.api_key || '',
        base_url: props.apiConfig.base_url || '',
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
          // 选中文本部分替换
          editorRef.value.editor.commands.setTextSelection(selection)
          editorRef.value.editor.commands.insertContent(jsonContent)
        } else {
          // 全文替换
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
          .split(/\r?\n|[,\uff0c]/)
          .map((item) => item.trim())
          .filter(Boolean)
        // ensemble 模式下自动取第一个角色作为 pov_character
        const effectivePovCharacter = beat.pov_mode === 'ensemble' && beat.pov_characters.length > 0
          ? beat.pov_characters[0]
          : beat.pov_character
        return {
          position: Math.max(1, Math.round(Number(beat.position) || 1)),
          beat_id: beat.beat_id,
          summary: beat.summary.trim() || `节拍${beat.position}`,
          location: beat.location,
          pov_character: effectivePovCharacter,
          pov_mode: beat.pov_mode || 'single',
          pov_characters: Array.isArray(beat.pov_characters) ? beat.pov_characters.filter(Boolean) : [],
          pov_aperture: beat.pov_aperture,
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
    
    // 在 reset() 之前保存数据
    const savedPayload = { ...payload }
    
    closeBeatReviewModal()
    reset()
    formError.value = ''
    generateStartTime = Date.now()
    
    // 确保 chapter_id 存在
    const chapterId = savedPayload.chapter_id || selectedChapter.value?.id
    if (!chapterId) {
      showToast('章节 ID 缺失，请重试', 'error')
      return
    }
    
    // V3.5+ 直接调用双轨生成 API
    const dualTrackPayload = {
      ...savedPayload,
      chapter_id: chapterId,  // 确保 chapter_id 存在
      beats: savedPayload.beats || []  // 使用保存的 beats
    }
    
    // 调用双轨生成 API
    console.log('[Debug] 双轨生成请求数据:', {
      chapterId: chapterId,
      payloadChapterId: dualTrackPayload.chapter_id,
      beatsCount: dualTrackPayload.beats?.length,
      hasApiKey: !!dualTrackPayload.api_key,
    })
    
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
        // 双轨模式返回 revision_count，普通模式可能返回 iterations
        const revisionCount = result.revision_count ?? result.iterations ?? 0
        const statusMsg = result.passed
          ? `本章正文生成完成！审查通过，共重写 ${revisionCount} 次 (${durationText}${topStageText}${aggregateStageText}${llmText})`
          : `本章正文生成完成！已达成最大迭代次数，共重写 ${revisionCount} 次 (${durationText}${topStageText}${aggregateStageText}${llmText})`
        openCompletionModal('生成完成', statusMsg)
      }
    }, `/chapters/${chapterId}/generate-dual-track`)
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

    // === 意图驱动路径（唯一生成路径）===
    // 传入章节数据，优先使用已保存的配置
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

    // 将即将生成的参数存入 pending 状态，用于被中断后恢复
    pendingAgenticPayload.value = payload
    pendingClearEditorOnConfirm.value = hasEditorContent

    // === 插入意图澄清流程 (Clarification Workflow) ===
    const currentOutline = chapter.outline_text?.trim() || ''
    if (currentOutline.length > 0 && currentOutline.length < 200) { // 如果大纲存在且字数偏少，启动澄清检查
      isClarifyingOutline.value = true
      try {
        const clarifyRes = await generateApi.clarifyOutline({
          chapter_id: chapter.id,
          ambiguous_text: currentOutline,
          api_key: props.apiConfig.api_key,
          base_url: props.apiConfig.base_url,
          model: props.apiConfig.reasoning_model || props.apiConfig.model || 'gpt-4o-mini',
          author_intent: chapter.author_intent
        })
        
        if (clarifyRes.is_ambiguous && (
          (clarifyRes.clarifying_questions && clarifyRes.clarifying_questions.length > 0) ||
          (clarifyRes.clarification_suggestions && clarifyRes.clarification_suggestions.length > 0)
        )) {
          // 拦截生成，弹出澄清框让用户补充
          clarificationResult.value = clarifyRes
          showClarificationModal.value = true
          return // 中断后续的 previewBeatsForReview，等待用户完成澄清
        }
      } catch (err: any) {
        console.warn('大纲澄清失败，退回直接生成模式', err)
      } finally {
        isClarifyingOutline.value = false
      }
    }

    // 如果不需要澄清或澄清失败，直接继续执行预览
    await previewBeatsForReview(payload, hasEditorContent)
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

  async function handlePartialOptimize(payload: { selection: any, instruction: string }) {
    if (!selectedChapter.value || !props.apiConfig.api_key) {
        showToast('请先配置 API Key', 'warning')
        return
    }
    
    isFormatting.value = true
    
    try {
        const { optimized_text } = await generateApi.optimizeSelection({
            chapter_id: selectedChapter.value.id,
            selected_text: payload.selection.text,
            context_before: payload.selection.contextBefore,
            context_after: payload.selection.contextAfter,
            user_instruction: payload.instruction,
            api_key: props.apiConfig.api_key,
            base_url: props.apiConfig.base_url,
            model: props.apiConfig.reasoning_model || props.apiConfig.model
        })
        
        if (optimized_text && editorRef.value) {
            // 调用 applyOptimizationDiff 而不是直接替换
            editorRef.value.applyOptimizationDiff(optimized_text)
            showToast('优化生成完成，请确认', 'success')
        } else {
            // 如果没有返回文本，重置状态
            editorRef.value.resetOptimization()
            showToast('优化未返回有效结果', 'warning')
        }
    } catch (e: any) {
        console.error('Optimization failed', e)
        showToast('优化失败: ' + e.message, 'error')
        // 出错时重置状态
        if (editorRef.value) {
            editorRef.value.resetOptimization()
        }
    } finally {
        isFormatting.value = false
    }
  }

  async function toggleAsset(assetId: string) {
    if (!selectedChapter.value) return
    const ids = [...selectedAssetIds.value]
    const index = ids.indexOf(assetId)
    if (index === -1) {
      ids.push(assetId)
    } else {
      ids.splice(index, 1)
    }
    selectedAssetIds.value = ids
    
    try {
      await assetApi.updateChapterAssets(selectedChapter.value.id, ids)
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

  watch(
    () => props.selectedChapter,
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
        
        characterUpdates.value = []
        chapterSummary.value = null
        workflowState.value = null
        isGenerating.value = false
        beatPreviewError.value = ''
        previewBeats.value = []
        showBeatReviewModal.value = false
        pendingAgenticPayload.value = null
        pendingClearEditorOnConfirm.value = false
        if (previewAbortController) {
          previewAbortController.abort()
          previewAbortController = null
        }
      }
    },
    { immediate: true }
  )

  return {
    toggleAsset,
    isAssetSelected,
    showCompletionModal: showCompletionModal,
    completionMessage: completionMessage,
    completionTitle: completionTitle,
    closeCompletionModal,
    beatPreviewError,
    beatPreviewLoading,
    chapterSummary,
    characterUpdates,
    closeAgenticSettingsModal,
    closeBeatReviewModal,
    closePublishModal,
    confirmBeatsAndGenerate,
    error,
    formError,
    generatedText,
    getBeatHookLabel,
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
    isPublishing,
    isStreamMode,
    localMetaCollapsed,
    openAgenticSettingsModal,
    openInspirationModal,
    optimizationFeedback,
    previewBeats,
    anchorPov,
    // anchorPov kept for backward-compat but no longer displayed
    publishChapter,
    selectedChapter,
    setEditorRef,
    scrollToCritique,
    setOptimizationFeedback,
    showAgenticSettingsModal,
    showBeatReviewModal,
    showInspirationModal,
    showPublishModal,
    showClarificationModal,
    clarificationResult,
    isClarifyingOutline,
    closeClarificationModal,
    handleApplyClarification,
    handleSubmitClarificationAnswers,
    startGenerate,
    toggleAgenticMode,
    toggleCharacter,
    toggleMetaCollapsed,
    toggleStreamMode,
    workflowState,
    handleApplyInspirationToOutline,
    closeInspirationModal
  }
}
