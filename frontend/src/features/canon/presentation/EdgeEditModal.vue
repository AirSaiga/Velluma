<script setup lang="ts">
/**
 * Canon 边编辑弹窗（V4.0 新建）。
 *
 * 支持创建/编辑/删除边。
 */
import { ref, computed, watchEffect } from 'vue'
import { useCanon, EDGE_TYPE_LABELS, VISIBILITY_LABELS } from '../composables/useCanon'
import type { CanonEdge, CanonNode, CanonEdgeType, CanonVisibility } from '../../../services/api/domain/canon.api'

const props = defineProps<{
  bookId: string
  edge: CanonEdge | null
  nodes: CanonNode[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', edge: CanonEdge): void
}>()

const canon = useCanon()
const isEditing = computed(() => !!props.edge)
const saving = ref(false)
const error = ref<string | null>(null)

const source_id = ref('')
const target_id = ref('')
const type = ref<CanonEdgeType>('hints')
const strength = ref(5)
const visibility = ref<CanonVisibility>('public')
const note = ref('')

watchEffect(() => {
  if (props.edge) {
    source_id.value = props.edge.source_id
    target_id.value = props.edge.target_id
    type.value = props.edge.type
    strength.value = props.edge.strength
    visibility.value = props.edge.visibility
    note.value = props.edge.note || ''
  }
})

const sourceNode = computed(() => props.nodes.find(n => n.id === source_id.value))
const targetNode = computed(() => props.nodes.find(n => n.id === target_id.value))

async function handleSave() {
  if (!source_id.value || !target_id.value) {
    error.value = '请选择 source 和 target'
    return
  }
  if (source_id.value === target_id.value) {
    error.value = 'source 和 target 不能相同'
    return
  }
  saving.value = true
  error.value = null
  try {
    if (isEditing.value && props.edge) {
      const updated = await canon.updateEdge(props.bookId, props.edge.id, {
        type: type.value,
        strength: strength.value,
        visibility: visibility.value,
        note: note.value,
      })
      emit('saved', updated)
    } else {
      const created = await canon.createEdge(props.bookId, {
        book_id: props.bookId,
        source_id: source_id.value,
        target_id: target_id.value,
        type: type.value,
        strength: strength.value,
        visibility: visibility.value,
        note: note.value,
      })
      emit('saved', created)
    }
  } catch (e: any) {
    error.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  if (!props.edge) return
  if (!confirm('删除这条边？')) return
  saving.value = true
  try {
    await canon.deleteEdge(props.bookId, props.edge.id)
    emit('close')
  } catch (e: any) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-header">
        <h2>{{ isEditing ? '编辑关系' : '新建关系' }}</h2>
        <button class="close-btn" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <div class="form-row">
          <label>起始节点（source）<span class="required">*</span></label>
          <select v-model="source_id" :disabled="isEditing">
            <option value="">请选择…</option>
            <option v-for="n in nodes" :key="n.id" :value="n.id">
              {{ n.label }}（{{ n.type }}）
            </option>
          </select>
        </div>

        <div class="edge-arrow">
          ↓
          <span class="edge-type-tag">{{ EDGE_TYPE_LABELS[type] }}</span>
          ↓
        </div>

        <div class="form-row">
          <label>目标节点（target）<span class="required">*</span></label>
          <select v-model="target_id" :disabled="isEditing">
            <option value="">请选择…</option>
            <option v-for="n in nodes" :key="n.id" :value="n.id">
              {{ n.label }}（{{ n.type }}）
            </option>
          </select>
        </div>

        <div class="preview" v-if="sourceNode && targetNode">
          {{ sourceNode.label }} → <strong>{{ EDGE_TYPE_LABELS[type] }}</strong> → {{ targetNode.label }}
        </div>

        <div class="form-row">
          <label>关系类型</label>
          <select v-model="type">
            <option v-for="(lbl, key) in EDGE_TYPE_LABELS" :key="key" :value="key">{{ lbl }}（{{ key }}）</option>
          </select>
          <p class="hint">
            causes=因果 / before=时序 / hints=暗示（弱伏笔）/ setups=铺设（强伏笔）/ callbacks=回收 / echoes=呼应
          </p>
        </div>

        <div class="form-row">
          <label>强度（1-10）</label>
          <input v-model.number="strength" type="number" min="1" max="10" />
        </div>

        <div class="form-row">
          <label>可见性</label>
          <select v-model="visibility">
            <option v-for="(lbl, key) in VISIBILITY_LABELS" :key="key" :value="key">{{ lbl }}</option>
          </select>
        </div>

        <div class="form-row">
          <label>备注（可选）</label>
          <textarea v-model="note" rows="2" placeholder="如：针脚暗示兰星的真实实力"></textarea>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
      </div>

      <footer class="modal-footer">
        <button v-if="isEditing" class="btn-danger" @click="handleDelete" :disabled="saving">删除</button>
        <div class="spacer"></div>
        <button class="btn-secondary" @click="emit('close')" :disabled="saving">取消</button>
        <button class="btn-primary" @click="handleSave" :disabled="saving">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal-card {
  background: var(--bg-primary);
  border-radius: 0.5rem;
  width: 90%;
  max-width: 480px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-color);
}
.modal-header h2 { font-size: 1rem; margin: 0; }
.close-btn {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--text-muted);
  line-height: 1;
}
.modal-body {
  padding: 1rem 1.25rem;
  overflow-y: auto;
  flex: 1;
}
.form-row {
  margin-bottom: 0.875rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.form-row label {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
}
.required { color: #dc2626; }
.form-row input,
.form-row select,
.form-row textarea {
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  background: var(--bg-primary);
  font-family: inherit;
  resize: vertical;
}
.edge-arrow {
  text-align: center;
  font-size: 0.875rem;
  color: var(--text-muted);
  margin: 0.5rem 0;
}
.edge-type-tag {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  background: var(--accent-500);
  color: white;
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  margin: 0 0.25rem;
}
.preview {
  padding: 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  margin-bottom: 0.875rem;
  text-align: center;
}
.hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin: 0;
}
.error {
  color: #dc2626;
  font-size: 0.75rem;
  margin-top: 0.5rem;
}
.modal-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--border-color);
}
.spacer { flex: 1; }
.btn-primary, .btn-secondary, .btn-danger {
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  cursor: pointer;
  border: 1px solid var(--border-color);
}
.btn-primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.btn-secondary { background: var(--bg-primary); }
.btn-danger { background: transparent; color: #dc2626; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
