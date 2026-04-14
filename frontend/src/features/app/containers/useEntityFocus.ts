import { ref, onBeforeUnmount } from 'vue'

export function useEntityFocus() {
  const editorFocusedEntity = ref('')
  let editorEntityDecayTimer: ReturnType<typeof setTimeout> | null = null

  function handleEditorEntityFocus(keyword: string) {
    const nextKeyword = (keyword || '').trim()
    editorFocusedEntity.value = nextKeyword
    if (editorEntityDecayTimer) {
      clearTimeout(editorEntityDecayTimer)
      editorEntityDecayTimer = null
    }
    if (!nextKeyword) return
    editorEntityDecayTimer = setTimeout(() => {
      editorFocusedEntity.value = ''
      editorEntityDecayTimer = null
    }, 2200)
  }

  onBeforeUnmount(() => {
    if (editorEntityDecayTimer) {
      clearTimeout(editorEntityDecayTimer)
      editorEntityDecayTimer = null
    }
  })

  return {
    editorFocusedEntity,
    editorEntityDecayTimer,
    handleEditorEntityFocus
  }
}
