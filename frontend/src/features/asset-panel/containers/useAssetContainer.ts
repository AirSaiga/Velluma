import { ref, onMounted, computed } from 'vue'
import { assetApi } from '../../../services/api'
import type { Asset } from '../../../shared/types'
import { showConfirm, showToast } from '../../../shared/utils/toast'

export function useAssetContainer(props: { bookId?: string }) {
  const assets = ref<Asset[]>([])
  const isLoading = ref(false)
  const searchQuery = ref('')
  
  // 编辑/创建状态
  const showEditModal = ref(false)
  const isEditing = ref(false)
  const editingAssetId = ref<string | null>(null)
  
  const formData = ref({
    name: '',
    aliases: '',
    static_description: '',
    current_state: '',
    importance_level: 1
  })

  const filteredAssets = computed(() => {
    if (!searchQuery.value) return assets.value
    const query = searchQuery.value.toLowerCase()
    return assets.value.filter(a => 
      a.name.toLowerCase().includes(query) || 
      (a.aliases && a.aliases.some(alias => alias.toLowerCase().includes(query)))
    )
  })

  async function loadAssets() {
    if (!props.bookId) return
    isLoading.value = true
    try {
      assets.value = await assetApi.getAll(props.bookId)
    } catch (error: any) {
      showToast('加载资产失败: ' + error.message, 'error')
    } finally {
      isLoading.value = false
    }
  }

  function openCreateModal() {
    isEditing.value = false
    editingAssetId.value = null
    formData.value = {
      name: '',
      aliases: '',
      static_description: '',
      current_state: '',
      importance_level: 1
    }
    showEditModal.value = true
  }

  function openEditModal(asset: Asset) {
    isEditing.value = true
    editingAssetId.value = asset.id
    formData.value = {
      name: asset.name,
      aliases: asset.aliases ? asset.aliases.join(', ') : '',
      static_description: asset.static_description || '',
      current_state: asset.current_state || '',
      importance_level: asset.importance_level || 1
    }
    showEditModal.value = true
  }

  async function saveAsset() {
    if (!props.bookId) return
    if (!formData.value.name.trim()) {
      showToast('资产名称不能为空', 'warning')
      return
    }

    const payload = {
      name: formData.value.name.trim(),
      aliases: formData.value.aliases.split(',').map(s => s.trim()).filter(Boolean),
      static_description: formData.value.static_description.trim() || null,
      current_state: formData.value.current_state.trim() || null,
      importance_level: formData.value.importance_level
    }

    try {
      if (isEditing.value && editingAssetId.value) {
        await assetApi.update(editingAssetId.value, payload)
        showToast('更新资产成功', 'success')
      } else {
        await assetApi.create(props.bookId, payload)
        showToast('创建资产成功', 'success')
      }
      showEditModal.value = false
      await loadAssets()
    } catch (error: any) {
      showToast('保存资产失败: ' + error.message, 'error')
    }
  }

  async function deleteAsset(id: string) {
    const ok = await showConfirm({
      title: '确认删除',
      message: '确定要删除该资产吗？这将同时移除所有章节中对该资产的引用。',
      warning: '此操作不可撤销'
    })
    if (!ok) return

    try {
      await assetApi.delete(id)
      showToast('删除资产成功', 'success')
      await loadAssets()
    } catch (error: any) {
      showToast('删除资产失败: ' + error.message, 'error')
    }
  }

  onMounted(() => {
    if (props.bookId) {
      loadAssets()
    }
  })

  return {
    assets,
    filteredAssets,
    isLoading,
    searchQuery,
    showEditModal,
    isEditing,
    formData,
    loadAssets,
    openCreateModal,
    openEditModal,
    saveAsset,
    deleteAsset
  }
}
