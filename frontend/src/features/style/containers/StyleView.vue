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
import { ref, computed, watch, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import SegmentedPill from '../../../components/SegmentedPill.vue'
import { styleApi, bookApi, chapterApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useAppStore } from '../../app/useAppStore'
import StyleSampleSection from '../presentation/StyleSampleSection.vue'
import StyleFingerprintSection from '../presentation/StyleFingerprintSection.vue'
import StyleNegativeSection from '../presentation/StyleNegativeSection.vue'
import StyleReconciliationSection from '../presentation/StyleReconciliationSection.vue'
import StyleExtractModal from '../presentation/StyleExtractModal.vue'
import StyleInboxSection from '../presentation/StyleInboxSection.vue'
import StyleAdoptedPool, { type AdoptedGhostItem } from '../presentation/StyleAdoptedPool.vue'
import StyleScanModal from '../presentation/StyleScanModal.vue'
import StyleSignatureCard from '../presentation/StyleSignatureCard.vue'
import StyleContractsSection from '../presentation/StyleContractsSection.vue'
// v4「笔迹谱」双视图：工坊（作者日常面）+ 实验室（全部数据与指标）
import StyleBanList from '../presentation/StyleBanList.vue'
import StyleRulesSwitches from '../presentation/StyleRulesSwitches.vue'
import StyleSandboxSection, { type SandboxRunState } from '../presentation/StyleSandboxSection.vue'
import type {
  StyleCard,
  StyleFingerprint,
  NegativeItem,
  AuthorSample,
  AuthorSampleSceneType,
  StyleInboxItem,
  StyleScanResult,
  StyleScanHit,
  TextureContractItem,
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
const paragraphRhythm = ref('')
const lockedKeys = ref<string[]>([])
// 2026-09-14 去参数化（第三期审计）：dialogue_ratio_target / style_knobs 已冻结
// 只读退役——前端不再持有编辑态、不再上送（后端 PUT 一律剥离）。
// 双写收敛（任务包 B）：book.style_blacklist 同步通道已删——历史书级黑名单由后端
// 启动迁移并入 negative_list，负面清单唯一权威是文风卡。

// 系统陈词库 + 本书豁免（补全批）
const systemCliches = ref<Array<{ id: string; pattern: string; alternative?: string | null; severity: string }>>([])
const clicheExemptions = ref<string[]>([])
// 写作规矩（质感契约按书覆盖，2026-09 收编批）：系统默认 + 本书定制生效视图
const textureContracts = ref<TextureContractItem[]>([])
const contractsSectionRef = ref<InstanceType<typeof StyleContractsSection> | null>(null)
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
const auditionRuns = ref<{ baseline: SandboxRunState; styled: SandboxRunState }>({
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
  negativeList.value.some(n => n.word.trim()),
)

// 零状态门闸：无样本且无任何既有配置才进坡道——旧 StyleCardManager 时代
// 填过负面清单/画像的书，不能被整页折叠成粘贴邀请（既有配置必须可见可改）
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
    const [styleCard, samplesData, fingerprintData, inboxData, chapterData, exemptionData, systemClicheData, goldenData, textureData] = await Promise.all([
      styleApi.get(bookId).catch(() => null),
      styleApi.listSamples(bookId).catch(() => []),
      styleApi.getFingerprint(bookId, true, 50).catch(() => null),
      styleApi.listInbox(bookId).catch(() => []),
      chapterApi.getAll(bookId).catch(() => []),
      styleApi.getClicheExemptions(bookId).catch(() => []),
      styleApi.listSystemCliches().catch(() => []),
      bookApi.getGoldenSnippets(bookId).catch(() => ({ golden_snippets: [] })),
      styleApi.getTextureContracts(bookId).catch(() => ({ contracts: [] })),
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
      paragraphRhythm.value = styleCard.paragraph_rhythm || ''
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
    textureContracts.value = ((textureData as { contracts?: TextureContractItem[] })?.contracts || [])
    goldenSnippetCount.value = ((goldenData as { golden_snippets?: string[] })?.golden_snippets || []).length
    chapters.value = ((chapterData as any[]) || [])
      .map((c: any) => ({ id: String(c.id), chapter_number: c.chapter_number, title: c.title || c.chapter_name || null }))
      .sort((a, b) => a.chapter_number - b.chapter_number)

    status.value = 'idle'
    errorText.value = ''

    // 深链：?chapter=<id> 直达章级特例编辑（原副驾「本章」入口已下线，直达能力保留；
    // 章级特例仍可从本页作用域切换进入，后端章级卡读写兼容不动）
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
      paragraph_rhythm: paragraphRhythm.value || null,
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
    showToast('已收进字帖（AI 写的，每次续写至多当一小段范例）', 'success')
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
    showToast('已收进字帖——AI 马上按新字学', 'success')
  } catch (error: unknown) {
    showToast('存入失败: ' + ((error as Error)?.message || ''), 'error')
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
    showToast(created.length > 0 ? `已把 ${created.length} 条黄金片段收进字帖` : '黄金片段都已导入过了', 'success')
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
    title: '从字帖删字',
    message: '确定从字帖里删掉这段字吗？',
    warning: '删掉后不可恢复。',
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
      created.length > 0 ? `已从章节收进 ${created.length} 段字` : '有正文的章节都收进过了，没有新增',
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

// （意图旋钮 S4 已退役 2026-09-14：档位/预设 UI 与状态整体下线，
//   docs/style-parameter-effectiveness-audit.md——两根支柱=亲笔样本+负面清单）

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

function applyCardToFields(card: { positive_profile?: Record<string, string>; negative_list?: NegativeItem[]; paragraph_rhythm?: string | null; locked_keys?: string[] | null } | null) {
  positiveProfile.value = { ...(card?.positive_profile || {}) }
  negativeList.value = Array.isArray(card?.negative_list)
    ? card!.negative_list!.map(n => ({ word: n.word || '', alternative: n.alternative || '', severity: n.severity }))
    : []
  paragraphRhythm.value = card?.paragraph_rhythm || ''
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
    showToast('已全部上锁——「开始提炼」不会再覆盖这些条目（特殊文体/亲笔描述保护）', 'info')
  }
  markDirty()
}

async function resetOverride() {
  const bookId = bookIdFromRoute.value
  if (!bookId || !scopeChapterId.value) return
  const ok = await showConfirm({
    title: '恢复用全书默认文风',
    message: '放下这一章单独设的文风，改回全书默认？',
    warning: '这一章的单独设置删掉后不可恢复（可以重新配）。',
  })
  if (!ok) return
  try {
    await styleApi.deleteChapterOverride(bookId, scopeChapterId.value)
    showToast('已恢复全书默认文风', 'success')
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
        // 靶场批（2026-09）：栏①裸奔= bare 开关（跳过画像+样本，只留系统基座，
        // 演示通用模型塑料味）；栏②= 草稿画像+亲笔样本全上（stitch 同源管线）
        ...(isBaseline
          ? { style_override: null, use_samples: false, bare: true }
          : { style_override: currentDraftOverride(), use_samples: true }),
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
    showToast('已生效（拦截清单已更新）', 'success')
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

// ============ 写作规矩（质感契约按书覆盖，2026-09 收编批）============

/** 以当前生效视图重建全部定制键（保留各键定制方式：rules 开关 / body 整文）。
 *  excludeKey 可选剔除（恢复默认路径用）。 */
function collectContractOverrides(excludeKey?: string): Record<string, { body?: string | null; disabled_rules?: string[] }> {
  const overrides: Record<string, { body?: string | null; disabled_rules?: string[] }> = {}
  for (const c of textureContracts.value) {
    if (c.is_default || c.key === excludeKey) continue
    if (c.customized_via === 'rules') {
      overrides[c.key] = { disabled_rules: c.rules.filter(r => !r.enabled).map(r => r.key) }
    } else {
      overrides[c.key] = { body: c.body }
    }
  }
  return overrides
}

/** 编辑保存：整体覆盖写该键契约（其余键不动——PUT 先读后写合并）。 */
async function saveTextureContract(key: string, body: string) {
  const bookId = bookIdFromRoute.value
  try {
    if (!bookId) return
    // PUT 为整体覆盖写：以当前生效视图重建全部定制键，再叠本次修改
    const overrides = collectContractOverrides()
    overrides[key] = { body }
    const res = await styleApi.putTextureContracts(bookId, overrides)
    textureContracts.value = res.contracts || []
    contractsSectionRef.value?.closeEdit()
    showToast('写作规矩已保存', 'success')
  } catch (error: unknown) {
    showToast('写作规矩保存失败: ' + ((error as Error)?.message || ''), 'error')
  } finally {
    // 子件的 busy 只置位、复位全靠本容器回调——任何出口（成功/失败/无书早退）
    // 都必须解锁，否则保存/取消双按钮永久禁用；成功路径 unlock 幂等
    contractsSectionRef.value?.unlock()
  }
}

/** 恢复默认：该键覆盖置空（后端 body 空=回系统默认），其余定制保留。 */
async function resetTextureContract(key: string) {
  const bookId = bookIdFromRoute.value
  if (!bookId) return
  try {
    const overrides = collectContractOverrides(key)
    overrides[key] = { body: null }
    const res = await styleApi.putTextureContracts(bookId, overrides)
    textureContracts.value = res.contracts || []
    showToast('已恢复系统默认', 'success')
  } catch (error: unknown) {
    showToast('恢复默认失败: ' + ((error as Error)?.message || ''), 'error')
  }
}

// ============ 负面词清洗库（模块 B，靶场批）============

/** 主契约（写作规矩开关的数据源；注册表当前唯一契约） */
const textureContract = computed(() => textureContracts.value[0] || null)
const rulesBusy = ref(false)

/** 划词/回车入禁：硬禁档（代码确定性拦截），去重后入清单头。 */
function addBanWord(word: string) {
  const w = word.trim()
  if (!w) return
  if (negativeList.value.some(n => n.word.trim() === w)) {
    showToast(`「${w}」已在清洗库里`, 'info')
    return
  }
  negativeList.value.unshift({ word: w, alternative: '', severity: 'blocker', id: `neg_ban_${Date.now()}` } as NegativeItem)
  markDirty()  // 2s 防抖自动保存落库
  showToast(`「${w}」已加入清洗库（硬禁）`, 'success')
}

function removeBanWord(index: number) {
  negativeList.value.splice(index, 1)
  markDirty()
}

/** 档位切换（与负面清单区同口径）：提醒 ⇄ 硬禁 */
function toggleBanItem(item: NegativeItem) {
  item.severity = item.severity === 'blocker' ? 'warning' : 'blocker'
  markDirty()
}

// ============ 写作规矩开关（模块 C，靶场批）============

/** 开关落库：以当前视图重建全部定制，再叠本次开关（整体覆盖写）。 */
async function toggleTextureRule(ruleKey: string, enabled: boolean) {
  const bookId = bookIdFromRoute.value
  const contract = textureContract.value
  if (!bookId || !contract || rulesBusy.value) return
  rulesBusy.value = true
  try {
    const overrides = collectContractOverrides()
    const currentDisabled = contract.rules.filter(r => !r.enabled).map(r => r.key)
    const disabled = enabled
      ? currentDisabled.filter(k => k !== ruleKey)
      : [...new Set([...currentDisabled, ruleKey])]
    overrides[contract.key] = { disabled_rules: disabled }
    const res = await styleApi.putTextureContracts(bookId, overrides)
    textureContracts.value = res.contracts || []
  } catch (error: unknown) {
    showToast('开关保存失败: ' + ((error as Error)?.message || ''), 'error')
  } finally {
    rulesBusy.value = false
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

// v4「笔迹谱」双视图（2026-09-18 实装）：工坊（默认，作者日常面——零数字零术语）
// ↔ 实验室（全部测量数据与设定指标）。v-show 驻留——两视图组件不卸载，
// 贴字草稿/规矩开关/试写结果零丢失。
const activeView = ref('work')
const viewOptions = [
  { label: '工坊', value: 'work' },
  { label: '实验室', value: 'lab' },
]

function scrollToSandbox() {
  nextTick(() => {
    document.getElementById('style-sec-sandbox')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
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
        <h1 class="page-title">文风设定</h1>
        <span class="book-name">{{ currentBook?.title || '' }}</span>
      </div>
      <SegmentedPill
        v-model="activeView"
        :options="viewOptions"
        class="view-seg"
      />
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
            <!-- ============ 视图一 · 工坊（作者日常面：零数字零术语） ============ -->
            <div v-show="activeView === 'work'" class="view-work">
              <!-- 开场白：状态灯 + 一句话（替代旧状态条；只答「起作用了吗·像不像」） -->
              <section class="opening">
                <div>
                  <div class="opening-eyebrow"><span class="opening-dot"></span>文风正在生效</div>
                  <p class="opening-line">AI 每次续写，都带着你的亲笔字、避开你拦下的词——像不像你，试写两句就知道。</p>
                </div>
                <button class="btn-try" @click="scrollToSandbox">
                  <Icon name="play" :size="12" />
                  试写两句，亲眼看
                </button>
              </section>

              <!-- 三栏工坊：字帖（你的字）/ 试写对比（像不像的裁判）/ 底线（护栏） -->
              <div class="workshop-row">
                <div class="workshop-col">
                  <div class="col-head">
                    <h3>亲笔字帖</h3>
                    <span class="col-hint">AI 学你写字，只认这里的字</span>
                  </div>
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
                </div>
                <div class="workshop-col">
                  <div class="col-head">
                    <h3>试写对比</h3>
                    <span class="col-hint">同一句开头写两遍：一遍不带你的文风，一遍带上</span>
                  </div>
                  <StyleSandboxSection
                    :runs="auditionRuns"
                    @run="text => runAudition(text, true)"
                    @ban="addBanWord"
                  />
                </div>
                <div class="workshop-col">
                  <div class="col-head">
                    <h3>写作底线</h3>
                    <span class="col-hint">给 AI 立的规矩，越线就拦</span>
                  </div>
                  <StyleRulesSwitches
                    :contract="textureContract"
                    :busy="rulesBusy"
                    @toggle="toggleTextureRule"
                  />
                  <StyleBanList
                    :items="negativeList"
                    @add="addBanWord"
                    @remove="removeBanWord"
                    @toggle="toggleBanItem"
                  />
                  <button class="scan-link" @click="openScan">用禁词清单查一整章正文——查到的每个词，由你决定：替换、收进清单，还是放过</button>
                </div>
              </div>

              <!-- 收件箱：候审横幅（空则整区隐藏；零数字——朱印代替计数） -->
              <StyleInboxSection
                v-if="growthStage === 'full'"
                :items="inboxItems"
                @confirm="confirmInbox"
                @dismiss="dismissInbox"
              />
            </div>

            <!-- ============ 视图二 · 实验室（全部测量数据与设定指标） ============ -->
            <section v-show="activeView === 'lab'" class="view-lab">
              <div class="lab-top">
                <div>
                  <div class="lab-eyebrow">实验室</div>
                  <p class="lab-lead">全部数据和指标都集中在这里——从你的文字实测得出，不是 AI 猜的；怎么解读，由你定。</p>
                </div>
                <button class="btn-back" @click="activeView = 'work'">
                  <Icon name="arrow-left" :size="12" />
                  回工坊
                </button>
              </div>

              <!-- 提炼建议（行动引导归实验室）：字攒够了，画像还没建 -->
              <div v-if="suggestExtract" class="suggest-banner">
                <span>亲笔字攒够了——要不要提炼一份文风画像？AI 会从你的字里总结你的写法，你过目后才生效。</span>
                <button class="btn-suggest" :disabled="isExtracting" @click="openExtract">开始提炼</button>
              </div>

              <!-- 笔迹签名：墨迹图 + 金线 + 事实数（实验室首屏） -->
              <StyleSignatureCard
                :fingerprint="fingerprint"
                :negative-count="negativeActiveCount"
              />

              <!-- 指标格 + 画像/按章设文风（高级面板） -->
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

              <!-- 逐章核对：两张趋势图 + 一句人话总结 -->
              <StyleReconciliationSection :fingerprint="fingerprint" />

              <!-- 写作规矩整文编辑（日常开关在工坊右栏） -->
              <StyleContractsSection
                ref="contractsSectionRef"
                :contracts="textureContracts"
                @save="saveTextureContract"
                @reset="resetTextureContract"
              />

              <!-- 禁词全量与陈词库 -->
              <StyleNegativeSection
                :negative-list="negativeList"
                :hit-counts="fingerprint?.negative_hit_counts"
                :system-cliches="systemCliches"
                :exemptions="clicheExemptions"
                @dirty="markDirty"
                @scan="openScan"
                @toggle-exemption="toggleExemption"
              />
            </section>
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
  background: var(--surface-desk); /* 06-modern §2.1：页面根=桌面 */
}
.style-header {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  flex-shrink: 0;
  padding: 0.625rem 1rem;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--line-faint);
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
  border-radius: var(--radius-xs);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}
.icon-btn:hover {
  background: var(--state-hover);
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
  font-size: var(--text-2xl);
  letter-spacing: 0.08em;
  font-weight: 600;
  color: var(--text-primary);
}
.book-name {
  overflow: hidden;
  font-size: var(--text-sm);
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text-muted);
}
.save-badge {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  font-size: var(--text-xs);
  border-radius: var(--radius-xs);
}
.badge-dirty {
  color: var(--warn);
  background: var(--warn-bg);
}
.badge-saving {
  color: var(--info);
  background: var(--info-bg);
}
.badge-saved {
  color: var(--ok);
  background: var(--ok-bg);
}
.badge-error {
  color: var(--danger);
  background: var(--danger-bg);
}
/* ---- v4 双视图 ---- */
/* SegmentedPill 根默认 width:100%（整行铺满用法）——页头场景必须收成内容宽，
   否则巨轨挤塌标题（2026-09-18 真机 bug 修复） */
.view-seg {
  width: fit-content;
  margin-left: auto;
  flex-shrink: 0;
  align-self: center;
}
.view-work,
.view-lab {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.view-lab {
  gap: var(--space-8);
}

/* ---- 开场白（工坊首行：状态灯 + 一句话，零数字零术语） ---- */
.opening {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-6) 0;
  border-bottom: 1px solid var(--line-faint);
}
.opening-eyebrow {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  letter-spacing: 0.18em;
  color: var(--cinnabar);
  font-weight: 600;
}
/* 薄荷呼吸点 = AI 正在带着你的字（状态灯，非数据） */
.opening-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--mint);
  animation: opening-breathe 2.4s ease-in-out infinite;
}
@keyframes opening-breathe {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}
.opening-line {
  margin: var(--space-2) 0 0;
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
  line-height: 1.6;
  letter-spacing: 0.01em;
  color: var(--text-primary);
}
.btn-try {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  flex-shrink: 0;
  min-height: var(--control-h-md);
  padding: 0 var(--space-5);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  margin-left: auto;
}
.btn-try:hover {
  background: var(--accent-600);
}

/* ---- 三栏工坊：字帖（窄）/ 试写对比（弹性主角）/ 底线（窄） ---- */
.workshop-row {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 320px;
  gap: var(--space-6);
  align-items: start;
  padding-top: var(--space-6);
}
.workshop-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  min-width: 0;
}
.col-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding-bottom: var(--space-2);
  border-bottom: 2px solid var(--line-strong);
}
.col-head h3 {
  margin: 0;
  font-family: var(--font-heading);
  font-size: var(--text-lg);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-primary);
  white-space: nowrap;
}
.col-hint {
  overflow: hidden;
  font-size: var(--text-xs);
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text-faint);
}
@container stylepage (max-width: 60rem) {
  .workshop-row {
    grid-template-columns: 1fr;
  }
}

/* ---- 扫描入口（工坊右栏底部；模态复用既有 StyleScanModal） ---- */
.scan-link {
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  color: var(--accent-500);
  text-align: left;
  background: transparent;
  border: 1px dashed color-mix(in srgb, var(--accent-500) 40%, transparent);
  border-radius: var(--radius-md);
  cursor: pointer;
}
.scan-link:hover {
  background: color-mix(in srgb, var(--accent-500) 7%, transparent);
}
/* ---- 实验室视图头（全部数据与指标的入口叙事） ---- */
.lab-top {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding-top: var(--space-6);
}
.lab-eyebrow {
  font-size: var(--text-xs);
  letter-spacing: 0.18em;
  color: var(--cinnabar);
  font-weight: 600;
}
.lab-lead {
  margin: var(--space-1) 0 0;
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 600;
  line-height: 1.5;
  color: var(--text-primary);
}
.btn-back {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
  min-height: var(--control-h-md);
  margin-left: auto;
  padding: 0 var(--space-4);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-back:hover {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.view-lab .suggest-banner {
  margin: 0;
}
.style-main {
  flex: 1;
  overflow-y: auto;
  container-type: inline-size;
  container-name: stylepage;
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
  font-size: var(--text-sm);
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--accent-500) 8%, var(--surface-overlay));
  border: 1px solid color-mix(in srgb, var(--accent-500) 30%, var(--border-color));
  border-radius: var(--radius-md);
}
.btn-suggest {
  flex-shrink: 0;
  min-height: 28px;
  padding: 0.3rem 0.75rem;
  font-size: var(--text-sm);
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-suggest:hover:not(:disabled) {
  background: var(--accent-600);
}
.btn-suggest:disabled {
  opacity: 0.5;
}
</style>
