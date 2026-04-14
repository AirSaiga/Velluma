<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Chapter, Character } from '../../../types'
import type { Asset } from '../../../shared/types'

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  assets?: Asset[]
  isCharacterSelected: (id: string) => boolean
  isAssetSelected: (id: string) => boolean
}>()

const emit = defineEmits<{
  (e: 'toggle-character', charId: string): void
  (e: 'toggle-asset', assetId: string): void
  (e: 'update-chapter', chapterId: string, updates: Record<string, any>): void
  (e: 'close'): void
}>()

const characterSearchQuery = ref('')
const assetSearchQuery = ref('')
const showCharacterSelector = ref(false)
const showAssetSelector = ref(false)

const selectedCharacters = computed(() => {
  return props.characters.filter(c => props.isCharacterSelected(c.id))
})

const filteredCharacters = computed(() => {
  if (!characterSearchQuery.value) return props.characters
  const query = characterSearchQuery.value.toLowerCase()
  return props.characters.filter(c => c.name.toLowerCase().includes(query))
})

const selectedAssets = computed(() => {
  return props.assets?.filter(a => props.isAssetSelected(a.id)) || []
})

const filteredAssets = computed(() => {
  if (!assetSearchQuery.value) return props.assets || []
  const query = assetSearchQuery.value.toLowerCase()
  return (props.assets || []).filter(a => a.name.toLowerCase().includes(query))
})

const hasAdvancedContent = computed(() => {
  return (props.selectedChapter?.chapter_assets_schema || '').trim().length > 0
})

const characterImportanceColor = (level: number) => {
  const colors: Record<number, string> = {
    1: 'bg-gray-100/80 text-gray-700 ring-gray-200',
    2: 'bg-blue-50 text-blue-700 ring-blue-200',
    3: 'bg-violet-50 text-violet-700 ring-violet-200',
    4: 'bg-amber-50 text-amber-700 ring-amber-200'
  }
  return colors[level] || colors[1]
}

let schemaTimeout: ReturnType<typeof setTimeout> | undefined
function handleAssetsSchemaInput(e: Event) {
  if (!props.selectedChapter) return
  clearTimeout(schemaTimeout)
  const value = (e.target as HTMLTextAreaElement).value
  schemaTimeout = setTimeout(() => {
    emit('update-chapter', props.selectedChapter!.id, { chapter_assets_schema: value })
  }, 500)
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-primary)]">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border-color)]/60">
      <h3 class="text-sm font-semibold text-[var(--text-primary)] tracking-tight">章节配置</h3>
      <button @click="emit('close')" class="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-canvas)] transition-colors">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
      <!-- 本章出场人物 -->
      <div class="rounded-xl bg-[var(--bg-panel)] border border-[var(--border-color)]/50 p-3.5">
        <div class="flex items-center justify-between mb-2.5">
          <div class="flex items-center gap-1.5 text-[var(--text-secondary)]">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
            </svg>
            <h4 class="text-xs font-semibold">本章出场人物</h4>
          </div>
          <span class="text-[10px] text-[var(--text-muted)]">{{ selectedCharacters.length }}</span>
        </div>

        <div class="flex flex-wrap items-center gap-1.5">
          <span
            v-for="char in selectedCharacters"
            :key="char.id"
            class="inline-flex items-center gap-1 pl-2.5 pr-1 py-1 text-[11px] rounded-full ring-1 transition-all"
            :class="characterImportanceColor(char.importance_level)"
          >
            {{ char.name }}
            <button
              @click="emit('toggle-character', char.id)"
              class="hover:text-rose-600 hover:bg-rose-100/60 rounded-full p-0.5 transition-colors"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </span>
          <button
            @click="showCharacterSelector = !showCharacterSelector"
            class="inline-flex items-center gap-0.5 px-2 py-1 text-[11px] rounded-full text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50/60 ring-1 ring-dashed ring-[var(--border-color)] hover:ring-accent-200 transition-all"
            :class="showCharacterSelector ? 'text-[var(--accent-500)] bg-accent-50/60 ring-accent-200' : ''"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="showCharacterSelector ? 'M5 15l7-7 7 7' : 'M12 4v16m8-8H4'"/>
            </svg>
            {{ selectedCharacters.length === 0 ? '添加人物' : '添加' }}
          </button>
        </div>

        <!-- 人物选择展开面板 -->
        <div
          v-if="showCharacterSelector"
          class="mt-3 p-2.5 bg-[var(--bg-canvas)] rounded-lg border border-[var(--border-color)]/60"
        >
          <div class="relative mb-2">
            <svg class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
            <input
              v-model="characterSearchQuery"
              type="text"
              placeholder="搜索人物..."
              class="w-full pl-8 pr-3 py-1.5 text-[11px] rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent-500)] transition-colors"
            />
          </div>
          <div class="max-h-40 overflow-y-auto custom-scrollbar">
            <div v-if="filteredCharacters.length === 0" class="text-center py-3 text-[11px] text-[var(--text-muted)]">
              未找到匹配的人物
            </div>
            <div v-else class="grid grid-cols-2 gap-1.5">
              <button
                v-for="char in filteredCharacters"
                :key="char.id"
                @click="emit('toggle-character', char.id)"
                class="px-2 py-1.5 text-[11px] rounded-md text-left transition-all border truncate"
                :class="isCharacterSelected(char.id)
                  ? 'bg-accent-50 text-accent-700 border-accent-300 shadow-sm'
                  : 'bg-[var(--bg-primary)] text-[var(--text-secondary)] border-[var(--border-color)] hover:border-accent-200 hover:bg-accent-50/30'"
              >
                <div class="flex items-center gap-1">
                  <span v-if="isCharacterSelected(char.id)" class="text-accent-500 shrink-0">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                    </svg>
                  </span>
                  <span class="truncate">{{ char.name }}</span>
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 本章关键道具 -->
      <div class="rounded-xl bg-[var(--bg-panel)] border border-[var(--border-color)]/50 p-3.5">
        <div class="flex items-center justify-between mb-2.5">
          <div class="flex items-center gap-1.5 text-[var(--text-secondary)]">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
            </svg>
            <h4 class="text-xs font-semibold">本章关键道具</h4>
          </div>
          <span class="text-[10px] text-[var(--text-muted)]">{{ selectedAssets.length }}</span>
        </div>

        <div class="flex flex-wrap items-center gap-1.5">
          <span
            v-for="asset in selectedAssets"
            :key="asset.id"
            class="inline-flex items-center gap-1 pl-2.5 pr-1 py-1 text-[11px] rounded-full ring-1 transition-all bg-emerald-50 text-emerald-700 ring-emerald-200"
          >
            {{ asset.name }}
            <button
              @click="emit('toggle-asset', asset.id)"
              class="hover:text-rose-600 hover:bg-rose-100/60 rounded-full p-0.5 transition-colors"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </span>
          <button
            @click="showAssetSelector = !showAssetSelector"
            class="inline-flex items-center gap-0.5 px-2 py-1 text-[11px] rounded-full text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50/60 ring-1 ring-dashed ring-[var(--border-color)] hover:ring-accent-200 transition-all"
            :class="showAssetSelector ? 'text-[var(--accent-500)] bg-accent-50/60 ring-accent-200' : ''"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="showAssetSelector ? 'M5 15l7-7 7 7' : 'M12 4v16m8-8H4'"/>
            </svg>
            {{ selectedAssets.length === 0 ? '添加道具' : '添加' }}
          </button>
        </div>

        <!-- 道具选择展开面板 -->
        <div
          v-if="showAssetSelector"
          class="mt-3 p-2.5 bg-[var(--bg-canvas)] rounded-lg border border-[var(--border-color)]/60"
        >
          <div class="relative mb-2">
            <svg class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
            <input
              v-model="assetSearchQuery"
              type="text"
              placeholder="搜索道具..."
              class="w-full pl-8 pr-3 py-1.5 text-[11px] rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent-500)] transition-colors"
            />
          </div>
          <div class="max-h-40 overflow-y-auto custom-scrollbar">
            <div v-if="filteredAssets.length === 0" class="text-center py-3 text-[11px] text-[var(--text-muted)]">
              未找到匹配的道具
            </div>
            <div v-else class="grid grid-cols-2 gap-1.5">
              <button
                v-for="asset in filteredAssets"
                :key="asset.id"
                @click="emit('toggle-asset', asset.id)"
                class="px-2 py-1.5 text-[11px] rounded-md text-left transition-all border truncate"
                :class="isAssetSelected(asset.id)
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-300 shadow-sm'
                  : 'bg-[var(--bg-primary)] text-[var(--text-secondary)] border-[var(--border-color)] hover:border-accent-200 hover:bg-accent-50/30'"
              >
                <div class="flex items-center gap-1">
                  <span v-if="isAssetSelected(asset.id)" class="text-emerald-500 shrink-0">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                    </svg>
                  </span>
                  <span class="truncate">{{ asset.name }}</span>
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Asset Schema -->
      <div class="rounded-xl bg-[var(--bg-panel)] border border-[var(--border-color)]/50 p-3.5">
        <div class="flex items-center gap-2 mb-2.5">
          <svg class="w-4 h-4 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/>
          </svg>
          <h4 class="text-xs font-semibold text-[var(--text-secondary)]">
            本章专属设定
            <span v-if="hasAdvancedContent" class="ml-1.5 w-1.5 h-1.5 rounded-full bg-amber-400 inline-block align-middle"></span>
          </h4>
        </div>

        <textarea
          :value="selectedChapter?.chapter_assets_schema || ''"
          @input="handleAssetsSchemaInput"
          rows="4"
          class="w-full px-3 py-2.5 rounded-lg bg-[var(--bg-canvas)] text-[var(--text-primary)] text-xs leading-relaxed focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-[var(--accent-500)] resize-y transition-shadow"
          placeholder="输入仅在本章生效的临时设定..."
        />
        <p class="mt-2 text-[10px] text-[var(--text-muted)] leading-relaxed">
          这些设定仅在当前章节有效，不会影响到其他章节的世界观。
        </p>
      </div>
    </div>
  </div>
</template>
