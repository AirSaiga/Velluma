import { ref } from 'vue'
import { generateApi } from './useApi'

export function useChapterGenerator() {
  const isGenerating = ref(false)
  const generatedText = ref('')
  const error = ref(null)

  function startGeneration(request) {
    if (isGenerating.value) {
      return
    }

    isGenerating.value = true
    generatedText.value = ''
    error.value = null

    generateApi.stream(
      request,
      (chunk) => {
        generatedText.value += chunk
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
