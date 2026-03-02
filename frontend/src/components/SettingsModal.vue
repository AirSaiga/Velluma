<script setup>
import { ref, watch } from 'vue'
import { useTheme } from '../composables/useTheme'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  config: {
    type: Object,
    default: () => ({
      api_key: '',
      base_url: '',
      model: 'gpt-4o-mini'
    })
  }
})

const emit = defineEmits(['close', 'update'])

const { theme, setTheme } = useTheme()

const localConfig = ref({ ...props.config })

watch(() => props.config, (newConfig) => {
  localConfig.value = { ...newConfig }
}, { deep: true })

const models = [
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
  { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' }
]

function handleThemeChange(newTheme) {
  setTheme(newTheme)
}

function handleMaskClick() {
  emit('close')
}

function saveConfig() {
  emit('update', { ...localConfig.value })
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-50 flex items-center justify-center"
      >
        <!-- 遮罩层 -->
        <div
          class="absolute inset-0 bg-black/50"
          @click="handleMaskClick"
        ></div>

        <!-- 弹窗内容 -->
        <div
          class="relative w-full max-w-md mx-4 rounded-xl shadow-xl"
          :class="theme === 'dark' ? 'bg-slate-800' : 'bg-white'"
        >
          <!-- 头部 -->
          <div
            class="flex items-center justify-between p-4 border-b"
            :class="theme === 'dark' ? 'border-slate-700' : 'border-slate-200'"
          >
            <h2
              class="text-lg font-semibold"
              :class="theme === 'dark' ? 'text-slate-100' : 'text-slate-800'"
            >
              设置
            </h2>
            <button
              @click="emit('close')"
              class="p-1 rounded-lg transition-colors"
              :class="theme === 'dark' 
                ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700' 
                : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- 内容区 -->
          <div class="p-4 space-y-6">
            <!-- 主题设置 -->
            <div class="space-y-3">
              <h3
                class="text-sm font-medium"
                :class="theme === 'dark' ? 'text-slate-300' : 'text-slate-700'"
              >
                主题
              </h3>
              <div class="flex gap-3">
                <!-- 浅色主题选项 -->
                <button
                  @click="handleThemeChange('light')"
                  class="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all"
                  :class="theme === 'light'
                    ? 'border-primary-500 bg-primary-500/10'
                    : theme === 'dark' 
                      ? 'border-slate-600 bg-slate-700 hover:border-slate-500' 
                      : 'border-slate-300 bg-slate-50 hover:border-slate-400'"
                >
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                  </svg>
                  <span
                    class="text-sm font-medium"
                    :class="theme === 'light' 
                      ? 'text-primary-600' 
                      : theme === 'dark' 
                        ? 'text-slate-300' 
                        : 'text-slate-700'"
                  >
                    浅色
                  </span>
                </button>

                <!-- 深色主题选项 -->
                <button
                  @click="handleThemeChange('dark')"
                  class="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all"
                  :class="theme === 'dark'
                    ? 'border-primary-500 bg-primary-500/10'
                    : 'border-slate-300 bg-slate-50 hover:border-slate-400'"
                >
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                  </svg>
                  <span
                    class="text-sm font-medium"
                    :class="theme === 'dark' 
                      ? 'text-primary-400' 
                      : 'text-slate-700'"
                  >
                    深色
                  </span>
                </button>
              </div>
            </div>

            <!-- API 配置 -->
            <div class="space-y-3">
              <h3
                class="text-sm font-medium"
                :class="theme === 'dark' ? 'text-slate-300' : 'text-slate-700'"
              >
                API 配置
              </h3>
              
              <div>
                <label 
                  class="block text-xs mb-1.5"
                  :class="theme === 'dark' ? 'text-slate-400' : 'text-slate-600'"
                >
                  API Key
                  <span class="text-rose-500">*</span>
                </label>
                <input
                  v-model="localConfig.api_key"
                  type="password"
                  @blur="saveConfig"
                  class="w-full px-3 py-2 rounded-lg border text-sm focus:outline-none focus:border-primary-500"
                  :class="theme === 'dark' 
                    ? 'bg-slate-700 border-slate-600 text-slate-100' 
                    : 'bg-white border-slate-300 text-slate-800'"
                  placeholder="sk-..."
                />
              </div>
              
              <div>
                <label 
                  class="block text-xs mb-1.5"
                  :class="theme === 'dark' ? 'text-slate-400' : 'text-slate-600'"
                >
                  Base URL (可选)
                </label>
                <input
                  v-model="localConfig.base_url"
                  type="text"
                  @blur="saveConfig"
                  class="w-full px-3 py-2 rounded-lg border text-sm focus:outline-none focus:border-primary-500"
                  :class="theme === 'dark' 
                    ? 'bg-slate-700 border-slate-600 text-slate-100' 
                    : 'bg-white border-slate-300 text-slate-800'"
                  placeholder="https://api.openai.com/v1"
                />
              </div>
              
              <div>
                <label 
                  class="block text-xs mb-1.5"
                  :class="theme === 'dark' ? 'text-slate-400' : 'text-slate-600'"
                >
                  模型
                </label>
                <select
                  v-model="localConfig.model"
                  @change="saveConfig"
                  class="w-full px-3 py-2 rounded-lg border text-sm focus:outline-none focus:border-primary-500"
                  :class="theme === 'dark' 
                    ? 'bg-slate-700 border-slate-600 text-slate-100' 
                    : 'bg-white border-slate-300 text-slate-800'"
                >
                  <option v-for="model in models" :key="model.value" :value="model.value">
                    {{ model.label }}
                  </option>
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
