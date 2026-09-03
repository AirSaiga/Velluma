<script setup lang="ts">
/**
 * 文风页容器（文风模块重构 S1，docs/style-module-redesign.md §6.2/§8）。
 *
 * 独立成页：文风回答"这个作者怎么写"，与世界页（世界是什么）正交，
 * 从设定页（bible）迁出。单页叙事线四区：①你的字 ②笔迹指纹 ③负面清单 ④对账。
 *
 * 职责：
 * - 数据加载/保存编排（文风卡 + 样本 + 指纹，2s 防抖自动保存沿用既有契约）
 * - 零状态坡道三幕切换（无样本 → 只显示邀请；贴入 → 指纹 3 秒内出现；≥3 条 → 提炼建议）
 * - 从样本提炼（不落库红线保持）/ 章节收编（零状态兜底）
 * presentation 组件纯渲染 + 抛事件（分层规范）。
 */
import { ref, computed, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { styleApi, bookApi, chapterApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useAppStore } from '../../app/useAppStore'
import StyleSampleSection from '../presentation/StyleSampleSection.vue'
import StyleFingerprintSection from '../presentation/StyleFingerprintSection.vue'
import StyleKnobsSection from '../presentation/StyleKnobsSection.vue'
import StyleNegativeSection from '../presentation/StyleNegativeSection.vue'
import StyleReconciliationSection from '../presentation/StyleReconciliationSection.vue'
import StyleExtractModal from '../presentation/StyleExtractModal.vue'
import StyleAuditionBar, { type AuditionRunState } from '../presentation/StyleAuditionBar.vue'
import StyleInboxSection from '../presentation/StyleInboxSection.vue'
import StyleAdoptedPool, { type AdoptedGhostItem } from '../presentation/StyleAdoptedPool.vue'
import StyleScanModal from '../presentation/StyleScanModal.vue'
import StyleStatusStrip from '../presentation/StyleStatusStrip.vue'
import type {
  StyleCard,
  StyleFingerprint,
  NegativeItem,
  AuthorSample,
  AuthorSampleSceneType,
  StyleInboxItem,
  StyleScanResult,
  StyleScanHit,
  StyleKnobKey,
} from '../../../types'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const currentBook = store.currentBook

// ============ 路由与书 ============
const bookIdFromRoute = computed(() => (route.params.bookId as string) || null)
watch(
  bookIdFromRoute,
  (newBookId) => {
    if (newBookId && newBookId !== store.currentBookId.value) {
      store.selectBook(newBookId)
    }
  },
  { immediate: true },
)

// ============ 状态 ============
const isLoading = ref(false)
const isBusy = ref(false)           // 样本上传/收编等操作中
const isExtracting = ref(false)
const status = ref<'idle' | 'dirty' | 'saving' | 'saved' | 'error'>('idle')
const errorText = ref('')

const fingerprint = ref<StyleFingerprint | null>(null)
const samples = ref<AuthorSample[]>([])

// 文风卡字段
const positiveProfile = ref<Record<string, string>>({})
const negativeList = ref<NegativeItem[]>([])
const dialogueRatioTarget = ref<number | null>(null)
const paragraphRhythm = ref('')
const styleKnobs = ref<Record<string, number>>({})
const lockedKeys = ref<string[]>([])
// 双写收敛（任务包 B）：book.style_blacklist 同步通道已删——历史书级黑名单由后端
// 启动迁移并入 negative_list，负面清单唯一权威是文风卡。

// 系统陈词库 + 本书豁免（补全批）
const systemCliches = ref<Array<{ id: string; pattern: string; alternative?: string | null; severity: string }>>([])
const clicheExemptions = ref<string[]>([])
// 存量黄金片段数（导入样本库入口的显隐依据）
const goldenSnippetCount = ref(0)

// 提炼弹窗
const showExtractModal = ref(false)
const extractPrefill = ref<string[]>([])

// ---- S3 交互环状态 ----
// 收件箱
const inboxItems = ref<StyleInboxItem[]>([])
// 章级特例（编辑对象：'' = 书级）
const chapters = ref<Array<{ id: string; chapter_number: number; title: string | null }>>([])
const scopeChapterId = ref('')
const scopeHasOverride = ref(false)
// 试听（A/B 双轨）
const auditionRuns = ref<{ baseline: AuditionRunState; styled: AuditionRunState }>({
  baseline: { running: false, text: '' },
  styled: { running: false, text: '' },
})
// 禁词扫描审稿
const showScanModal = ref(false)
const isScanning = ref(false)
const scanResult = ref<StyleScanResult | null>(null)
const scanResolvedWords = ref<string[]>([])

const PROFILE_KEYS = [
  'sentence_rhythm', 'vocabulary', 'register', 'opening_habit', 'ending_habit',
]

const hasStyleConfig = computed(() =>
  PROFILE_KEYS.some(k => (positiveProfile.value[k] || '').trim()) ||
  negativeList.value.some(n => n.word.trim()) ||
  Object.keys(styleKnobs.value).length > 0 ||
  dialogueRatioTarget.value !== null,
)

// 零状态门闸：无样本且无任何既有配置才进坡道——旧 StyleCardManager 时代
// 填过负面清单/画像/旋钮的书，不能被整页折叠成粘贴邀请（既有配置必须可见可改）
const zeroState = computed(() => samples.value.length === 0 && !hasStyleConfig.value)

/** 坡道三幕（设计稿 §6.3「页面随数据生长」）：
 *  ramp  整页只有一个邀请（无样本无配置）
 *  early 只长「你的字 + 笔迹指纹」（1-2 条样本的啊哈时刻），其余分区以长成预告占位
 *  full  全部分区摊开（≥3 条样本，或已有文风配置；章级特例深链直接 full 防死路） */
const growthStage = computed<'ramp' | 'early' | 'full'>(() => {
  if (scopeChapterId.value) return 'full'
  if (zeroState.value) return 'ramp'
  if (samples.value.length < 3 && !hasStyleConfig.value) return 'early'
  return 'full'
})

/** 状态条取数：语料聚合为空（有配置但无样本）时不报假数字 */
const corpusReady = computed(() => (fingerprint.value?.corpus?.word_count || 0) > 0)
const negativeActiveCount = computed(() => negativeList.value.filter(n => n.word.trim()).length)

/** 试听默认测试段：样本库里最长的一条（截 600 字） */
const auditionDefaultText = computed(() => {
  const longest = [...samples.value].sort((a, b) => b.word_count - a.word_count)[0]
  return longest ? longest.content.slice(0, 600) : ''
})

const fingerprintBySample = computed<Record<string, StyleFingerprint['samples'][number]['fingerprint']>>(() => {
  const map: Record<string, StyleFingerprint['samples'][number]['fingerprint']> = {}
  for (const s of fingerprint.value?.samples || []) {
    map[s.sample_id] = s.fingerprint
  }
  return map
})

// 零状态坡道第三幕：样本 ≥3 且画像还是空的 → 浮出提炼建议
const suggestExtract = computed(() => {
  if (zeroState.value || samples.value.length < 3) return false
  return PROFILE_KEYS.every(k => !(positiveProfile.value[k] || '').trim())
})

const statusLabel = computed(() => {
  switch (status.value) {
    case 'dirty': return '未保存'
    case 'saving': return '保存中…'
    case 'saved': return '已保存'
    case 'error': return errorText.value || '保存失败'
    default: return ''
  }
})

// ============ 数据加载 ============
async function loadAll() {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  isLoading.value = true
  try {
    const [styleCard, samplesData, fingerprintData, inboxData, chapterData, exemptionData, systemClicheData, goldenData] = await Promise.all([
      styleApi.get(bookId).catch(() => null),
      styleApi.listSamples(bookId).catch(() => []),
      styleApi.getFingerprint(bookId, true, 50).catch(() => null),
      styleApi.listInbox(bookId).catch(() => []),
      chapterApi.getAll(bookId).catch(() => []),
      styleApi.getClicheExemptions(bookId).catch(() => []),
      styleApi.listSystemCliches().catch(() => []),
      bookApi.getGoldenSnippets(bookId).catch(() => ({ golden_snippets: [] })),
    ])

    if (styleCard) {
      positiveProfile.value = { ...(styleCard.positive_profile || {}) }
      negativeList.value = Array.isArray(styleCard.negative_list)
        ? styleCard.negative_list.map((n, i) => ({
            word: n.word || '',
            alternative: n.alternative || '',
            severity: n.severity,
            id: `neg_${i}_${Date.now()}`,
          } as NegativeItem))
        : []
      dialogueRatioTarget.value = styleCard.dialogue_ratio_target ?? null
      paragraphRhythm.value = styleCard.paragraph_rhythm || ''
      styleKnobs.value = { ...(styleCard.style_knobs || {}) }
      lockedKeys.value = [...(styleCard.locked_keys || [])]
    }
    for (const key of PROFILE_KEYS) {
      if (!(key in positiveProfile.value)) positiveProfile.value[key] = ''
    }

    samples.value = samplesData as AuthorSample[]
    fingerprint.value = fingerprintData
    inboxItems.value = inboxData as StyleInboxItem[]
    clicheExemptions.value = exemptionData as string[]
    systemCliches.value = systemClicheData as typeof systemCliches.value
    goldenSnippetCount.value = ((goldenData as { golden_snippets?: string[] })?.golden_snippets || []).length
    chapters.value = ((chapterData as any[]) || [])
      .map((c: any) => ({ id: String(c.id), chapter_number: c.chapter_number, title: c.title || c.chapter_name || null }))
      .sort((a, b) => a.chapter_number - b.chapter_number)

    status.value = 'idle'
    errorText.value = ''

    // 深链：?chapter=<id> 直达章级特例编辑（副驾「本章文风」卡跳转入口）
    const queryChapter = route.query.chapter as string
    if (queryChapter && chapters.value.some(c => c.id === queryChapter)) {
      await switchScope(queryChapter)
    }
  } catch (error: unknown) {
    status.value = 'error'
    errorText.value = '加载失败: ' + ((error as Error)?.message || '')
  } finally {
    isLoading.value = false
  }
}

/** 样本增删后只刷新样本与指纹（文风卡与章正文未变）；顺带刷新采纳池 */
async function reloadSamplesAndFingerprint() {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  const [samplesData, fingerprintData] = await Promise.all([
    styleApi.listSamples(bookId).catch(() => samples.value),
    styleApi.getFingerprint(bookId, true, 50).catch(() => fingerprint.value),
  ])
  samples.value = samplesData as AuthorSample[]
  fingerprint.value = fingerprintData
  void loadAdoptedPool()
}

// ============ 保存（2s 防抖，迁移自 StyleCardManager） ============
let autosaveTimer: ReturnType<typeof setTimeout> | undefined
const AUTOSAVE_DELAY_MS = 2000

async function saveStyleCard() {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  status.value = 'saving'
  errorText.value = ''
  try {
    const payload: Partial<StyleCard> & { chapter_id?: string } = {
      positive_profile: { ...positiveProfile.value },
      negative_list: negativeList.value
        .filter(n => n.word.trim())
        // severity 未设不补键——后端按 warning（提醒）兜底
        .map(n => ({
          word: n.word.trim(),
          alternative: n.alternative?.trim() || null,
          ...(n.severity ? { severity: n.severity } : {}),
        })),
      dialogue_ratio_target: dialogueRatioTarget.value,
      paragraph_rhythm: paragraphRhythm.value || null,
      style_knobs: { ...styleKnobs.value },
      locked_keys: [...lockedKeys.value],
    }
    // 章级特例：保存只落该章的覆盖卡
    if (scopeChapterId.value) payload.chapter_id = scopeChapterId.value
    await styleApi.upsert(bookId, payload)
    if (scopeChapterId.value) scopeHasOverride.value = true

    status.value = 'saved'
    setTimeout(() => {
      if (status.value === 'saved') status.value = 'idle'
    }, 1500)
  } catch (error: unknown) {
    status.value = 'error'
    errorText.value = (error as Error)?.message || '保存失败'
  }
}

function markDirty() {
  if (isLoading.value) return
  status.value = 'dirty'
  errorText.value = ''
  clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => {
    if (status.value !== 'dirty') return
    saveStyleCard()
  }, AUTOSAVE_DELAY_MS)
}

// ============ 样本操作 ============
// ===== P5 采纳幽灵收编池（三平面分权·选择平面，2026-08-29）=====
// 作者采纳过的幽灵草稿——「这段 AI 写的你觉得像你，收为样本？」
// 红线：候选不直接生效，确认才入库（source=adopted_ghost，装配每批 ≤1）
const adoptedPool = ref<AdoptedGhostItem[]>([])
const adoptedBusyKey = ref<string | null>(null)

async function loadAdoptedPool() {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  try {
    adoptedPool.value = await styleApi.listAdoptedGhosts(bookId)
  } catch {
    adoptedPool.value = []  // 池拿不到静默（非关键路径）
  }
}

async function collectAdopted(item: AdoptedGhostItem) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  // 在飞守卫（2026-09-04 审计修复）：busy 门此前 key 错位恒不生效，
  // 双击=同一段 AI 文本重复入库，污染「AI 来源每批 ≤1」配额
  if (adoptedBusyKey.value !== null) return
  adoptedBusyKey.value = item.ts
  try {
    await styleApi.createSample(bookId, { content: item.text, source: 'adopted_ghost' })
    adoptedPool.value = adoptedPool.value.filter((g) => g !== item)
    await reloadSamplesAndFingerprint()
    showToast('已收为样本（AI 来源，每批示范至多占 1 条）', 'success')
  } catch (error: unknown) {
    showToast('收编失败: ' + ((error as Error)?.message || ''), 'error')
  } finally {
    adoptedBusyKey.value = null
  }
}

async function uploadSample(content: string, sceneType: AuthorSampleSceneType, era: 'recent' | 'early' = 'recent') {
  const bookId = bookIdFromRoute.value
  if (!bookId || !content.trim()) return
  isBusy.value = true
  try {
    await styleApi.createSample(bookId, { content, scene_type: sceneType, era })
    await reloadSamplesAndFingerprint()
    showToast('样本已存入——指纹已更新', 'success')
  } catch (error: unknown) {
    showToast('上传失败: ' + ((error as Error)?.message || ''), 'error')
  } finally {
    isBusy.value = false
  }
}

/** 样本局部更新（时期/收藏/场景类型/正文） */
async function patchSample(sampleId: string, patch: { era?: 'recent' | 'early'; favorite?: boolean; scene_type?: AuthorSampleSceneType; content?: string }) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  try {
    const updated = await styleApi.patchSample(bookId, sampleId, patch)
    const idx = samples.value.findIndex(s => s.id === sampleId)
    if (idx >= 0) samples.value[idx] = updated
    // 时期/正文变化影响语料聚合与样本指纹 → 重算指纹
    if (patch.era || patch.content) await reloadSamplesAndFingerprint()
  } catch (error: unknown) {
    showToast('更新失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

/** 存量黄金片段一键导入样本库（补全批：from-golden 通路） */
async function importFromGolden() {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  isBusy.value = true
  try {
    const created = await styleApi.createSamplesFromGolden(bookId)
    await reloadSamplesAndFingerprint()
    goldenSnippetCount.value = Math.max(0, goldenSnippetCount.value - created.length)
    showToast(created.length > 0 ? `已导入 ${created.length} 条黄金片段为文风样本` : '黄金片段都已导入过了', 'success')
  } catch (error: unknown) {
    showToast('导入失败: ' + ((error as Error)?.message || ''), 'error')
  } finally {
    isBusy.value = false
  }
}

async function deleteSample(sampleId: string) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  const ok = await showConfirm({
    title: '删除文风样本',
    message: '确定删除这条文风样本吗？',
    warning: '样本及其向量将一并删除，不可恢复。',
  })
  if (!ok) return
  try {
    await styleApi.deleteSample(bookId, sampleId)
    await reloadSamplesAndFingerprint()
    showToast('样本已删除', 'success')
  } catch (error: unknown) {
    showToast('删除失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

async function importFromChapters() {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  isBusy.value = true
  try {
    const created = await styleApi.createSamplesFromChapters(bookId)
    await reloadSamplesAndFingerprint()
    showToast(
      created.length > 0 ? `已从章节收编 ${created.length} 条样本` : '有正文的章节都已收编过了，没有新增样本',
      created.length > 0 ? 'success' : 'info',
    )
  } catch (error: unknown) {
    const message = (error as { message?: string })?.message || ''
    showToast(message.includes('404') || message.includes('章节') ? '本书尚无可收编的章节正文' : '收编失败: ' + message, 'warning')
  } finally {
    isBusy.value = false
  }
}

// ============ 提炼（不落库红线保持） ============
function openExtract() {
  // 预填样本库里最长的 3 条（零状态坡道第三幕承接）
  extractPrefill.value = [...samples.value]
    .sort((a, b) => b.word_count - a.word_count)
    .slice(0, 3)
    .map(s => s.content)
  showExtractModal.value = true
}

async function runExtract(validSamples: string[]) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  isExtracting.value = true
  try {
    const result = await styleApi.extract(bookId, validSamples, (currentBook.value?.genre as string) || undefined)
    if (result.degraded) {
      showToast(`提炼没成，先用题材默认画像：${result.degraded.reason}`, 'warning')
    } else {
      showToast('文风画像提炼完成', 'success')
    }
    if (result.positive_profile) {
      // 画像字段锁（补全批）：被锁字段不被提炼结果覆盖
      const merged: Record<string, string> = {}
      let skipped = 0
      for (const [k, v] of Object.entries(result.positive_profile)) {
        if (lockedKeys.value.includes(k)) {
          skipped += 1
          continue
        }
        merged[k] = v
      }
      positiveProfile.value = { ...positiveProfile.value, ...merged }
      if (skipped > 0) showToast(`提炼完成（🔒 ${skipped} 个锁定字段未覆盖）`, 'info')
    }
    if (result.negative_list?.length) {
      negativeList.value = result.negative_list.map((n, i) => ({
        word: n.word || '',
        alternative: n.alternative || '',
        severity: n.severity,
        id: `neg_extract_${i}_${Date.now()}`,
      } as NegativeItem))
    }
    if (result.dialogue_ratio_target !== null && result.dialogue_ratio_target !== undefined) {
      dialogueRatioTarget.value = result.dialogue_ratio_target
    }
    if (result.paragraph_rhythm) {
      paragraphRhythm.value = result.paragraph_rhythm
    }
    markDirty()
    showExtractModal.value = false
  } catch (error: unknown) {
    showToast('提炼失败: ' + ((error as Error)?.message || ''), 'error')
  } finally {
    isExtracting.value = false
  }
}

// ============ 意图旋钮（S4）============
function updateKnob(key: StyleKnobKey, tier: number | null) {
  if (tier === null) {
    delete styleKnobs.value[key]
  } else {
    styleKnobs.value[key] = tier
  }
}

function applyPreset(preset: { label?: string; knobs: Record<string, number>; profilePatch: Record<string, string>; dialogueTarget: number }) {
  styleKnobs.value = { ...preset.knobs }
  positiveProfile.value = { ...positiveProfile.value, ...preset.profilePatch }
  dialogueRatioTarget.value = preset.dialogueTarget
  const bookId = bookIdFromRoute.value
  if (bookId) styleApi.logStyleEvent(bookId, 'apply_preset', preset.label || undefined)
  markDirty()
  showToast('预设已套用（可继续手调，试听听效果）', 'success')
}

// ============ 章级特例（S3）============
async function switchScope(chapterId: string) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  if (scopeChapterId.value === chapterId) return
  // 切走前若有未保存改动，交给既有防抖（不阻塞切换——防抖目标已变，丢弃更安全）
  clearTimeout(autosaveTimer)
  status.value = 'idle'

  if (!chapterId) {
    scopeChapterId.value = ''
    scopeHasOverride.value = false
    const card = await styleApi.get(bookId).catch(() => null)
    applyCardToFields(card)
    return
  }
  scopeChapterId.value = chapterId
  const card = await styleApi.get(bookId, chapterId).catch(() => null)
  // 后端无章级覆盖时回退返回书级卡（回退是特性，编辑基底正是书级值）——
  // 「已有特例」标记必须看 chapter_id 非空，书级卡不算特例
  scopeHasOverride.value = !!card?.chapter_id
  applyCardToFields(card)
}

function applyCardToFields(card: { positive_profile?: Record<string, string>; negative_list?: NegativeItem[]; dialogue_ratio_target?: number | null; paragraph_rhythm?: string | null; style_knobs?: Record<string, number> | null; locked_keys?: string[] | null } | null) {
  positiveProfile.value = { ...(card?.positive_profile || {}) }
  negativeList.value = Array.isArray(card?.negative_list)
    ? card!.negative_list!.map(n => ({ word: n.word || '', alternative: n.alternative || '', severity: n.severity }))
    : []
  dialogueRatioTarget.value = card?.dialogue_ratio_target ?? null
  paragraphRhythm.value = card?.paragraph_rhythm || ''
  styleKnobs.value = { ...(card?.style_knobs || {}) }
  lockedKeys.value = [...(card?.locked_keys || [])]
  for (const key of PROFILE_KEYS) {
    if (!(key in positiveProfile.value)) positiveProfile.value[key] = ''
  }
}

// ---- 画像字段锁（补全批）----
function toggleLock(key: string) {
  const idx = lockedKeys.value.indexOf(key)
  if (idx >= 0) lockedKeys.value.splice(idx, 1)
  else lockedKeys.value.push(key)
  markDirty()
}

function toggleLockAll() {
  const allLocked = PROFILE_KEYS.every(k => lockedKeys.value.includes(k))
  lockedKeys.value = allLocked ? [] : [...PROFILE_KEYS]
  if (!allLocked) {
    showToast('已锁定全部画像字段——「从样本提炼」将不再覆盖它们（特殊文体/亲笔描述保护）', 'info')
  }
  markDirty()
}

async function resetOverride() {
  const bookId = bookIdFromRoute.value
  if (!bookId || !scopeChapterId.value) return
  const ok = await showConfirm({
    title: '恢复继承书级文风',
    message: '删除本章的文风特例，本章生成回到全书默认文风？',
    warning: '章级特例删除后不可恢复（可重新配置）。',
  })
  if (!ok) return
  try {
    await styleApi.deleteChapterOverride(bookId, scopeChapterId.value)
    showToast('已恢复继承书级文风', 'success')
    scopeChapterId.value = ''
    scopeHasOverride.value = false
    const card = await styleApi.get(bookId).catch(() => null)
    applyCardToFields(card)
  } catch (error: unknown) {
    showToast('删除失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

// ============ 试听（S3 试衣间）============
function currentDraftOverride() {
  // 未保存的草稿配置直接试听——调了立刻听得见
  return {
    positive_profile: { ...positiveProfile.value },
    negative_list: negativeList.value.filter(n => n.word.trim()),
    dialogue_ratio_target: dialogueRatioTarget.value,
    paragraph_rhythm: paragraphRhythm.value || null,
  }
}

async function runAuditionOnce(track: 'baseline' | 'styled', text: string) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  auditionRuns.value[track] = { running: true, text: '' }
  const isBaseline = track === 'baseline'
  try {
    await styleApi.audition(
      bookId,
      {
        text,
        style_override: isBaseline ? null : currentDraftOverride(),
        use_samples: !isBaseline,
        target_chars: Math.min(2000, Math.max(80, text.length)),
        // 章级编辑态：baseline 轨对照的应是该章生效卡（章级特例整卡覆盖）
        ...(scopeChapterId.value ? { chapter_id: scopeChapterId.value } : {}),
      },
      {
        onChunk: (delta: string) => {
          auditionRuns.value[track] = { running: true, text: auditionRuns.value[track].text + delta }
        },
        onDone: (full: string) => {
          auditionRuns.value[track] = { running: false, text: full }
        },
        onError: (msg: string) => {
          auditionRuns.value[track] = { running: false, text: auditionRuns.value[track].text || `（失败：${msg}）` }
          showToast(`试听失败: ${msg}`, 'error')
        },
      },
    )
  } catch (error: unknown) {
    auditionRuns.value[track] = { running: false, text: auditionRuns.value[track].text || `（失败：${(error as Error)?.message || ''}）` }
  }
}

async function runAudition(text: string, withBaseline: boolean) {
  const bookId = bookIdFromRoute.value
  if (bookId) styleApi.logStyleEvent(bookId, withBaseline ? 'audition_run_ab' : 'audition_run')
  const tasks: Promise<void>[] = [runAuditionOnce('styled', text)]
  if (withBaseline) tasks.push(runAuditionOnce('baseline', text))
  await Promise.all(tasks)
}

// ============ 收件箱（S3）============
/** confirm（✓ 收入清单）：overrides = 收件箱就地编辑后的词块覆盖（Phase 3——
 *  后端 confirm 端点支持可选 word/alternative 覆盖字段，不带则维持原候选入清单） */
async function confirmInbox(itemId: string, overrides?: { word?: string; alternative?: string | null }) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  try {
    await styleApi.confirmInboxItem(bookId, itemId, overrides)
    if (bookId) styleApi.logStyleEvent(bookId, 'inbox_confirm')
    showToast('已生效（负面清单已更新）', 'success')
    // 重载卡字段 + 收件箱（负面清单变了）
    const [card, inboxData] = await Promise.all([
      scopeChapterId.value ? Promise.resolve(null) : styleApi.get(bookId).catch(() => null),
      styleApi.listInbox(bookId).catch(() => []),
    ])
    if (!scopeChapterId.value && card) applyCardToFields(card)
    inboxItems.value = inboxData as StyleInboxItem[]
  } catch (error: unknown) {
    showToast('确认失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

async function dismissInbox(itemId: string) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  try {
    await styleApi.dismissInboxItem(bookId, itemId)
    if (bookId) styleApi.logStyleEvent(bookId, 'inbox_dismiss')
    inboxItems.value = inboxItems.value.filter(i => i.id !== itemId)
  } catch (error: unknown) {
    showToast('忽略失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

/** 系统陈词本书豁免切换（补全批：三层禁词的系统层可见性） */
async function toggleExemption(pattern: string, exempted: boolean) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  const next = exempted
    ? [...new Set([...clicheExemptions.value, pattern])]
    : clicheExemptions.value.filter(p => p !== pattern)
  try {
    await styleApi.putClicheExemptions(bookId, next)
    clicheExemptions.value = next
  } catch (error: unknown) {
    showToast('豁免设置失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

// ============ 禁词扫描审稿（S3 E3）============
const scanChapterId = ref('')

function openScan() {
  scanResult.value = null
  scanResolvedWords.value = []
  showScanModal.value = true
}

async function scanChapter(chapterId: string) {
  const bookId = bookIdFromRoute.value
  if (!bookId || !chapterId) return
  scanChapterId.value = chapterId
  isScanning.value = true
  scanResult.value = null
  try {
    scanResult.value = await styleApi.scanNegative(bookId, { chapter_id: chapterId })
  } catch (error: unknown) {
    showToast('扫描失败: ' + ((error as Error)?.message || ''), 'error')
  } finally {
    isScanning.value = false
  }
}

async function applyHit(hit: StyleScanHit) {
  // 替换：把该词在本章正文中的全部出现替换为替代词（作者逐条 ✓ 后才动手）
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  try {
    const chapter = await chapterApi.get(scanChapterId.value)
    const content = chapter.content_text || ''
    if (!content.includes(hit.word)) {
      showToast('本章正文中已找不到该词（可能已被编辑）', 'warning')
      scanResolvedWords.value.push(hit.word)
      return
    }
    const replaced = content.split(hit.word).join(hit.alternative)
    await chapterApi.update(chapter.id, { content_text: replaced })
    scanResolvedWords.value.push(hit.word)
    showToast(`已替换 ${hit.count} 处「${hit.word}」→「${hit.alternative}」`, 'success')
  } catch (error: unknown) {
    showToast('替换失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

function collectHit(hit: StyleScanHit) {
  // 仅收入清单：加入负面清单本地编辑（走 2s 防抖保存），不改本章正文；
  // 硬禁档随命中一并带入（Phase 3 severity 贯通）
  const exists = negativeList.value.some(n => n.word.trim() === hit.word)
  if (!exists) {
    negativeList.value.unshift({
      word: hit.word,
      alternative: hit.alternative || '',
      severity: hit.severity === 'blocker' ? 'blocker' : undefined,
    })
    markDirty()
  }
  scanResolvedWords.value.push(hit.word)
}

function ignoreHit(hit: StyleScanHit) {
  scanResolvedWords.value.push(hit.word)
}

// ============ 导航 ============
const anchors = [
  { id: 'style-sec-samples', label: '你的字' },
  { id: 'style-sec-fingerprint', label: '笔迹指纹' },
  { id: 'style-sec-negative', label: '负面清单' },
  { id: 'style-sec-recon', label: '逐章核对' },
]

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function backToLibrary() {
  router.push({ name: 'library' })
}

// ============ 生命周期 ============
watch(bookIdFromRoute, (newId) => {
  if (newId) loadAll()
}, { immediate: true })

onUnmounted(() => clearTimeout(autosaveTimer))
</script>

<template>
  <div class="style-view">
    <header class="style-header">
      <button class="icon-btn" title="返回书架" @click="backToLibrary">
        <Icon name="arrow-left" :size="16" />
      </button>
      <div class="title-block">
        <h1 class="page-title">文风</h1>
        <span class="book-name">{{ currentBook?.title || '' }}</span>
      </div>
      <span
        v-if="statusLabel"
        class="save-badge"
        :class="{
          'badge-dirty': status === 'dirty',
          'badge-saving': status === 'saving',
          'badge-saved': status === 'saved',
          'badge-error': status === 'error',
        }"
      >{{ statusLabel }}</span>
    </header>

    <nav v-if="growthStage === 'full' && !isLoading" class="anchor-nav">
      <button
        v-for="a in anchors"
        :key="a.id"
        class="anchor-btn"
        @click="scrollToSection(a.id)"
      >{{ a.label }}</button>
    </nav>

    <main class="style-main">
      <div class="style-column" :class="{ 'ramp-mode': growthStage === 'ramp' && !isLoading }">
        <div v-if="isLoading" class="loading-note">加载中…</div>

        <template v-else>
          <!-- 坡道第一幕：整页只有一个邀请（设计稿 §6.3） -->
          <StyleSampleSection
            v-if="growthStage === 'ramp'"
            :samples="samples"
            :fingerprint-by-sample="fingerprintBySample"
            :ramp="true"
            :busy="isBusy"
            @upload="uploadSample"
            @delete="deleteSample"
            @import-chapters="importFromChapters"
          />

          <template v-else>
            <!-- 顶部常驻状态条：一句话总结 + ▶ 试听（设计稿 §6.2） -->
            <StyleStatusStrip
              v-if="growthStage === 'full'"
              :sample-count="fingerprint?.sample_count ?? samples.length"
              :cv="corpusReady ? (fingerprint?.corpus.sentence_len_cv ?? null) : null"
              :cv-healthy="fingerprint?.reference.cv_healthy ?? null"
              :dialogue-ratio="corpusReady ? (fingerprint?.corpus.dialogue_ratio ?? null) : null"
              :negative-count="negativeActiveCount"
              @audition="scrollToSection('style-sec-audition')"
            />

            <!-- S3 试听横条：调了看得见（full 才摊开，early 暂无配置可听） -->
            <StyleAuditionBar
              v-if="growthStage === 'full'"
              :default-text="auditionDefaultText"
              :runs="auditionRuns"
              :has-style-config="hasStyleConfig"
              @run="runAudition"
            />

            <!-- 第三幕建议：样本够了，画像还没建 -->
            <div v-if="suggestExtract" class="suggest-banner">
              <span>样本攒够 {{ samples.length }} 条了——要不要提炼一份文风画像？</span>
              <button class="btn-suggest" :disabled="isExtracting" @click="openExtract">开始提炼</button>
            </div>

            <!-- 事实层配对：左边贴字，右边立刻看到测量（啊哈时刻并排成立） -->
            <div class="section-row duo duo-measure">
              <StyleSampleSection
                :samples="samples"
                :fingerprint-by-sample="fingerprintBySample"
                :golden-count="goldenSnippetCount"
                :busy="isBusy"
                @upload="uploadSample"
                @delete="deleteSample"
                @import-chapters="importFromChapters"
                @import-golden="importFromGolden"
                @update-sample="patchSample"
              />
              <StyleAdoptedPool
                :items="adoptedPool"
                :busy-id="adoptedBusyKey"
                @collect="collectAdopted"
              />

              <StyleFingerprintSection
                :fingerprint="fingerprint"
                :positive-profile="positiveProfile"
                :paragraph-rhythm="paragraphRhythm"
                :is-extracting="isExtracting"
                :chapters="chapters"
                :scope-chapter-id="scopeChapterId"
                :has-override="scopeHasOverride"
                :locked-keys="lockedKeys"
                @dirty="markDirty"
                @extract="openExtract"
                @update:paragraph-rhythm="v => { paragraphRhythm = v }"
                @edit-scope="switchScope"
                @reset-override="resetOverride"
                @toggle-lock="toggleLock"
                @lock-all="toggleLockAll"
              />
            </div>

            <template v-if="growthStage === 'full'">
              <!-- S4 意图旋钮：档位制 + 预设 + 实测锚偏差提示（整宽） -->
              <div class="section-row">
                <StyleKnobsSection
                  :knobs="styleKnobs"
                  :dialogue-target="dialogueRatioTarget"
                  :corpus-sentence-mean="fingerprint?.corpus?.sentence_len_mean ?? null"
                  :corpus-dialogue="fingerprint?.corpus?.dialogue_ratio ?? null"
                  @dirty="markDirty"
                  @update-knob="updateKnob"
                  @update-dialogue="v => { dialogueRatioTarget = v }"
                  @apply-preset="applyPreset"
                />
              </div>

              <!-- 反馈层配对：禁令台账 + 结果回看 -->
              <div class="section-row duo duo-feedback">
                <StyleNegativeSection
                  :negative-list="negativeList"
                  :hit-counts="fingerprint?.negative_hit_counts"
                  :system-cliches="systemCliches"
                  :exemptions="clicheExemptions"
                  @dirty="markDirty"
                  @scan="openScan"
                  @toggle-exemption="toggleExemption"
                />

                <StyleReconciliationSection :fingerprint="fingerprint" />
              </div>

              <!-- S3 收件箱：候选过目区（空则整区隐藏） -->
              <StyleInboxSection
                :items="inboxItems"
                @confirm="confirmInbox"
                @dismiss="dismissInbox"
              />
            </template>

            <!-- 第二幕长成预告：数据再长一点，这些分区会展开 -->
            <div v-else class="grow-teaser">
              负面清单 · 意图旋钮 · 逐章核对 —— 再贴 {{ Math.max(0, 3 - samples.length) }} 条样本，这些分区会在这里长出来
            </div>
          </template>
        </template>
      </div>
    </main>

    <StyleExtractModal
      :open="showExtractModal"
      :prefill="extractPrefill"
      :is-extracting="isExtracting"
      @close="showExtractModal = false"
      @run="runExtract"
    />

    <!-- S3 E3 禁词扫描审稿模态 -->
    <StyleScanModal
      :open="showScanModal"
      :chapters="chapters"
      :scanning="isScanning"
      :result="scanResult"
      :resolved-words="scanResolvedWords"
      @close="showScanModal = false"
      @scan="scanChapter"
      @apply="applyHit"
      @collect="collectHit"
      @ignore="ignoreHit"
    />
  </div>
</template>

<style scoped>
.style-view {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg-canvas);
}
.style-header {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  flex-shrink: 0;
  padding: 0.625rem 1rem;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  color: var(--text-secondary);
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.title-block {
  display: flex;
  align-items: baseline;
  gap: 0.625rem;
  flex: 1;
  min-width: 0;
}
.page-title {
  margin: 0;
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.book-name {
  overflow: hidden;
  font-size: 0.75rem;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text-muted);
}
.save-badge {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  font-size: 0.625rem;
  border-radius: 0.25rem;
}
.badge-dirty {
  color: #b45309;
  background: #fef3c7;
}
.badge-saving {
  color: #1d4ed8;
  background: #dbeafe;
}
.badge-saved {
  color: #047857;
  background: #d1fae5;
}
.badge-error {
  color: #b91c1c;
  background: #fee2e2;
}
.anchor-nav {
  display: flex;
  gap: 0.25rem;
  flex-shrink: 0;
  padding: 0.375rem 1rem;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}
.anchor-btn {
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  cursor: pointer;
}
.anchor-btn:hover {
  color: var(--accent-500);
  background: var(--hover-bg);
}
.style-main {
  flex: 1;
  overflow-y: auto;
}
/* 流式宽度：随窗口生长，96rem 封顶（超宽屏不拉疯），侧 padding 随窗宽缩放 */
.style-column {
  width: 100%;
  max-width: 96rem;
  margin: 0 auto;
  padding: 0.5rem clamp(1.5rem, 4vw, 3.5rem) 3rem;
}
/* 坡道第一幕：邀请区在可视区内垂直居中，整页只有一个邀请 */
.style-column.ramp-mode {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 100%;
  padding-top: 0;
  padding-bottom: 0;
}
/* 分区行：hairline 分隔归容器（组件自身不带底线）；duo = 两栏网格 */
.section-row {
  border-bottom: 1px solid var(--border-color);
}
.section-row:last-child {
  border-bottom: none;
}
.section-row.duo {
  display: grid;
  gap: 0 2.5rem;
}
.section-row.duo > :first-child {
  border-right: 1px solid var(--border-color);
}
.duo-measure {
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
}
.duo-feedback {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
/* 窄窗兜底：两栏塌回单列，栏间改虚线分隔 */
@media (max-width: 74rem) {
  .section-row.duo {
    grid-template-columns: 1fr;
  }
  .section-row.duo > :first-child {
    border-right: none;
    border-bottom: 1px dashed var(--border-color);
  }
}
.loading-note {
  padding: 3rem 0;
  font-size: 0.8125rem;
  text-align: center;
  color: var(--text-muted);
}
.suggest-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.625rem 0.875rem;
  margin: 0.75rem 0 0;
  font-size: 0.75rem;
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--accent-500) 8%, var(--bg-panel));
  border: 1px solid color-mix(in srgb, var(--accent-500) 30%, var(--border-color));
  border-radius: 0.5rem;
}
.btn-suggest {
  flex-shrink: 0;
  padding: 0.3rem 0.75rem;
  font-size: 0.75rem;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-suggest:hover:not(:disabled) {
  background: var(--accent-600);
}
.btn-suggest:disabled {
  opacity: 0.5;
}
/* 第二幕长成预告（单行细带） */
.grow-teaser {
  padding: 0.625rem 1rem;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  text-align: center;
  color: var(--text-muted);
  border: 1px dashed var(--border-color);
  border-radius: 0.5rem;
}
</style>
