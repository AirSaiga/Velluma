<script setup>
import { ref, watch, computed } from 'vue'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { show: showConfirm } = useConfirmDialog()

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  config: {
    type: Object,
    default: () => ({
      provider: 'openrouter',
      api_key: '',
      base_url: 'https://openrouter.ai/api/v1',
      model: 'google/gemini-2.0-flash-001'
    })
  }
})

const emit = defineEmits(['close', 'save'])

const PROVIDERS = {
  openrouter: {
    name: 'OpenRouter (推荐)',
    baseUrl: 'https://openrouter.ai/api/v1',
    models: [
      'z-ai/glm-5',
      'moonshotai/kimi-k2.5',
      'qwen/qwen3.5-plus-02-15',
      'google/gemini-3-flash-preview',
      'google/gemini-3.1-pro-preview'
    ]
  },
  aliyun: {
    name: '阿里云 (通义千问)',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen3-max', 'qwen3.5-plus']
  },
  custom: {
    name: '自定义 / Custom',
    baseUrl: '',
    models: []
  }
}

const formData = ref({
  provider: 'openrouter',
  api_key: '',
  base_url: '',
  model: ''
})

const isManualModel = ref(false)

// 当打开模态框时，初始化表单数据
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    formData.value = { ...props.config }
    // 如果没有 provider 字段（旧数据），尝试根据 base_url 推断或默认为 custom
    if (!formData.value.provider) {
      const match = Object.entries(PROVIDERS).find(([key, p]) => p.baseUrl === formData.value.base_url)
      formData.value.provider = match ? match[0] : 'custom'
    }
    
    // 检查当前模型是否在预定义列表中，如果不在，切换到手动模式
    const provider = PROVIDERS[formData.value.provider]
    if (provider && provider.models.length > 0 && !provider.models.includes(formData.value.model)) {
      isManualModel.value = true
    } else {
      isManualModel.value = false
    }
  }
})

const currentProvider = computed(() => PROVIDERS[formData.value.provider] || PROVIDERS.custom)
const isCustomProvider = computed(() => formData.value.provider === 'custom')

function handleProviderChange() {
  const provider = PROVIDERS[formData.value.provider]
  if (provider && formData.value.provider !== 'custom') {
    formData.value.base_url = provider.baseUrl
    // 切换服务商时，重置手动模式并选中第一个模型
    isManualModel.value = false
    if (provider.models.length > 0) {
      formData.value.model = provider.models[0]
    } else {
      formData.value.model = ''
    }
  }
}

function handleSave() {
  emit('save', { ...formData.value })
  emit('close')
}

async function handleResetLocal() {
  const ok = await showConfirm({
    title: '确认重置',
    message: '将清除本地保存的 API 配置、主题与布局偏好。不会删除任何书籍/章节/角色数据。确定继续？'
  })
  if (!ok) return
  localStorage.removeItem('velluma_theme')
  localStorage.removeItem('velluma_ui_prefs_v1')
  sessionStorage.removeItem('velluma_api_config')
  emit('close')
  window.location.reload()
}
</script>

<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
    <div class="bg-[var(--bg-secondary)] rounded-xl shadow-2xl w-full max-w-lg border border-[var(--border-color)] flex flex-col max-h-[90vh]">
      <!-- Header -->
      <div class="flex items-center justify-between p-4 border-b border-[var(--border-color)]">
        <h2 class="text-lg font-semibold text-[var(--text-primary)]">API 设置</h2>
        <button 
          @click="$emit('close')"
          class="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
      </div>

      <!-- Body -->
      <div class="p-6 space-y-5 overflow-y-auto">
        <!-- Provider Select -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">服务商</label>
          <select
            v-model="formData.provider"
            @change="handleProviderChange"
            class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500"
          >
            <option v-for="(p, key) in PROVIDERS" :key="key" :value="key">
              {{ p.name }}
            </option>
          </select>
        </div>

        <!-- API Key -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">API Key</label>
          <input
            v-model="formData.api_key"
            type="password"
            placeholder="sk-..."
            class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500"
          />
          <p class="mt-1 text-xs text-[var(--text-muted)]">
            您的 API Key 仅存储在本地浏览器中，不会上传到服务器。
          </p>
        </div>

        <!-- Base URL -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Base URL</label>
          <input
            v-model="formData.base_url"
            type="text"
            :placeholder="isCustomProvider ? 'https://api.example.com/v1' : ''"
            :readonly="!isCustomProvider"
            :class="['w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500', !isCustomProvider && 'opacity-75 cursor-not-allowed']"
          />
        </div>

        <!-- Model -->
        <div>
          <div class="flex items-center justify-between mb-1">
            <label class="block text-sm font-medium text-[var(--text-primary)]">模型</label>
            <button 
              v-if="!isCustomProvider && currentProvider.models.length > 0"
              @click="isManualModel = !isManualModel"
              class="text-xs text-primary-600 hover:text-primary-700 font-medium transition-colors"
            >
              {{ isManualModel ? '从列表选择' : '手动输入' }}
            </button>
          </div>
          
          <div v-if="!isCustomProvider && currentProvider.models.length > 0 && !isManualModel">
            <select
              v-model="formData.model"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500"
            >
              <option v-for="m in currentProvider.models" :key="m" :value="m">
                {{ m }}
              </option>
            </select>
          </div>
          <input
            v-else
            v-model="formData.model"
            type="text"
            placeholder="例如: gpt-4o"
            class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500"
          />
        </div>
      </div>

      <!-- Footer -->
      <div class="p-4 border-t border-[var(--border-color)] flex justify-end space-x-3">
        <button
          @click="handleResetLocal"
          class="px-4 py-2 text-sm font-medium text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors"
        >
          重置本地设置
        </button>
        <button 
          @click="$emit('close')"
          class="px-4 py-2 text-sm font-medium text-[var(--text-primary)] bg-transparent hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors"
        >
          取消
        </button>
        <button 
          @click="handleSave"
          class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-lg shadow-sm transition-colors"
        >
          保存设置
        </button>
      </div>
    </div>
  </div>
</template>
