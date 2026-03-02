<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  entities: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['create', 'update', 'delete', 'select'])

const searchQuery = ref('')
const selectedType = ref('all')
const editingEntity = ref(null)
const showForm = ref(false)

const entityTypes = [
  { value: 'character', label: '角色', color: 'bg-purple-500' },
  { value: 'world', label: '世界观', color: 'bg-emerald-500' },
  { value: 'item', label: '物品', color: 'bg-amber-500' },
  { value: 'event', label: '事件', color: 'bg-rose-500' },
  { value: 'other', label: '其他', color: 'bg-slate-500' }
]

const filteredEntities = computed(() => {
  return props.entities.filter(entity => {
    const matchesSearch = entity.name.toLowerCase().includes(searchQuery.value.toLowerCase())
    const matchesType = selectedType.value === 'all' || entity.type === selectedType.value
    return matchesSearch && matchesType
  })
})

const formData = ref({
  name: '',
  type: 'character',
  description: ''
})

function openCreateForm() {
  editingEntity.value = null
  formData.value = { name: '', type: 'character', description: '' }
  showForm.value = true
}

function openEditForm(entity) {
  editingEntity.value = entity
  formData.value = { ...entity }
  showForm.value = true
}

function closeForm() {
  showForm.value = false
  editingEntity.value = null
}

function saveEntity() {
  if (!formData.value.name.trim()) return
  
  if (editingEntity.value) {
    emit('update', editingEntity.value.id, formData.value)
  } else {
    emit('create', formData.value)
  }
  closeForm()
}

function deleteEntity(entity) {
  if (confirm(`确定要删除 "${entity.name}" 吗？`)) {
    emit('delete', entity.id)
  }
}

function getTypeLabel(type) {
  return entityTypes.find(t => t.value === type)?.label || type
}

function getTypeColor(type) {
  return entityTypes.find(t => t.value === type)?.color || 'bg-slate-500'
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-secondary)] border-r border-[var(--border-color)]">
    <!-- 头部 -->
    <div class="p-4 border-b border-[var(--border-color)]">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-[var(--text-primary)]">设定库</h2>
        <button
          @click="openCreateForm"
          class="px-3 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded-lg transition-colors flex items-center gap-1"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          新建
        </button>
      </div>
      
      <!-- 搜索和筛选 -->
      <div class="space-y-2">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索设定..."
          class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm focus:outline-none focus:border-primary-500"
        />
        <select
          v-model="selectedType"
          class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500"
        >
          <option value="all">全部类型</option>
          <option v-for="type in entityTypes" :key="type.value" :value="type.value">
            {{ type.label }}
          </option>
        </select>
      </div>
    </div>
    
    <!-- 实体列表 -->
    <div class="flex-1 overflow-y-auto p-3 space-y-2">
      <div
        v-for="entity in filteredEntities"
        :key="entity.id"
        class="group p-3 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)] hover:border-[var(--text-muted)] transition-all cursor-pointer"
        @click="emit('select', entity)"
      >
        <div class="flex items-start justify-between">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span
                class="px-1.5 py-0.5 text-xs text-white rounded"
                :class="getTypeColor(entity.type)"
              >
                {{ getTypeLabel(entity.type) }}
              </span>
              <span class="font-medium text-[var(--text-primary)] truncate">{{ entity.name }}</span>
            </div>
            <p class="text-xs text-[var(--text-muted)] line-clamp-2">{{ entity.description || '暂无描述' }}</p>
          </div>
          <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-2">
            <button
              @click.stop="openEditForm(entity)"
              class="p-1 text-[var(--text-muted)] hover:text-primary-400 transition-colors"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
              </svg>
            </button>
            <button
              @click.stop="deleteEntity(entity)"
              class="p-1 text-[var(--text-muted)] hover:text-rose-400 transition-colors"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
      
      <div v-if="filteredEntities.length === 0" class="text-center py-8 text-[var(--text-muted)] text-sm">
        暂无设定数据
      </div>
    </div>
    
    <!-- 编辑弹窗 -->
    <div v-if="showForm" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="closeForm">
      <div class="bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] p-6 w-full max-w-md mx-4">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">
          {{ editingEntity ? '编辑设定' : '新建设定' }}
        </h3>
        
        <div class="space-y-4">
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">名称</label>
            <input
              v-model="formData.name"
              type="text"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              placeholder="输入设定名称"
            />
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">类型</label>
            <select
              v-model="formData.type"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
            >
              <option v-for="type in entityTypes" :key="type.value" :value="type.value">
                {{ type.label }}
              </option>
            </select>
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">描述</label>
            <textarea
              v-model="formData.description"
              rows="4"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500 resize-none"
              placeholder="输入详细描述..."
            />
          </div>
        </div>
        
        <div class="flex justify-end gap-3 mt-6">
          <button
            @click="closeForm"
            class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            取消
          </button>
          <button
            @click="saveEntity"
            class="px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
