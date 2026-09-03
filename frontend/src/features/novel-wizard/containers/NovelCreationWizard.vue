<script setup lang="ts">
/**
 * 小说创作向导 - 主组件
 * 
 * 职责：
 * - 向导流程的入口和容器
 * - 步骤导航
 * - 模式切换
 * - 草稿管理
 */
import { computed, onMounted, provide } from 'vue'
import { useNovelWizard } from '../composables/useNovelWizard'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useToast } from '../../../composables/useToast'
import { STORY_GENRE_PRESETS, type WizardStep } from '../types/wizard.types'
import StoryBasicsPanel from '../presentation/StoryBasicsPanel.vue'
import WorldBuildingPanel from '../presentation/WorldBuildingPanel.vue'
import CharacterManagerPanel from '../presentation/CharacterManagerPanel.vue'
import ChapterConfigPanel from '../presentation/ChapterConfigPanel.vue'
import ExpertSettingsPanel from '../presentation/ExpertSettingsPanel.vue'

// =------------- Props & Emits -------------=

const emit = defineEmits<{
  (e: 'start-generation', data: any): void
  (e: 'close'): void
}>()

// =------------- 状态管理 -------------=

const wizard = useNovelWizard()
const { show: showConfirm } = useConfirmDialog()
const { showToast } = useToast()

// 向子组件提供向导状态
provide('wizard', wizard)

// =------------- 计算属性 -------------=

const stepComponents: Record<WizardStep, any> = {
  story: StoryBasicsPanel,
  world: WorldBuildingPanel,
  characters: CharacterManagerPanel,
  chapter: ChapterConfigPanel,
  settings: ExpertSettingsPanel
}

const currentStepComponent = computed(() => {
  return stepComponents[wizard.currentStep.value]
})

const canProceed = computed(() => {
  return wizard.validate().filter(e => e.severity === 'error').length === 0
})

// =------------- 生命周期 -------------=

onMounted(() => {
  // 尝试加载草稿
  const hasDraft = wizard.loadDraft()
  if (hasDraft) {
    // 草稿恢复是用户关心的事，不能只在控制台吱一声
    showToast('已恢复上次保存的草稿', 'info')
  }
})

// =------------- 方法 -------------=

function handleModeToggle() {
  const newMode = wizard.isExpertMode.value ? 'basic' : 'expert'
  wizard.setMode(newMode)
}

function handleStepClick(step: WizardStep) {
  wizard.goToStep(step)
}

function handleNext() {
  if (wizard.goNext() && wizard.isLastStep.value) {
    // 到达最后一步，可以开始生成
    handleSubmit()
  }
}

function handlePrev() {
  wizard.goPrev()
}

async function handleSaveDraft() {
  await wizard.saveDraft()
}

function handleSubmit() {
  const validationErrors = wizard.validate()
  const errors = validationErrors.filter(e => e.severity === 'error')
  if (errors.length > 0) {
    // 此前静默 return：用户点「开始生成」没反应且不知道原因
    showToast(errors[0].message || '请完善必填项后再创建', 'warning')
    return
  }

  emit('start-generation', wizard.formData.value)
}

// 书架页在创建全链成功后调用（2026-09-04 审计修复：clearDraft 此前零调用，
// 草稿留在 localStorage 跨书复活——下次开向导自动恢复旧书设定诱导重复建书）。
// 失败路径不由这里清：向导留着可改后重试。
defineExpose({ clearDraft: () => wizard.clearDraft() })

async function handleClose() {
  // 未保存更改守卫：UI 显示了「• 有未保存的更改」却曾可直接关闭全丢
  if (wizard.isDirty.value) {
    const ok = await showConfirm({
      title: '关闭向导',
      message: '当前有未保存的更改，关闭后将丢失。',
      warning: '可先点「保存草稿」保留进度，下次打开继续。',
      confirmText: '仍要关闭',
      cancelText: '继续编辑',
    })
    if (!ok) return
  }
  emit('close')
}
</script>

<template>
  <div class="wizard-container fixed inset-0 z-50 bg-[var(--bg-primary)]/95 backdrop-blur-sm">
    <div class="wizard-content h-full max-w-5xl mx-auto flex flex-col p-4">
      
      <!-- 头部：标题 + 模式切换 -->
      <header class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-3">
          <h1 class="text-xl font-heading font-semibold text-[var(--text-primary)]">
            📚 小说创作向导
          </h1>
          <span 
            v-if="wizard.isDirty.value" 
            class="text-xs text-[var(--text-muted)]"
          >
            • 有未保存的更改
          </span>
        </div>
        
        <div class="flex items-center gap-3">
          <!-- 模式切换 -->
          <div class="flex items-center gap-2 bg-[var(--bg-secondary)] rounded-lg p-1">
            <button
              @click="handleModeToggle"
              :class="[
                'px-3 py-1.5 text-xs font-medium rounded-md transition-all',
                !wizard.isExpertMode.value 
                  ? 'bg-accent-500 text-white shadow-sm' 
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              ]"
            >
              基础模式
            </button>
            <button
              @click="handleModeToggle"
              :class="[
                'px-3 py-1.5 text-xs font-medium rounded-md transition-all',
                wizard.isExpertMode.value 
                  ? 'bg-accent-500 text-white shadow-sm' 
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              ]"
            >
              专家模式
            </button>
          </div>
          
          <!-- 关闭按钮（D3 加固：图标钮无文字，文字版按钮清单易漏看——补 title/aria 提升可发现性） -->
          <button
            @click="handleClose"
            title="关闭向导（未保存更改会先确认）"
            aria-label="关闭向导"
            class="p-2 rounded-lg hover:bg-[var(--bg-secondary)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </header>
      
      <!-- 步骤指示器 -->
      <nav class="mb-6">
        <div class="flex items-center justify-center gap-1">
          <template v-for="(step, index) in wizard.stepOrder" :key="step">
            <button
              @click="handleStepClick(step as WizardStep)"
              :class="[
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all',
                wizard.currentStep.value === step
                  ? 'bg-accent-500/15 text-accent-700 font-medium'
                  : wizard.stepIndex.value > index
                    ? 'text-accent-600 hover:bg-accent-500/10'
                    : 'text-[var(--text-muted)] hover:bg-[var(--bg-secondary)]'
              ]"
            >
              <span
                :class="[
                  'w-6 h-6 rounded-full flex items-center justify-center text-xs',
                  wizard.currentStep.value === step
                    ? 'bg-accent-500 text-white'
                    : wizard.stepIndex.value > index
                      ? 'bg-accent-500/20 text-accent-600'
                      : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
                ]"
              >
                {{ wizard.stepIndex.value > index ? '✓' : index + 1 }}
              </span>
              <span>{{ wizard.stepLabels[step as WizardStep] }}</span>
            </button>
            
            <!-- 连接线 -->
            <div
              v-if="index < wizard.stepOrder.length - 1"
              :class="[
                'w-8 h-0.5 mx-1',
                wizard.stepIndex.value > index ? 'bg-accent-500' : 'bg-[var(--bg-tertiary)]'
              ]"
            />
          </template>
        </div>
        
        <!-- 专家模式提示 -->
        <p 
          v-if="wizard.isExpertMode.value && wizard.currentStep.value !== 'settings'"
          class="text-center text-xs text-[var(--text-muted)] mt-2"
        >
          💡 专家模式下可配置更多高级选项
        </p>
      </nav>
      
      <!-- 内容区域 -->
      <main class="flex-1 min-h-0 overflow-hidden rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)]/30">
        <Transition name="fade" mode="out-in">
          <component 
            :is="currentStepComponent" 
            :key="wizard.currentStep.value"
            :form-data="wizard.formData.value"
            :is-expert-mode="wizard.isExpertMode.value"
            :errors="wizard.errors.value"
            :story-templates="STORY_GENRE_PRESETS"
            @update:story="(updates) => wizard.formData.value.story = { ...wizard.formData.value.story, ...updates }"
            @apply-template="wizard.applyStoryTemplate"
            @add-world-item="wizard.addWorldItem"
            @remove-world-item="wizard.removeWorldItem"
            @add-location="wizard.addLocation"
            @remove-location="wizard.removeLocation"
            @add-character="wizard.addCharacter"
            @update-character="wizard.updateCharacter"
            @remove-character="wizard.removeCharacter"
            @add-relationship="wizard.addRelationship"
            @update-relationship="wizard.updateRelationship"
            @remove-relationship="wizard.removeRelationship"
            @update-chapter="wizard.updateChapterConfig"
            @toggle-character="wizard.toggleChapterCharacter"
            @update-expert-settings="wizard.updateExpertSettings"
          />
        </Transition>
      </main>
      
      <!-- 底部操作栏 -->
      <footer class="flex items-center justify-between mt-4 pt-4 border-t border-[var(--border-color)]/30">
        <div class="flex items-center gap-2">
          <button
            v-if="wizard.isDirty.value"
            @click="handleSaveDraft"
            :disabled="wizard.isSaving.value"
            class="px-4 py-2 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-lg transition-colors flex items-center gap-2"
          >
            <svg v-if="wizard.isSaving.value" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <span>{{ wizard.isSaving.value ? '保存中...' : '保存草稿' }}</span>
          </button>
          
          <span
            v-if="wizard.formData.value.draftStatus === 'saved'"
            class="text-xs text-green-500"
          >
            ✓ 已保存
          </span>
        </div>
        
        <div class="flex items-center gap-3">
          <button
            @click="handlePrev"
            :disabled="wizard.isFirstStep.value"
            :class="[
              'px-4 py-2 text-sm rounded-lg transition-colors',
              wizard.isFirstStep.value
                ? 'text-[var(--text-muted)] cursor-not-allowed'
                : 'text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]'
            ]"
          >
            ← 上一步
          </button>
          
          <button
            v-if="!wizard.isLastStep.value"
            @click="handleNext"
            class="px-6 py-2 text-sm font-medium bg-accent-500 hover:bg-accent-600 text-white rounded-lg shadow-sm transition-colors"
          >
            下一步 →
          </button>
          
          <button
            v-else
            @click="handleSubmit"
            :disabled="!canProceed"
            :class="[
              'px-6 py-2 text-sm font-medium rounded-lg shadow-sm transition-colors',
              canProceed
                ? 'bg-green-500 hover:bg-green-600 text-white'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] cursor-not-allowed'
            ]"
          >
            创建书籍
          </button>
        </div>
      </footer>
      
    </div>
  </div>
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
