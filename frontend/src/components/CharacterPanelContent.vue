<script setup>
import { ref, computed } from 'vue'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

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
  canUpdateDynamicState: {
    type: Boolean,
    default: false
  },
  updateDynamicStateAction: {
    type: Function,
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

const searchQuery = ref('')
const selectedCharacter = ref(null)
const showCharacterDrawer = ref(false)
const showRelationshipPanel = ref(false)

const filteredCharacters = computed(() => {
  return props.characters.filter(c =>
    c.name.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

const characterHighlightLevelMap = computed(() => {
  const levelMap = new Map()
  for (const id of (props.prioritizedCharacterIds || [])) {
    levelMap.set(id, 'weak')
  }

  const focused = (props.focusedEntity || '').trim().toLowerCase()
  if (!focused) return levelMap

  for (const char of props.characters) {
    const name = (char.name || '').trim().toLowerCase()
    if (!name) continue
    const isStrong = name === focused || focused.includes(name)
    const isWeak = name.includes(focused)
    if (isStrong) {
      levelMap.set(char.id, 'strong')
      continue
    }
    if (isWeak && !levelMap.has(char.id)) {
      levelMap.set(char.id, 'weak')
    }
  }

  return levelMap
})

const sortedCharacters = computed(() => {
  const levelMap = characterHighlightLevelMap.value
  return [...filteredCharacters.value].sort((a, b) => {
    const scoreA = levelMap.get(a.id) === 'strong' ? 2 : (levelMap.get(a.id) === 'weak' ? 1 : 0)
    const scoreB = levelMap.get(b.id) === 'strong' ? 2 : (levelMap.get(b.id) === 'weak' ? 1 : 0)
    if (scoreA !== scoreB) return scoreB - scoreA
    return (b.importance_level || 0) - (a.importance_level || 0)
  })
})

function getCharacterHighlightClass(charId) {
  const level = characterHighlightLevelMap.value.get(charId)
  if (level === 'strong') return 'ring-amber-300 bg-amber-50/60 animate-pulse'
  if (level === 'weak') return 'ring-accent-300 bg-accent-50/40'
  return 'ring-transparent'
}

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
const isUpdatingState = ref(false)

async function handleUpdateDynamicState() {
  if (!selectedCharacter.value || !props.selectedChapterId || !props.updateDynamicStateAction) return

  if (!props.canUpdateDynamicState) {
    showToast('请先在设置中配置 API Key', 'warning')
    return
  }

  const ok = await showConfirm({
    title: '确认更新',
    message: '确定要基于当前章节内容更新角色的动态状态吗？\n此操作会分析章节正文并直接更新数据库。',
    warning: '此操作会直接修改数据库中的角色状态'
  })
  if (!ok) {
    return
  }

  isUpdatingState.value = true
  try {
    const newDynamicState = await props.updateDynamicStateAction(selectedCharacter.value.id, formData.value.dynamic_state)
    if (newDynamicState) {
      formData.value.dynamic_state = newDynamicState
      showToast('动态状态更新成功', 'success')
    }
  } catch (error) {
    showToast('更新失败: ' + (error.message || '未知错误'), 'error')
  } finally {
    isUpdatingState.value = false
  }
}

function openCreateDrawer() {
  selectedCharacter.value = null
  formData.value = {
    name: '',
    static_prompt: '',
    dynamic_state: '',
    current_state: '',
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
    current_state: character.current_state,
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
    emit('update-character', selectedCharacter.value.id, formData.value, (ok) => {
      if (ok !== false) {
        closeDrawer()
      }
    })
  } else {
    emit('create-character', formData.value, (ok) => {
      if (ok !== false) {
        closeDrawer()
      }
    })
  }
}

async function deleteCharacter(character) {
  const ok = await showConfirm({
    title: '确认删除',
    message: `确定要删除 "${character.name}" 吗？`
  })
  if (ok) {
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

async function deleteRelationship(id) {
  const ok = await showConfirm({
    title: '确认删除',
    message: '确定要删除这条关系吗？'
  })
  if (ok) {
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
  const colors = {
    1: 'bg-ink-100 text-ink-600',
    2: 'bg-accent-100 text-accent-700',
    3: 'bg-violet-100 text-violet-700',
    4: 'bg-amber-100 text-amber-700'
  }
  return colors[level] || 'bg-ink-100 text-ink-600'
}
</script>

<template>
  <div class="h-full flex flex-col bg-transparent">
    <div class="p-3">
      <div class="flex items-center justify-between mb-2">
        <h2 class="text-xs font-semibold text-[var(--text-primary)]">角色库</h2>
        <div class="flex gap-1">
          <button
            @click="showRelationshipPanel = true"
            class="px-2 py-1 bg-parchment-50 text-ink-700 text-[10px] rounded-xl ring-1 ring-[var(--border-color)]/60 hover:bg-ink-50 hover:shadow-md transition-all duration-200"
            title="关系配置"
          >
            关系
          </button>
          <button
            @click="openCreateDrawer"
            class="px-2 py-1 bg-accent-600 text-white text-[10px] font-medium rounded-xl shadow-sm hover:bg-accent-500 transition-colors flex items-center gap-1"
          >
            + 新建
          </button>
        </div>
      </div>

      <input
        v-model="searchQuery"
        type="text"
        placeholder="搜索角色..."
        class="w-full px-2 py-2 bg-parchment-50 rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-xs focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
      />
    </div>

    <div class="flex-1 overflow-y-auto p-3 space-y-2.5">
      <div
        v-for="char in sortedCharacters"
        :key="char.id"
        class="group p-3 bg-parchment-50 rounded-xl ring-1 ring-[var(--border-color)]/60 hover:shadow-md transition-all duration-200 cursor-pointer"
        :class="getCharacterHighlightClass(char.id)"
        @click="openEditDrawer(char)"
      >
        <div class="flex items-start justify-between">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5 mb-1">
              <span
                class="px-1.5 py-1 text-[9px] rounded-full"
                :class="getImportanceColor(char.importance_level)"
              >
                {{ getImportanceLabel(char.importance_level) }}
              </span>
              <span class="text-sm font-medium text-[var(--text-primary)] truncate">{{ char.name }}</span>
              <span
                v-if="characterHighlightLevelMap.get(char.id)"
                class="px-1.5 py-0.5 text-[9px] rounded-full"
                :class="characterHighlightLevelMap.get(char.id) === 'strong' ? 'bg-amber-100 text-amber-700' : 'bg-accent-100 text-accent-700'"
              >
                {{ characterHighlightLevelMap.get(char.id) === 'strong' ? '焦点强匹配' : '焦点弱匹配' }}
              </span>
            </div>
            <p class="text-[11px] text-[var(--text-muted)] line-clamp-1">{{ char.static_prompt || '暂无设定' }}</p>
            <div class="mt-1.5 space-y-1">
              <p v-if="char.dynamic_state" class="text-[10px] text-accent-600 line-clamp-1">
                <span class="font-medium">动态:</span> {{ char.dynamic_state }}
              </p>
              <p v-if="char.current_state" class="text-[10px] text-amber-600 line-clamp-1">
                <span class="font-medium">此刻:</span> {{ char.current_state }}
              </p>
            </div>
          </div>
          <div class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity ml-1">
            <button
              @click.stop="openEditDrawer(char)"
              class="p-0.5 text-[var(--text-muted)] hover:text-primary-400 transition-colors"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
              </svg>
            </button>
            <button
              @click.stop="deleteCharacter(char)"
              class="p-0.5 text-[var(--text-muted)] hover:text-rose-400 transition-colors"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
            </button>
          </div>
        </div>
      </div>

      <div v-if="sortedCharacters.length === 0" class="text-center py-4 text-[var(--text-muted)] text-xs">
        暂无角色数据
      </div>
    </div>

    <Transition name="modal">
      <div v-if="showCharacterDrawer" class="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" @click.self="closeDrawer">
        <div class="modal-content bg-[var(--bg-secondary)] rounded-2xl shadow-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <h3 class="text-lg font-heading font-semibold text-[var(--text-primary)] mb-4">
          {{ selectedCharacter ? '编辑角色' : '新建角色' }}
        </h3>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">名称</label>
            <input
              v-model="formData.name"
              type="text"
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
              placeholder="输入角色名称"
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">重要程度</label>
            <select
              v-model="formData.importance_level"
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
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
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              placeholder="角色的外貌、基础性格等不易变更的属性..."
            />
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="block text-sm text-[var(--text-muted)]">动态状态 (章节级快照)</label>
              <button
                v-if="selectedCharacter && selectedChapterId"
                @click="handleUpdateDynamicState"
                :disabled="isUpdatingState"
                class="px-2 py-0.5 text-[10px] rounded-xl bg-accent-50 text-accent-600 hover:bg-accent-100 disabled:opacity-50 transition-colors"
                title="基于当前章节内容自动更新"
              >
                {{ isUpdatingState ? '更新中...' : 'AI 自动更新' }}
              </button>
            </div>
            <textarea
              v-model="formData.dynamic_state"
              rows="3"
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              placeholder="角色当前的状态，如：在第X章受伤、情绪低落等..."
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">此刻状态 (实时快照)</label>
            <textarea
              v-model="formData.current_state"
              rows="2"
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              placeholder="从世界快照中提取的此刻状态，如：重伤倒地、正在逃跑..."
            />
            <p class="text-[10px] text-[var(--text-muted)] mt-1">此字段通常在章节发布时自动更新</p>
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
            class="px-4 py-2 bg-[var(--accent-500)] text-white rounded-full transition-colors"
          >
            保存
          </button>
        </div>
        </div>
      </div>
    </Transition>

    <Transition name="modal">
      <div v-if="showRelationshipPanel" class="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" @click.self="showRelationshipPanel = false">
        <div class="modal-content bg-[var(--bg-secondary)] rounded-2xl shadow-xl p-6 w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <h3 class="text-lg font-heading font-semibold text-[var(--text-primary)] mb-4">角色关系配置</h3>

        <div class="space-y-4 mb-6">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">源角色</label>
              <select
                v-model="relationshipForm.source_char_id"
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
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
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
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
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
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
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              placeholder="描述两人互动时的行为模式，如：A一直暗恋B且说话结巴"
            />
          </div>

          <button
            @click="saveRelationship"
            class="w-full px-4 py-2 bg-[var(--accent-500)] text-white rounded-full transition-colors"
          >
            {{ editingRelationshipId ? '保存修改' : '添加关系' }}
          </button>
          <button
            v-if="editingRelationshipId"
            @click="resetRelationshipForm"
            class="w-full px-4 py-2 bg-[var(--bg-panel)] hover:bg-parchment-50 text-[var(--text-primary)] rounded-full ring-1 ring-[var(--border-color)]/60 hover:shadow-md transition-all duration-200"
          >
            取消编辑
          </button>
        </div>

        <div class="border-t border-[var(--border-color)]/60 pt-4">
          <h4 class="text-sm font-medium text-[var(--text-primary)] mb-3">已有关系</h4>
          <div class="space-y-2">
            <div
              v-for="rel in relationships"
              :key="rel.id"
              class="flex items-center justify-between p-3 bg-[var(--bg-panel)] rounded-xl ring-1 ring-[var(--border-color)]/60 hover:shadow-md transition-all duration-200"
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
    </Transition>
  </div>
</template>
