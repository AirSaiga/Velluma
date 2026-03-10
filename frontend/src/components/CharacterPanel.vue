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
  apiConfig: {
    type: Object,
    default: () => ({})
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
  return !!props.apiConfig?.api_key
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
    api_key: props.apiConfig.api_key,
    base_url: props.apiConfig.base_url,
    model: props.apiConfig.model,
    manual_current_state: currentState,
    proxy_enabled: props.apiConfig.proxy_enabled !== false,
    proxy_url: props.apiConfig.proxy_url || undefined
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
