<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  label?: string
  hint?: string
  error?: string
  required?: boolean
  labelPosition?: 'top' | 'left'
}

const props = withDefaults(defineProps<Props>(), {
  label: undefined,
  hint: undefined,
  error: undefined,
  required: false,
  labelPosition: 'top'
})

const hasLabel = computed(() => !!props.label)
const showError = computed(() => !!props.error)
</script>

<template>
  <div class="form-field" :class="`label-${labelPosition}`">
    <label v-if="hasLabel" class="field-label">
      {{ label }}
      <span v-if="required" class="required-mark">*</span>
    </label>
    
    <div class="field-wrapper">
      <slot />
      
      <p v-if="hint && !showError" class="field-hint">{{ hint }}</p>
      <p v-if="showError" class="field-error">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field.label-left {
  flex-direction: row;
  align-items: flex-start;
  gap: 12px;
}

.form-field.label-left .field-label {
  width: 80px;
  flex-shrink: 0;
  padding-top: 8px;
}

.form-field.label-left .field-wrapper {
  flex: 1;
}

.field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  line-height: 1.4;
}

.required-mark {
  color: #dc2626;
  margin-left: 2px;
}

.field-wrapper {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-hint {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}

.field-error {
  font-size: 11px;
  color: #dc2626;
  line-height: 1.4;
}
</style>
