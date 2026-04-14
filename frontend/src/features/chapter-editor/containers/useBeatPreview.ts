import { ref } from 'vue'
import { generateApi, publishPromptData } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import type { ConfirmedStoryBeat, GenerateChapterAgenticPayload, GenerateChapterAgenticPayloadWithBeats } from '../../../types'
import type { BeatEditorItem } from '../../../types'

const beatFieldMap = {
  openingState: 'entry_state',
  stoppingState: 'exit_state',
  forbiddenEventsText: 'red_lines'
} as const

export function useBeatPreview() {
  const { showToast } = useToast()

  const beatPreviewLoading = ref(false)
  const beatPreviewError = ref('')
  const previewBeats = ref<BeatEditorItem[]>([])
  const showBeatReviewModal = ref(false)
  const pendingAgenticPayload = ref<GenerateChapterAgenticPayload | null>(null)
  const pendingClearEditorOnConfirm = ref(false)
  let previewAbortController: AbortController | null = null

  function closeBeatReviewModal() {
    showBeatReviewModal.value = false
    beatPreviewError.value = ''
    previewBeats.value = []
    pendingAgenticPayload.value = null
    pendingClearEditorOnConfirm.value = false
    if (previewAbortController) {
      previewAbortController.abort()
      previewAbortController = null
    }
  }

  function getBeatHookLabel(beat: Pick<BeatEditorItem, 'hook_ids'>) {
    if (!Array.isArray(beat.hook_ids) || beat.hook_ids.length === 0) return '无'
    return beat.hook_ids.join(' / ')
  }

  async function previewBeatsForReview(payload: GenerateChapterAgenticPayload, clearEditorOnConfirm: boolean) {
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
        return
      }
      beatPreviewError.value = (err as Error).message || '节拍预览失败'
      showToast('节拍预览失败: ' + beatPreviewError.value, 'error')
    } finally {
      beatPreviewLoading.value = false
      previewAbortController = null
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
    closeBeatReviewModal,
    getBeatHookLabel,
    previewBeatsForReview,
    buildConfirmedBeatsPayload
  }
}
