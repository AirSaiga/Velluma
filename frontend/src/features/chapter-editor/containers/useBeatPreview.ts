import { ref } from 'vue'
import { generateApi, planApi, publishPromptData } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import type {
  ConfirmedStoryBeat,
  GenerateChapterAgenticPayload,
  GenerateChapterAgenticPayloadWithBeats,
  ChapterCard,
} from '../../../types'
import type { BeatEditorItem } from '../../../types'

const beatFieldMap = {
  openingState: 'entry_state',
  stoppingState: 'exit_state',
  forbiddenEventsText: 'red_lines'
} as const

/**
 * 将后端 beat dict 映射为 BeatEditorItem（用于编辑 UI）。
 * 抽出为独立函数，供初始预览与重规划复用。
 */
function mapBeatToEditorItem(beat: ConfirmedStoryBeat): BeatEditorItem {
  return {
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
  }
}

export function useBeatPreview() {
  const { showToast } = useToast()

  const beatPreviewLoading = ref(false)
  const beatPreviewError = ref('')
  const previewBeats = ref<BeatEditorItem[]>([])
  const showBeatReviewModal = ref(false)
  const pendingAgenticPayload = ref<GenerateChapterAgenticPayload | null>(null)
  const pendingClearEditorOnConfirm = ref(false)
  let previewAbortController: AbortController | null = null

  // CP2.5b：合并闸门核心——章节卡状态
  const chapterCard = ref<ChapterCard | null>(null)
  const planDegraded = ref<{ reason: string; action: string; detail?: string } | null>(null)
  const currentChapterId = ref<string>('')

  function closeBeatReviewModal() {
    showBeatReviewModal.value = false
    beatPreviewError.value = ''
    previewBeats.value = []
    pendingAgenticPayload.value = null
    pendingClearEditorOnConfirm.value = false
    chapterCard.value = null
    planDegraded.value = null
    if (previewAbortController) {
      previewAbortController.abort()
      previewAbortController = null
    }
  }

  function getBeatHookLabel(beat: Pick<BeatEditorItem, 'hook_ids'>) {
    if (!Array.isArray(beat.hook_ids) || beat.hook_ids.length === 0) return '无'
    return beat.hook_ids.join(' / ')
  }

  /**
   * 联合预览：调 POST /api/chapters/{id}/plan（CP2.5b 合并闸门主入口）。
   *
   * 流程：
   * 1. 调 planApi.preview（2 次 LLM，5-15s）
   * 2. 拆解 PlanPreviewResponse → chapterCard + previewBeats
   * 3. 显示 PlanReviewModal
   *
   * CP4.5：skip_plan_gate 兼容开关已移除（旧 previewAgenticBeats 端点已删除）。
   * 所有节拍预览统一走合并闸门 planApi.preview。
   */
  async function previewBeatsForReview(payload: GenerateChapterAgenticPayload, clearEditorOnConfirm: boolean) {
    if (previewAbortController) {
      previewAbortController.abort()
    }
    previewAbortController = new AbortController()

    beatPreviewLoading.value = true
    beatPreviewError.value = ''
    try {
      const chapterId = String(payload.chapter_id || '')
      currentChapterId.value = chapterId

      // CP4.5：合并闸门为唯一路径（旧 skip_plan_gate + previewAgenticBeats 已下线）
      const result = await planApi.preview(chapterId, null)
      if (!result?.beats?.length) {
        throw new Error('未生成可用节拍，请调整大纲或章节卡后重试')
      }
      applyBeatsResult(result.beats, result.chapter_card, result.degraded || null)
      if (result.debug_prompt) {
        publishPromptData(result.debug_prompt)
      }

      pendingAgenticPayload.value = payload
      pendingClearEditorOnConfirm.value = clearEditorOnConfirm
      showBeatReviewModal.value = true
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return
      }
      beatPreviewError.value = (err as Error).message || '章节规划失败'
      showToast('章节规划失败: ' + beatPreviewError.value, 'error')
    } finally {
      beatPreviewLoading.value = false
      previewAbortController = null
    }
  }

  /** 内部工具：应用 beats + chapter_card 结果到 UI 状态 */
  function applyBeatsResult(
    beats: ConfirmedStoryBeat[],
    card: ChapterCard | null,
    degraded: { reason: string; action: string; detail?: string } | null,
  ) {
    previewBeats.value = beats.map(mapBeatToEditorItem)
    chapterCard.value = card
    planDegraded.value = degraded
  }

  /**
   * CP2.5b 重规划：用户编辑章节卡后触发，用 editedCardFields 调 /plan 重新生成节拍。
   *
   * 业务流程：
   * 1. 收集当前编辑的 chapterCard 字段（含 purpose/must_hit_events 等）
   * 2. 调 planApi.preview(chapterId, editedCardFields)
   * 3. 返回新 beats，覆盖 previewBeats（章节卡保留用户编辑版本）
   */
  async function regenerateBeatsWithEditedCard(editedCardFields: Record<string, any>): Promise<boolean> {
    if (!currentChapterId.value) {
      showToast('无法重规划：缺少章节 ID', 'error')
      return false
    }
    beatPreviewLoading.value = true
    beatPreviewError.value = ''
    try {
      const result = await planApi.preview(currentChapterId.value, editedCardFields)
      if (!result?.beats?.length) {
        throw new Error('重规划未生成可用节拍')
      }
      // beats 覆盖，章节卡字段保留用户编辑版本（不覆盖）
      previewBeats.value = result.beats.map(mapBeatToEditorItem)
      planDegraded.value = result.degraded || null
      showToast('节拍已重新生成', 'success')
      return true
    } catch (err) {
      beatPreviewError.value = (err as Error).message || '重规划失败'
      showToast('重规划失败: ' + beatPreviewError.value, 'error')
      return false
    } finally {
      beatPreviewLoading.value = false
    }
  }

  /**
   * CP2.5b 确认章节卡 + 节拍：调 POST /api/chapters/{id}/plan/confirm。
   * 在触发生成（/generate-chapter）之前必须调用本函数。
   *
   * CP4.5：skip_plan_gate 兼容开关已移除，confirm 为必经路径。
   *
   * Returns:
   *   true=确认成功，可继续触发生成；false=失败或跳过
   */
  async function confirmPlan(): Promise<boolean> {
    if (!currentChapterId.value || !chapterCard.value) {
      showToast('无法确认：缺少章节卡', 'error')
      return false
    }
    try {
      const beatsPayload = buildConfirmedBeatsPayload()
      if (!beatsPayload) {
        showToast('无法确认：缺少节拍', 'error')
        return false
      }
      await planApi.confirm(currentChapterId.value, {
        chapter_card_fields: chapterCard.value as any,
        beats: beatsPayload.beats,
        word_count: beatsPayload.word_count,
      })
      return true
    } catch (err) {
      showToast('章节卡确认失败: ' + (err as Error).message, 'error')
      return false
    }
  }

  function buildConfirmedBeatsPayload(): GenerateChapterAgenticPayloadWithBeats | null {
    if (!pendingAgenticPayload.value || previewBeats.value.length === 0) {
      return null
    }
    const beats = previewBeats.value.map((beat) => {
      const redLines = beat.forbiddenEventsText
        .split(/\r?\n|[,\uff0c]/)
        .map((item) => item.trim())
        .filter(Boolean)
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
    return { ...pendingAgenticPayload.value, beats }
  }

  return {
    beatPreviewLoading,
    beatPreviewError,
    previewBeats,
    showBeatReviewModal,
    pendingAgenticPayload,
    pendingClearEditorOnConfirm,
    // CP2.5b 新增
    chapterCard,
    planDegraded,
    currentChapterId,
    closeBeatReviewModal,
    getBeatHookLabel,
    previewBeatsForReview,
    buildConfirmedBeatsPayload,
    // CP2.5b 新增方法
    regenerateBeatsWithEditedCard,
    confirmPlan,
  }
}
