<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { systemApi } from '../services/api/domain'

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
      model: 'google/gemini-2.0-flash-001',
      reasoning_model: '',
      creative_model: ''
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
      'deepseek/deepseek-v3.2',
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
  model: '',
  reasoning_model: '',
  creative_model: ''
})

const proxyEnabled = ref(true)
const proxyUrl = ref('http://127.0.0.1:4780')

const isManualModel = ref(false)
const enableDualModel = ref(false)

onMounted(async () => {
  try {
    const config = await systemApi.getProxyConfig()
    proxyEnabled.value = config.enabled
    proxyUrl.value = config.url
  } catch (e) {
    console.error('Failed to load proxy config:', e)
  }
})

// 当打开模态框时，初始化表单数据
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    formData.value = { 
      ...props.config,
      // 确保新字段有默认值
      reasoning_model: props.config.reasoning_model || '',
      creative_model: props.config.creative_model || ''
    }
    
    // 检查是否启用了双模型
    enableDualModel.value = !!(props.config.reasoning_model || props.config.creative_model)
    
    // 如果没有 provider 字段（旧数据），尝试根据 base_url 推断或默认为 custom
    if (!formData.value.provider) {
      const match = Object.entries(PROVIDERS).find(([key, p]) => p.baseUrl === formData.value.base_url)
      formData.value.provider = match ? match[0] : 'custom'
    }
    
    // 检查当前模型是否在预定义列表中
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
    
    // 切换服务商时，保持双模型开关状态，但用户可能需要更新模型名
  }
}

function handleDualModelToggle() {
  if (!enableDualModel.value) {
    // 关闭双模型时，清空专用模型字段
    formData.value.reasoning_model = ''
    formData.value.creative_model = ''
  } else {
    // 开启双模型时，默认使用当前模型作为 reasoning_model
    formData.value.reasoning_model = formData.value.model || ''
  }
}

async function handleSave() {
  // 构建保存的配置
  const configToSave = {
    ...formData.value,
    proxy_enabled: proxyEnabled.value,
    proxy_url: proxyUrl.value
  }
  
  // 如果未启用双模型，清空专用字段
  if (!enableDualModel.value) {
    configToSave.reasoning_model = ''
    configToSave.creative_model = ''
  }
  
  emit('save', configToSave)
  try {
    await systemApi.updateProxyConfig({
      enabled: proxyEnabled.value,
      url: proxyUrl.value
    })
  } catch (e) {
    console.error('Failed to save proxy config:', e)
  }
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
  localStorage.removeItem('velluma_api_config')
  emit('close')
  window.location.reload()
}
</script>

<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
    <div class="bg-[var(--bg-secondary)] rounded-xl shadow-2xl w-full max-w-2xl border border-[var(--border-color)] flex flex-col max-h-[90vh]">
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

        <!-- Default Model -->
        <div>
          <div class="flex items-center justify-between mb-1">
            <label class="block text-sm font-medium text-[var(--text-primary)]">默认模型</label>
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
          <p class="mt-1 text-xs text-[var(--text-muted)]">
            当未启用双模型时，使用此模型进行所有生成任务。
          </p>
        </div>

        <!-- Dual Model Toggle -->
        <div class="border-t border-[var(--border-color)] pt-4">
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-[var(--text-primary)]">启用双模型架构</label>
              <p class="text-xs text-[var(--text-muted)] mt-0.5">
                逻辑推理模型 + 创意生成模型，提升生成质量
              </p>
            </div>
            <button
              @click="enableDualModel = !enableDualModel; handleDualModelToggle()"
              :class="[
                'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                enableDualModel ? 'bg-primary-500' : 'bg-[var(--bg-tertiary)]'
              ]"
            >
              <span
                :class="[
                  'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                  enableDualModel ? 'translate-x-6' : 'translate-x-1'
                ]"
              />
            </button>
          </div>
        </div>

        <!-- Dual Model Settings -->
        <div v-if="enableDualModel" class="space-y-4 border border-[var(--border-color)] rounded-lg p-4 bg-[var(--bg-tertiary)]/50">
          <!-- Reasoning Model -->
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
              <span class="inline-flex items-center gap-1.5">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-blue-500"><path d="M12 2L2 7l10 5 10-5-10-5z"></path><path d="M2 17l10 5 10-5"></path><path d="M2 12l10 5 10-5"></path></svg>
                逻辑推理模型
              </span>
            </label>
            <input
              v-model="formData.reasoning_model"
              type="text"
              placeholder="例如: gpt-4o, claude-3-5-sonnet, qwen-max"
              class="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500"
            />
            <p class="mt-1 text-xs text-[var(--text-muted)]">
              用于 Scene Intent 分析、潜意识生成、审阅与精修阶段
            </p>
          </div>

          <!-- Creative Model -->
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
              <span class="inline-flex items-center gap-1.5">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-amber-500"><path d="M12 3v18"></path><path d="M3 12h18"></path><circle cx="12" cy="12" r="9"></circle></svg>
                创意生成模型
              </span>
            </label>
            <input
              v-model="formData.creative_model"
              type="text"
              placeholder="例如: claude-3-haiku, gemini-flash, qwen-plus"
              class="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500"
            />
            <p class="mt-1 text-xs text-[var(--text-muted)]">
              用于正文起草阶段，需要较强的创意和写作能力
            </p>
          </div>

          <!-- 使用说明 -->
          <div class="mt-4 pt-4 border-t border-[var(--border-color)]">
            <h4 class="text-xs font-medium text-[var(--text-primary)] mb-2 flex items-center gap-1.5">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
              模型使用说明
            </h4>
            <div class="space-y-1.5 text-xs text-[var(--text-muted)]">
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"></span>
                <span><strong class="text-[var(--text-secondary)]">逻辑推理模型</strong>：用于 Scene Intent 分析、潜意识生成、审阅指导、灵感生成、文本润色等</span>
              </p>
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0"></span>
                <span><strong class="text-[var(--text-secondary)]">创意生成模型</strong>：仅用于 Agentic 文章生成的正文起草阶段（Prose Draft）</span>
              </p>
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-gray-400 mt-1.5 shrink-0"></span>
                <span>其他功能（格式化、发布、角色状态更新）使用逻辑推理模型或默认模型</span>
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- 代理设置 -->
      <div class="px-6 pb-6 space-y-3">
        <div class="flex items-center justify-between">
          <label class="text-sm font-medium text-[var(--text-primary)]">使用代理</label>
          <button
            @click="proxyEnabled = !proxyEnabled"
            :class="[
              'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
              proxyEnabled ? 'bg-primary-500' : 'bg-[var(--bg-tertiary)]'
            ]"
          >
            <span
              :class="[
                'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                proxyEnabled ? 'translate-x-6' : 'translate-x-1'
              ]"
            />
          </button>
        </div>
        <div v-if="proxyEnabled">
          <label class="text-xs text-[var(--text-secondary)] block mb-1">代理地址</label>
          <input
            v-model="proxyUrl"
            type="text"
            placeholder="http://127.0.0.1:7890"
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
