import { computed } from 'vue'
import { characterApi, relationshipApi } from '../../../services/api'
import type { Character, Relationship } from '../../../types'

export function useCharacterManager(options: {
  currentBookId: { value: string | null }
  characters: { value: Character[] }
  relationships: { value: Relationship[] }
  editorFocusedEntity: { value: string }
  selectedChapterCharacterIds: { value: string[] }
  showToast: (message: string, type?: string) => void
}) {
  const { currentBookId, characters, relationships, editorFocusedEntity, selectedChapterCharacterIds, showToast } = options

  const autoHighlightedCharacterIds = computed<string[]>(() => {
    const focused = editorFocusedEntity.value.trim().toLowerCase()
    const selectedIds = selectedChapterCharacterIds.value
    const merged = new Set<string>(selectedIds)
    if (focused) {
      for (const char of characters.value) {
        const name = (char?.name || '').toLowerCase()
        if (name && (name.includes(focused) || focused.includes(name))) {
          merged.add(char.id)
        }
      }
    }
    return Array.from(merged)
  })

  const autoHighlightedCharacterNames = computed<string[]>(() => {
    const idSet = new Set(autoHighlightedCharacterIds.value)
    return characters.value
      .filter((char) => idSet.has(char.id))
      .map((char) => char.name)
  })

  async function createCharacter(data: any, onDone?: (success: boolean) => void) {
    if (!currentBookId.value) {
      showToast('请先创建或选择一本书籍', 'warning')
      onDone?.(false)
      return
    }
    try {
      const newChar = await characterApi.create({
        ...data,
        book_id: currentBookId.value
      })
      characters.value.push(newChar)
      onDone?.(true)
    } catch (error: any) {
      showToast('创建失败: ' + error.message, 'error')
      onDone?.(false)
    }
  }

  async function updateCharacter(id: string, data: any, onDone?: (success: boolean) => void) {
    try {
      const updated = await characterApi.update(id, data)
      const index = characters.value.findIndex(c => c.id === id)
      if (index !== -1) {
        characters.value[index] = updated
      }
      onDone?.(true)
    } catch (error: any) {
      showToast('更新失败: ' + error.message, 'error')
      onDone?.(false)
    }
  }

  async function deleteCharacter(id: string) {
    try {
      await characterApi.delete(id)
      characters.value = characters.value.filter(c => c.id !== id)
    } catch (error: any) {
      showToast('删除失败: ' + error.message, 'error')
    }
  }

  async function createRelationship(data: any) {
    if (!currentBookId.value) {
      showToast('请先创建或选择一本书籍', 'warning')
      return
    }
    try {
      const newRel = await relationshipApi.create({
        ...data,
        book_id: currentBookId.value
      })
      relationships.value.push(newRel)
    } catch (error: any) {
      showToast('创建失败: ' + error.message, 'error')
    }
  }

  async function updateRelationship(id: string, data: any) {
    try {
      const updated = await relationshipApi.update(id, data)
      const index = relationships.value.findIndex(r => r.id === id)
      if (index !== -1) {
        relationships.value[index] = updated
      }
    } catch (error: any) {
      showToast('更新失败: ' + error.message, 'error')
    }
  }

  async function deleteRelationship(id: string) {
    try {
      await relationshipApi.delete(id)
      relationships.value = relationships.value.filter(r => r.id !== id)
    } catch (error: any) {
      showToast('删除失败: ' + error.message, 'error')
    }
  }

  async function loadCharacters() {
    if (!currentBookId.value) return
    try {
      const chars = await characterApi.getAll(currentBookId.value)
      characters.value = chars
    } catch (error: any) {
      console.error('加载角色失败:', error)
    }
  }

  return {
    autoHighlightedCharacterIds,
    autoHighlightedCharacterNames,
    createCharacter,
    updateCharacter,
    deleteCharacter,
    createRelationship,
    updateRelationship,
    deleteRelationship,
    loadCharacters
  }
}
