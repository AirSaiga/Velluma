<script setup>
import { ref, computed } from 'vue'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { PanelContainer, PanelSection, PanelCard, PanelEmpty, PanelSearch } from './panels'
import Icon from './Icon.vue'

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

const emit = defineEmits(['create-character', 'update-character', 'delete-character', 'create-relationship', 'update-relationship', 'delete-relationship', 'close'])

const searchQuery = ref('')
const selectedCharacter = ref(null)
const showCharacterDrawer = ref(false)
const showRelationshipPanel = ref(false)

const filteredCharacters = computed(() => {
  if (!searchQuery.value) return props.characters
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

function getCharacterHighlight(charId) {
  const level = characterHighlightLevelMap.value.get(charId)
  return level || 'none'
}

function getImportanceLabel(level) {
  const labels = { 1: '普通', 2: '重要', 3: '核心', 4: '主角' }
  return labels[level] || '普通'
}

function getImportanceColor(level) {
  const colors = {
    1: 'bg-gray-100 text-gray-600',
    2: 'bg-blue-50 text-blue-600',
    3: 'bg-purple-50 text-purple-600',
    4: 'bg-amber-50 text-amber-600'
  }
  return colors[level] || 'bg-gray-100 text-gray-600'
}

const formData = ref({
  name: '',
  static_prompt: '',
  dynamic_state: '',
  current_state: '',
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
    showToast('请先选择章节', 'warning')
    return
  }

  const ok = await showConfirm({
    title: '确认更新',
    message: '确定要基于当前章节内容更新角色的动态状态吗？\n此操作会分析章节正文并直接更新数据库。',
    warning: '此操作会直接修改数据库中的角色状态'
  })
  if (!ok) return

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
      if (ok !== false) closeDrawer()
    })
  } else {
    emit('create-character', formData.value, (ok) => {
      if (ok !== false) closeDrawer()
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

function handleClose() {
  emit('close')
}
</script>

<template>
  <PanelContainer
    title="角色库"
    icon="users"
    description="管理书籍中的角色和关系"
    :header-actions="[
      { icon: 'link', label: '关系', onClick: () => showRelationshipPanel = true },
      { icon: 'plus', label: '新建', onClick: openCreateDrawer, variant: 'primary' }
    ]"
    @close="handleClose"
  >
    <div class="character-panel-content">
      <!-- 搜索栏 -->
      <PanelSearch
        v-model="searchQuery"
        placeholder="搜索角色..."
        :debounce="200"
      />

      <!-- 角色列表 -->
      <div class="characters-list">
        <PanelCard
          v-for="char in sortedCharacters"
          :key="char.id"
          :title="char.name"
          :subtitle="char.static_prompt || '暂无设定'"
          :highlight="getCharacterHighlight(char.id)"
          clickable
          :actions="[
            { icon: 'pencil', label: '编辑', onClick: () => openEditDrawer(char) },
            { icon: 'trash', label: '删除', onClick: () => deleteCharacter(char), variant: 'danger' }
          ]"
          @click="openEditDrawer(char)"
        >
          <template #footer>
            <div class="character-meta">
              <span class="importance-badge" :class="getImportanceColor(char.importance_level)">
                {{ getImportanceLabel(char.importance_level) }}
              </span>
              <span v-if="char.dynamic_state" class="meta-item dynamic">
                动态: {{ char.dynamic_state }}
              </span>
              <span v-if="char.current_state" class="meta-item current">
                此刻: {{ char.current_state }}
              </span>
            </div>
          </template>
        </PanelCard>

        <PanelEmpty
          v-if="sortedCharacters.length === 0"
          icon="users"
          :title="searchQuery ? '未找到匹配角色' : '暂无角色'"
          :description="searchQuery ? '尝试其他关键词搜索' : '点击「新建」按钮创建第一个角色'"
          :action-label="searchQuery ? '清除搜索' : undefined"
          @action="searchQuery = ''"
        />
      </div>
    </div>
  </PanelContainer>

  <!-- 角色编辑抽屉 -->
  <Transition name="modal">
    <div v-if="showCharacterDrawer" class="modal-overlay" @click.self="closeDrawer">
      <div class="modal-content">
        <div class="drawer-header">
          <h3>{{ selectedCharacter ? '编辑角色' : '新建角色' }}</h3>
          <button class="close-btn" @click="closeDrawer">
            <Icon name="close" :size="18" />
          </button>
        </div>

        <div class="drawer-body">
          <div class="form-group">
            <label>名称 <span class="required">*</span></label>
            <input v-model="formData.name" type="text" placeholder="输入角色名称" />
          </div>

          <div class="form-group">
            <label>重要程度</label>
            <select v-model="formData.importance_level">
              <option :value="1">普通</option>
              <option :value="2">重要</option>
              <option :value="3">核心</option>
              <option :value="4">主角</option>
            </select>
          </div>

          <div class="form-group">
            <label>静态设定（外貌/性格）</label>
            <textarea v-model="formData.static_prompt" rows="3" placeholder="角色的外貌、基础性格等不易变更的属性..." />
          </div>

          <div class="form-group">
            <div class="label-with-action">
              <label>动态状态（章节级快照）</label>
              <button
                v-if="selectedCharacter && selectedChapterId"
                @click="handleUpdateDynamicState"
                :disabled="isUpdatingState"
                class="ai-update-btn"
              >
                {{ isUpdatingState ? '更新中...' : 'AI 自动更新' }}
              </button>
            </div>
            <textarea v-model="formData.dynamic_state" rows="3" placeholder="角色当前的状态，如：在第X章受伤、情绪低落等..." />
          </div>

          <div class="form-group">
            <label>此刻状态（实时快照）</label>
            <textarea v-model="formData.current_state" rows="2" placeholder="从世界快照中提取的此刻状态..." />
            <p class="form-hint">此字段通常在章节发布时自动更新</p>
          </div>
        </div>

        <div class="drawer-footer">
          <button class="btn-secondary" @click="closeDrawer">取消</button>
          <button class="btn-primary" @click="saveCharacter">保存</button>
        </div>
      </div>
    </div>
  </Transition>

  <!-- 关系面板 -->
  <Transition name="modal">
    <div v-if="showRelationshipPanel" class="modal-overlay" @click.self="showRelationshipPanel = false">
      <div class="modal-content relationship-modal">
        <div class="drawer-header">
          <h3>角色关系配置</h3>
          <button class="close-btn" @click="showRelationshipPanel = false">
            <Icon name="close" :size="18" />
          </button>
        </div>

        <div class="drawer-body">
          <!-- 添加关系表单 -->
          <div class="relationship-form">
            <div class="form-row">
              <div class="form-group">
                <label>源角色</label>
                <select v-model="relationshipForm.source_char_id">
                  <option value="">选择角色</option>
                  <option v-for="char in characters" :key="char.id" :value="char.id">{{ char.name }}</option>
                </select>
              </div>
              <div class="form-group">
                <label>目标角色</label>
                <select v-model="relationshipForm.target_char_id">
                  <option value="">选择角色</option>
                  <option v-for="char in characters" :key="char.id" :value="char.id">{{ char.name }}</option>
                </select>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>关系类型</label>
                <input v-model="relationshipForm.relation_type" type="text" placeholder="如：朋友、敌人、恋人" />
              </div>
              <div class="form-group">
                <label>亲密度 ({{ relationshipForm.affinity_score }})</label>
                <input v-model="relationshipForm.affinity_score" type="range" min="0" max="100" />
              </div>
            </div>

            <div class="form-group">
              <label>互动设定</label>
              <textarea v-model="relationshipForm.interaction_prompt" rows="2" placeholder="描述两人互动时的行为模式..." />
            </div>

            <button class="btn-primary w-full" @click="saveRelationship">
              {{ editingRelationshipId ? '保存修改' : '添加关系' }}
            </button>
            <button v-if="editingRelationshipId" class="btn-secondary w-full mt-2" @click="resetRelationshipForm">
              取消编辑
            </button>
          </div>

          <!-- 关系列表 -->
          <div class="relationship-list">
            <h4>已有关系</h4>
            <PanelCard
              v-for="rel in relationships"
              :key="rel.id"
              :title="`${getCharacterName(rel.source_char_id)} ${rel.relation_type} ${getCharacterName(rel.target_char_id)}`"
              :subtitle="`亲密度: ${rel.affinity_score ?? 50}`"
              :actions="[
                { icon: 'pencil', label: '编辑', onClick: () => editRelationship(rel) },
                { icon: 'trash', label: '删除', onClick: () => deleteRelationship(rel.id), variant: 'danger' }
              ]"
            />
            <PanelEmpty
              v-if="relationships.length === 0"
              icon="link"
              title="暂没有关系"
              description="使用上方表单添加角色之间的关系"
            />
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.character-panel-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
}

.characters-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.character-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.importance-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.meta-item {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 150px;
}

.meta-item.dynamic {
  color: var(--accent-500);
}

.meta-item.current {
  color: #d97706;
}

/* 模态框样式 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 20px;
}

.modal-content {
  background: var(--bg-primary);
  border-radius: 16px;
  width: 100%;
  max-width: 480px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.modal-content.relationship-modal {
  max-width: 560px;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.drawer-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: var(--bg-panel);
  color: var(--text-primary);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

/* 表单样式 */
.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.form-group label .required {
  color: #dc2626;
}

.label-with-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ai-update-btn {
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  color: var(--accent-500);
  background: rgba(124, 106, 173, 0.1);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.ai-update-btn:hover:not(:disabled) {
  background: var(--accent-500);
  color: white;
}

.ai-update-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  transition: all 0.2s ease;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.form-group textarea {
  resize: vertical;
  min-height: 80px;
}

.form-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

/* 按钮样式 */
.btn-primary {
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 500;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  background: var(--accent-600);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124, 106, 173, 0.25);
}

.btn-secondary {
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.btn-primary.w-full,
.btn-secondary.w-full {
  width: 100%;
}

.mt-2 {
  margin-top: 8px;
}

/* 关系列表 */
.relationship-form {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 20px;
}

.relationship-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.relationship-list h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

/* 过渡动画 */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.25s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}

.modal-content {
  transition: all 0.25s ease;
}
</style>
