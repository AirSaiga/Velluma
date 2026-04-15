<script setup>
import { computed } from 'vue'
import CharacterPanelContent from './CharacterPanelContent.vue'
import { characterApi } from '../services/api'

const props = defineProps({
  characters: {
    type: Array,
    default: () => []
  },
  relationships: {
    type: Array,
    default: () => []
  },
  selectedChapterId: {
    type: String,
    default: null
  },

  prioritizedCharacterIds: {
    type: Array,
    default: () => []
  },
  focusedEntity: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['create-character', 'update-character', 'delete-character', 'create-relationship', 'update-relationship', 'delete-relationship'])

const canUpdateDynamicState = computed(() => {
  return !!props.selectedChapterId
})

function forwardCreateCharacter(data, onDone) {
  emit('create-character', data, onDone)
}

function forwardUpdateCharacter(id, data, onDone) {
  emit('update-character', id, data, onDone)
}

function forwardDeleteCharacter(id) {
  emit('delete-character', id)
}

function forwardCreateRelationship(data) {
  emit('create-relationship', data)
}

function forwardUpdateRelationship(id, data) {
  emit('update-relationship', id, data)
}

function forwardDeleteRelationship(id) {
  emit('delete-relationship', id)
}

async function handleUpdateDynamicState(characterId, currentState) {
  if (!characterId || !props.selectedChapterId) return ''

  const result = await characterApi.updateDynamicState(characterId, {
    chapter_id: props.selectedChapterId,
    manual_current_state: currentState
  })

  return result?.new_dynamic_state || ''
}
</script>

<template>
  <CharacterPanelContent
    :characters="characters"
    :relationships="relationships"
    :selected-chapter-id="selectedChapterId"
    :prioritized-character-ids="prioritizedCharacterIds"
    :focused-entity="focusedEntity"
    :can-update-dynamic-state="canUpdateDynamicState"
    :update-dynamic-state-action="handleUpdateDynamicState"
    @create-character="forwardCreateCharacter"
    @update-character="forwardUpdateCharacter"
    @delete-character="forwardDeleteCharacter"
    @create-relationship="forwardCreateRelationship"
    @update-relationship="forwardUpdateRelationship"
    @delete-relationship="forwardDeleteRelationship"
  />
</template>
