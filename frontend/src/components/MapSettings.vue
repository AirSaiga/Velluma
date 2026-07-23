<script setup>
import { ref, watch, computed } from 'vue'
import { mapApi } from '../services/api'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { PanelContainer, PanelSection, PanelCard, PanelEmpty, PanelSearch } from './panels'
import Icon from './Icon.vue'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const props = defineProps({
  chapter: {
    type: Object,
    default: null
  },
  focusedEntity: {
    type: String,
    default: ''
  },
  activeCharacterNames: {
    type: Array,
    default: () => []
  },
  closable: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['update-chapter', 'close'])

const searchQuery = ref('')
const mapActivityRange = ref('')
const isDirty = ref(false)
const locations = ref([])
const chapterLocations = ref([])
const showCreateModal = ref(false)
const showEditModal = ref(false)
const editingLocation = ref(null)
const locationForm = ref({ name: '', description: '', current_state: '' })
const isLoading = ref(false)

const normalizedFocusedEntity = computed(() => (props.focusedEntity || '').trim().toLowerCase())

// 是否已有选中章节：章节级功能（关联切换、活动范围）依赖它
const hasChapter = computed(() => !!props.chapter?.id)
const normalizedActiveNames = computed(() =>
  (props.activeCharacterNames || [])
    .map((name) => String(name || '').trim().toLowerCase())
    .filter(Boolean)
)

const filteredLocations = computed(() => {
  if (!searchQuery.value) return sortedLocations.value
  const query = searchQuery.value.toLowerCase()
  return sortedLocations.value.filter(loc => 
    loc.name.toLowerCase().includes(query) || 
    (loc.description && loc.description.toLowerCase().includes(query))
  )
})

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
  if (level === 'strong') return 'strong-match'
  if (level === 'weak') return 'weak-match'
  return isSelected(locId) ? 'selected' : 'default'
}

watch(() => props.chapter?.id, async (newId, oldId) => {
  if (newId && newId !== oldId) {
    mapActivityRange.value = props.chapter.map_activity_range || ''
    isDirty.value = false
    await loadData()
  }
}, { immediate: true })

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

function handleChange() {
  isDirty.value = true
}

function saveRange() {
  if (!props.chapter) return
  emit('update-chapter', props.chapter.id, { map_activity_range: mapActivityRange.value })
  isDirty.value = false
}

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
  if (!props.chapter?.book_id) {
    showToast('请先创建并选择一个章节后再管理地点', 'warning')
    return
  }
  try {
    const newLoc = await mapApi.createLocation(props.chapter.book_id, locationForm.value)
    locations.value.push(newLoc)
    showCreateModal.value = false
    showToast('地点创建成功', 'success')
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
    const chapIdx = chapterLocations.value.findIndex(cl => cl.location_id === updated.id)
    if (chapIdx !== -1) {
      chapterLocations.value[chapIdx].location = updated
    }
    showEditModal.value = false
    showToast('地点更新成功', 'success')
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
    showToast('地点已删除', 'success')
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error')
  }
}

function isSelected(locId) {
  return chapterLocations.value.some(cl => cl.location_id === locId)
}

// 卡片操作按钮：有关联章节时才提供"关联/取消关联"，编辑与删除始终可用
function locationActions(loc) {
  const actions = []
  if (hasChapter.value) {
    actions.push({
      icon: 'link',
      label: isSelected(loc.id) ? '取消关联本章' : '关联到本章',
      onClick: () => toggleLocation(loc)
    })
  }
  actions.push({ icon: 'pencil', label: '编辑', onClick: () => openEditModal(loc) })
  actions.push({ icon: 'trash', label: '删除', onClick: () => deleteLocation(loc.id), variant: 'danger' })
  return actions
}

async function toggleLocation(loc) {
  if (!props.chapter?.id) {
    showToast('请先在写作台选择要关联的章节', 'warning')
    return
  }
  const existing = chapterLocations.value.find(cl => cl.location_id === loc.id)
  try {
    if (existing) {
      await mapApi.removeLocationFromChapter(props.chapter.id, loc.id)
      chapterLocations.value = chapterLocations.value.filter(cl => cl.location_id !== loc.id)
    } else {
      const newRel = await mapApi.addLocationToChapter(props.chapter.id, loc.id)
      if (!newRel.location && loc) {
        newRel.location = loc
      }
      chapterLocations.value.push(newRel)
    }
  } catch (e) {
    console.error('切换关联失败', e)
    if (e.message.includes('404') || e.message.includes('400')) {
      await loadData()
    }
  }
}

function handleClose() {
  emit('close')
}
</script>

<template>
  <PanelContainer
    title="场景地图"
    icon="map-pin"
    description="管理章节关联的地点和场景"
    :loading="isLoading"
    :closable="closable"
    :header-actions="[
      { icon: 'plus', label: '新建地点', onClick: openCreateModal, variant: 'primary' }
    ]"
    @close="handleClose"
  >
    <div class="map-content">
      <!-- 地点库 -->
      <PanelSection title="地点库" :badge="filteredLocations.length" collapsible>
        <PanelSearch
          v-model="searchQuery"
          placeholder="搜索地点..."
          :debounce="200"
        />

        <div class="locations-list">
          <PanelCard
            v-for="loc in filteredLocations"
            :key="loc.id"
            :title="loc.name"
            :description="loc.description || '暂无描述'"
            :highlight="getLocationHighlightClass(loc.id) === 'strong-match' ? 'strong' : getLocationHighlightClass(loc.id) === 'weak-match' ? 'weak' : 'none'"
            :active="isSelected(loc.id)"
            clickable
            :actions="locationActions(loc)"
            @click="openEditModal(loc)"
          >
            <template #default>
              <div class="location-meta">
                <span v-if="loc.current_state" class="current-state">
                  <Icon name="clock" :size="10" />
                  {{ loc.current_state }}
                </span>
                <span v-if="isSelected(loc.id)" class="selected-badge">
                  <Icon name="check" :size="10" />
                  已关联
                </span>
              </div>
            </template>
          </PanelCard>

          <PanelEmpty
            v-if="filteredLocations.length === 0"
            icon="map-pin"
            :title="searchQuery ? '未找到匹配地点' : '暂无地点'"
            :description="searchQuery ? '尝试其他关键词搜索' : '点击「新建地点」创建第一个地点'"
            :action-label="searchQuery ? '清除搜索' : undefined"
            @action="searchQuery = ''"
          />
        </div>
      </PanelSection>

      <!-- 本章活动范围（依赖选中章节，无章节时隐藏） -->
      <PanelSection v-if="hasChapter" title="本章活动范围限制" collapsible :collapsed="false">
        <div class="activity-range">
          <textarea
            v-model="mapActivityRange"
            @input="handleChange"
            rows="4"
            class="range-textarea"
            placeholder="在此输入针对本章的具体路线或活动范围限制..."
          />
          <div class="range-actions">
            <span v-if="!isDirty" class="saved-hint">
              <Icon name="check" :size="12" />
              已自动保存
            </span>
            <button 
              v-else
              class="save-btn"
              @click="saveRange"
            >
              <Icon name="check" :size="12" />
              保存更改
            </button>
          </div>
        </div>
      </PanelSection>
    </div>
  </PanelContainer>

  <!-- 新建/编辑地点模态框 -->
  <Transition name="modal">
    <div v-if="showCreateModal || showEditModal" class="modal-overlay" @click.self="showCreateModal = false; showEditModal = false">
      <div class="modal-content">
        <div class="drawer-header">
          <h3>{{ showEditModal ? '编辑地点' : '新建地点' }}</h3>
          <button class="close-btn" @click="showCreateModal = false; showEditModal = false">
            <Icon name="close" :size="18" />
          </button>
        </div>

        <div class="modal-body">
          <div class="form-group">
            <label>名称 <span class="required">*</span></label>
            <input v-model="locationForm.name" type="text" placeholder="例如：暴风城、幽暗密林" />
          </div>

          <div class="form-group">
            <label>描述（Prompt上下文）</label>
            <textarea v-model="locationForm.description" rows="3" placeholder="详细描述该地点的环境、氛围、规则等..." />
          </div>

          <div class="form-group">
            <label>此刻状态（实时快照）</label>
            <textarea v-model="locationForm.current_state" rows="2" placeholder="从世界快照中提取的此刻场景状态..." />
            <p class="form-hint">此字段通常在章节发布时自动更新</p>
          </div>
        </div>

        <div class="drawer-footer">
          <button class="btn-secondary" @click="showCreateModal = false; showEditModal = false">取消</button>
          <button class="btn-primary" @click="showEditModal ? updateLocation() : createLocation()">
            {{ showEditModal ? '保存' : '创建' }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.map-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: 100%;
  min-height: 0;
}

.locations-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow-y: auto;
  min-height: 0;
}

.location-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.current-state {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 10px;
  color: #d97706;
  background: #fef3c7;
  border-radius: 4px;
}

.selected-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 10px;
  color: white;
  background: var(--accent-500);
  border-radius: 4px;
}

.activity-range {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.range-textarea {
  width: 100%;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  resize: vertical;
  min-height: 100px;
  transition: all 0.2s ease;
}

.range-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.range-actions {
  display: flex;
  justify-content: flex-end;
}

.saved-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.save-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 500;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.save-btn:hover {
  background: var(--accent-600);
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
  max-width: 440px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
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

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

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

.form-group input,
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

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

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
