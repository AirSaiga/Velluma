<script setup lang="ts">
/**
 * 章节配置面板
 * 
 * 职责：
 * - 配置章节基本信息
 * - 选择出场角色
 * - 配置生成参数（字数、节奏、张力等）
 * - 专家模式下显示更多高级选项
 */
import { ref, computed, watch } from 'vue'
import type { 
  ChapterConfig, 
  CharacterInfo,
  PacingStyle,
  MemoryStrategy,
  CreativityLevel,
  RefinementDepth,
  ValidationError 
} from '../types/wizard.types'

// =------------- Props & Emits -------------=

const props = defineProps<{
  formData: { 
    chapter: ChapterConfig
    characters: CharacterInfo[]
  }
  isExpertMode: boolean
  errors: ValidationError[]
}>()

const emit = defineEmits<{
  (e: 'update-chapter', updates: Partial<ChapterConfig>): void
  (e: 'toggle-character', characterId: string): void
}>()

// =------------- 状态 -------------=

const showAdvancedSettings = ref(false)

// =------------- 计算属性 -------------=

const chapter = computed(() => props.formData.chapter)

const fieldErrors = computed(() => {
  const map = new Map<string, string>()
  for (const err of props.errors) {
    if (err.field.startsWith('chapter.')) {
      map.set(err.field.replace('chapter.', ''), err.message)
    }
  }
  return map
})

const selectedCharacters = computed(() => {
  return props.formData.characters.filter(c => 
    chapter.value.characterIds.includes(c.id)
  )
})

const availableCharacters = computed(() => {
  return props.formData.characters.filter(c => 
    !chapter.value.characterIds.includes(c.id)
  )
})

const pacingLabels: Record<PacingStyle, string> = {
  slow_burn: '舒缓',
  balanced: '均衡',
  fast_paced: '紧凑'
}

const pacingDescriptions: Record<PacingStyle, string> = {
  slow_burn: '缓慢铺陈，注重细节和氛围',
  balanced: '张弛有度，情节与描写平衡',
  fast_paced: '节奏紧凑，情节推进快速'
}

const memoryStrategyLabels: Record<MemoryStrategy, string> = {
  recent_only: '仅近章',
  balanced_reference: '均衡参考',
  deep_dive: '深度追溯'
}

const creativityLabels: Record<CreativityLevel, string> = {
  strict_prompt: '严格遵循',
  balanced_creation: '平衡创作',
  wild_imagination: '自由发挥'
}

const refinementLabels: Record<RefinementDepth, string> = {
  light: '轻度',
  standard: '标准',
  deep: '深度'
}

const tensionLevelEmoji = computed(() => {
  const level = chapter.value.tensionLevel
  if (level <= 3) return '😌'
  if (level <= 5) return '😊'
  if (level <= 7) return '😮'
  return '😱'
})

const wordCountRecommendation = computed(() => {
  const wc = chapter.value.targetWordCount
  if (wc < 1500) return '适合场景描写或过渡章节'
  if (wc < 3000) return '标准章节长度'
  if (wc < 5000) return '较长章节，建议包含多个场景'
  return '超长章节，建议拆分或确保内容丰富'
})

// =------------- 方法 -------------=

function updateField<K extends keyof ChapterConfig>(field: K, value: ChapterConfig[K]) {
  emit('update-chapter', { [field]: value })
}

function toggleCharacterSelection(characterId: string) {
  emit('toggle-character', characterId)
}

function selectAllCharacters() {
  for (const char of availableCharacters.value) {
    toggleCharacterSelection(char.id)
  }
}

function clearAllCharacters() {
  for (const char of selectedCharacters.value) {
    toggleCharacterSelection(char.id)
  }
}
</script>

<template>
  <div class="chapter-config-panel h-full overflow-y-auto p-6">
    <div class="max-w-3xl mx-auto space-y-8">
      
      <!-- 标题 -->
      <div class="text-center mb-8">
        <h2 class="text-2xl font-heading font-semibold text-[var(--text-primary)] mb-2">
          章节配置 📝
        </h2>
        <p class="text-sm text-[var(--text-muted)]">
          设置本章的基本信息和生成参数
        </p>
      </div>
      
      <!-- 章节基本信息 -->
      <section class="space-y-4">
        <div class="grid grid-cols-3 gap-4">
          <!-- 章节编号 -->
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
              章节编号
            </label>
            <input
              :value="chapter.chapterNumber"
              type="number"
              readonly
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] rounded-xl text-[var(--text-muted)] text-sm"
            />
          </div>
          
          <!-- 章节标题 -->
          <div class="col-span-2">
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
              章节标题
            </label>
            <input
              :value="chapter.title"
              @input="updateField('title', ($event.target as HTMLInputElement).value)"
              type="text"
              placeholder="为这一章取个名字..."
              class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
            />
          </div>
        </div>
        
        <!-- 章节大纲 -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            章节大纲 <span class="text-rose-500">*</span>
          </label>
          <textarea
            :value="chapter.outline"
            @input="updateField('outline', ($event.target as HTMLTextAreaElement).value)"
            rows="5"
            placeholder="描述这一章要发生的事情，包括关键情节、转折点等...&#10;&#10;示例：&#10;1. 主角在深夜接到神秘电话&#10;2. 发现信封里藏有密码&#10;3. 决定前往废弃工厂调查"
            class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
            :class="{ 'ring-rose-500': fieldErrors.get('outline') }"
          />
          <p v-if="fieldErrors.get('outline')" class="text-xs text-rose-500 mt-1">
            {{ fieldErrors.get('outline') }}
          </p>
        </div>
        
        <!-- 作者意图 -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            作者意图
            <span class="text-xs text-[var(--text-muted)] font-normal ml-1">(可选)</span>
          </label>
          <input
            :value="chapter.authorIntent"
            @input="updateField('authorIntent', ($event.target as HTMLInputElement).value)"
            type="text"
            placeholder="想在这一章强调什么？如：揭示主角内心矛盾、埋下伏笔..."
            class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
          />
        </div>
      </section>
      
      <!-- 出场角色 -->
      <section>
        <div class="flex items-center justify-between mb-3">
          <div>
            <h3 class="text-base font-medium text-[var(--text-primary)]">出场角色</h3>
            <p class="text-xs text-[var(--text-muted)]">选择本章会出现的角色</p>
          </div>
          <div class="flex gap-2">
            <button
              @click="selectAllCharacters"
              :disabled="availableCharacters.length === 0"
              class="px-2 py-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-50"
            >
              全选
            </button>
            <button
              @click="clearAllCharacters"
              :disabled="selectedCharacters.length === 0"
              class="px-2 py-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-50"
            >
              清空
            </button>
          </div>
        </div>
        
        <!-- 已选角色 -->
        <div v-if="selectedCharacters.length > 0" class="flex flex-wrap gap-2 mb-3">
          <div
            v-for="char in selectedCharacters"
            :key="char.id"
            @click="toggleCharacterSelection(char.id)"
            class="flex items-center gap-1.5 px-3 py-1.5 bg-accent-500/10 text-accent-700 rounded-full text-sm cursor-pointer hover:bg-accent-500/20 transition-colors"
          >
            <span>{{ char.name }}</span>
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
        </div>
        
        <!-- 可选角色 -->
        <div v-if="availableCharacters.length > 0" class="flex flex-wrap gap-2">
          <div
            v-for="char in availableCharacters"
            :key="char.id"
            @click="toggleCharacterSelection(char.id)"
            class="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-panel)] text-[var(--text-primary)] rounded-full text-sm cursor-pointer hover:bg-[var(--bg-secondary)] transition-colors border border-[var(--border-color)]/50"
          >
            <span class="text-[var(--text-muted)]">+</span>
            <span>{{ char.name }}</span>
          </div>
        </div>
        
        <div v-if="formData.characters.length === 0" class="text-center py-4 text-sm text-[var(--text-muted)]">
          还没有创建角色，请先在"角色"步骤中创建
        </div>
      </section>
      
      <!-- 生成参数 -->
      <section class="grid grid-cols-2 gap-6">
        <!-- 目标字数 -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            目标字数
          </label>
          <div class="flex items-center gap-3">
            <input
              :value="chapter.targetWordCount"
              @input="updateField('targetWordCount', parseInt(($event.target as HTMLInputElement).value) || 0)"
              type="number"
              min="500"
              max="20000"
              step="500"
              class="w-32 px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
            />
            <span class="text-xs text-[var(--text-muted)]">字</span>
          </div>
          <p class="text-xs text-[var(--text-muted)] mt-1">{{ wordCountRecommendation }}</p>
        </div>
        
        <!-- 节奏风格（仅专家模式或展开时显示） -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            节奏风格
          </label>
          <div class="grid grid-cols-3 gap-1">
            <button
              v-for="(label, key) in pacingLabels"
              :key="key"
              @click="updateField('pacingStyle', key as PacingStyle)"
              :class="[
                'px-2 py-2 text-xs rounded-lg transition-colors',
                chapter.pacingStyle === key
                  ? 'bg-accent-500 text-white'
                  : 'bg-[var(--bg-panel)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
              ]"
            >
              {{ label }}
            </button>
          </div>
          <p class="text-xs text-[var(--text-muted)] mt-1">
            {{ pacingDescriptions[chapter.pacingStyle] }}
          </p>
        </div>
      </section>
      
      <!-- 高级设置（折叠区域） -->
      <section class="border-t border-[var(--border-color)]/30 pt-6">
        <button
          @click="showAdvancedSettings = !showAdvancedSettings"
          class="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]"
        >
          <svg
            :class="['w-4 h-4 transition-transform', showAdvancedSettings ? 'rotate-90' : '']"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
          </svg>
          <span>高级设置</span>
          <span v-if="isExpertMode" class="px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-600 rounded">专家</span>
        </button>
        
        <Transition name="expand">
          <div v-if="showAdvancedSettings" class="mt-4 space-y-6 pl-6">
            
            <!-- 戏剧张力 -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
                戏剧张力
                <span class="text-lg ml-1">{{ tensionLevelEmoji }}</span>
              </label>
              <input
                :value="chapter.tensionLevel"
                @input="updateField('tensionLevel', parseInt(($event.target as HTMLInputElement).value))"
                type="range"
                min="1"
                max="10"
                class="w-full"
              />
              <div class="flex justify-between text-xs text-[var(--text-muted)] mt-1">
                <span>平静</span>
                <span>{{ chapter.tensionLevel }}</span>
                <span>紧张</span>
              </div>
            </div>
            
            <!-- 章节禁区 -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
                章节禁区
              </label>
              <textarea
                :value="chapter.forbiddenContent"
                @input="updateField('forbiddenContent', ($event.target as HTMLTextAreaElement).value)"
                rows="2"
                placeholder="不要在这一章出现的内容..."
                class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              />
              <p class="text-[10px] text-[var(--text-muted)] mt-1">
                内部字段：chapter_assets_schema — 定义本章的创作边界
              </p>
            </div>
            
            <!-- 记忆检索策略 -->
            <div v-if="isExpertMode">
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
                <span class="flex items-center gap-1.5">
                  <span class="px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-600 rounded">专家</span>
                  记忆检索策略
                </span>
              </label>
              <div class="grid grid-cols-3 gap-2">
                <button
                  v-for="(label, key) in memoryStrategyLabels"
                  :key="key"
                  @click="updateField('memoryStrategy', key as MemoryStrategy)"
                  :class="[
                    'px-2 py-2 text-xs rounded-lg transition-colors',
                    chapter.memoryStrategy === key
                      ? 'bg-amber-500 text-white'
                      : 'bg-[var(--bg-panel)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
                  ]"
                >
                  {{ label }}
                </button>
              </div>
              <p class="text-xs text-[var(--text-muted)] mt-1">
                内部字段：memory_span — 控制AI回顾历史章节的深度
              </p>
            </div>
            
            <!-- 创作自由度 -->
            <div v-if="isExpertMode">
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
                <span class="flex items-center gap-1.5">
                  <span class="px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-600 rounded">专家</span>
                  创作自由度
                </span>
              </label>
              <div class="grid grid-cols-3 gap-2">
                <button
                  v-for="(label, key) in creativityLabels"
                  :key="key"
                  @click="updateField('creativityLevel', key as CreativityLevel)"
                  :class="[
                    'px-2 py-2 text-xs rounded-lg transition-colors',
                    chapter.creativityLevel === key
                      ? 'bg-amber-500 text-white'
                      : 'bg-[var(--bg-panel)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
                  ]"
                >
                  {{ label }}
                </button>
              </div>
              <p class="text-xs text-[var(--text-muted)] mt-1">
                内部字段：creativity_level — 控制AI对大纲的遵循程度
              </p>
            </div>
            
            <!-- 精修深度 -->
            <div v-if="isExpertMode">
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
                <span class="flex items-center gap-1.5">
                  <span class="px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-600 rounded">专家</span>
                  精修深度
                </span>
              </label>
              <div class="grid grid-cols-3 gap-2">
                <button
                  v-for="(label, key) in refinementLabels"
                  :key="key"
                  @click="updateField('refinementDepth', key as RefinementDepth)"
                  :class="[
                    'px-2 py-2 text-xs rounded-lg transition-colors',
                    chapter.refinementDepth === key
                      ? 'bg-amber-500 text-white'
                      : 'bg-[var(--bg-panel)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
                  ]"
                >
                  {{ label }}
                </button>
              </div>
              <p class="text-xs text-[var(--text-muted)] mt-1">
                内部字段：refinement_depth — 控制审阅-精修的迭代深度
              </p>
            </div>
            
          </div>
        </Transition>
      </section>
      
      <!-- 提示信息 -->
      <div class="bg-accent-500/5 rounded-xl p-4 mt-6">
        <div class="flex items-start gap-3">
          <span class="text-lg">💡</span>
          <div class="text-sm text-[var(--text-secondary)]">
            <p class="font-medium mb-1">章节大纲建议</p>
            <ul class="text-xs text-[var(--text-muted)] space-y-1">
              <li>• 包含明确的开始、发展、结束</li>
              <li>• 标注关键转折点或冲突</li>
              <li>• 可以简要描述期望的场景氛围</li>
            </ul>
          </div>
        </div>
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
