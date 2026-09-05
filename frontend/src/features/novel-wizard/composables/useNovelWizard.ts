/**
 * 小说创作向导 - 状态管理组合式函数
 * 
 * 职责：
 * - 管理向导整体状态
 * - 处理步骤导航
 * - 处理草稿保存
 * - 处理表单验证
 * - 提供模式切换
 */

import { ref, computed, watch, type Ref, type ComputedRef } from 'vue'
import {
  type WizardFormData,
  type WizardStep,
  type EditorMode,
  type ValidationError,
  type CharacterInfo,
  type CharacterRelationship,
  type WorldItem,
  type Location,
  type StoryTemplate,
  createDefaultWizardData,
  STORY_GENRE_PRESETS
} from '../types/wizard.types'

// ============== 常量定义 ==============

const DRAFT_STORAGE_KEY = 'velluma_wizard_draft_v1'
const MODE_STORAGE_KEY = 'velluma_wizard_mode_v1'
const AUTOSAVE_DELAY_MS = 3000

const STEP_ORDER: WizardStep[] = ['story', 'world', 'characters', 'chapter', 'settings']

const STEP_LABELS: Record<WizardStep, string> = {
  story: '故事设定',
  world: '世界观',
  characters: '角色',
  chapter: '章节',
  settings: '高级设置'
}

// ============== 返回类型 ==============

export interface UseNovelWizardReturn {
  // 状态
  formData: Ref<WizardFormData>
  currentStep: ComputedRef<WizardStep>
  isExpertMode: ComputedRef<boolean>
  stepIndex: ComputedRef<number>
  isFirstStep: ComputedRef<boolean>
  isLastStep: ComputedRef<boolean>
  errors: Ref<ValidationError[]>
  isDirty: Ref<boolean>
  isSaving: Ref<boolean>
  
  // 步骤信息
  stepLabels: typeof STEP_LABELS
  stepOrder: typeof STEP_ORDER
  
  // 方法
  setMode: (mode: EditorMode) => void
  goToStep: (step: WizardStep) => void
  goNext: () => boolean
  goPrev: () => void
  validate: () => ValidationError[]
  saveDraft: () => Promise<void>
  loadDraft: () => boolean
  clearDraft: () => void
  reset: () => void
  
  // 故事设定
  applyStoryTemplate: (template: StoryTemplate) => void
  
  // 世界观
  addWorldItem: (type: 'background' | 'rules', item: WorldItem) => void
  removeWorldItem: (type: 'background' | 'rules', id: string) => void
  addLocation: (location: Location) => void
  removeLocation: (id: string) => void
  
  // 角色管理
  addCharacter: (character: CharacterInfo) => void
  updateCharacter: (id: string, updates: Partial<CharacterInfo>) => void
  removeCharacter: (id: string) => void
  addRelationship: (relationship: CharacterRelationship) => void
  updateRelationship: (id: string, updates: Partial<CharacterRelationship>) => void
  removeRelationship: (id: string) => void
  
  // 章节配置
  updateChapterConfig: (updates: Partial<WizardFormData['chapter']>) => void
  toggleChapterCharacter: (characterId: string) => void
  
  // 专家设置
  updateExpertSettings: (updates: Partial<WizardFormData['expertSettings']>) => void
}

// ============== 组合式函数 ==============

export function useNovelWizard(): UseNovelWizardReturn {
  // =------------- 状态初始化 -------------=
  
  const formData = ref<WizardFormData>(createDefaultWizardData())
  const errors = ref<ValidationError[]>([])
  const isDirty = ref(false)
  const isSaving = ref(false)
  
  let autosaveTimer: ReturnType<typeof setTimeout> | null = null
  
  // 从本地存储恢复模式
  const savedMode = localStorage.getItem(MODE_STORAGE_KEY) as EditorMode | null
  if (savedMode) {
    formData.value.mode = savedMode
  }
  
  // =------------- 计算属性 -------------=
  
  const currentStep = computed(() => formData.value.currentStep)
  const isExpertMode = computed(() => formData.value.mode === 'expert')
  const stepIndex = computed(() => STEP_ORDER.indexOf(formData.value.currentStep))
  const isFirstStep = computed(() => stepIndex.value === 0)
  const isLastStep = computed(() => stepIndex.value === STEP_ORDER.length - 1)
  
  // =------------- 模式切换 -------------=
  
  function setMode(mode: EditorMode) {
    formData.value.mode = mode
    localStorage.setItem(MODE_STORAGE_KEY, mode)
  }
  
  // =------------- 步骤导航 -------------=
  
  function goToStep(step: WizardStep) {
    if (validateStep(formData.value.currentStep)) {
      formData.value.currentStep = step
    }
  }
  
  function goNext(): boolean {
    if (isLastStep.value) return false
    if (!validateStep(formData.value.currentStep)) return false
    
    const nextIndex = stepIndex.value + 1
    formData.value.currentStep = STEP_ORDER[nextIndex]
    return true
  }
  
  function goPrev() {
    if (isFirstStep.value) return
    const prevIndex = stepIndex.value - 1
    formData.value.currentStep = STEP_ORDER[prevIndex]
  }
  
  // =------------- 验证逻辑 -------------=
  
  function validateStep(step: WizardStep): boolean {
    const stepErrors: ValidationError[] = []
    
    switch (step) {
      case 'story':
        if (!formData.value.story.title.trim()) {
          stepErrors.push({ field: 'story.title', message: '请输入书名', severity: 'error' })
        }
        if (!formData.value.story.genre.trim()) {
          stepErrors.push({ field: 'story.genre', message: '请选择故事类型', severity: 'error' })
        }
        break
        
      case 'chapter':
        if (!formData.value.chapter.title.trim()) {
          stepErrors.push({ field: 'chapter.title', message: '请输入章节标题', severity: 'warning' })
        }
        if (!formData.value.chapter.outline.trim()) {
          stepErrors.push({ field: 'chapter.outline', message: '请填写章节大纲', severity: 'error' })
        }
        if (formData.value.chapter.targetWordCount < 500) {
          stepErrors.push({ field: 'chapter.targetWordCount', message: '目标字数至少500字', severity: 'error' })
        }
        break
    }
    
    errors.value = stepErrors
    return stepErrors.filter(e => e.severity === 'error').length === 0
  }
  
  function validate(): ValidationError[] {
    const allErrors: ValidationError[] = []
    
    // 验证故事设定
    if (!formData.value.story.title.trim()) {
      allErrors.push({ field: 'story.title', message: '请输入书名', severity: 'error' })
    }
    
    // 验证章节配置
    if (!formData.value.chapter.outline.trim()) {
      allErrors.push({ field: 'chapter.outline', message: '请填写章节大纲', severity: 'error' })
    }
    
    errors.value = allErrors
    return allErrors
  }
  
  // =------------- 草稿保存 -------------=
  
  async function saveDraft(): Promise<void> {
    isSaving.value = true
    formData.value.draftStatus = 'saving'
    
    try {
      const draftData = JSON.stringify(formData.value)
      localStorage.setItem(DRAFT_STORAGE_KEY, draftData)
      formData.value.draftStatus = 'saved'
      isDirty.value = false
      
      setTimeout(() => {
        if (formData.value.draftStatus === 'saved') {
          formData.value.draftStatus = 'idle'
        }
      }, 1500)
    } catch (error) {
      formData.value.draftStatus = 'error'
      console.error('保存草稿失败:', error)
    } finally {
      isSaving.value = false
    }
  }
  
  function loadDraft(): boolean {
    try {
      const saved = localStorage.getItem(DRAFT_STORAGE_KEY)
      if (saved) {
        formData.value = JSON.parse(saved)
        return true
      }
    } catch (error) {
      console.error('加载草稿失败:', error)
    }
    return false
  }
  
  function clearDraft() {
    localStorage.removeItem(DRAFT_STORAGE_KEY)
    reset()
  }
  
  function reset() {
    formData.value = createDefaultWizardData()
    errors.value = []
    isDirty.value = false
  }
  
  // 自动保存
  function triggerAutosave() {
    isDirty.value = true
    formData.value.draftStatus = 'dirty'
    
    if (autosaveTimer) {
      clearTimeout(autosaveTimer)
    }
    
    autosaveTimer = setTimeout(() => {
      if (isDirty.value && !isSaving.value) {
        saveDraft()
      }
    }, AUTOSAVE_DELAY_MS)
  }
  
  // 监听数据变化
  watch(formData, triggerAutosave, { deep: true })
  
  // =------------- 故事模板 -------------=
  
  function applyStoryTemplate(template: StoryTemplate) {
    formData.value.story.genre = template.genre
    formData.value.chapter.tensionLevel = template.tensionDefault
    formData.value.chapter.pacingStyle = template.pacingDefault
  }
  
  // =------------- 世界观操作 -------------=
  
  function addWorldItem(type: 'background' | 'rules', item: WorldItem) {
    formData.value.world[type].push(item)
  }
  
  function removeWorldItem(type: 'background' | 'rules', id: string) {
    formData.value.world[type] = formData.value.world[type].filter(i => i.id !== id)
  }
  
  function addLocation(location: Location) {
    formData.value.world.locations.push(location)
  }
  
  function removeLocation(id: string) {
    formData.value.world.locations = formData.value.world.locations.filter(l => l.id !== id)
  }
  
  // =------------- 角色操作 -------------=
  
  function addCharacter(character: CharacterInfo) {
    formData.value.characters.push(character)
  }
  
  function updateCharacter(id: string, updates: Partial<CharacterInfo>) {
    const index = formData.value.characters.findIndex(c => c.id === id)
    if (index !== -1) {
      formData.value.characters[index] = { ...formData.value.characters[index], ...updates }
    }
  }
  
  function removeCharacter(id: string) {
    formData.value.characters = formData.value.characters.filter(c => c.id !== id)
    // 同时移除相关关系
    formData.value.relationships = formData.value.relationships.filter(
      r => r.sourceId !== id && r.targetId !== id
    )
  }
  
  function addRelationship(relationship: CharacterRelationship) {
    formData.value.relationships.push(relationship)
  }
  
  function updateRelationship(id: string, updates: Partial<CharacterRelationship>) {
    const index = formData.value.relationships.findIndex(r => r.id === id)
    if (index !== -1) {
      formData.value.relationships[index] = { ...formData.value.relationships[index], ...updates }
    }
  }
  
  function removeRelationship(id: string) {
    formData.value.relationships = formData.value.relationships.filter(r => r.id !== id)
  }
  
  // =------------- 章节配置 -------------=
  
  function updateChapterConfig(updates: Partial<WizardFormData['chapter']>) {
    formData.value.chapter = { ...formData.value.chapter, ...updates }
  }
  
  function toggleChapterCharacter(characterId: string) {
    const ids = formData.value.chapter.characterIds
    const index = ids.indexOf(characterId)
    if (index === -1) {
      ids.push(characterId)
    } else {
      ids.splice(index, 1)
    }
  }
  
  // =------------- 专家设置 -------------=
  
  function updateExpertSettings(updates: Partial<WizardFormData['expertSettings']>) {
    formData.value.expertSettings = { ...formData.value.expertSettings, ...updates }
  }
  
  return {
    // 状态
    formData,
    currentStep,
    isExpertMode,
    stepIndex,
    isFirstStep,
    isLastStep,
    errors,
    isDirty,
    isSaving,
    
    // 步骤信息
    stepLabels: STEP_LABELS,
    stepOrder: STEP_ORDER,
    
    // 方法
    setMode,
    goToStep,
    goNext,
    goPrev,
    validate,
    saveDraft,
    loadDraft,
    clearDraft,
    reset,
    
    // 故事设定
    applyStoryTemplate,
    
    // 世界观
    addWorldItem,
    removeWorldItem,
    addLocation,
    removeLocation,
    
    // 角色管理
    addCharacter,
    updateCharacter,
    removeCharacter,
    addRelationship,
    updateRelationship,
    removeRelationship,
    
    // 章节配置
    updateChapterConfig,
    toggleChapterCharacter,
    
    // 专家设置
    updateExpertSettings
  }
}
