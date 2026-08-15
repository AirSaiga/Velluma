<script setup lang="ts">
import { ref, watch, onUnmounted, computed } from 'vue'
import { styleApi, bookApi } from '../services/api'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { PanelContainer, PanelSection, PanelCard, PanelEmpty } from './panels'
import Icon from './Icon.vue'
import type { StyleCard, NegativeItem, AuthorSample, AuthorSampleSceneType } from '../types'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const props = withDefaults(defineProps<{
  bookId: string
  genre?: string | null
  closable?: boolean
}>(), {
  genre: null,
  closable: true
})

const emit = defineEmits(['close'])

// ============ 状态 ============
const activeTab = ref<'profile' | 'negative' | 'metrics' | 'samples'>('profile')
const isLoading = ref(false)
const isSaving = ref(false)
const isExtracting = ref(false)
const status = ref<'idle' | 'dirty' | 'saving' | 'saved' | 'error'>('idle')
const errorText = ref('')

// StyleCard 字段
const positiveProfile = ref<Record<string, string>>({})
const negativeList = ref<NegativeItem[]>([])
const dialogueRatioTarget = ref<number | null>(null)
const paragraphRhythm = ref('')

// 兼容字段（向下兼容 book.golden_snippets / style_blacklist）
const goldenSnippets = ref<string[]>([])
const styleBlacklist = ref<string[]>([])

// AuthorSample
const samples = ref<AuthorSample[]>([])
const newSampleContent = ref('')
const newSampleSceneType = ref<AuthorSampleSceneType>('general')

// Match My Style 提炼
const showExtractModal = ref(false)
const extractSamples = ref<string[]>(['', '', ''])
const extractResult = ref<any>(null)

let autosaveTimer: any
const AUTOSAVE_DELAY_MS = 2000

// 正面画像的固定键（蓝图 §4.4）
const profileKeys = [
  { key: 'sentence_rhythm', label: '句长节奏' },
  { key: 'vocabulary', label: '词汇层级' },
  { key: 'register', label: '语域偏好' },
  { key: 'opening_habit', label: '开头习惯' },
  { key: 'ending_habit', label: '结尾习惯' },
]

const statusLabel = computed(() => {
  switch (status.value) {
    case 'dirty': return '未保存'
    case 'saving': return '保存中...'
    case 'saved': return '已保存'
    case 'error': return errorText.value || '保存失败'
    default: return ''
  }
})

// ============ 数据加载 ============
async function loadData() {
  if (!props.bookId) return
  isLoading.value = true
  try {
    const [styleCard, goldenData, blacklistData, samplesData] = await Promise.all([
      styleApi.get(props.bookId).catch(() => null),
      bookApi.getGoldenSnippets(props.bookId).catch(() => ({ golden_snippets: [] })),
      bookApi.getStyleBlacklist(props.bookId).catch(() => ({ style_blacklist: [] })),
      styleApi.listSamples(props.bookId).catch(() => []),
    ])

    // StyleCard
    if (styleCard) {
      positiveProfile.value = { ...(styleCard.positive_profile || {}) }
      negativeList.value = Array.isArray(styleCard.negative_list)
        ? styleCard.negative_list.map((n, i) => ({ word: n.word || '', alternative: n.alternative || '', id: `neg_${i}_${Date.now()}` } as any))
        : []
      dialogueRatioTarget.value = styleCard.dialogue_ratio_target ?? null
      paragraphRhythm.value = styleCard.paragraph_rhythm || ''
    }
    // 确保所有 profileKeys 都有值
    for (const pk of profileKeys) {
      if (!(pk.key in positiveProfile.value)) {
        positiveProfile.value[pk.key] = ''
      }
    }

    // 兼容字段
    goldenSnippets.value = (goldenData as any)?.golden_snippets || []
    styleBlacklist.value = (blacklistData as any)?.style_blacklist || []

    // AuthorSample
    samples.value = samplesData as AuthorSample[]

    status.value = 'idle'
    errorText.value = ''
  } catch (error: any) {
    console.error('加载文风卡失败:', error)
    status.value = 'error'
    errorText.value = '加载失败: ' + (error?.message || '')
  } finally {
    isLoading.value = false
  }
}

// ============ 保存 ============
async function saveStyleCard() {
  if (!props.bookId) return
  isSaving.value = true
  status.value = 'saving'
  errorText.value = ''
  try {
    const payload: Partial<StyleCard> = {
      positive_profile: { ...positiveProfile.value },
      negative_list: negativeList.value
        .filter(n => n.word.trim())
        .map(n => ({ word: n.word.trim(), alternative: n.alternative?.trim() || null })),
      dialogue_ratio_target: dialogueRatioTarget.value,
      paragraph_rhythm: paragraphRhythm.value || null,
    }
    await styleApi.upsert(props.bookId, payload)

    // 同步兼容字段（style_blacklist 与 negative_list 保持一致）
    const blacklistFromNegative = negativeList.value
      .filter(n => n.word.trim())
      .map(n => n.word.trim())
    if (JSON.stringify(blacklistFromNegative) !== JSON.stringify(styleBlacklist.value)) {
      styleBlacklist.value = blacklistFromNegative
      await bookApi.updateStyleBlacklist(props.bookId, blacklistFromNegative).catch(() => {})
    }

    status.value = 'saved'
    setTimeout(() => {
      if (status.value === 'saved') status.value = 'idle'
    }, 1500)
  } catch (error: any) {
    console.error('保存失败:', error)
    status.value = 'error'
    errorText.value = error?.message || '保存失败'
  } finally {
    isSaving.value = false
  }
}

function markDirty() {
  if (isLoading.value) return
  status.value = 'dirty'
  errorText.value = ''
  clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => {
    if (status.value !== 'dirty' || isSaving.value) return
    saveStyleCard()
  }, AUTOSAVE_DELAY_MS)
}

// ============ 负面清单操作 ============
function addNegative() {
  negativeList.value.unshift({ word: '', alternative: '' } as any)
  markDirty()
}
function removeNegative(idx: number) {
  negativeList.value.splice(idx, 1)
  markDirty()
}

// ============ Match My Style 提炼 ============
async function runExtract() {
  const validSamples = extractSamples.value.filter(s => s.trim().length > 20)
  if (validSamples.length < 1) {
    showToast('请至少提供 1 段有效样本（>20字）', 'warning')
    return
  }
  isExtracting.value = true
  try {
    const result = await styleApi.extract(props.bookId, validSamples, props.genre || undefined)
    extractResult.value = result
    if (result.degraded) {
      showToast(`提炼降级：${result.degraded.reason}（已用题材默认画像）`, 'warning')
    } else {
      showToast('文风画像提炼完成', 'success')
    }
    // 自动填充到编辑区
    if (result.positive_profile) {
      positiveProfile.value = { ...positiveProfile.value, ...result.positive_profile }
    }
    if (result.negative_list?.length) {
      negativeList.value = result.negative_list.map((n, i) => ({
        word: n.word || '',
        alternative: n.alternative || '',
        id: `neg_extract_${i}_${Date.now()}`,
      } as any))
    }
    if (result.dialogue_ratio_target !== null && result.dialogue_ratio_target !== undefined) {
      dialogueRatioTarget.value = result.dialogue_ratio_target
    }
    if (result.paragraph_rhythm) {
      paragraphRhythm.value = result.paragraph_rhythm
    }
    markDirty()
    showExtractModal.value = false
  } catch (error: any) {
    showToast('提炼失败: ' + (error?.message || ''), 'error')
  } finally {
    isExtracting.value = false
  }
}

// ============ AuthorSample 操作 ============
async function createSample() {
  if (!newSampleContent.value.trim()) {
    showToast('样本内容不能为空', 'warning')
    return
  }
  try {
    const sample = await styleApi.createSample(props.bookId, {
      content: newSampleContent.value.trim(),
      scene_type: newSampleSceneType.value,
    })
    samples.value.unshift(sample)
    newSampleContent.value = ''
    showToast('样本已上传（已自动向量化）', 'success')
  } catch (error: any) {
    showToast('上传失败: ' + (error?.message || ''), 'error')
  }
}

async function deleteSample(sampleId: string) {
  // 删除无确认曾是保护缺口（书籍/章节删除均有 ConfirmDialog + warning）
  const ok = await showConfirm({
    title: '删除文风样本',
    message: '确定删除这条文风样本吗？',
    warning: '样本及其向量将一并删除，不可恢复。',
  })
  if (!ok) return
  try {
    await styleApi.deleteSample(props.bookId, sampleId)
    samples.value = samples.value.filter(s => s.id !== sampleId)
    showToast('样本已删除', 'success')
  } catch (error: any) {
    showToast('删除失败: ' + (error?.message || ''), 'error')
  }
}

const sceneTypeLabels: Record<string, string> = {
  dialogue: '对话',
  action: '动作',
  lyrical: '抒情',
  suspense: '悬念',
  general: '通用',
}

// ============ 生命周期 ============
watch(() => props.bookId, (newId) => {
  if (newId) loadData()
}, { immediate: true })

onUnmounted(() => {
  clearTimeout(autosaveTimer)
})
</script>

<template>
  <PanelContainer
    title="文风卡 & 作者样本"
    icon="sparkles"
    :closable="closable"
    @close="emit('close')"
  >
    <div class="flex items-center justify-end mb-1">
      <span v-if="statusLabel" class="text-[10px] px-1.5 py-0.5 rounded"
        :class="{
          'bg-amber-100 text-amber-700': status === 'dirty',
          'bg-blue-100 text-blue-700': status === 'saving',
          'bg-green-100 text-green-700': status === 'saved',
          'bg-red-100 text-red-700': status === 'error',
        }"
      >{{ statusLabel }}</span>
    </div>

    <!-- Tab 切换 -->
    <div class="flex border-b border-[var(--border-color)] mb-3">
      <button
        v-for="tab in [
          { key: 'profile', label: '正面画像' },
          { key: 'negative', label: '负面清单' },
          { key: 'metrics', label: '量化指标' },
          { key: 'samples', label: '作者样本' },
        ]"
        :key="tab.key"
        @click="activeTab = tab.key as any"
        class="px-3 py-1.5 text-xs font-medium transition-colors"
        :class="activeTab === tab.key
          ? 'text-[var(--accent-500)] border-b-2 border-[var(--accent-500)]'
          : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'"
      >{{ tab.label }}</button>
    </div>

    <div v-if="isLoading" class="text-center py-8 text-[var(--text-muted)] text-sm">加载中...</div>

    <!-- Tab 1: 正面画像 -->
    <div v-else-if="activeTab === 'profile'" class="space-y-3">
      <div class="flex justify-between items-center mb-2">
        <p class="text-[11px] text-[var(--text-muted)]">从样本归纳作者的真实文风特征</p>
        <button
          @click="showExtractModal = true"
          class="px-2 py-1 text-[11px] rounded bg-[var(--accent-500)] text-white hover:bg-[var(--accent-600)]"
        >
          <Icon name="wand" class="w-3 h-3 inline mr-1" />从样本提炼
        </button>
      </div>
      <div v-for="pk in profileKeys" :key="pk.key" class="space-y-1">
        <label class="text-[11px] text-[var(--text-muted)]">{{ pk.label }}</label>
        <textarea
          v-model="positiveProfile[pk.key]"
          rows="2"
          @input="markDirty"
          class="w-full px-2 py-1 text-xs bg-[var(--bg-panel)] rounded border border-[var(--border-color)] focus:border-[var(--accent-400)] focus:outline-none"
          :placeholder="`例：短句与长句交替，平均 15 字`"
        ></textarea>
      </div>
    </div>

    <!-- Tab 2: 负面清单 -->
    <div v-else-if="activeTab === 'negative'" class="space-y-2">
      <div class="flex justify-between items-center mb-2">
        <p class="text-[11px] text-[var(--text-muted)]">禁词/禁句式 + 每条替代规则</p>
        <button @click="addNegative" class="px-2 py-1 text-[11px] rounded bg-[var(--bg-panel)] hover:bg-parchment-100">+ 添加</button>
      </div>
      <div v-if="negativeList.length === 0" class="text-center py-4 text-[var(--text-muted)] text-xs">
        暂无负面清单
      </div>
      <div
        v-for="(item, idx) in negativeList"
        :key="idx"
        class="flex items-start gap-2 p-2 bg-[var(--bg-panel)] rounded border border-[var(--border-color)]"
      >
        <input
          v-model="item.word"
          @input="markDirty"
          class="flex-1 px-2 py-1 text-xs bg-transparent rounded border border-[var(--border-color)] focus:outline-none"
          placeholder="禁用词/句式"
        />
        <input
          v-model="item.alternative"
          @input="markDirty"
          class="flex-1 px-2 py-1 text-xs bg-transparent rounded border border-[var(--border-color)] focus:outline-none"
          placeholder="替代规则"
        />
        <button @click="removeNegative(idx)" class="text-red-400 hover:text-red-600 text-xs">✕</button>
      </div>
    </div>

    <!-- Tab 3: 量化指标 -->
    <div v-else-if="activeTab === 'metrics'" class="space-y-4">
      <div>
        <label class="text-[11px] text-[var(--text-muted)]">对话占比目标：{{ dialogueRatioTarget !== null ? (dialogueRatioTarget * 100).toFixed(0) + '%' : '未设置' }}</label>
        <input
          v-model.number="dialogueRatioTarget"
          type="range"
          min="0"
          max="1"
          step="0.05"
          @input="markDirty"
          class="w-full mt-1"
        />
      </div>
      <div>
        <label class="text-[11px] text-[var(--text-muted)]">段落节奏</label>
        <textarea
          v-model="paragraphRhythm"
          rows="3"
          @input="markDirty"
          class="w-full mt-1 px-2 py-1 text-xs bg-[var(--bg-panel)] rounded border border-[var(--border-color)] focus:outline-none"
          placeholder="例：段落短促，常 2-3 句一段"
        ></textarea>
      </div>
    </div>

    <!-- Tab 4: 作者样本 -->
    <div v-else-if="activeTab === 'samples'" class="space-y-3">
      <p class="text-[11px] text-[var(--text-muted)]">上传作者已写文本作 few-shot 锚定（自动向量化检索）</p>

      <!-- 上传新样本 -->
      <div class="p-3 bg-[var(--bg-panel)] rounded border border-[var(--border-color)] space-y-2">
        <textarea
          v-model="newSampleContent"
          rows="3"
          class="w-full px-2 py-1 text-xs bg-transparent rounded border border-[var(--border-color)] focus:outline-none"
          placeholder="粘贴作者样本原文（建议 200-2000 字）"
        ></textarea>
        <div class="flex items-center gap-2">
          <select
            v-model="newSampleSceneType"
            class="px-2 py-1 text-xs bg-transparent rounded border border-[var(--border-color)] focus:outline-none"
          >
            <option v-for="(label, key) in sceneTypeLabels" :key="key" :value="key">{{ label }}</option>
          </select>
          <button
            @click="createSample"
            class="px-3 py-1 text-xs rounded bg-[var(--accent-500)] text-white hover:bg-[var(--accent-600)]"
          >上传</button>
        </div>
      </div>

      <!-- 已有样本列表 -->
      <div v-if="samples.length === 0" class="text-center py-4 text-[var(--text-muted)] text-xs">
        暂无作者样本
      </div>
      <div
        v-for="sample in samples"
        :key="sample.id"
        class="p-2 bg-[var(--bg-panel)] rounded border border-[var(--border-color)]"
      >
        <div class="flex items-center justify-between mb-1">
          <span class="px-1.5 py-0.5 text-[10px] rounded bg-blue-100 text-blue-700">
            {{ sceneTypeLabels[sample.scene_type] || sample.scene_type }}
          </span>
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-[var(--text-muted)]">{{ sample.word_count }}字</span>
            <button @click="deleteSample(sample.id)" class="text-red-400 hover:text-red-600 text-xs">✕</button>
          </div>
        </div>
        <p class="text-xs text-[var(--text-secondary)] line-clamp-3">{{ sample.content }}</p>
      </div>
    </div>

    <!-- ============ Match My Style 提炼 Modal ============ -->
    <Teleport to="body">
      <div
        v-if="showExtractModal"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
        @click.self="showExtractModal = false"
      >
        <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
          <div class="p-3 border-b border-[var(--border-color)] flex items-center justify-between">
            <h3 class="text-sm font-semibold">从样本提炼文风画像（Match My Style）</h3>
            <button @click="showExtractModal = false" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
          </div>
          <div class="p-4 overflow-y-auto space-y-3">
            <p class="text-[11px] text-[var(--text-muted)]">
              粘贴 2-3 段作者已写的文字，AI 将提炼出句长节奏、词汇层级、负面清单等结构化画像。
            </p>
            <div v-for="(_, idx) in extractSamples" :key="idx">
              <label class="text-[11px] text-[var(--text-muted)]">样本 {{ idx + 1 }}</label>
              <textarea
                v-model="extractSamples[idx]"
                rows="5"
                class="w-full mt-0.5 px-2 py-1 text-xs bg-[var(--bg-panel)] rounded border border-[var(--border-color)] focus:outline-none"
                placeholder="粘贴作者原文（建议 200-2000 字）"
              ></textarea>
            </div>
          </div>
          <div class="p-3 border-t border-[var(--border-color)] flex justify-end gap-2">
            <button @click="showExtractModal = false" class="px-3 py-1.5 text-xs rounded bg-[var(--bg-panel)]">取消</button>
            <button
              @click="runExtract"
              :disabled="isExtracting"
              class="px-3 py-1.5 text-xs rounded bg-[var(--accent-500)] text-white hover:bg-[var(--accent-600)] disabled:opacity-50"
            >{{ isExtracting ? '提炼中（5-15s）...' : '开始提炼' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </PanelContainer>
</template>
