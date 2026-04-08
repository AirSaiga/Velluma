<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '../Icon.vue'

interface Props {
  modelValue: string
  placeholder?: string
  debounce?: number
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: '搜索...',
  debounce: 0
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  search: [value: string]
}>()

const inputRef = ref<HTMLInputElement>()
const debounceTimer = ref<ReturnType<typeof setTimeout> | null>(null)

function handleInput(e: Event) {
  const target = e.target as HTMLInputElement
  const value = target.value
  
  emit('update:modelValue', value)
  
  if (props.debounce > 0) {
    if (debounceTimer.value) {
      clearTimeout(debounceTimer.value)
    }
    debounceTimer.value = setTimeout(() => {
      emit('search', value)
    }, props.debounce)
  } else {
    emit('search', value)
  }
}

function clearSearch() {
  emit('update:modelValue', '')
  emit('search', '')
  inputRef.value?.focus()
}

function focus() {
  inputRef.value?.focus()
}

defineExpose({
  focus
})
</script>

<template>
  <div class="panel-search">
    <Icon name="magnifying-glass" :size="16" class="search-icon" />
    <input
      ref="inputRef"
      :value="modelValue"
      type="text"
      :placeholder="placeholder"
      class="search-input"
      @input="handleInput"
    />
    <button
      v-if="modelValue"
      class="search-clear"
      @click="clearSearch"
    >
      <Icon name="close" :size="14" />
    </button>
  </div>
</template>

<style scoped>
.panel-search {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}

.search-icon {
  position: absolute;
  left: 12px;
  color: var(--text-muted);
  pointer-events: none;
}

.search-input {
  width: 100%;
  height: 38px;
  padding: 0 36px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  transition: all 0.2s ease;
}

.search-input::placeholder {
  color: var(--text-muted);
}

.search-input:hover {
  border-color: var(--hover-bg);
}

.search-input:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.search-clear {
  position: absolute;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.search-clear:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
</style>
