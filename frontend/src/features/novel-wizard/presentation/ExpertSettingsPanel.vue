<script setup lang="ts">
/**
 * 专家设置面板
 * 
 * 职责：
 * - 配置模型选择
 * - 配置推理模式
 * - 配置 RAG 记忆检索参数
 * - 配置双轨生成和迭代参数
 */
import { ref, computed } from 'vue'
import type { 
  ExpertSettings, 
  ReasoningEffort,
  RAGSettings,
  GenerationSettings,
  ValidationError 
} from '../types/wizard.types'

// =------------- Props & Emits -------------=

const props = defineProps<{
  formData: { expertSettings: ExpertSettings }
  isExpertMode: boolean
  errors: ValidationError[]
}>()

const emit = defineEmits<{
  (e: 'update-expert-settings', updates: Partial<ExpertSettings>): void
}>()

// =------------- 状态 -------------=

const expandedSections = ref({
  models: true,
  reasoning: false,
  rag: false,
  generation: false
})

// =------------- 计算属性 -------------=

const settings = computed(() => props.formData.expertSettings)

const reasoningEffortLabels: Record<ReasoningEffort, string> = {
  xhigh: '极高',
  high: '高',
  medium: '中',
  low: '低',
  minimal: '极低',
  none: '禁用'
}

const reasoningEffortDescriptions: Record<ReasoningEffort, string> = {
  xhigh: '约 95% tokens 用于推理',
  high: '约 80% tokens 用于推理',
  medium: '约 50% tokens 用于推理',
  low: '约 20% tokens 用于推理',
  minimal: '约 10% tokens 用于推理',
  none: '不使用推理模式'
}

const ragWeightTotal = computed(() => {
  const { semanticWeight, timeDecayWeight, foreshadowingWeight } = settings.value.ragConfig
  return semanticWeight + timeDecayWeight + foreshadowingWeight
})

const ragWeightWarning = computed(() => {
  const total = ragWeightTotal.value
  if (Math.abs(total - 1) > 0.01) {
    return `权重总和应为 1.0，当前为 ${total.toFixed(2)}`
  }
  return null
})

// =------------- 方法 -------------=

function updateRagConfig(updates: Partial<RAGSettings>) {
  emit('update-expert-settings', {
    ragConfig: { ...settings.value.ragConfig, ...updates }
  })
}

function updateGenerationConfig(updates: Partial<GenerationSettings>) {
  emit('update-expert-settings', {
    generationConfig: { ...settings.value.generationConfig, ...updates }
  })
}

function toggleSection(section: keyof typeof expandedSections.value) {
  expandedSections.value[section] = !expandedSections.value[section]
}
</script>

<template>
  <div class="expert-settings-panel h-full overflow-y-auto p-6">
    <div class="max-w-3xl mx-auto">
      
      <!-- 标题 -->
      <div class="text-center mb-8">
        <div class="flex items-center justify-center gap-2 mb-2">
          <span class="px-2 py-1 text-xs bg-amber-500/10 text-amber-600 rounded-lg">专家模式</span>
          <h2 class="text-2xl font-heading font-semibold text-[var(--text-primary)]">
            高级设置 ⚙️
          </h2>
        </div>
        <p class="text-sm text-[var(--text-muted)]">
          精细控制 AI 的生成行为（普通用户可跳过此步骤）
        </p>
      </div>
      
      <!-- 提示信息 -->
      <div class="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4 mb-8">
        <div class="flex items-start gap-3">
          <span class="text-lg">⚠️</span>
          <div class="text-sm text-[var(--text-secondary)]">
            <p class="font-medium text-amber-600 mb-1">专家设置说明</p>
            <p class="text-xs text-[var(--text-muted)]">
              以下设置需要一定的技术背景。如果你不确定某个参数的作用，建议使用默认值。
              错误的配置可能会影响生成质量。
            </p>
          </div>
        </div>
      </div>
      
      <!-- 模型选择 -->
      <section class="mb-6">
        <button
          @click="toggleSection('models')"
          class="w-full flex items-center justify-between p-4 bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]/50 hover:bg-[var(--bg-secondary)] transition-colors"
        >
          <div class="flex items-center gap-3">
            <span class="text-lg">🤖</span>
            <div class="text-left">
              <h3 class="text-base font-medium text-[var(--text-primary)]">模型选择</h3>
              <p class="text-xs text-[var(--text-muted)]">配置生成和推理使用的语言模型</p>
            </div>
          </div>
          <svg
            :class="['w-5 h-5 text-[var(--text-muted)] transition-transform', expandedSections.models ? 'rotate-90' : '']"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
          </svg>
        </button>
        
        <Transition name="expand">
          <div v-if="expandedSections.models" class="mt-4 pl-4 space-y-4">
            <div class="p-4 bg-[var(--bg-panel)]/50 rounded-xl border border-[var(--border-color)]/30">
              <p class="text-sm text-[var(--text-secondary)] mb-2">
                当前模型配置仅通过本地配置文件管理，不在此处修改。
              </p>
              <p class="text-xs text-[var(--text-muted)] leading-relaxed">
                请手动编辑项目根目录下的 <code class="px-1.5 py-0.5 bg-[var(--bg-tertiary)] rounded text-[var(--text-primary)]">model_config.json</code> 来配置模型。
              </p>
              <div class="mt-3 text-xs text-[var(--text-muted)] space-y-1">
                <p>V4.2 起支持为 <span class="text-[var(--text-secondary)]">reasoning</span>（推理）和 <span class="text-[var(--text-secondary)]">creative</span>（创意）分别指定不同的模型提供商：</p>
                <ul class="list-disc list-inside ml-1 space-y-0.5">
                  <li><span class="text-[var(--text-secondary)]">openrouter</span> — OpenRouter 聚合平台</li>
                  <li><span class="text-[var(--text-secondary)]">volcengine</span> — 字节火山引擎（兼容 OpenAI 协议）</li>
                  <li><span class="text-[var(--text-secondary)]">deepseek</span> — Deepseek API（兼容 OpenAI 协议）</li>
                </ul>
              </div>
              <p class="text-[10px] text-[var(--text-muted)] mt-3">
                修改后请重启后端服务以生效。
              </p>
            </div>
          </div>
        </Transition>
      </section>
      
      <!-- 推理模式配置 -->
      <section class="mb-6">
        <button
          @click="toggleSection('reasoning')"
          class="w-full flex items-center justify-between p-4 bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]/50 hover:bg-[var(--bg-secondary)] transition-colors"
        >
          <div class="flex items-center gap-3">
            <span class="text-lg">🧠</span>
            <div class="text-left">
              <h3 class="text-base font-medium text-[var(--text-primary)]">推理模式</h3>
              <p class="text-xs text-[var(--text-muted)]">让模型在生成前进行深度思考</p>
            </div>
          </div>
          <svg
            :class="['w-5 h-5 text-[var(--text-muted)] transition-transform', expandedSections.reasoning ? 'rotate-90' : '']"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
          </svg>
        </button>
        
        <Transition name="expand">
          <div v-if="expandedSections.reasoning" class="mt-4 pl-4 space-y-4">
            
            <!-- 默认模型推理配置 -->
            <div class="p-4 bg-[var(--bg-panel)]/50 rounded-xl border border-[var(--border-color)]/30">
              <div class="flex items-center justify-between mb-3">
                <label class="text-sm font-medium text-[var(--text-primary)]">默认模型推理模式</label>
                <button
                  @click="emit('update-expert-settings', { 
                    reasoningConfig: { 
                      ...settings.reasoningConfig, 
                      enabled: !settings.reasoningConfig.enabled 
                    } 
                  })"
                  :class="[
                    'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                    settings.reasoningConfig.enabled ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
                  ]"
                >
                  <span
                    :class="[
                      'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                      settings.reasoningConfig.enabled ? 'translate-x-5' : 'translate-x-1'
                    ]"
                  />
                </button>
              </div>
              
              <Transition name="expand">
                <div v-if="settings.reasoningConfig.enabled" class="space-y-3">
                  <div>
                    <label class="block text-xs text-[var(--text-muted)] mb-1">推理强度</label>
                    <select
                      :value="settings.reasoningConfig.effort"
                      @change="emit('update-expert-settings', { 
                        reasoningConfig: { 
                          ...settings.reasoningConfig, 
                          effort: ($event.target as HTMLSelectElement).value as ReasoningEffort 
                        } 
                      })"
                      class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
                    >
                      <option v-for="(label, key) in reasoningEffortLabels" :key="key" :value="key">
                        {{ label }} - {{ reasoningEffortDescriptions[key as ReasoningEffort] }}
                      </option>
                    </select>
                  </div>
                  <div class="flex items-center gap-2">
                    <input
                      type="checkbox"
                      :checked="settings.reasoningConfig.excludeProcess"
                      @change="emit('update-expert-settings', { 
                        reasoningConfig: { 
                          ...settings.reasoningConfig, 
                          excludeProcess: ($event.target as HTMLInputElement).checked 
                        } 
                      })"
                      class="rounded"
                    />
                    <span class="text-xs text-[var(--text-muted)]">排除推理过程（不返回思考过程）</span>
                  </div>
                </div>
              </Transition>
            </div>
            

          </div>
        </Transition>
      </section>
      
      <!-- RAG 记忆检索 -->
      <section class="mb-6">
        <button
          @click="toggleSection('rag')"
          class="w-full flex items-center justify-between p-4 bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]/50 hover:bg-[var(--bg-secondary)] transition-colors"
        >
          <div class="flex items-center gap-3">
            <span class="text-lg">📚</span>
            <div class="text-left">
              <h3 class="text-base font-medium text-[var(--text-primary)]">记忆检索 (RAG)</h3>
              <p class="text-xs text-[var(--text-muted)]">控制 AI 如何从历史章节中检索相关信息</p>
            </div>
          </div>
          <svg
            :class="['w-5 h-5 text-[var(--text-muted)] transition-transform', expandedSections.rag ? 'rotate-90' : '']"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
          </svg>
        </button>
        
        <Transition name="expand">
          <div v-if="expandedSections.rag" class="mt-4 pl-4 space-y-4">
            
            <!-- 检索数量 -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
                记忆检索数量
              </label>
              <input
                :value="settings.ragConfig.topK"
                @input="updateRagConfig({ topK: parseInt(($event.target as HTMLInputElement).value) || 5 })"
                type="number"
                min="1"
                max="20"
                class="w-24 px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
              />
              <p class="text-[10px] text-[var(--text-muted)] mt-1">
                内部字段：rag_top_k — 从历史章节中检索多少条相关记忆
              </p>
            </div>
            
            <!-- 权重配置 -->
            <div class="p-4 bg-[var(--bg-panel)]/50 rounded-xl">
              <div class="flex items-center justify-between mb-3">
                <label class="text-sm font-medium text-[var(--text-primary)]">检索权重配置</label>
                <span 
                  class="text-xs px-2 py-1 rounded-lg"
                  :class="ragWeightWarning ? 'bg-amber-500/10 text-amber-600' : 'bg-green-500/10 text-green-600'"
                >
                  总和: {{ ragWeightTotal.toFixed(2) }}
                </span>
              </div>
              
              <div class="space-y-3">
                <div>
                  <div class="flex items-center justify-between text-xs mb-1">
                    <span class="text-[var(--text-muted)]">语义相关度权重</span>
                    <span class="text-[var(--text-primary)]">{{ settings.ragConfig.semanticWeight.toFixed(2) }}</span>
                  </div>
                  <input
                    :value="settings.ragConfig.semanticWeight"
                    @input="updateRagConfig({ semanticWeight: parseFloat(($event.target as HTMLInputElement).value) || 0.6 })"
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    class="w-full"
                  />
                  <p class="text-[10px] text-[var(--text-muted)]">内部字段：rag_alpha</p>
                </div>
                
                <div>
                  <div class="flex items-center justify-between text-xs mb-1">
                    <span class="text-[var(--text-muted)]">时间衰减权重</span>
                    <span class="text-[var(--text-primary)]">{{ settings.ragConfig.timeDecayWeight.toFixed(2) }}</span>
                  </div>
                  <input
                    :value="settings.ragConfig.timeDecayWeight"
                    @input="updateRagConfig({ timeDecayWeight: parseFloat(($event.target as HTMLInputElement).value) || 0.2 })"
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    class="w-full"
                  />
                  <p class="text-[10px] text-[var(--text-muted)]">内部字段：rag_beta — 较近章节的记忆权重更高</p>
                </div>
                
                <div>
                  <div class="flex items-center justify-between text-xs mb-1">
                    <span class="text-[var(--text-muted)]">伏笔权重</span>
                    <span class="text-[var(--text-primary)]">{{ settings.ragConfig.foreshadowingWeight.toFixed(2) }}</span>
                  </div>
                  <input
                    :value="settings.ragConfig.foreshadowingWeight"
                    @input="updateRagConfig({ foreshadowingWeight: parseFloat(($event.target as HTMLInputElement).value) || 0.2 })"
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    class="w-full"
                  />
                  <p class="text-[10px] text-[var(--text-muted)]">内部字段：rag_gamma — 与伏笔相关的记忆权重更高</p>
                </div>
              </div>
              
              <p v-if="ragWeightWarning" class="text-xs text-amber-600 mt-3">
                ⚠️ {{ ragWeightWarning }}
              </p>
            </div>
            
          </div>
        </Transition>
      </section>
      
      <!-- 生成流程配置 -->
      <section class="mb-6">
        <button
          @click="toggleSection('generation')"
          class="w-full flex items-center justify-between p-4 bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]/50 hover:bg-[var(--bg-secondary)] transition-colors"
        >
          <div class="flex items-center gap-3">
            <span class="text-lg">🔄</span>
            <div class="text-left">
              <h3 class="text-base font-medium text-[var(--text-primary)]">生成流程</h3>
              <p class="text-xs text-[var(--text-muted)]">控制生成-审阅-精修的迭代流程</p>
            </div>
          </div>
          <svg
            :class="['w-5 h-5 text-[var(--text-muted)] transition-transform', expandedSections.generation ? 'rotate-90' : '']"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
          </svg>
        </button>
        
        <Transition name="expand">
          <div v-if="expandedSections.generation" class="mt-4 pl-4 space-y-4">
            
            <!-- 最大迭代次数 -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
                最大迭代次数
              </label>
              <input
                :value="settings.generationConfig.maxIterations"
                @input="updateGenerationConfig({ maxIterations: parseInt(($event.target as HTMLInputElement).value) || 3 })"
                type="number"
                min="1"
                max="5"
                class="w-24 px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
              />
              <p class="text-[10px] text-[var(--text-muted)] mt-1">
                内部字段：max_iterations — 生成-审阅-精修的循环次数上限
              </p>
            </div>
            
            <!-- 双轨生成 -->
            <div class="flex items-center justify-between p-3 bg-[var(--bg-panel)]/50 rounded-xl">
              <div>
                <label class="text-sm font-medium text-[var(--text-primary)]">启用双轨生成</label>
                <p class="text-xs text-[var(--text-muted)]">并行生成 + 连贯性校验</p>
              </div>
              <button
                @click="updateGenerationConfig({ enableDualTrack: !settings.generationConfig.enableDualTrack })"
                :class="[
                  'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                  settings.generationConfig.enableDualTrack ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
                ]"
              >
                <span
                  :class="[
                    'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                    settings.generationConfig.enableDualTrack ? 'translate-x-5' : 'translate-x-1'
                  ]"
                />
              </button>
            </div>
            
            <!-- 跳过轻微问题 -->
            <div class="flex items-center justify-between p-3 bg-[var(--bg-panel)]/50 rounded-xl">
              <div>
                <label class="text-sm font-medium text-[var(--text-primary)]">跳过轻微问题</label>
                <p class="text-xs text-[var(--text-muted)]">审阅发现小问题时不触发精修</p>
              </div>
              <button
                @click="updateGenerationConfig({ skipMinorRefine: !settings.generationConfig.skipMinorRefine })"
                :class="[
                  'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                  settings.generationConfig.skipMinorRefine ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
                ]"
              >
                <span
                  :class="[
                    'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                    settings.generationConfig.skipMinorRefine ? 'translate-x-5' : 'translate-x-1'
                  ]"
                />
              </button>
            </div>
            
            <!-- 强制并行起草 -->
            <div class="flex items-center justify-between p-3 bg-[var(--bg-panel)]/50 rounded-xl">
              <div>
                <label class="text-sm font-medium text-[var(--text-primary)]">强制并行起草</label>
                <p class="text-xs text-[var(--text-muted)]">多个节拍同时起草（可能影响连贯性）</p>
              </div>
              <button
                @click="updateGenerationConfig({ forceParallelProse: !settings.generationConfig.forceParallelProse })"
                :class="[
                  'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                  settings.generationConfig.forceParallelProse ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
                ]"
              >
                <span
                  :class="[
                    'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                    settings.generationConfig.forceParallelProse ? 'translate-x-5' : 'translate-x-1'
                  ]"
                />
              </button>
            </div>
            
          </div>
        </Transition>
      </section>
      
      <!-- 跳过说明 -->
      <div class="bg-[var(--bg-panel)]/50 rounded-xl p-4 mt-8 text-center">
        <p class="text-sm text-[var(--text-muted)]">
          如果不确定如何配置，可以直接跳过此步骤，系统会使用默认设置。
        </p>
      </div>
      
    </div>
  </div>
</template>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 1000px;
}
</style>
