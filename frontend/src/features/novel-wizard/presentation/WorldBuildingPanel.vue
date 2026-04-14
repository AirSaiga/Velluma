<script setup lang="ts">
/**
 * 世界观构建面板
 * 
 * 职责：
 * - 管理世界背景条目
 * - 管理地点/场景
 * - 专家模式下显示世界规则配置
 */
import { ref, computed } from 'vue'
import type { WorldBuilding, WorldItem, Location, ValidationError } from '../types/wizard.types'

// =------------- Props & Emits -------------=

const props = defineProps<{
  formData: { world: WorldBuilding }
  isExpertMode: boolean
  errors: ValidationError[]
}>()

const emit = defineEmits<{
  (e: 'add-world-item', type: 'background' | 'rules', item: WorldItem): void
  (e: 'remove-world-item', type: 'background' | 'rules', id: string): void
  (e: 'add-location', location: Location): void
  (e: 'remove-location', id: string): void
}>()

// =------------- 状态 -------------=

const newBackgroundTitle = ref('')
const newBackgroundContent = ref('')
const newLocationName = ref('')
const newLocationDesc = ref('')
const newRuleTitle = ref('')
const newRuleContent = ref('')
const showImportExport = ref(false)
const importExportText = ref('')

// =------------- 计算属性 -------------=

const world = computed(() => props.formData.world)
const hasBackground = computed(() => world.value.background.length > 0)
const hasLocations = computed(() => world.value.locations.length > 0)
const hasRules = computed(() => world.value.rules.length > 0)

// =------------- 方法 -------------=

function generateId(): string {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function addBackground() {
  if (!newBackgroundTitle.value.trim()) return
  
  emit('add-world-item', 'background', {
    id: generateId(),
    title: newBackgroundTitle.value.trim(),
    content: newBackgroundContent.value.trim(),
    collapsed: false
  })
  
  newBackgroundTitle.value = ''
  newBackgroundContent.value = ''
}

function addLocation() {
  if (!newLocationName.value.trim()) return
  
  emit('add-location', {
    id: generateId(),
    name: newLocationName.value.trim(),
    description: newLocationDesc.value.trim(),
    tags: []
  })
  
  newLocationName.value = ''
  newLocationDesc.value = ''
}

function addRule() {
  if (!newRuleTitle.value.trim()) return
  
  emit('add-world-item', 'rules', {
    id: generateId(),
    title: newRuleTitle.value.trim(),
    content: newRuleContent.value.trim(),
    collapsed: false
  })
  
  newRuleTitle.value = ''
  newRuleContent.value = ''
}

function openImportExport() {
  importExportText.value = JSON.stringify({
    background: world.value.background,
    locations: world.value.locations,
    rules: world.value.rules
  }, null, 2)
  showImportExport.value = true
}

function applyImport() {
  try {
    const parsed = JSON.parse(importExportText.value || '{}')
    // 这里需要批量更新，暂时简化处理
    showImportExport.value = false
  } catch {
    console.error('导入内容不是合法 JSON')
  }
}
</script>

<template>
  <div class="world-building-panel h-full overflow-y-auto p-6">
    <div class="max-w-3xl mx-auto space-y-8">
      
      <!-- 标题 -->
      <div class="text-center mb-8">
        <h2 class="text-2xl font-heading font-semibold text-[var(--text-primary)] mb-2">
          构建你的世界 🌍
        </h2>
        <p class="text-sm text-[var(--text-muted)]">
          定义故事发生的时代背景、重要地点和世界规则
        </p>
      </div>
      
      <!-- 世界背景 -->
      <section>
        <div class="flex items-center justify-between mb-4">
          <div>
            <h3 class="text-lg font-medium text-[var(--text-primary)]">世界背景</h3>
            <p class="text-xs text-[var(--text-muted)] mt-0.5">
              描述故事发生的时代、社会、历史背景
            </p>
          </div>
          <button
            @click="openImportExport"
            class="px-3 py-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-[var(--bg-panel)] rounded-lg transition-colors"
          >
            导入/导出
          </button>
        </div>
        
        <!-- 已有条目 -->
        <div v-if="hasBackground" class="space-y-2 mb-4">
          <div
            v-for="item in world.background"
            :key="item.id"
            class="bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]/50 overflow-hidden"
          >
            <div class="flex items-center gap-2 px-4 py-3">
              <span class="text-sm font-medium text-[var(--text-primary)]">{{ item.title }}</span>
              <span class="flex-1"></span>
              <button
                @click="emit('remove-world-item', 'background', item.id)"
                class="p-1 text-[var(--text-muted)] hover:text-rose-500 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div v-if="item.content" class="px-4 pb-3 pt-0">
              <p class="text-xs text-[var(--text-muted)] line-clamp-2">{{ item.content }}</p>
            </div>
          </div>
        </div>
        
        <!-- 添加新条目 -->
        <div class="bg-[var(--bg-panel)]/50 rounded-xl p-4 border border-dashed border-[var(--border-color)]">
          <div class="grid grid-cols-1 gap-3">
            <input
              v-model="newBackgroundTitle"
              type="text"
              placeholder="条目标题，如：历史背景、社会结构..."
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
            />
            <textarea
              v-model="newBackgroundContent"
              rows="3"
              placeholder="详细描述..."
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
            />
            <button
              @click="addBackground"
              :disabled="!newBackgroundTitle.trim()"
              class="self-end px-4 py-2 text-sm font-medium bg-accent-500 hover:bg-accent-600 disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-muted)] text-white rounded-lg transition-colors"
            >
              添加条目
            </button>
          </div>
        </div>
      </section>
      
      <!-- 地点/场景 -->
      <section>
        <div class="mb-4">
          <h3 class="text-lg font-medium text-[var(--text-primary)]">地点/场景</h3>
          <p class="text-xs text-[var(--text-muted)] mt-0.5">
            故事中会出现的各种地点
          </p>
        </div>
        
        <!-- 已有地点 -->
        <div v-if="hasLocations" class="grid grid-cols-2 gap-3 mb-4">
          <div
            v-for="loc in world.locations"
            :key="loc.id"
            class="bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]/50 p-3 group"
          >
            <div class="flex items-start justify-between">
              <div class="flex-1 min-w-0">
                <h4 class="text-sm font-medium text-[var(--text-primary)] truncate">{{ loc.name }}</h4>
                <p v-if="loc.description" class="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">
                  {{ loc.description }}
                </p>
              </div>
              <button
                @click="emit('remove-location', loc.id)"
                class="p-1 opacity-0 group-hover:opacity-100 text-[var(--text-muted)] hover:text-rose-500 transition-all"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
        </div>
        
        <!-- 添加新地点 -->
        <div class="flex gap-3">
          <input
            v-model="newLocationName"
            type="text"
            placeholder="地点名称"
            class="flex-1 px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
          />
          <input
            v-model="newLocationDesc"
            type="text"
            placeholder="简短描述（可选）"
            class="flex-1 px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
          />
          <button
            @click="addLocation"
            :disabled="!newLocationName.trim()"
            class="px-4 py-2 text-sm font-medium bg-accent-500 hover:bg-accent-600 disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-muted)] text-white rounded-lg transition-colors"
          >
            添加
          </button>
        </div>
      </section>
      
      <!-- 世界规则（仅专家模式） -->
      <Transition name="expand">
        <section v-if="isExpertMode" class="pt-6 border-t border-[var(--border-color)]/30">
          <div class="flex items-center gap-2 mb-4">
            <span class="px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-600 rounded">专家</span>
            <h3 class="text-lg font-medium text-[var(--text-primary)]">世界规则</h3>
          </div>
          <p class="text-xs text-[var(--text-muted)] mb-4">
            定义魔法体系、科技水平、社会规则等深层设定
          </p>
          
          <!-- 已有规则 -->
          <div v-if="hasRules" class="space-y-2 mb-4">
            <div
              v-for="rule in world.rules"
              :key="rule.id"
              class="bg-[var(--bg-panel)] rounded-xl border border-amber-500/20 overflow-hidden"
            >
              <div class="flex items-center gap-2 px-4 py-3">
                <span class="text-sm font-medium text-[var(--text-primary)]">{{ rule.title }}</span>
                <span class="flex-1"></span>
                <button
                  @click="emit('remove-world-item', 'rules', rule.id)"
                  class="p-1 text-[var(--text-muted)] hover:text-rose-500 transition-colors"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
          
          <!-- 添加新规则 -->
          <div class="bg-amber-500/5 rounded-xl p-4 border border-dashed border-amber-500/30">
            <div class="grid grid-cols-1 gap-3">
              <input
                v-model="newRuleTitle"
                type="text"
                placeholder="规则名称，如：魔法体系、社会等级..."
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-amber-500/40"
              />
              <textarea
                v-model="newRuleContent"
                rows="3"
                placeholder="详细规则描述..."
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-amber-500/40 resize-none"
              />
              <button
                @click="addRule"
                :disabled="!newRuleTitle.trim()"
                class="self-end px-4 py-2 text-sm font-medium bg-amber-500 hover:bg-amber-600 disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-muted)] text-white rounded-lg transition-colors"
              >
                添加规则
              </button>
            </div>
          </div>
        </section>
      </Transition>
      
      <!-- 提示信息 -->
      <div class="bg-[var(--bg-panel)]/50 rounded-xl p-4 mt-6">
        <div class="flex items-start gap-3">
          <span class="text-lg">💡</span>
          <div class="text-sm text-[var(--text-secondary)]">
            <p class="font-medium mb-1">小贴士</p>
            <p class="text-xs text-[var(--text-muted)]">
              世界观设定可以帮助 AI 保持故事的一致性。如果只是简单的故事，可以跳过此步骤，
              在后续创作中逐步补充。
            </p>
          </div>
        </div>
      </div>
      
    </div>
    
    <!-- 导入导出弹窗 -->
    <Transition name="modal">
      <div
        v-if="showImportExport"
        class="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50"
        @click.self="showImportExport = false"
      >
        <div class="bg-[var(--bg-secondary)] rounded-2xl shadow-xl p-6 w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
          <h3 class="text-lg font-heading font-semibold text-[var(--text-primary)] mb-4">
            世界观导入 / 导出
          </h3>
          <textarea
            v-model="importExportText"
            rows="14"
            class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none font-mono"
          />
          <div class="flex justify-end gap-3 mt-4">
            <button
              @click="showImportExport = false"
              class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              关闭
            </button>
            <button
              @click="applyImport"
              class="px-4 py-2 bg-[var(--accent-500)] text-white rounded-full transition-colors"
            >
              导入并应用
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
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 1000px;
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
