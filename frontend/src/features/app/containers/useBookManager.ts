import { ref } from 'vue'
import { bookApi } from '../../../services/api'
import type { Book } from '../../../types'

export function useBookManager(options: {
  books: { value: Book[] }
  currentBookId: { value: string | null }
  currentBook: { value: Book | null }
  showToast: (message: string, type?: string) => void
  showConfirm: (options: { title: string; message: string; warning?: string }) => Promise<boolean>
}) {
  const { books, currentBookId, currentBook, showToast, showConfirm } = options

  const showBookModal = ref(false)
  const showManageBookModal = ref(false)
  const bookForm = ref({ title: '', genre: '', global_sys_prompt: '', core_motifs_taboos: '' })
  const manageBookForm = ref({ title: '', genre: '', core_motifs_taboos: '' })

  async function createBook() {
    if (!bookForm.value.title.trim()) return
    try {
      const newBook = await bookApi.create({
        ...bookForm.value,
        global_sys_prompt: bookForm.value.global_sys_prompt || '',
        core_motifs_taboos: bookForm.value.core_motifs_taboos || ''
      })
      books.value.push(newBook)
      currentBookId.value = newBook.id
      showBookModal.value = false
      bookForm.value = { title: '', genre: '', global_sys_prompt: '', core_motifs_taboos: '' }
    } catch (error: any) {
      showToast('创建失败: ' + error.message, 'error')
    }
  }

  async function updateBook(data: Partial<Book>) {
    if (!currentBookId.value) return
    try {
      const updated = await bookApi.update(currentBookId.value, data)
      const index = books.value.findIndex(b => b.id === currentBookId.value)
      if (index !== -1) {
        books.value[index] = updated
      }
      return updated
    } catch (error: any) {
      console.error('更新失败:', error)
      throw error
    }
  }

  function openManageBookModal() {
    if (!currentBook.value) return
    manageBookForm.value = {
      title: currentBook.value.title || '',
      genre: currentBook.value.genre || '',
      core_motifs_taboos: currentBook.value.core_motifs_taboos || ''
    }
    showManageBookModal.value = true
  }

  async function saveManageBook() {
    if (!currentBookId.value) return
    if (!manageBookForm.value.title.trim()) return
    await updateBook({
      title: manageBookForm.value.title,
      genre: manageBookForm.value.genre,
      core_motifs_taboos: manageBookForm.value.core_motifs_taboos
    })
    showManageBookModal.value = false
  }

  async function deleteCurrentBook() {
    if (!currentBookId.value) return
    const ok = await showConfirm({
      title: '确认删除',
      message: `确定要删除书籍 "${currentBook.value?.title || ''}" 吗？此操作会删除其下所有章节与角色。`,
      warning: '此操作不可撤销'
    })
    if (!ok) return
    try {
      const deletingId = currentBookId.value
      await bookApi.delete(deletingId)
      books.value = books.value.filter(b => b.id !== deletingId)
      if (books.value.length > 0) {
        currentBookId.value = books.value[0].id
      } else {
        currentBookId.value = null
      }
      showManageBookModal.value = false
    } catch (error: any) {
      showToast('删除失败: ' + error.message, 'error')
    }
  }

  return {
    showBookModal,
    showManageBookModal,
    bookForm,
    manageBookForm,
    createBook,
    updateBook,
    openManageBookModal,
    saveManageBook,
    deleteCurrentBook
  }
}
