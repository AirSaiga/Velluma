<script setup lang="ts">
import { useAssetContainer } from '../containers/useAssetContainer'
import type { Asset } from '../../../shared/types'

const props = defineProps<{
  bookId?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const {
  assets,
  filteredAssets,
  isLoading,
  searchQuery,
  showEditModal,
  isEditing,
  formData,
  openCreateModal,
  openEditModal,
  saveAsset,
  deleteAsset
} = useAssetContainer(props)

function getImportanceColor(level: number) {
  const colors: Record<number, string> = {
    1: 'bg-gray-100 text-gray-600 border-gray-200',
    2: 'bg-blue-50 text-blue-600 border-blue-200',
    3: 'bg-violet-50 text-violet-600 border-violet-200',
    4: 'bg-amber-50 text-amber-600 border-amber-200',
    5: 'bg-rose-50 text-rose-600 border-rose-200'
  }
  return colors[level] || colors[1]
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-primary)] overflow-hidden">
    <!-- 头部区域 -->
    <div class="p-4 border-b border-[var(--border-color)] flex-shrink-0 bg-[var(--bg-canvas)]">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-heading font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <svg class="w-5 h-5 text-[var(--accent-500)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
          </svg>
          资产管理
        </h2>
        <div class="flex items-center gap-2">
          <button 
            @click="openCreateModal"
            class="px-3 py-1.5 text-xs font-medium bg-[var(--accent-500)] text-white rounded-lg hover:bg-accent-600 transition-colors shadow-sm flex items-center gap-1"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            新建资产
          </button>
          <button @click="emit('close')" class="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-panel)] rounded-md transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>
      
      <!-- 搜索框 -->
      <div class="relative">
        <svg class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
        </svg>
        <input 
          v-model="searchQuery"
          type="text" 
          placeholder="搜索资产名称或别名..."
          class="w-full pl-9 pr-4 py-2 text-sm bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/20 focus:border-[var(--accent-500)] transition-all placeholder:text-[var(--text-muted)]"
        />
      </div>
    </div>

    <!-- 列表区域 -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="isLoading" class="flex justify-center items-center py-8">
        <svg class="animate-spin h-6 w-6 text-[var(--accent-500)]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      </div>
      
      <div v-else-if="filteredAssets.length === 0" class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 rounded-full bg-[var(--bg-canvas)] flex items-center justify-center">
          <svg class="w-8 h-8 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
          </svg>
        </div>
        <p class="text-[var(--text-secondary)] font-medium mb-1">暂无资产</p>
        <p class="text-sm text-[var(--text-muted)]">点击右上角"新建资产"添加道具或法宝</p>
      </div>

      <div v-else class="space-y-3">
        <div 
          v-for="asset in filteredAssets" 
          :key="asset.id"
          class="bg-[var(--bg-canvas)] rounded-xl border border-[var(--border-color)] overflow-hidden hover:border-[var(--accent-300)] transition-colors group"
        >
          <div class="p-3 border-b border-[var(--border-color)]/50 flex items-start justify-between bg-[var(--bg-primary)]/50">
            <div class="flex-1 min-w-0 pr-4">
              <div class="flex items-center gap-2 mb-1">
                <h3 class="font-medium text-[var(--text-primary)] truncate">{{ asset.name }}</h3>
                <span 
                  class="px-2 py-0.5 text-[10px] font-medium rounded-full border"
                  :class="getImportanceColor(asset.importance_level)"
                >
                  T{{ asset.importance_level }}
                </span>
              </div>
              <div v-if="asset.aliases?.length" class="text-xs text-[var(--text-muted)] truncate">
                别名: {{ asset.aliases.join(', ') }}
              </div>
            </div>
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button 
                @click="openEditModal(asset)"
                class="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50 rounded-md transition-colors"
                title="编辑"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                </svg>
              </button>
              <button 
                @click="deleteAsset(asset.id)"
                class="p-1.5 text-[var(--text-muted)] hover:text-rose-500 hover:bg-rose-50 rounded-md transition-colors"
                title="删除"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                </svg>
              </button>
            </div>
          </div>
          
          <div class="p-3 space-y-3">
            <div v-if="asset.static_description">
              <div class="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-1">静态设定</div>
              <p class="text-xs text-[var(--text-secondary)] line-clamp-2 leading-relaxed">{{ asset.static_description }}</p>
            </div>
            
            <div v-if="asset.current_state">
              <div class="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-1">当前状态</div>
              <p class="text-xs text-amber-600 bg-amber-50 px-2 py-1.5 rounded-md line-clamp-2">{{ asset.current_state }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑模态框 -->
    <Teleport to="body">
      <div v-if="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" @click="showEditModal = false"></div>
        <div class="relative bg-[var(--bg-primary)] rounded-xl shadow-xl w-full max-w-lg flex flex-col max-h-[90vh]">
          <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between shrink-0">
            <h3 class="text-lg font-semibold text-[var(--text-primary)]">
              {{ isEditing ? '编辑资产' : '新建资产' }}
            </h3>
            <button @click="showEditModal = false" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
          
          <div class="p-4 overflow-y-auto flex-1 space-y-4">
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1.5">资产名称 *</label>
              <input 
                v-model="formData.name"
                type="text" 
                class="w-full px-3 py-2 bg-[var(--bg-canvas)] border border-[var(--border-color)] rounded-lg focus:outline-none focus:border-[var(--accent-500)] text-sm text-[var(--text-primary)]"
                placeholder="例如：霜之哀伤"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1.5">别名 (逗号分隔)</label>
              <input 
                v-model="formData.aliases"
                type="text" 
                class="w-full px-3 py-2 bg-[var(--bg-canvas)] border border-[var(--border-color)] rounded-lg focus:outline-none focus:border-[var(--accent-500)] text-sm text-[var(--text-primary)]"
                placeholder="例如：魔剑, 诅咒之剑"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1.5">重要性等级</label>
              <div class="flex items-center gap-4">
                <input 
                  v-model.number="formData.importance_level"
                  type="range" 
                  min="1" 
                  max="5" 
                  step="1"
                  class="flex-1 accent-[var(--accent-500)]"
                />
                <span class="text-sm font-medium w-16 text-center" :class="getImportanceColor(formData.importance_level).replace('bg-', 'text-').replace('text-', '')">
                  Tier {{ formData.importance_level }}
                </span>
              </div>
              <p class="text-xs text-[var(--text-muted)] mt-1">等级越高，在生成章节时越容易被优先分配上下文 token</p>
            </div>

            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1.5">静态设定</label>
              <textarea 
                v-model="formData.static_description"
                rows="3"
                class="w-full px-3 py-2 bg-[var(--bg-canvas)] border border-[var(--border-color)] rounded-lg focus:outline-none focus:border-[var(--accent-500)] text-sm text-[var(--text-primary)] resize-y"
                placeholder="描述资产的外观、基础功能、历史渊源等永恒不变的属性..."
              ></textarea>
            </div>

            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1.5">当前状态</label>
              <textarea 
                v-model="formData.current_state"
                rows="2"
                class="w-full px-3 py-2 bg-[var(--bg-canvas)] border border-[var(--border-color)] rounded-lg focus:outline-none focus:border-[var(--accent-500)] text-sm text-[var(--text-primary)] resize-y"
                placeholder="描述资产目前的状况，例如：轻微破损、充能中、被封印..."
              ></textarea>
              <p class="text-xs text-[var(--text-muted)] mt-1">章节发布时，大模型会根据剧情自动更新资产状态。</p>
            </div>
          </div>

          <div class="p-4 border-t border-[var(--border-color)] flex justify-end gap-2 shrink-0 bg-[var(--bg-canvas)]">
            <button 
              @click="showEditModal = false"
              class="px-4 py-2 text-sm font-medium text-[var(--text-secondary)] bg-[var(--bg-panel)] rounded-lg hover:bg-black/5 transition-colors border border-[var(--border-color)]"
            >
              取消
            </button>
            <button 
              @click="saveAsset"
              class="px-4 py-2 text-sm font-medium text-white bg-[var(--accent-500)] rounded-lg hover:bg-accent-600 transition-colors shadow-sm"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
