<script setup>
import { ref, watch, computed } from 'vue'
import { mapApi } from '../services/api'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const props = defineProps({
  chapter: {
    type: Object,
    required: true
  },
  focusedEntity: {
    type: String,
    default: ''
  },
  activeCharacterNames: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update-chapter'])

const mapActivityRange = ref('')
const isDirty = ref(false)
const locations = ref([]) // All available locations for the book
const chapterLocations = ref([]) // Locations associated with this chapter
const showCreateModal = ref(false)
const showEditModal = ref(false)
const editingLocation = ref(null)
const locationForm = ref({ name: '', description: '', current_state: '' })
const isLoading = ref(false)
const normalizedFocusedEntity = computed(() => (props.focusedEntity || '').trim().toLowerCase())
const normalizedActiveNames = computed(() =>
  (props.activeCharacterNames || [])
    .map((name) => String(name || '').trim().toLowerCase())
    .filter(Boolean)
)

const locationHighlightLevelMap = computed(() => {
  const focused = normalizedFocusedEntity.value
  const activeNames = normalizedActiveNames.value
  const map = new Map()
  for (const loc of locations.value) {
    const name = (loc?.name || '').toLowerCase()
    const description = (loc?.description || '').toLowerCase()
    if (focused && name && (name === focused || focused.includes(name))) {
      map.set(loc.id, 'strong')
      continue
    }
    if (focused && ((name && name.includes(focused)) || (description && description.includes(focused)))) {
      map.set(loc.id, 'weak')
      continue
    }
    if (activeNames.length > 0 && activeNames.some((token) => token && (name.includes(token) || description.includes(token)))) {
      map.set(loc.id, 'weak')
    }
  }
  return map
})

const sortedLocations = computed(() => {
  const levelMap = locationHighlightLevelMap.value
  return [...locations.value].sort((a, b) => {
    const scoreA = levelMap.get(a.id) === 'strong' ? 2 : (levelMap.get(a.id) === 'weak' ? 1 : 0)
    const scoreB = levelMap.get(b.id) === 'strong' ? 2 : (levelMap.get(b.id) === 'weak' ? 1 : 0)
    if (scoreA !== scoreB) return scoreB - scoreA
    return (a.name || '').localeCompare(b.name || '', 'zh-Hans-CN')
  })
})

function getLocationHighlightClass(locId) {
  const level = locationHighlightLevelMap.value.get(locId)
  if (level === 'strong') return 'bg-amber-50 border-amber-300 ring-1 ring-amber-200 animate-pulse'
  if (level === 'weak') return 'bg-indigo-50 border-indigo-200 ring-1 ring-indigo-100'
  return isSelected(locId)
    ? 'bg-indigo-50 border-indigo-200 hover:border-indigo-300'
    : 'bg-[var(--bg-panel)] border-transparent hover:border-slate-200'
}

// Initialize
watch(() => props.chapter?.id, async (newId, oldId) => {
  if (newId && newId !== oldId) {
    mapActivityRange.value = props.chapter.map_activity_range || ''
    isDirty.value = false
    await loadData()
  }
}, { immediate: true })

// Keep mapActivityRange in sync if it changes externally (e.g. save) but avoid overwriting user input
watch(() => props.chapter?.map_activity_range, (newVal) => {
  if (!isDirty.value && newVal !== mapActivityRange.value) {
    mapActivityRange.value = newVal || ''
  }
})

async function loadData() {
  if (!props.chapter?.book_id) return
  isLoading.value = true
  try {
    const [allLocs, chapLocs] = await Promise.all([
      mapApi.getLocations(props.chapter.book_id),
      mapApi.getChapterLocations(props.chapter.id)
    ])
    locations.value = allLocs
    chapterLocations.value = chapLocs
  } catch (e) {
    console.error('加载地图数据失败', e)
  } finally {
    isLoading.value = false
  }
}

// Activity Range Logic
function handleChange() {
  isDirty.value = true
}

function saveRange() {
  if (!props.chapter) return
  emit('update-chapter', props.chapter.id, { map_activity_range: mapActivityRange.value })
  isDirty.value = false
}

// Location Management Logic
function openCreateModal() {
  locationForm.value = { name: '', description: '', current_state: '' }
  showCreateModal.value = true
}

function openEditModal(loc) {
  editingLocation.value = loc
  locationForm.value = { name: loc.name, description: loc.description, current_state: loc.current_state || '' }
  showEditModal.value = true
}

async function createLocation() {
  if (!locationForm.value.name.trim()) return
  try {
    const newLoc = await mapApi.createLocation(props.chapter.book_id, locationForm.value)
    locations.value.push(newLoc)
    showCreateModal.value = false
  } catch (e) {
    showToast('创建失败: ' + e.message, 'error')
  }
}

async function updateLocation() {
  if (!editingLocation.value || !locationForm.value.name.trim()) return
  try {
    const updated = await mapApi.updateLocation(editingLocation.value.id, locationForm.value)
    const idx = locations.value.findIndex(l => l.id === updated.id)
    if (idx !== -1) locations.value[idx] = updated
    // Also update in chapter locations if present
    const chapIdx = chapterLocations.value.findIndex(cl => cl.location_id === updated.id)
    if (chapIdx !== -1) {
       // Ideally re-fetch or manually update structure, but simplistic update:
       chapterLocations.value[chapIdx].location = updated
    }
    showEditModal.value = false
  } catch (e) {
    showToast('更新失败: ' + e.message, 'error')
  }
}

async function deleteLocation(id) {
  const ok = await showConfirm({
    title: '确认删除',
    message: '确定要删除这个地点吗？这将移除所有关联。'
  })
  if (!ok) return
  try {
    await mapApi.deleteLocation(id)
    locations.value = locations.value.filter(l => l.id !== id)
    chapterLocations.value = chapterLocations.value.filter(cl => cl.location_id !== id)
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error')
  }
}

// Association Logic
function isSelected(locId) {
  return chapterLocations.value.some(cl => cl.location_id === locId)
}

async function toggleLocation(loc) {
  const existing = chapterLocations.value.find(cl => cl.location_id === loc.id)
  try {
    if (existing) {
      // API call expects location_id, not relation_id
      await mapApi.removeLocationFromChapter(props.chapter.id, loc.id)
      chapterLocations.value = chapterLocations.value.filter(cl => cl.location_id !== loc.id)
    } else {
      const newRel = await mapApi.addLocationToChapter(props.chapter.id, loc.id)
      // If the backend doesn't return the full location object, populate it manually
      if (!newRel.location && loc) {
        newRel.location = loc
      }
      chapterLocations.value.push(newRel)
    }
  } catch (e) {
    console.error('切换关联失败', e)
    // Refresh data if state is desynced
    if (e.message.includes('404') || e.message.includes('400')) {
      await loadData()
    }
  }
}
</script>

<template>
  <div class="h-full flex flex-col p-3 gap-4">
    <!-- Map Selection Area -->
    <div class="flex-1 min-h-0 flex flex-col">
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-xs font-medium text-[var(--text-primary)]">场景地图库</h3>
        <button 
          @click="openCreateModal"
          class="p-1 rounded hover:bg-black/5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          title="新建地点"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
        </button>
      </div>
      
      <div class="flex-1 overflow-y-auto space-y-2 pr-1">
        <div v-if="isLoading && sortedLocations.length === 0" class="text-center text-[10px] text-[var(--text-muted)] py-4">
          加载中...
        </div>
        <div v-else-if="sortedLocations.length === 0" class="text-center text-[10px] text-[var(--text-muted)] py-4">
          暂无地点，点击上方 + 号创建
        </div>
        
        <div 
          v-for="loc in sortedLocations" 
          :key="loc.id"
          class="group relative p-2 rounded-lg border transition-all cursor-pointer"
          :class="getLocationHighlightClass(loc.id)"
          @click="toggleLocation(loc)"
        >
          <div class="flex items-start justify-between">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-1.5">
                <div 
                  class="w-3 h-3 rounded-full border flex items-center justify-center transition-colors"
                  :class="isSelected(loc.id) ? 'bg-indigo-500 border-indigo-500' : 'border-slate-300'"
                >
                  <svg v-if="isSelected(loc.id)" class="w-2 h-2 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
                  </svg>
                </div>
                <span class="text-xs font-medium text-[var(--text-primary)] truncate">{{ loc.name }}</span>
                <span
                  v-if="locationHighlightLevelMap.get(loc.id)"
                  class="px-1 py-0.5 text-[9px] rounded-full"
                  :class="locationHighlightLevelMap.get(loc.id) === 'strong' ? 'bg-amber-100 text-amber-700' : 'bg-indigo-100 text-indigo-700'"
                >
                  {{ locationHighlightLevelMap.get(loc.id) === 'strong' ? '强匹配' : '弱匹配' }}
                </span>
              </div>
              <p class="mt-1 text-[10px] text-[var(--text-secondary)] line-clamp-2 pl-4.5">{{ loc.description || '暂无描述' }}</p>
              <p v-if="loc.current_state" class="mt-0.5 text-[10px] text-amber-600 line-clamp-1 pl-4.5">
                <span class="font-medium">此刻:</span> {{ loc.current_state }}
              </p>
            </div>
            
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity pl-2">
              <button 
                @click.stop="openEditModal(loc)"
                class="p-1 text-slate-400 hover:text-indigo-600"
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/>
                </svg>
              </button>
              <button 
                @click.stop="deleteLocation(loc.id)"
                class="p-1 text-slate-400 hover:text-rose-500"
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Specific Constraints -->
    <div class="h-1/3 flex flex-col border-t border-slate-100 pt-3">
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-xs font-medium text-[var(--text-primary)]">本章活动范围限制</h3>
        <button 
          v-if="isDirty"
          @click="saveRange"
          class="px-2 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-500 transition-colors"
        >
          保存
        </button>
        <span v-else class="text-[10px] text-[var(--text-muted)]">已保存</span>
      </div>
      <textarea
        v-model="mapActivityRange"
        @input="handleChange"
        class="flex-1 w-full p-2 text-xs bg-[var(--bg-panel)] text-[var(--text-primary)] rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-indigo-500 border border-transparent focus:border-indigo-500 transition-all"
        placeholder="在此输入针对本章的具体路线或活动范围限制..."
      ></textarea>
    </div>

    <!-- Modals -->
    <div v-if="showCreateModal || showEditModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm" @click.self="showCreateModal = false; showEditModal = false">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-4 mx-4">
        <h3 class="text-sm font-semibold text-slate-800 mb-3">{{ showEditModal ? '编辑地点' : '新建地点' }}</h3>
        <div class="space-y-3">
          <div>
            <label class="block text-xs text-slate-500 mb-1">名称</label>
            <input 
              v-model="locationForm.name"
              class="w-full px-2 py-1.5 text-xs border rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
              placeholder="例如：暴风城、幽暗密林"
            />
          </div>
          <div>
            <label class="block text-xs text-slate-500 mb-1">描述 (Prompt上下文)</label>
            <textarea 
              v-model="locationForm.description"
              rows="3"
              class="w-full px-2 py-1.5 text-xs border rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
              placeholder="详细描述该地点的环境、氛围、规则等..."
            ></textarea>
          </div>
          <div>
            <label class="block text-xs text-slate-500 mb-1">此刻状态 (实时快照)</label>
            <textarea 
              v-model="locationForm.current_state"
              rows="2"
              class="w-full px-2 py-1.5 text-xs border rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
              placeholder="从世界快照中提取的此刻场景状态..."
            ></textarea>
            <p class="text-[10px] text-slate-400 mt-0.5">此字段通常在章节发布时自动更新</p>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-4">
          <button 
            @click="showCreateModal = false; showEditModal = false"
            class="px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            取消
          </button>
          <button 
            @click="showEditModal ? updateLocation() : createLocation()"
            class="px-3 py-1.5 text-xs bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition-colors"
          >
            确定
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
