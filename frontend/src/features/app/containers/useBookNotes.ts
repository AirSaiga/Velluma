import { ref, watch } from 'vue'
import type { Book } from '../../../types'

export function useBookNotes(options: {
  currentBook: { value: Book | null }
  updateBook: (data: Partial<Book>) => Promise<any>
  showToast: (message: string, type?: string) => void
}) {
  const { currentBook, updateBook, showToast } = options

  const notesStatus = ref<'idle' | 'dirty' | 'saving' | 'saved' | 'error'>('idle')
  const notesError = ref('')
  const localBookNotes = ref('')

  watch(
    () => currentBook.value,
    (book) => {
      localBookNotes.value = book ? book.global_sys_prompt : ''
      notesStatus.value = 'idle'
      notesError.value = ''
    },
    { immediate: true }
  )

  watch(localBookNotes, () => {
    if (!currentBook.value) return
    notesStatus.value = 'dirty'
    notesError.value = ''
  })

  async function saveBookNotes() {
    if (!currentBook.value) return
    notesStatus.value = 'saving'
    notesError.value = ''
    try {
      await updateBook({ global_sys_prompt: localBookNotes.value })
      notesStatus.value = 'saved'
      setTimeout(() => {
        if (notesStatus.value === 'saved') {
          notesStatus.value = 'idle'
        }
      }, 1400)
    } catch (error: any) {
      notesStatus.value = 'error'
      notesError.value = error?.message || '保存失败'
    }
  }

  async function saveBookNotesFn(notes: string) {
    if (!currentBook.value) return
    await updateBook({ global_sys_prompt: notes })
  }

  return {
    localBookNotes,
    notesStatus,
    notesError,
    saveBookNotes,
    saveBookNotesFn
  }
}
