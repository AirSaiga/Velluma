<script setup lang="ts">
/**
 * 角色管理面板
 * 
 * 职责：
 * - 管理角色列表
 * - 管理角色关系
 * - 提供关系图可视化
 * - 专家模式下显示更多角色属性
 */
import { ref, computed } from 'vue'
import type { 
  CharacterInfo, 
  CharacterRelationship, 
  CharacterImportance,
  ValidationError 
} from '../types/wizard.types'

// =------------- Props & Emits -------------=

const props = defineProps<{
  formData: { characters: CharacterInfo[]; relationships: CharacterRelationship[] }
  isExpertMode: boolean
  errors: ValidationError[]
}>()

const emit = defineEmits<{
  (e: 'add-character', character: CharacterInfo): void
  (e: 'update-character', id: string, updates: Partial<CharacterInfo>): void
  (e: 'remove-character', id: string): void
  (e: 'add-relationship', relationship: CharacterRelationship): void
  (e: 'update-relationship', id: string, updates: Partial<CharacterRelationship>): void
  (e: 'remove-relationship', id: string): void
}>()

// =------------- 状态 -------------=

const showCharacterModal = ref(false)
const showRelationshipModal = ref(false)
const editingCharacterId = ref<string | null>(null)
const editingRelationshipId = ref<string | null>(null)
const searchQuery = ref('')

// 角色表单
const characterForm = ref({
  name: '',
  importance: 'normal' as CharacterImportance,
  profile: '',
  currentState: '',
  instantState: ''
})

// 关系表单
const relationshipForm = ref({
  sourceId: '',
  targetId: '',
  relationType: '',
  affinity: 50,
  interactionPattern: ''
})

// =------------- 计算属性 -------------=

const filteredCharacters = computed(() => {
  if (!searchQuery.value) return props.formData.characters
  const query = searchQuery.value.toLowerCase()
  return props.formData.characters.filter(c => 
    c.name.toLowerCase().includes(query) ||
    c.profile.toLowerCase().includes(query)
  )
})

const sortedCharacters = computed(() => {
  const importanceOrder: Record<CharacterImportance, number> = {
    core: 4,
    protagonist: 3,
    important: 2,
    normal: 1
  }
  return [...filteredCharacters.value].sort((a, b) => 
    importanceOrder[b.importance] - importanceOrder[a.importance]
  )
})

const importanceLabels: Record<CharacterImportance, string> = {
  normal: '普通',
  important: '重要',
  protagonist: '主角',
  core: '核心'
}

const importanceColors: Record<CharacterImportance, string> = {
  normal: 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]',
  important: 'bg-blue-500/10 text-blue-600',
  protagonist: 'bg-purple-500/10 text-purple-600',
  core: 'bg-amber-500/10 text-amber-600'
}

// =------------- 方法 -------------=

function generateId(): string {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function openCreateCharacter() {
  editingCharacterId.value = null
  characterForm.value = {
    name: '',
    importance: 'normal',
    profile: '',
    currentState: '',
    instantState: ''
  }
  showCharacterModal.value = true
}

function openEditCharacter(char: CharacterInfo) {
  editingCharacterId.value = char.id
  characterForm.value = {
    name: char.name,
    importance: char.importance,
    profile: char.profile,
    currentState: char.currentState,
    instantState: char.instantState
  }
  showCharacterModal.value = true
}

function saveCharacter() {
  if (!characterForm.value.name.trim()) return
  
  if (editingCharacterId.value) {
    emit('update-character', editingCharacterId.value, {
      name: characterForm.value.name,
      importance: characterForm.value.importance,
      profile: characterForm.value.profile,
      currentState: characterForm.value.currentState,
      instantState: characterForm.value.instantState
    })
  } else {
    emit('add-character', {
      id: generateId(),
      name: characterForm.value.name,
      importance: characterForm.value.importance,
      profile: characterForm.value.profile,
      currentState: characterForm.value.currentState,
      instantState: characterForm.value.instantState
    })
  }
  
  showCharacterModal.value = false
}

function deleteCharacter(id: string) {
  emit('remove-character', id)
}

function openCreateRelationship() {
  editingRelationshipId.value = null
  relationshipForm.value = {
    sourceId: props.formData.characters[0]?.id || '',
    targetId: props.formData.characters[1]?.id || '',
    relationType: '',
    affinity: 50,
    interactionPattern: ''
  }
  showRelationshipModal.value = true
}

function openEditRelationship(rel: CharacterRelationship) {
  editingRelationshipId.value = rel.id
  relationshipForm.value = {
    sourceId: rel.sourceId,
    targetId: rel.targetId,
    relationType: rel.relationType,
    affinity: rel.affinity,
    interactionPattern: rel.interactionPattern
  }
  showRelationshipModal.value = true
}

function saveRelationship() {
  if (!relationshipForm.value.sourceId || 
      !relationshipForm.value.targetId || 
      !relationshipForm.value.relationType) return
  
  if (editingRelationshipId.value) {
    emit('update-relationship', editingRelationshipId.value, {
      sourceId: relationshipForm.value.sourceId,
      targetId: relationshipForm.value.targetId,
      relationType: relationshipForm.value.relationType,
      affinity: relationshipForm.value.affinity,
      interactionPattern: relationshipForm.value.interactionPattern
    })
  } else {
    emit('add-relationship', {
      id: generateId(),
      sourceId: relationshipForm.value.sourceId,
      targetId: relationshipForm.value.targetId,
      relationType: relationshipForm.value.relationType,
      affinity: relationshipForm.value.affinity,
      interactionPattern: relationshipForm.value.interactionPattern
    })
  }
  
  showRelationshipModal.value = false
}

function deleteRelationship(id: string) {
  emit('remove-relationship', id)
}

function getCharacterName(id: string): string {
  return props.formData.characters.find(c => c.id === id)?.name || id
}

function getAffinityColor(affinity: number): string {
  if (affinity >= 70) return 'text-green-500'
  if (affinity >= 40) return 'text-[var(--text-muted)]'
  return 'text-red-500'
}
</script>

<template>
  <div class="character-manager-panel h-full overflow-y-auto p-6">
    <div class="max-w-4xl mx-auto">
      
      <!-- 标题 -->
      <div class="text-center mb-8">
        <h2 class="text-2xl font-heading font-semibold text-[var(--text-primary)] mb-2">
          角色管理 👥
        </h2>
        <p class="text-sm text-[var(--text-muted)]">
          创建故事中的角色，定义他们的属性和关系
        </p>
      </div>
      
      <!-- 操作栏 -->
      <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-3">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索角色..."
            class="w-48 px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
          />
        </div>
        <div class="flex items-center gap-2">
          <button
            @click="openCreateRelationship"
            :disabled="formData.characters.length < 2"
            class="px-3 py-2 text-sm font-medium bg-[var(--bg-panel)] hover:bg-[var(--bg-secondary)] text-[var(--text-primary)] rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            + 关系
          </button>
          <button
            @click="openCreateCharacter"
            class="px-4 py-2 text-sm font-medium bg-accent-500 hover:bg-accent-600 text-white rounded-lg transition-colors"
          >
            + 新建角色
          </button>
        </div>
      </div>
      
      <!-- 角色列表 -->
      <div class="grid grid-cols-2 gap-4 mb-8">
        <div
          v-for="char in sortedCharacters"
          :key="char.id"
          @click="openEditCharacter(char)"
          class="bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]/50 p-4 cursor-pointer hover:border-accent-500/50 transition-all group reveal-parent"
        >
          <div class="flex items-start justify-between mb-2">
            <div class="flex items-center gap-2">
              <span
                :class="importanceColors[char.importance]"
                class="px-2 py-0.5 text-xs font-medium rounded-full"
              >
                {{ importanceLabels[char.importance] }}
              </span>
              <h4 class="text-base font-medium text-[var(--text-primary)]">{{ char.name }}</h4>
            </div>
            <button
              @click.stop="deleteCharacter(char.id)"
              class="p-1 reveal-on-hover--danger text-[var(--text-muted)] hover:text-rose-500 transition-all"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          <p v-if="char.profile" class="text-xs text-[var(--text-muted)] line-clamp-2 mb-2">
            {{ char.profile }}
          </p>
          
          <div v-if="char.currentState" class="mt-2 pt-2 border-t border-[var(--border-color)]/30">
            <p class="text-xs text-accent-600">
              <span class="font-medium">当前状态：</span>{{ char.currentState }}
            </p>
          </div>
          
          <div v-if="isExpertMode && char.instantState" class="mt-1">
            <p class="text-xs text-amber-600">
              <span class="font-medium">此刻状态：</span>{{ char.instantState }}
            </p>
          </div>
        </div>
        
        <!-- 空状态 -->
        <div
          v-if="sortedCharacters.length === 0"
          class="col-span-2 py-12 text-center"
        >
          <p class="text-[var(--text-muted)] mb-4">还没有创建任何角色</p>
          <button
            @click="openCreateCharacter"
            class="px-4 py-2 text-sm font-medium bg-accent-500 hover:bg-accent-600 text-white rounded-lg transition-colors"
          >
            创建第一个角色
          </button>
        </div>
      </div>
      
      <!-- 关系图可视化（简化版） -->
      <div v-if="formData.relationships.length > 0" class="mt-8">
        <h3 class="text-lg font-medium text-[var(--text-primary)] mb-4">人物关系</h3>
        <div class="bg-[var(--bg-panel)]/50 rounded-xl p-4 border border-[var(--border-color)]/30">
          <div class="space-y-2">
            <div
              v-for="rel in formData.relationships"
              :key="rel.id"
              @click="openEditRelationship(rel)"
              class="flex items-center justify-between px-3 py-2 bg-[var(--bg-panel)] rounded-lg cursor-pointer hover:bg-[var(--bg-secondary)] transition-colors group reveal-parent"
            >
              <div class="flex items-center gap-3">
                <span class="text-sm font-medium text-[var(--text-primary)]">
                  {{ getCharacterName(rel.sourceId) }}
                </span>
                <div class="flex items-center gap-1">
                  <div class="w-8 h-0.5 bg-[var(--border-color)]"></div>
                  <span class="text-xs text-[var(--text-muted)] px-2 py-0.5 bg-[var(--bg-secondary)] rounded">
                    {{ rel.relationType }}
                  </span>
                  <div class="w-8 h-0.5 bg-[var(--border-color)]"></div>
                </div>
                <span class="text-sm font-medium text-[var(--text-primary)]">
                  {{ getCharacterName(rel.targetId) }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <span 
                  class="text-xs"
                  :class="getAffinityColor(rel.affinity)"
                >
                  {{ rel.affinity }}%
                </span>
                <button
                  @click.stop="deleteRelationship(rel.id)"
                  class="p-1 reveal-on-hover--danger text-[var(--text-muted)] hover:text-rose-500 transition-all"
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 关系图占位（无关系时） -->
      <div v-else-if="formData.characters.length >= 2" class="mt-8">
        <div class="bg-[var(--bg-panel)]/30 rounded-xl p-8 border border-dashed border-[var(--border-color)] text-center">
          <p class="text-sm text-[var(--text-muted)] mb-3">添加角色之间的关系</p>
          <button
            @click="openCreateRelationship"
            class="px-4 py-2 text-sm font-medium bg-[var(--bg-panel)] hover:bg-[var(--bg-secondary)] text-[var(--text-primary)] rounded-lg transition-colors"
          >
            创建关系
          </button>
        </div>
      </div>
      
    </div>
    
    <!-- 角色编辑弹窗 -->
    <Transition name="modal">
      <div
        v-if="showCharacterModal"
        class="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[var(--z-modal)]"
        @click.self="showCharacterModal = false"
      >
        <div class="bg-[var(--bg-secondary)] rounded-2xl shadow-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
          <h3 class="text-lg font-heading font-semibold text-[var(--text-primary)] mb-4">
            {{ editingCharacterId ? '编辑角色' : '新建角色' }}
          </h3>
          
          <div class="space-y-4">
            <!-- 名称 -->
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">角色名称</label>
              <input
                v-model="characterForm.name"
                type="text"
                placeholder="输入角色名称"
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
              />
            </div>
            
            <!-- 重要程度 -->
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">重要程度</label>
              <div class="grid grid-cols-4 gap-2">
                <button
                  v-for="(label, key) in importanceLabels"
                  :key="key"
                  @click="characterForm.importance = key as CharacterImportance"
                  :class="[
                    'px-3 py-2 text-xs rounded-lg transition-colors',
                    characterForm.importance === key
                      ? 'bg-accent-500 text-white'
                      : 'bg-[var(--bg-panel)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
                  ]"
                >
                  {{ label }}
                </button>
              </div>
            </div>
            
            <!-- 角色档案 -->
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">角色档案</label>
              <textarea
                v-model="characterForm.profile"
                rows="4"
                placeholder="外貌、性格、背景故事等基本设定..."
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              />
            </div>
            
            <!-- 当前状态 -->
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">当前状态</label>
              <textarea
                v-model="characterForm.currentState"
                rows="2"
                placeholder="角色在故事发展中的最新状态..."
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              />
            </div>
            
            <!-- 此刻状态（仅专家模式） -->
            <Transition name="expand">
              <div v-if="isExpertMode">
                <label class="block text-sm text-[var(--text-muted)] mb-1">
                  <span class="flex items-center gap-1.5">
                    <span class="px-1.5 py-0.5 text-xs bg-amber-500/10 text-amber-600 rounded">专家</span>
                    此刻状态
                  </span>
                </label>
                <textarea
                  v-model="characterForm.instantState"
                  rows="2"
                  placeholder="从世界快照中提取的实时状态..."
                  class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
                />
                <p class="text-xs text-[var(--text-muted)] mt-1">
                  内部字段：current_state — 通常在章节发布时自动更新
                </p>
              </div>
            </Transition>
          </div>
          
          <div class="flex justify-end gap-3 mt-6">
            <button
              @click="showCharacterModal = false"
              class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              取消
            </button>
            <button
              @click="saveCharacter"
              :disabled="!characterForm.name.trim()"
              class="px-4 py-2 bg-[var(--accent-500)] hover:bg-accent-600 disabled:bg-[var(--bg-tertiary)] text-white rounded-full transition-colors"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </Transition>
    
    <!-- 关系编辑弹窗 -->
    <Transition name="modal">
      <div
        v-if="showRelationshipModal"
        class="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[var(--z-modal)]"
        @click.self="showRelationshipModal = false"
      >
        <div class="bg-[var(--bg-secondary)] rounded-2xl shadow-xl p-6 w-full max-w-md mx-4">
          <h3 class="text-lg font-heading font-semibold text-[var(--text-primary)] mb-4">
            {{ editingRelationshipId ? '编辑关系' : '新建关系' }}
          </h3>
          
          <div class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-sm text-[var(--text-muted)] mb-1">角色 A</label>
                <select
                  v-model="relationshipForm.sourceId"
                  class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
                >
                  <option v-for="c in formData.characters" :key="c.id" :value="c.id">
                    {{ c.name }}
                  </option>
                </select>
              </div>
              <div>
                <label class="block text-sm text-[var(--text-muted)] mb-1">角色 B</label>
                <select
                  v-model="relationshipForm.targetId"
                  class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
                >
                  <option v-for="c in formData.characters" :key="c.id" :value="c.id">
                    {{ c.name }}
                  </option>
                </select>
              </div>
            </div>
            
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">关系类型</label>
              <input
                v-model="relationshipForm.relationType"
                type="text"
                placeholder="如：朋友、敌人、恋人、师徒..."
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
              />
            </div>
            
            <div>
              <label class="block text-sm text-[var(--text-muted)] mb-1">
                好感度: {{ relationshipForm.affinity }}%
              </label>
              <input
                v-model.number="relationshipForm.affinity"
                type="range"
                min="0"
                max="100"
                class="w-full"
              />
              <div class="flex justify-between text-xs text-[var(--text-muted)]">
                <span>敌对</span>
                <span>中立</span>
                <span>亲密</span>
              </div>
            </div>
            
            <!-- 互动模式（仅专家模式） -->
            <Transition name="expand">
              <div v-if="isExpertMode">
                <label class="block text-sm text-[var(--text-muted)] mb-1">
                  <span class="flex items-center gap-1.5">
                    <span class="px-1.5 py-0.5 text-xs bg-amber-500/10 text-amber-600 rounded">专家</span>
                    互动模式
                  </span>
                </label>
                <textarea
                  v-model="relationshipForm.interactionPattern"
                  rows="2"
                  placeholder="描述两人互动时的行为特点..."
                  class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
                />
              </div>
            </Transition>
          </div>
          
          <div class="flex justify-end gap-3 mt-6">
            <button
              @click="showRelationshipModal = false"
              class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              取消
            </button>
            <button
              @click="saveRelationship"
              :disabled="!relationshipForm.relationType.trim()"
              class="px-4 py-2 bg-[var(--accent-500)] hover:bg-accent-600 disabled:bg-[var(--bg-tertiary)] text-white rounded-full transition-colors"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 200px;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
