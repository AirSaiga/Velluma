import { ref } from 'vue'
import { generateApi } from './useApi'

export function useChapterGenerator() {
  const isGenerating = ref(false)
  const generatedText = ref('')
  const error = ref(null)

  function startGeneration(request, onChunk?: (chunk: string) => void) {
    if (isGenerating.value) {
      return
    }

    isGenerating.value = true
    generatedText.value = ''
    error.value = null

    // @ts-ignore
    generateApi.stream(
      request,
      (chunk) => {
        generatedText.value += chunk
        if (onChunk) onChunk(chunk)
      },
      () => {
        isGenerating.value = false
      },
      (err) => {
        error.value = err
        isGenerating.value = false
      }
    )
  }

  function reset() {
    isGenerating.value = false
    generatedText.value = ''
    error.value = null
  }

  return {
    isGenerating,
    generatedText,
    error,
    startGeneration,
    reset
  }
}
