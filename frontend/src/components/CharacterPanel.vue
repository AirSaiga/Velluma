<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  characters: {
    type: Array,
    default: () => []
  },
  relationships: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['create-character', 'update-character', 'delete-character', 'create-relationship', 'update-relationship', 'delete-relationship'])

const searchQuery = ref('')
const selectedCharacter = ref(null)
const showCharacterDrawer = ref(false)
const showRelationshipPanel = ref(false)

const filteredCharacters = computed(() => {
  return props.characters.filter(c => 
    c.name.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

const formData = ref({
  name: '',
  static_prompt: '',
  dynamic_state: '',
  importance_level: 1
})

const relationshipForm = ref({
  source_char_id: '',
  target_char_id: '',
  relation_type: '',
  affinity_score: 50,
  interaction_prompt: ''
})
const editingRelationshipId = ref(null)

function openCreateDrawer() {
  selectedCharacter.value = null
  formData.value = {
    name: '',
    static_prompt: '',
    dynamic_state: '',
    importance_level: 1
  }
  showCharacterDrawer.value = true
}

function openEditDrawer(character) {
  selectedCharacter.value = character
  formData.value = {
    name: character.name,
    static_prompt: character.static_prompt,
    dynamic_state: character.dynamic_state,
    importance_level: character.importance_level
  }
  showCharacterDrawer.value = true
}

function closeDrawer() {
  showCharacterDrawer.value = false
  selectedCharacter.value = null
}

function saveCharacter() {
  if (!formData.value.name.trim()) return
  
  if (selectedCharacter.value) {
    emit('update-character', selectedCharacter.value.id, formData.value)
  } else {
    emit('create-character', formData.value)
  }
  closeDrawer()
}

function deleteCharacter(character) {
  if (confirm(`确定要删除 "${character.name}" 吗？`)) {
    emit('delete-character', character.id)
  }
}

function saveRelationship() {
  if (!relationshipForm.value.source_char_id || 
      !relationshipForm.value.target_char_id ||
      !relationshipForm.value.relation_type) {
    return
  }
  
  if (editingRelationshipId.value) {
    emit('update-relationship', editingRelationshipId.value, relationshipForm.value)
  } else {
    emit('create-relationship', relationshipForm.value)
  }
  resetRelationshipForm()
}

function resetRelationshipForm() {
  editingRelationshipId.value = null
  relationshipForm.value = {
    source_char_id: '',
    target_char_id: '',
    relation_type: '',
    affinity_score: 50,
    interaction_prompt: ''
  }
}

function editRelationship(rel) {
  editingRelationshipId.value = rel.id
  relationshipForm.value = {
    source_char_id: rel.source_char_id,
    target_char_id: rel.target_char_id,
    relation_type: rel.relation_type,
    affinity_score: rel.affinity_score ?? 50,
    interaction_prompt: rel.interaction_prompt ?? ''
  }
  showRelationshipPanel.value = true
}

function deleteRelationship(id) {
  if (confirm('确定要删除这条关系吗？')) {
    emit('delete-relationship', id)
  }
}

function getCharacterName(id) {
  const char = props.characters.find(c => c.id === id)
  return char?.name || id
}

function getImportanceLabel(level) {
  const labels = { 1: '普通', 2: '重要', 3: '主角', 4: '核心' }
  return labels[level] || '普通'
}

function getImportanceColor(level) {
  const colors = { 1: 'bg-slate-500', 2: 'bg-blue-500', 3: 'bg-purple-500', 4: 'bg-amber-500' }
  return colors[level] || 'bg-slate-500'
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-secondary)] border-r border-[var(--border-color)]">
    <div class="p-4 border-b border-[var(--border-color)]">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-[var(--text-primary)]">角色库</h2>
        <div class="flex gap-2">
          <button
            @click="showRelationshipPanel = true"
            class="px-2.5 py-1.5 bg-[var(--bg-tertiary)] hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm rounded-lg transition-colors"
            title="关系配置"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
            </svg>
          </button>
          <button
            @click="openCreateDrawer"
            class="px-3 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded-lg transition-colors flex items-center gap-1"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            新建
          </button>
        </div>
      </div>
      
      <input
        v-model="searchQuery"
        type="text"
        placeholder="搜索角色..."
        class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm focus:outline-none focus:border-primary-500"
      />
    </div>
    
    <div class="flex-1 overflow-y-auto p-3 space-y-2">
      <div
        v-for="char in filteredCharacters"
        :key="char.id"
        class="group p-3 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)] hover:border-[var(--text-muted)] transition-all cursor-pointer"
        @click="openEditDrawer(char)"
      >
        <div class="flex items-start justify-between">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span
                class="px-1.5 py-0.5 text-xs text-white rounded"
                :class="getImportanceColor(char.importance_level)"
              >
                {{ getImportanceLabel(char.importance_level) }}
              </span>
              <span class="font-medium text-[var(--text-primary)] truncate">{{ char.name }}</span>
            </div>
            <p class="text-xs text-[var(--text-muted)] line-clamp-2">{{ char.static_prompt || '暂无设定' }}</p>
          </div>
          <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-2">
            <button
              @click.stop="openEditDrawer(char)"
              class="p-1 text-[var(--text-muted)] hover:text-primary-400 transition-colors"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
              </svg>
            </button>
            <button
              @click.stop="deleteCharacter(char)"
              class="p-1 text-[var(--text-muted)] hover:text-rose-400 transition-colors"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
      
      <div v-if="filteredCharacters.length === 0" class="text-center py-8 text-[var(--text-muted)] text-sm">
        暂无角色数据
      </div>
    </div>
    
    <div v-if="showCharacterDrawer" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="closeDrawer">
      <div class="bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">
          {{ selectedCharacter ? '编辑角色' : '新建角色' }}
        </h3>
        
        <div class="space-y-4">
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">名称</label>
            <input
              v-model="formData.name"
              type="text"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              placeholder="输入角色名称"
            />
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">重要程度</label>
            <select
              v-model="formData.importance_level"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
            >
              <option :value="1">普通</option>
              <option :value="2">重要</option>
              <option :value="3">主角</option>
              <option :value="4">核心</option>
            </select>
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">静态设定 (外貌/性格)</label>
            <textarea
              v-model="formData.static_prompt"
              rows="3"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500 resize-none"
              placeholder="角色的外貌、基础性格等不易变更的属性..."
            />
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">动态状态 (当前状态)</label>
            <textarea
              v-model="formData.dynamic_state"
              rows="3"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500 resize-none"
              placeholder="角色当前的状态，如：在第X章受伤、情绪低落等..."
            />
          </div>
        </div>
        
        <div class="flex justify-end gap-3 mt-6">
          <button
            @click="closeDrawer"
            class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            取消
          </button>
          <button
            @click="saveCharacter"
            class="px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors"
          >
            保存
          </button>
        </div>
      </div>
    </div>
    
    <div v-if="showRelationshipPanel" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="showRelationshipPanel = false">
      <div class="bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] p-6 w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">角色关系配置</h3>
        
        <div class="space-y-4 mb-6">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">源角色</label>
              <select
                v-model="relationshipForm.source_char_id"
                class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              >
                <option value="">选择角色</option>
                <option v-for="char in characters" :key="char.id" :value="char.id">
                  {{ char.name }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">目标角色</label>
              <select
                v-model="relationshipForm.target_char_id"
                class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              >
                <option value="">选择角色</option>
                <option v-for="char in characters" :key="char.id" :value="char.id">
                  {{ char.name }}
                </option>
              </select>
            </div>
          </div>
          
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">关系类型</label>
              <input
                v-model="relationshipForm.relation_type"
                type="text"
                class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
                placeholder="如：朋友、敌人、恋人"
              />
            </div>
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">亲密度 ({{ relationshipForm.affinity_score }})</label>
              <input
                v-model="relationshipForm.affinity_score"
                type="range"
                min="0"
                max="100"
                class="w-full"
              />
            </div>
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">互动设定</label>
            <textarea
              v-model="relationshipForm.interaction_prompt"
              rows="2"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500 resize-none"
              placeholder="描述两人互动时的行为模式，如：A一直暗恋B且说话结巴"
            />
          </div>
          
          <button
            @click="saveRelationship"
            class="w-full px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors"
          >
            {{ editingRelationshipId ? '保存修改' : '添加关系' }}
          </button>
          <button
            v-if="editingRelationshipId"
            @click="resetRelationshipForm"
            class="w-full px-4 py-2 bg-[var(--bg-tertiary)] hover:bg-[var(--hover-bg)] text-[var(--text-primary)] rounded-lg transition-colors"
          >
            取消编辑
          </button>
        </div>
        
        <div class="border-t border-[var(--border-color)] pt-4">
          <h4 class="text-sm font-medium text-[var(--text-primary)] mb-3">已有关系</h4>
          <div class="space-y-2">
            <div
              v-for="rel in relationships"
              :key="rel.id"
              class="flex items-center justify-between p-3 bg-[var(--bg-tertiary)] rounded-lg"
            >
              <div class="flex items-center gap-2 text-sm">
                <span class="text-[var(--text-primary)]">{{ getCharacterName(rel.source_char_id) }}</span>
                <span class="text-[var(--text-muted)]">{{ rel.relation_type }}</span>
                <span class="text-[var(--text-primary)]">{{ getCharacterName(rel.target_char_id) }}</span>
              </div>
              <div class="flex items-center gap-2">
                <button
                  @click="editRelationship(rel)"
                  class="text-[var(--text-muted)] hover:text-primary-400 transition-colors"
                  title="编辑"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                  </svg>
                </button>
                <button
                  @click="deleteRelationship(rel.id)"
                  class="text-[var(--text-muted)] hover:text-rose-400 transition-colors"
                  title="删除"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                </button>
              </div>
            </div>
            <div v-if="relationships.length === 0" class="text-center py-4 text-[var(--text-muted)] text-sm">
              暂无关系配置
            </div>
          </div>
        </div>
        
        <div class="flex justify-end gap-3 mt-6">
          <button
            @click="showRelationshipPanel = false"
            class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
