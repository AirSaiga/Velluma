<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  config: {
    type: Object,
    default: () => ({
      style: ''
    })
  }
})

const emit = defineEmits(['update'])

const localConfig = ref({ style: props.config.style || '' })

watch(() => props.config, (newConfig) => {
  localConfig.value = { style: newConfig.style || '' }
}, { deep: true })

const stylePresets = [
  { value: '', label: '默认风格' },
  { value: '仙侠修真，古风韵味，意境深远，文笔优美', label: '仙侠古风' },
  { value: '科幻硬核，逻辑严密，技术细节丰富', label: '硬科幻' },
  { value: '悬疑推理，节奏紧凑，伏笔巧妙', label: '悬疑推理' },
  { value: '浪漫言情，细腻温柔，情感真挚', label: '浪漫言情' },
  { value: '史诗奇幻，宏大叙事，世界构建完整', label: '史诗奇幻' }
]

function saveConfig() {
  emit('update', { style: localConfig.value.style })
}

function applyStylePreset(preset) {
  localConfig.value.style = preset
  saveConfig()
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-secondary)] border-l border-[var(--border-color)]">
    <!-- 头部 -->
    <div class="p-4 border-b border-[var(--border-color)]">
      <h2 class="text-lg font-semibold text-[var(--text-primary)]">配置面板</h2>
    </div>
    
    <!-- 配置表单 -->
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <!-- 风格配置 -->
      <div class="space-y-4">
        <h3 class="text-sm font-medium text-[var(--text-muted)] uppercase tracking-wider">写作风格</h3>
        
        <!-- 风格预设 -->
        <div class="flex flex-wrap gap-2">
          <button
            v-for="preset in stylePresets"
            :key="preset.value"
            @click="applyStylePreset(preset.value)"
            class="px-2.5 py-1 text-xs rounded-full border transition-all"
            :class="localConfig.style === preset.value 
              ? 'bg-primary-600/20 border-primary-500 text-primary-400' 
              : 'bg-[var(--bg-tertiary)] border-[var(--border-color)] text-[var(--text-muted)] hover:border-[var(--text-muted)]'"
          >
            {{ preset.label }}
          </button>
        </div>
        
        <div>
          <label class="block text-xs text-[var(--text-muted)] mb-1.5">自定义风格描述</label>
          <textarea
            v-model="localConfig.style"
            @blur="saveConfig"
            rows="4"
            class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500 resize-none"
            placeholder="描述您想要的写作风格，例如：古风仙侠，文笔优美，意境深远..."
          />
        </div>
      </div>
      
      <!-- 使用说明 -->
      <div class="p-4 bg-[var(--bg-tertiary)]/50 rounded-lg border border-[var(--border-color)]">
        <h4 class="text-sm font-medium text-[var(--text-secondary)] mb-2">使用提示</h4>
        <ul class="text-xs text-[var(--text-muted)] space-y-1.5 list-disc list-inside">
          <li>点击右上角"设置"按钮配置 API Key</li>
          <li>在左侧设定库管理角色和世界观</li>
          <li>在中间编辑器创建剧情节拍</li>
          <li>为每个节拍选择相关的设定</li>
          <li>点击"生成正文"按钮开始 AI 写作</li>
          <li>生成的内容会自动保存</li>
        </ul>
      </div>
      
      <!-- 关于 -->
      <div class="pt-4 border-t border-[var(--border-color)]">
        <div class="text-center">
          <h4 class="text-sm font-medium text-[var(--text-secondary)]">Velluma AI</h4>
          <p class="text-xs text-[var(--text-muted)] mt-1">专为长篇小说写作特化的 AI 助手</p>
          <p class="text-xs text-[var(--text-muted)] mt-2">版本 0.1.0</p>
        </div>
      </div>
    </div>
  </div>
</template>
