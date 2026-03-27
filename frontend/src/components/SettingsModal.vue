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
  creative_model: '',
  // 默认模型的推理模式配置
  reasoning_enabled: false,
  reasoning_effort: 'medium',
  reasoning_exclude: false,
  // 逻辑推理模型的推理模式配置（用于 Scene Intent / Subconscious / Review）
  reasoning_model_reasoning_enabled: false,
  reasoning_model_reasoning_effort: 'high',
  reasoning_model_reasoning_exclude: false,
  // 创意生成模型的推理模式配置（用于 Prose Draft）
  creative_model_reasoning_enabled: false,
  creative_model_reasoning_effort: 'low',
  creative_model_reasoning_exclude: false
})

const proxyEnabled = ref(true)
const proxyUrl = ref('http://127.0.0.1:4780')

const isManualModel = ref(false)
const enableDualModel = ref(false)

// 测试连接状态
const isTestingConnection = ref(false)
/** @type {{ success: boolean; message: string; reasoning_supported?: boolean; reasoning_message?: string; response_time_ms?: number } | null} */
const testResult = ref(null)

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
      creative_model: props.config.creative_model || '',
      // 默认模型的推理模式配置初始化
      reasoning_enabled: props.config.reasoning_enabled ?? false,
      reasoning_effort: props.config.reasoning_effort || 'medium',
      reasoning_exclude: props.config.reasoning_exclude ?? false,
      // 逻辑推理模型的推理模式配置初始化
      reasoning_model_reasoning_enabled: props.config.reasoning_model_reasoning_enabled ?? false,
      reasoning_model_reasoning_effort: props.config.reasoning_model_reasoning_effort || 'high',
      reasoning_model_reasoning_exclude: props.config.reasoning_model_reasoning_exclude ?? false,
      // 创意生成模型的推理模式配置初始化
      creative_model_reasoning_enabled: props.config.creative_model_reasoning_enabled ?? false,
      creative_model_reasoning_effort: props.config.creative_model_reasoning_effort || 'low',
      creative_model_reasoning_exclude: props.config.creative_model_reasoning_exclude ?? false
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
  
  // 如果未启用双模型，清空专用字段和推理配置
  if (!enableDualModel.value) {
    configToSave.reasoning_model = ''
    configToSave.creative_model = ''
    configToSave.reasoning_model_reasoning_enabled = false
    configToSave.reasoning_model_reasoning_effort = 'high'
    configToSave.reasoning_model_reasoning_exclude = false
    configToSave.creative_model_reasoning_enabled = false
    configToSave.creative_model_reasoning_effort = 'low'
    configToSave.creative_model_reasoning_exclude = false
  } else {
    // 双模型模式：如果未启用推理模式，重置推理配置
    if (!formData.value.reasoning_model_reasoning_enabled) {
      configToSave.reasoning_model_reasoning_effort = 'high'
      configToSave.reasoning_model_reasoning_exclude = false
    }
    if (!formData.value.creative_model_reasoning_enabled) {
      configToSave.creative_model_reasoning_effort = 'low'
      configToSave.creative_model_reasoning_exclude = false
    }
  }
  
  // 单模型模式：如果未启用推理模式，重置推理配置
  if (!formData.value.reasoning_enabled) {
    configToSave.reasoning_effort = 'medium'
    configToSave.reasoning_exclude = false
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

async function handleTestConnection() {
  if (!formData.value.api_key) {
    testResult.value = {
      success: false,
      message: '请先输入 API Key'
    }
    return
  }
  
  // 双模型模式：测试两个模型
  if (enableDualModel.value) {
    // 测试逻辑推理模型
    if (!formData.value.reasoning_model) {
      testResult.value = {
        success: false,
        message: '请先输入逻辑推理模型名称'
      }
      return
    }
    
    isTestingConnection.value = true
    testResult.value = null
    
    try {
      // 先测试逻辑推理模型
      const reasoningResult = await systemApi.testModel({
        api_key: formData.value.api_key,
        base_url: formData.value.base_url || undefined,
        model: formData.value.reasoning_model,
        reasoning_enabled: formData.value.reasoning_model_reasoning_enabled,
        reasoning_effort: formData.value.reasoning_model_reasoning_effort
      })
      
      if (!reasoningResult.success) {
        testResult.value = {
          success: false,
          message: `逻辑推理模型测试失败: ${reasoningResult.message}`
        }
        isTestingConnection.value = false
        return
      }
      
      // 如果有创意生成模型，也测试它
      if (formData.value.creative_model) {
        const creativeResult = await systemApi.testModel({
          api_key: formData.value.api_key,
          base_url: formData.value.base_url || undefined,
          model: formData.value.creative_model,
          reasoning_enabled: formData.value.creative_model_reasoning_enabled,
          reasoning_effort: formData.value.creative_model_reasoning_effort
        })
        
        if (!creativeResult.success) {
          testResult.value = {
            success: false,
            message: `创意生成模型测试失败: ${creativeResult.message}`
          }
          isTestingConnection.value = false
          return
        }
        
        // 两个模型都成功
        testResult.value = {
          success: true,
          message: `双模型测试成功！逻辑推理: ${reasoningResult.message.split('，')[0]}，创意: ${creativeResult.message.split('，')[0]}`,
          reasoning_supported: reasoningResult.reasoning_supported,
          reasoning_message: reasoningResult.reasoning_message,
          response_time_ms: (reasoningResult.response_time_ms || 0) + (creativeResult.response_time_ms || 0)
        }
      } else {
        // 只有逻辑推理模型
        testResult.value = reasoningResult
      }
    } catch (e) {
      testResult.value = {
        success: false,
        message: `测试失败: ${e.message || '未知错误'}`
      }
    } finally {
      isTestingConnection.value = false
    }
    return
  }
  
  // 单模型模式
  if (!formData.value.model) {
    testResult.value = {
      success: false,
      message: '请先选择或输入模型名称'
    }
    return
  }
  
  isTestingConnection.value = true
  testResult.value = null
  
  try {
    const result = await systemApi.testModel({
      api_key: formData.value.api_key,
      base_url: formData.value.base_url || undefined,
      model: formData.value.model,
      reasoning_enabled: formData.value.reasoning_enabled,
      reasoning_effort: formData.value.reasoning_effort
    })
    
    testResult.value = result
    
    // 如果启用了推理模式但模型不支持，显示警告
    if (formData.value.reasoning_enabled && result.success && result.reasoning_supported === false) {
      // 用户已看到警告，无需额外处理
    }
  } catch (e) {
    testResult.value = {
      success: false,
      message: `测试失败: ${e.message || '未知错误'}`
    }
  } finally {
    isTestingConnection.value = false
  }
}
</script>

<template>
  <Transition name="modal">
    <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div class="modal-content bg-[var(--bg-secondary)] rounded-2xl shadow-xl w-full max-w-2xl border border-[var(--border-color)] flex flex-col max-h-[90vh]">
      <!-- Header -->
      <div class="flex items-center justify-between p-4 border-b border-[var(--border-color)]">
        <h2 class="text-lg font-heading font-semibold text-[var(--text-primary)]">API 设置</h2>
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
            class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
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
            class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
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
            :class="['w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40', !isCustomProvider && 'opacity-75 cursor-not-allowed']"
          />
        </div>

        <!-- Default Model -->
        <div>
          <div class="flex items-center justify-between mb-1">
            <label class="block text-sm font-medium text-[var(--text-primary)]">默认模型</label>
            <button 
              v-if="!isCustomProvider && currentProvider.models.length > 0"
              @click="isManualModel = !isManualModel"
              class="text-xs text-accent-600 hover:text-accent-700 font-medium transition-colors"
            >
              {{ isManualModel ? '从列表选择' : '手动输入' }}
            </button>
          </div>
          
          <div v-if="!isCustomProvider && currentProvider.models.length > 0 && !isManualModel">
            <select
              v-model="formData.model"
              class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
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
            class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
          />
          <p class="mt-1 text-xs text-[var(--text-muted)]">
            当未启用双模型时，使用此模型进行所有生成任务。
          </p>
        </div>

        <!-- Test Connection Button -->
        <div class="border-t border-[var(--border-color)] pt-4">
          <button
            @click="handleTestConnection"
            :disabled="isTestingConnection"
            :class="[
              'w-full px-4 py-2.5 text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2',
              isTestingConnection 
                ? 'bg-[var(--bg-panel)] text-[var(--text-muted)] cursor-not-allowed' 
                : 'bg-[var(--bg-panel)] text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] ring-1 ring-[var(--border-color)]'
            ]"
          >
            <svg v-if="isTestingConnection" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
            {{ isTestingConnection ? '测试中...' : '测试连接' }}
          </button>
          
          <!-- Test Result -->
          <div v-if="testResult" class="mt-3 p-3 rounded-lg text-sm" :class="testResult.success ? 'bg-green-500/10 border border-green-500/30' : 'bg-red-500/10 border border-red-500/30'">
            <div class="flex items-start gap-2">
              <svg v-if="testResult.success" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-green-500 mt-0.5 shrink-0"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-red-500 mt-0.5 shrink-0"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
              <div class="flex-1">
                <p :class="testResult.success ? 'text-green-400' : 'text-red-400'">{{ testResult.message }}</p>
                <p v-if="testResult.response_time_ms" class="text-xs text-[var(--text-muted)] mt-1">
                  响应时间: {{ testResult.response_time_ms.toFixed(0) }}ms
                </p>
              </div>
            </div>
            
            <!-- Reasoning Support Warning -->
            <div v-if="testResult.success && testResult.reasoning_supported === false && formData.reasoning_enabled" class="mt-2 pt-2 border-t border-amber-500/30">
              <div class="flex items-start gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-amber-500 mt-0.5 shrink-0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                <p class="text-amber-400 text-xs">{{ testResult.reasoning_message }}</p>
              </div>
            </div>
            
            <!-- Reasoning Support Success -->
            <div v-if="testResult.success && testResult.reasoning_supported === true && formData.reasoning_enabled" class="mt-2 pt-2 border-t border-green-500/30">
              <div class="flex items-start gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-green-500 mt-0.5 shrink-0"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                <p class="text-green-400 text-xs">{{ testResult.reasoning_message }}</p>
              </div>
            </div>
          </div>
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
                enableDualModel ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
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
        <div v-if="enableDualModel" class="space-y-4 border border-[var(--border-color)] rounded-xl p-4 bg-[var(--bg-panel)]/50 ring-1 ring-[var(--border-color)]/60">
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
              placeholder="例如: openai/o3-mini, anthropic/claude-3.7-sonnet, deepseek/deepseek-r1"
              class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
            />
            <p class="mt-1 text-xs text-[var(--text-muted)]">
              用于 Scene Intent 分析、潜意识生成、审阅与精修阶段
            </p>
            
            <!-- 逻辑推理模型的推理模式配置 -->
            <div class="mt-3 pl-3 border-l-2 border-blue-500/30">
              <div class="flex items-center justify-between mb-2">
                <label class="text-xs font-medium text-[var(--text-secondary)]">启用推理模式</label>
                <button
                  @click="formData.reasoning_model_reasoning_enabled = !formData.reasoning_model_reasoning_enabled"
                  :class="[
                    'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                    formData.reasoning_model_reasoning_enabled ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
                  ]"
                >
                  <span
                    :class="[
                      'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                      formData.reasoning_model_reasoning_enabled ? 'translate-x-5' : 'translate-x-1'
                    ]"
                  />
                </button>
              </div>
              <p class="text-xs text-[var(--text-muted)] mb-2">逻辑推理模型最推荐启用推理模式</p>
              
              <div v-if="formData.reasoning_model_reasoning_enabled" class="space-y-2">
                <select
                  v-model="formData.reasoning_model_reasoning_effort"
                  class="w-full px-2 py-1.5 text-xs bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
                >
                  <option value="xhigh">极高 (xhigh) - 约 95% tokens 用于推理</option>
                  <option value="high">高 (high) - 约 80% tokens 用于推理</option>
                  <option value="medium">中 (medium) - 约 50% tokens 用于推理</option>
                  <option value="low">低 (low) - 约 20% tokens 用于推理</option>
                </select>
                <div class="flex items-center gap-2">
                  <input type="checkbox" v-model="formData.reasoning_model_reasoning_exclude" class="rounded" />
                  <span class="text-xs text-[var(--text-muted)]">排除推理 tokens（不返回推理过程）</span>
                </div>
              </div>
            </div>
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
              class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
            />
            <p class="mt-1 text-xs text-[var(--text-muted)]">
              用于正文起草阶段，需要较强的创意和写作能力
            </p>
            
            <!-- 创意生成模型的推理模式配置 -->
            <div class="mt-3 pl-3 border-l-2 border-amber-500/30">
              <div class="flex items-center justify-between mb-2">
                <label class="text-xs font-medium text-[var(--text-secondary)]">启用推理模式</label>
                <button
                  @click="formData.creative_model_reasoning_enabled = !formData.creative_model_reasoning_enabled"
                  :class="[
                    'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                    formData.creative_model_reasoning_enabled ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
                  ]"
                >
                  <span
                    :class="[
                      'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                      formData.creative_model_reasoning_enabled ? 'translate-x-5' : 'translate-x-1'
                    ]"
                  />
                </button>
              </div>
              <p class="text-xs text-[var(--text-muted)] mb-2">创意写作通常不需要推理模式</p>
              
              <div v-if="formData.creative_model_reasoning_enabled" class="space-y-2">
                <select
                  v-model="formData.creative_model_reasoning_effort"
                  class="w-full px-2 py-1.5 text-xs bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
                >
                  <option value="high">高 (high) - 约 80% tokens 用于推理</option>
                  <option value="medium">中 (medium) - 约 50% tokens 用于推理</option>
                  <option value="low">低 (low) - 约 20% tokens 用于推理</option>
                  <option value="minimal">极低 (minimal) - 约 10% tokens 用于推理</option>
                </select>
                <div class="flex items-center gap-2">
                  <input type="checkbox" v-model="formData.creative_model_reasoning_exclude" class="rounded" />
                  <span class="text-xs text-[var(--text-muted)]">排除推理 tokens（不返回推理过程）</span>
                </div>
              </div>
            </div>
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
                <span><strong class="text-[var(--text-secondary)]">逻辑推理模型</strong>：用于 Scene Intent 分析、潜意识生成、审阅指导、灵感生成、文本润色等。推荐使用推理模型（如 o3-mini、deepseek-r1）并启用推理模式。</span>
              </p>
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0"></span>
                <span><strong class="text-[var(--text-secondary)]">创意生成模型</strong>：仅用于 Agentic 文章生成的正文起草阶段（Prose Draft）。通常不需要推理模式。</span>
              </p>
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-gray-400 mt-1.5 shrink-0"></span>
                <span>其他功能（格式化、发布、角色状态更新）使用逻辑推理模型或默认模型</span>
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- 推理模式设置（仅单模型模式时显示） -->
      <div v-if="!enableDualModel" class="px-6 pb-6 space-y-3 border-t border-[var(--border-color)] pt-4">
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-[var(--text-primary)]">启用推理模式</label>
            <p class="text-xs text-[var(--text-muted)] mt-0.5">
              适用于 OpenRouter 推理模型（o1, o3, GPT-5, Claude thinking 等）
            </p>
          </div>
          <button
            @click="formData.reasoning_enabled = !formData.reasoning_enabled"
            :class="[
              'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
              formData.reasoning_enabled ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
            ]"
          >
            <span
              :class="[
                'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                formData.reasoning_enabled ? 'translate-x-6' : 'translate-x-1'
              ]"
            />
          </button>
        </div>
        
        <!-- 推理模式详细配置 -->
        <div v-if="formData.reasoning_enabled" class="space-y-4 border border-[var(--border-color)] rounded-xl p-4 bg-[var(--bg-panel)]/50 ring-1 ring-[var(--border-color)]/60">
          <!-- 推理努力程度 -->
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
              推理努力程度
            </label>
            <select
              v-model="formData.reasoning_effort"
              class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
            >
              <option value="xhigh">极高 (xhigh) - 约 95% tokens 用于推理</option>
              <option value="high">高 (high) - 约 80% tokens 用于推理</option>
              <option value="medium">中 (medium) - 约 50% tokens 用于推理</option>
              <option value="low">低 (low) - 约 20% tokens 用于推理</option>
              <option value="minimal">极低 (minimal) - 约 10% tokens 用于推理</option>
              <option value="none">禁用 (none)</option>
            </select>
            <p class="mt-1 text-xs text-[var(--text-muted)]">
              推理努力程度越高，模型在生成前会进行更深入的思考，但响应时间也会增加。
            </p>
          </div>
          
          <!-- 排除推理 tokens -->
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-[var(--text-primary)]">排除推理 tokens</label>
              <p class="text-xs text-[var(--text-muted)] mt-0.5">
                模型仍会推理，但不在响应中返回推理过程
              </p>
            </div>
            <button
              @click="formData.reasoning_exclude = !formData.reasoning_exclude"
              :class="[
                'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                formData.reasoning_exclude ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
              ]"
            >
              <span
                :class="[
                  'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                  formData.reasoning_exclude ? 'translate-x-5' : 'translate-x-1'
                ]"
              />
            </button>
          </div>
          
          <!-- 使用说明 -->
          <div class="mt-4 pt-4 border-t border-[var(--border-color)]">
            <h4 class="text-xs font-medium text-[var(--text-primary)] mb-2 flex items-center gap-1.5">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
              推理模式说明
            </h4>
            <div class="space-y-1.5 text-xs text-[var(--text-muted)]">
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-purple-500 mt-1.5 shrink-0"></span>
                <span><strong class="text-[var(--text-secondary)]">支持的模型</strong>：OpenAI o1/o3/GPT-5、Anthropic Claude 3.7+、Gemini thinking、xAI Grok 等</span>
              </p>
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-green-500 mt-1.5 shrink-0"></span>
                <span><strong class="text-[var(--text-secondary)]">适用场景</strong>：Scene Intent 分析、审阅精修、复杂逻辑推理等任务</span>
              </p>
              <p class="flex items-start gap-2">
                <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0"></span>
                <span><strong class="text-[var(--text-secondary)]">注意事项</strong>：推理 tokens 会计入输出 token 并收费，启用后响应时间会增加</span>
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
              proxyEnabled ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
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
            class="w-full px-3 py-2 bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] rounded-xl text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40"
          />
        </div>
      </div>

      <!-- Footer -->
      <div class="p-4 border-t border-[var(--border-color)] flex justify-end space-x-3">
        <button
          @click="handleResetLocal"
          class="px-4 py-2 text-sm font-medium text-rose-400 hover:bg-rose-500/10 rounded-xl transition-colors"
        >
          重置本地设置
        </button>
        <button 
          @click="$emit('close')"
          class="px-4 py-2 text-sm font-medium text-[var(--text-primary)] bg-transparent hover:bg-[var(--bg-panel)] rounded-xl transition-colors"
        >
          取消
        </button>
        <button 
          @click="handleSave"
          class="px-4 py-2 text-sm font-medium text-white bg-accent-600 hover:bg-accent-700 rounded-xl shadow-sm transition-colors"
        >
          保存设置
        </button>
      </div>
      </div>
    </div>
  </Transition>
</template>
