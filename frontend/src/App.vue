<script setup>
import { ref, onMounted } from 'vue'
import EntityPanel from './components/EntityPanel.vue'
import BeatEditor from './components/BeatEditor.vue'
import ConfigPanel from './components/ConfigPanel.vue'
import SettingsModal from './components/SettingsModal.vue'
import { entityApi, beatApi, configApi, generateApi } from './composables/useApi'
import { useTheme } from './composables/useTheme'

// 设置弹窗状态
const showSettings = ref(false)

// 初始化主题
const { initTheme } = useTheme()

// 数据状态
const entities = ref([])
const beats = ref([])
const config = ref({
  api_key: '',
  base_url: '',
  model: 'gpt-4o-mini',
  style: ''
})
const loading = ref(false)

// 加载数据
async function loadData() {
  loading.value = true
  try {
    const [entitiesData, beatsData, configData] = await Promise.all([
      entityApi.getAll(),
      beatApi.getAll(),
      configApi.get()
    ])
    entities.value = entitiesData
    beats.value = beatsData
    config.value = { ...config.value, ...configData }
  } catch (error) {
    console.error('加载数据失败:', error)
  } finally {
    loading.value = false
  }
}

// Entity 操作
async function createEntity(data) {
  try {
    const newEntity = await entityApi.create(data)
    entities.value.push(newEntity)
  } catch (error) {
    alert('创建失败: ' + error.message)
  }
}

async function updateEntity(id, data) {
  try {
    const updated = await entityApi.update(id, data)
    const index = entities.value.findIndex(e => e.id === id)
    if (index !== -1) {
      entities.value[index] = updated
    }
  } catch (error) {
    alert('更新失败: ' + error.message)
  }
}

async function deleteEntity(id) {
  try {
    await entityApi.delete(id)
    entities.value = entities.value.filter(e => e.id !== id)
  } catch (error) {
    alert('删除失败: ' + error.message)
  }
}

// Beat 操作
async function createBeat(data) {
  try {
    const newBeat = await beatApi.create(data)
    beats.value.push(newBeat)
  } catch (error) {
    alert('创建失败: ' + error.message)
  }
}

async function updateBeat(id, data) {
  try {
    const updated = await beatApi.update(id, data)
    const index = beats.value.findIndex(b => b.id === id)
    if (index !== -1) {
      beats.value[index] = updated
    }
  } catch (error) {
    alert('更新失败: ' + error.message)
  }
}

async function deleteBeat(id) {
  try {
    await beatApi.delete(id)
    beats.value = beats.value.filter(b => b.id !== id)
  } catch (error) {
    alert('删除失败: ' + error.message)
  }
}

// 生成文本
function generateText(beat, onChunk, onDone, onError) {
  const requestData = {
    beat: beat,
    style: config.value.style,
    api_key: config.value.api_key,
    base_url: config.value.base_url || undefined,
    model: config.value.model
  }
  
  generateApi.stream(requestData, onChunk, onDone, onError)
}

// 保存生成的文本
async function saveGeneratedText(beatId, text) {
  try {
    const updated = await beatApi.update(beatId, { generated_text: text })
    const index = beats.value.findIndex(b => b.id === beatId)
    if (index !== -1) {
      beats.value[index] = updated
    }
  } catch (error) {
    console.error('保存失败:', error)
  }
}

// 配置更新
async function updateConfig(newConfig) {
  try {
    const updated = await configApi.update(newConfig)
    config.value = { ...config.value, ...updated }
  } catch (error) {
    alert('保存配置失败: ' + error.message)
  }
}

// 初始化
onMounted(async () => {
  await loadData()
  initTheme()
})
</script>

<template>
  <div class="h-full w-full bg-[var(--bg-primary)] flex flex-col">
    <!-- 顶部栏 -->
    <div class="h-12 flex-shrink-0 flex items-center justify-end px-4 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
      <!-- 设置按钮 -->
      <button
        @click="showSettings = true"
        class="flex items-center gap-2 px-3 py-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)] transition-colors"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd" />
        </svg>
        <span class="text-sm font-medium">设置</span>
      </button>
    </div>
    
    <!-- 主内容区 -->
    <div class="flex-1 flex min-h-0">
      <!-- 左侧：设定库 -->
      <div class="w-72 flex-shrink-0 h-full">
        <EntityPanel
          :entities="entities"
          @create="createEntity"
          @update="updateEntity"
          @delete="deleteEntity"
        />
      </div>
      
      <!-- 中间：编辑器工作区 -->
      <div class="flex-1 h-full min-w-0">
        <BeatEditor
          :beats="beats"
          :entities="entities"
          :config="config"
          @create="createBeat"
          @update="updateBeat"
          @delete="deleteBeat"
          @generate="generateText"
          @save-generated="saveGeneratedText"
        />
      </div>
      
      <!-- 右侧：配置面板 -->
      <div class="w-80 flex-shrink-0 h-full">
        <ConfigPanel
          :config="config"
          @update="updateConfig"
        />
      </div>
    </div>
    
    <!-- 设置弹窗 -->
    <SettingsModal
      :visible="showSettings"
      @close="showSettings = false"
    />
  </div>
</template>
