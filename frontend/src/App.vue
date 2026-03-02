<script setup>
import { ref, onMounted } from 'vue'
import EntityPanel from './components/EntityPanel.vue'
import BeatEditor from './components/BeatEditor.vue'
import ConfigPanel from './components/ConfigPanel.vue'
import { entityApi, beatApi, configApi, generateApi } from './composables/useApi'

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
onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="h-full w-full bg-slate-950 flex">
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
</template>
