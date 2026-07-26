<script setup lang="ts">
/**
 * 智能副驾（Inspector，V3.1 F2 骨架 + F3 接入生成流程，规格 §4.3）。
 *
 * 右栏六 tab：
 * - 规划：生成主控（定档、V5 引擎切换 ADF/BS-ADF、轨道 A/B、「生成本章」、V4.2 介入点 1 规划确认、生成进度）
 * - 设定：场景设定（角色/地点/资产）
 * - 润色：V4.1 Refinery（诊断问题清单 → 作者确认 → 手术 + 回读 + 抛光）
 * - 反馈：V4.3 读者反馈 + 审校结论（ADF 锚点审计 / Refinery 整体回读）+ Precondition 落地
 * - 节拍：V5 BS-ADF（Track B 槽位卡编辑 / 渲染进度 / Track A 槽位卡预览）
 * - Canon：本章 Precondition / 情绪曲线 / 出场角色速查，并跳转 Canon 脑图
 *
 * Ctrl+1~6 切 tab。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useToast } from '../../../composables/useToast'
import { useAppStore } from '../../app/useAppStore'
import ChapterBadges from '../presentation/ChapterBadges.vue'
import TierSelector from '../../../components/TierSelector.vue'
import RefineryIssuesPanel from '../../generation/presentation/RefineryIssuesPanel.vue'
import RefineryProgress from '../../generation/presentation/RefineryProgress.vue'
import BeatSlotPanel from '../../generation/presentation/BeatSlotPanel.vue'
import BeatProgress from '../../generation/presentation/BeatProgress.vue'
import SlotPreview from '../../generation/presentation/SlotPreview.vue'
import DegradedBeatPlaceholder from '../../generation/presentation/DegradedBeatPlaceholder.vue'
import TrackSelector from '../../generation/presentation/TrackSelector.vue'
import PlanConfirmModal from '../../generation/presentation/PlanConfirmModal.vue'
import type { IssueDecision, RefineryIssue, PlanSuggestionResponse, BeatSlot } from '../../../services/api/domain'
import { adfApi, refineryApi } from '../../../services/api/domain'
import GenerationStepper from '../../generation/presentation/GenerationStepper.vue'
import SceneSettingsPanel from '../presentation/SceneSettingsPanel.vue'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'

type InspectorTab = 'plan' | 'setting' | 'refine' | 'feedback' | 'canon' | 'beats'

// BS-ADF 引擎选择（V5）：adf = 原 ADF 引擎（session.start）；bsadf = 新 BS-ADF（session.startBeat）
type EngineChoice = 'adf' | 'bsadf'
type TrackChoice = 'A' | 'B'

interface TabDef {
  key: InspectorTab
  label: string
  icon: string
  ready: boolean
}

const store = useAppStore()
const selectedChapter = store.selectedChapter
const characters = store.characters
const selectedChapterId = store.selectedChapterId

// V4.x 重构：session 从外部传入（由 WorkspaceView 创建并共享给中栏覆盖面板）
// 如果没传（独立使用 InspectorPanel），自己创建
const props = withDefaults(defineProps<{
  externalSession?: ReturnType<typeof useGenerationSession> | null
}>(), {
  externalSession: null,
})

const tabs: TabDef[] = [
  { key: 'plan', label: '规划', icon: 'sparkles', ready: true },
  { key: 'setting', label: '设定', icon: 'map', ready: true },
  { key: 'refine', label: '润色', icon: 'pencil', ready: true },
  { key: 'feedback', label: '反馈', icon: 'chat', ready: true },
  { key: 'beats', label: '节拍', icon: 'bolt', ready: true },
  { key: 'canon', label: 'Canon', icon: 'link', ready: true },
]

const activeTab = ref<InspectorTab>('plan')

// 生成会话（V4.x：优先用外部传入的，否则自建）
const session = props.externalSession || useGenerationSession()
const tierSelection = ref<'auto' | 'climax' | 'turn' | 'progress' | 'transition'>('auto')
// V3.5：字数指定（null = 自动按定档推导；用户填了就用用户的）
const targetWordCount = ref<number | null>(null)

// V5 BS-ADF：引擎选择 + 渲染轨道（仅 BS-ADF 引擎显示 TrackSelector）
const selectedEngine = ref<EngineChoice>('adf')
const selectedTrack = ref<TrackChoice>('A')

// V4.2 介入点 1：章节规划确认
const planSuggestion = ref<PlanSuggestionResponse | null>(null)
const showPlanModal = ref(false)
const pendingAuthorIntent = ref('')

// V4.3 介入点 3：读者反馈
const readerFeedback = ref('')
const loadingFeedback = ref(false)

// 生成完成后自动切到反馈 tab；精修诊断完成切到精修 tab
// V5：BS-ADF 暂停态（beat_pending）/ 渲染中（beat_rendering）切到节拍 tab
watch(
  () => session.stage.value,
  (newStage) => {
    if (newStage === 'beat_pending' && session.beatSlots.value.length > 0) {
      activeTab.value = 'beats'
    } else if (newStage === 'beat_rendering') {
      activeTab.value = 'beats'
    } else if (newStage === 'done') {
      // BS-ADF 完成后停在节拍 tab 看槽位卡预览；ADF/Refinery 完成切到反馈
      if (session.lastDoneMode.value === 'bsadf' && session.beatSlots.value.length > 0) {
        activeTab.value = 'beats'
      } else {
        activeTab.value = 'feedback'
      }
    } else if (newStage === 'refining' && session.refineryIssues.value.length > 0) {
      activeTab.value = 'refine'
    }
  }
)

function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key >= '1' && e.key <= String(tabs.length)) {
    e.preventDefault()
    const idx = parseInt(e.key) - 1
    if (idx < tabs.length) {
      activeTab.value = tabs[idx].key
    }
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))

const chapterCharacters = computed(() => {
  if (!selectedChapter.value) return []
  const ids = (selectedChapter.value as any).character_ids || []
  return characters.value.filter((c) => ids.includes(c.id))
})

const wordCount = computed(() => (selectedChapter.value?.content_text || '').length)

/** 审校 verdict 中文标签（ADF 审计与 Refinery 回读共用） */
const VERDICT_LABELS: Record<string, string> = {
  pass: '通过',
  pass_with_fixes: '修改后通过',
  needs_refinement: '需要精修',
  needs_final_touch: '需要再修',
  fail: '未通过',
  unaudited: '未审校',
}
function verdictLabel(v?: string | null) {
  return (v && VERDICT_LABELS[v]) || v || '—'
}

/** 更新章节字段（标题/大纲），带简易防抖避免每次按键写库 */
const fieldTimers: Record<string, ReturnType<typeof setTimeout> | undefined> = {}
function updateChapterField(field: 'title' | 'outline_text', value: string) {
  if (!selectedChapterId.value) return
  clearTimeout(fieldTimers[field])
  fieldTimers[field] = setTimeout(() => {
    store.updateChapter(selectedChapterId.value!, { [field]: value })
  }, 500)
}

const emit = defineEmits<{
  (e: 'generate', payload: { tier: string; authorIntent?: string }): void
  (e: 'generated', text: string): void
  (e: 'jump-to-offset', offset: [number, number] | undefined): void
}>()

function startGenerate() {
  if (!selectedChapterId.value) {
    console.warn('[Inspector] startGenerate: 无选中章节')
    return
  }
  console.log('[Inspector] startGenerate:', { tier: tierSelection.value, chapterId: selectedChapterId.value })
  // V4.2 介入点 1：先弹章节规划确认，再进入 V3.2 ADF 生成
  fetchPlanAndShow()
}

async function fetchPlanAndShow() {
  if (!selectedChapterId.value) {
    console.warn('[Inspector] fetchPlanAndShow: 无选中章节')
    return
  }
  // V5：BS-ADF 引擎不走 plan-suggestion 介入点（用 BeatSlot 卡作为介入点），直接启动
  if (selectedEngine.value === 'bsadf') {
    startBeatGenerate()
    return
  }
  const toast = useToast()
  try {
    console.log('[Inspector] 请求 plan-suggestion...')
    planSuggestion.value = await adfApi.getPlanSuggestion(selectedChapterId.value)
    console.log('[Inspector] plan-suggestion 成功，弹窗', planSuggestion.value)
    showPlanModal.value = true
  } catch (e: any) {
    // 失败则提示并跳过介入点，直接生成
    console.error('[Inspector] plan-suggestion 失败:', e)
    toast.showToast(`规划建议获取失败（${e.message || '网络错误'}），已跳过确认环节`, 'warning')
    // 降级：跳过介入点 1，直接生成
    session.start(selectedChapterId.value, tierSelection.value, {
      targetWordCount: targetWordCount.value,
    })
    emit('generate', { tier: tierSelection.value })
  }
}

/** V5 BS-ADF：启动生成（Track A 全自动 / Track B 跑到槽位卡暂停） */
function startBeatGenerate() {
  if (!selectedChapterId.value) {
    console.warn('[Inspector] startBeatGenerate: 无选中章节')
    return
  }
  console.log('[Inspector] startBeatGenerate:', {
    tier: tierSelection.value,
    track: selectedTrack.value,
    chapterId: selectedChapterId.value,
  })
  session.startBeat(selectedChapterId.value, tierSelection.value, {
    track: selectedTrack.value,
    targetWordCount: targetWordCount.value,
    authorIntent: pendingAuthorIntent.value || undefined,
  })
  emit('generate', { tier: tierSelection.value, authorIntent: pendingAuthorIntent.value })
}

function handlePlanConfirm(payload: { authorIntent: string; expectationActions: Record<string, string>; payoffDecision: string }) {
  showPlanModal.value = false
  pendingAuthorIntent.value = payload.authorIntent
  if (!selectedChapterId.value) return
  // V5：按引擎分流
  if (selectedEngine.value === 'bsadf') {
    startBeatGenerate()
    return
  }
  // V4.2：把作者意图真正透传到 ADF 生成请求
  session.start(selectedChapterId.value, tierSelection.value, {
    authorIntent: payload.authorIntent,
    expectationActions: payload.expectationActions,
    targetWordCount: targetWordCount.value,
  })
  emit('generate', { tier: tierSelection.value, authorIntent: payload.authorIntent })
}

function handlePlanSkip() {
  showPlanModal.value = false
  if (!selectedChapterId.value) return
  // V5：按引擎分流
  if (selectedEngine.value === 'bsadf') {
    startBeatGenerate()
    return
  }
  session.start(selectedChapterId.value, tierSelection.value, {
    targetWordCount: targetWordCount.value,
  })
}

/** V4.2 介入点 1：作者取消生成（不进入生成了） */
function handlePlanCancel() {
  showPlanModal.value = false
  planSuggestion.value = null
}

/** V4.1 启动精修（诊断阶段） */
function handleStartRefinery() {
  if (!selectedChapterId.value) return
  session.startRefinery(selectedChapterId.value, { mode: 'deep', enablePolish: true })
}

/** V4.1 作者确认问题清单后，执行手术+回读+抛光 */
function handleRefineryConfirm(payload: { run_id: string; decisions: IssueDecision[]; custom_issues: RefineryIssue[] }) {
  if (!selectedChapterId.value) return
  session.confirmRefinery(selectedChapterId.value, payload.decisions, payload.custom_issues)
}

/** V4.1 取消精修（清空 refinery 状态，回到 done） */
function handleRefineryCancel() {
  session.refineryIssues.value = []
  session.refineryRunId.value = null
  session.stage.value = 'done'
}

/** V5 BS-ADF：作者确认槽位卡编辑，恢复渲染 */
function handleBeatConfirm(payload: { run_id: string; edited_slots: BeatSlot[] }) {
  if (!selectedChapterId.value) return
  session.confirmBeats(selectedChapterId.value, payload.edited_slots)
}

/** V5 BS-ADF：作者取消（回滚到 idle） */
function handleBeatCancel() {
  session.cancelBeat()
}

/**
 * V5 BS-ADF Phase 4d：降级单卡恢复。
 * - rerender：拿 slot 数据调 session.rerenderBeat（调 /rerender-beat 单卡重渲染）。
 *   slot 来源：优先 session.beatSlots（done 态 SlotPreview 仍持有）；
 *   找不到时（Track B confirm 后 beatSlots 已清空）从 degraded_beat 构造最小 slot
 *   （仅 beat_id + segment_index 必填，其余字段后端补默认值）。
 * - skip：直接从 degradedBeats 移除该 beat（保留正文中的占位，作者手动放弃）。
 */
async function handleRerenderBeat(slot: BeatSlot) {
  if (!selectedChapterId.value) return
  await session.rerenderBeat(selectedChapterId.value, slot.beat_id, slot)
}

function handleSkipBeat(beatId: string) {
  session.degradedBeats.value = session.degradedBeats.value.filter(d => d.beat_id !== beatId)
}

/** 取降级 beat 对应的 slot：beatSlots 优先（done 态 SlotPreview 持有全量 slot），
 *  找不到则从 degraded_beat 构造最小占位 slot（仅 id + segment_index，后端补默认值）。 */
function getSlotForDegraded(beatId: string): BeatSlot | undefined {
  const found = session.beatSlots.value.find(s => s.beat_id === beatId)
  if (found) return found
  const db = session.degradedBeats.value.find(d => d.beat_id === beatId)
  if (!db) return undefined
  // 最小占位 slot：后端 BeatSlotSchema 仅 beat_id/segment_index 必填，其余字段用默认值兜底
  return {
    beat_id: db.beat_id,
    segment_index: db.segment_index,
    beat_type: 'ESTABLISH',
    target_word_count: 600,
    anchor_actions: [],
    sensory_details: [],
    text_carrier: '',
    conflict_trigger: '',
    psych_subtext: '',
    ban_words: [],
    sentence_rhythm: 'VARIED',
    perspective: 'THIRD_LIMITED',
    emotion_register: '',
    emotion_energy: 5,
    landed_preconditions: [],
    shot_type: '',
    transition: '',
    status: 'degraded',
    edit_count: 0,
    render_attempts: db.attempts,
    edited: false,
  } as BeatSlot
}

/** V4.3 介入点 3：获取读者反馈 */
async function handleReaderFeedback() {
  if (!selectedChapterId.value) return
  loadingFeedback.value = true
  readerFeedback.value = ''
  try {
    const result = await refineryApi.getReaderFeedback(selectedChapterId.value)
    readerFeedback.value = result.feedback
  } catch (e: any) {
    readerFeedback.value = `获取失败：${e.message}`
  } finally {
    loadingFeedback.value = false
  }
}

/** V4.1 现场跳转 Canon 编辑（RefineryIssuesPanel 触发） */
const router = useRouter()
function handleEditCanon() {
  const bookId = store.currentBookId.value
  if (!bookId) return
  // 保留当前 refinery 状态，跳转到 Canon 页；作者编辑完手动回来继续
  router.push({ name: 'canon', params: { bookId } })
}

function handleCancel() {
  session.cancel()
}

function handleDismissInflight(idx: number) {
  session.inflightEvents.value.splice(idx, 1)
}

// collapse 逻辑已移除（不再收起副驾）

// 注：原"生成完成时把正文通知父级"的 emit('generated') watcher 已删除。
// WorkspaceView 的 watch(session.stage) 已独立覆盖完成检测（写章节 + 弹窗 + 系统通知），
// 此处的 emit 路径与之语义重复，会在 done 瞬间双触发 handleGenerated，已移除。
</script>

<template>
  <aside class="inspector">
    <!-- tab 头 -->
    <div class="tab-bar">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="tab-btn"
        :class="{ active: activeTab === t.key }"
        :title="`${t.label} (Ctrl+${tabs.indexOf(t) + 1})`"
        @click="activeTab = t.key"
      >
        <Icon :name="t.icon" :size="15" />
        <span class="tab-label">{{ t.label }}</span>
      </button>
    </div>

    <!-- tab 内容 -->
    <div class="tab-content">
      <!-- V4.2 介入点 1：章节规划确认弹窗（放在 tab-content 内部，作为 overlay） -->
      <PlanConfirmModal
        v-if="showPlanModal && planSuggestion"
        :suggestion="planSuggestion"
        @confirm="handlePlanConfirm"
        @skip="handlePlanSkip"
        @cancel="handlePlanCancel"
      />
      <!-- 本章 tab -->
      <!-- ====== 规划 tab：定档 + 生成 + 介入点 1 ====== -->
      <div v-if="activeTab === 'plan'" class="panel plan-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 章节卡摘要（可编辑：标题 + 大纲） -->
          <section class="card-strip">
            <header class="strip-header">
              <span class="strip-num">第 {{ selectedChapter.chapter_number }} 章</span>
              <ChapterBadges :chapter="selectedChapter" />
            </header>
            <input
              class="strip-title-input"
              :value="selectedChapter.title"
              placeholder="章节标题"
              @input="(e) => updateChapterField('title', (e.target as HTMLInputElement).value)"
            />
            <textarea
              class="strip-outline-input"
              :value="selectedChapter.outline_text"
              placeholder="一句话主旨 / 大纲（AI 生成时会参考）"
              rows="5"
              @input="(e) => updateChapterField('outline_text', (e.target as HTMLTextAreaElement).value)"
            ></textarea>
          </section>

          <!-- 场景设定入口提示（实际选择在"设定"tab） -->
          <div v-if="!session.generating.value" class="setting-entry-hint">
            <Icon name="map" :size="13" />
            <span>
              场景设定（角色/地点/资产）请在
              <button class="link-btn" @click="activeTab = 'setting'">「设定」标签</button>
              中选择
            </span>
          </div>

          <!-- 生成进度（生成中 / 失败时显示，失败含重试入口） -->
          <GenerationStepper
            v-if="session.generating.value || (session.stage.value !== 'idle' && session.stage.value !== 'done')"
            :session="session"
            @cancel="handleCancel"
            @dismiss-inflight="handleDismissInflight"
            @retry="session.retry"
          />

          <!-- 生成主控（未生成 / 完成时显示） -->
          <section v-if="!session.generating.value" class="generate-section">
            <div class="section-label">篇幅</div>
            <TierSelector v-model="tierSelection" />

            <!-- V5 引擎切换：ADF / BS-ADF -->
            <div class="engine-toggle">
              <label class="wc-label">引擎</label>
              <div class="engine-options">
                <button
                  class="engine-btn"
                  :class="{ active: selectedEngine === 'adf' }"
                  title="锚点驱动流（ADF）：直接生成全章正文"
                  @click="selectedEngine = 'adf'"
                >
                  <span class="engine-name">ADF</span>
                  <span class="engine-desc">整章直写</span>
                </button>
                <button
                  class="engine-btn"
                  :class="{ active: selectedEngine === 'bsadf' }"
                  title="分段节拍流（BS-ADF）：先拆段再逐段渲染，可在轨道 B 编辑槽位"
                  @click="selectedEngine = 'bsadf'"
                >
                  <span class="engine-name">BS-ADF</span>
                  <span class="engine-desc">分段节拍</span>
                </button>
              </div>
            </div>

            <!-- V5 BS-ADF 轨道选择（仅 BS-ADF 引擎显示） -->
            <TrackSelector v-if="selectedEngine === 'bsadf'" v-model="selectedTrack" />

            <div class="word-count-input">
              <label class="wc-label">目标字数</label>
              <input
                type="number"
                class="wc-field"
                :value="targetWordCount ?? ''"
                placeholder="自动"
                min="500"
                max="20000"
                step="100"
                @input="(e) => {
                  const v = parseInt((e.target as HTMLInputElement).value)
                  targetWordCount = (isNaN(v) || v < 500) ? null : v
                }"
              />
              <span class="wc-hint">{{ targetWordCount ? '已指定' : '按定档自动' }}</span>
            </div>
            <button class="btn-generate" :disabled="session.generating.value" @click="startGenerate">
              <Icon name="sparkles" :size="15" />
              <span>{{ session.stage.value === 'done' ? '重新生成' : '生成本章' }}</span>
            </button>
            <p class="hint">
              <template v-if="selectedEngine === 'bsadf' && selectedTrack === 'B'">
                BS-ADF 轨道 B：先生成槽位卡，你编辑后再逐段渲染。
              </template>
              <template v-else-if="selectedEngine === 'bsadf'">
                BS-ADF 轨道 A：全自动拆段 + 逐段渲染，无需介入。
              </template>
              <template v-else>
                先确认篇幅与设定，再逐段写作。
              </template>
            </p>
          </section>

          <!-- 统计 -->
          <section class="stats-section">
            <div class="stat">
              <span class="stat-num">{{ wordCount }}</span>
              <span class="stat-label">字</span>
            </div>
            <div class="stat">
              <span class="stat-num">{{ chapterCharacters.length }}</span>
              <span class="stat-label">出场角色</span>
            </div>
          </section>
        </template>
      </div>

      <!-- ====== 设定 tab：场景设定（角色/地点/资产） ====== -->
      <div v-else-if="activeTab === 'setting'" class="panel setting-panel">
        <SceneSettingsPanel :chapter-id="selectedChapterId" />
      </div>

      <!-- ====== 精修 tab：介入点 2 + 手术进度 ====== -->
      <div v-else-if="activeTab === 'refine'" class="panel refine-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 精修未启动时 -->
          <section v-if="session.stage.value !== 'refining' && !session.refinerySurgeries.value.length" class="refine-entry">
            <div v-if="session.stage.value === 'idle'" class="empty">
              <div class="empty-icon"><Icon name="pencil" :size="40" /></div>
              <p>本章尚未生成。</p>
              <p class="muted">生成完成后，可启动润色。</p>
            </div>
            <!-- 诊断进行中（stage='auditing'）：显示过渡态，避免"空白没反应"观感 -->
            <div v-else-if="session.stage.value === 'auditing' && session.generating.value" class="refine-loading">
              <div class="empty-icon spinning"><Icon name="sparkles" :size="32" /></div>
              <p>正在通读全文找问题…</p>
              <p class="muted">检查 + 归类需要一点时间，请稍候。</p>
            </div>
            <div v-else-if="session.stage.value === 'done' && !session.refineryRunId.value">
              <button class="btn-refinery" @click="handleStartRefinery">
                <Icon name="sparkles" :size="14" />
                <span>启动润色（检查 + 修改）</span>
              </button>
              <p class="hint">
                AI 通读全文找问题 → 你确认 → 逐处修改 → 通读检查 → 定稿润色。
              </p>
            </div>
          </section>

          <!-- 精修问题清单（介入点 2：诊断完成、等作者确认） -->
          <RefineryIssuesPanel
            v-if="session.stage.value === 'refining' && session.refineryIssues.value.length > 0 && session.refineryRunId.value"
            :issues="session.refineryIssues.value"
            :run-id="session.refineryRunId.value"
            @confirm="handleRefineryConfirm"
            @cancel="handleRefineryCancel"
            @edit-canon="handleEditCanon"
          />

          <!-- 精修手术进度 -->
          <RefineryProgress
            v-if="session.stage.value === 'refining' && session.refineryRunId.value === null && (session.generating.value || session.refinerySurgeries.value.length > 0)"
            :surgeries="session.refinerySurgeries.value"
            :holistic-verdict="session.refineryHolisticVerdict.value"
            :stage-label="session.stepProgress.value?.label || ''"
            :stage="session.stage.value"
          />

          <!-- 精修完成后的手术历史 -->
          <section v-if="session.stage.value === 'done' && session.refinerySurgeries.value.length" class="refine-history">
            <div class="section-label">润色记录（{{ session.refinerySurgeries.value.filter(s => s.applied).length }}/{{ session.refinerySurgeries.value.length }} 成功）</div>
            <div v-for="s in session.refinerySurgeries.value" :key="s.operation_id" class="surgery-row" :class="{ failed: !s.applied }">
              <span class="surgery-status">{{ s.applied ? '✓' : '✗' }}</span>
              <span class="surgery-diff">{{ s.diff_summary }}</span>
            </div>
            <button class="btn-refinery" @click="handleStartRefinery">
              <Icon name="arrow-path" :size="14" />
              <span>再次润色</span>
            </button>
          </section>
        </template>
      </div>

      <!-- ====== 反馈 tab：读者反馈 + 审校结论 ====== -->
      <div v-else-if="activeTab === 'feedback'" class="panel feedback-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 介入点 3：读者反馈 -->
          <section class="feedback-section">
            <button
              class="btn-refinery secondary"
              :disabled="loadingFeedback || session.stage.value === 'idle'"
              :title="session.stage.value === 'idle' ? '需先生成或已有章节内容' : 'AI 扮演读者写叙述性感受'"
              @click="handleReaderFeedback"
            >
              <Icon name="chat" :size="14" />
              <span>{{ loadingFeedback ? '读者阅读中…' : '获取读者反馈' }}</span>
            </button>
            <div v-if="readerFeedback" class="reader-feedback-card">
              <div class="rf-header">📖 读者反馈</div>
              <p class="rf-text">{{ readerFeedback }}</p>
            </div>
            <p v-else-if="session.stage.value !== 'idle'" class="hint">
              AI 扮演读者写叙述性感受（不是检查清单）。
            </p>
          </section>

          <!-- 审校结论（来自 adfAudit / refineryHolisticVerdict） -->
          <section v-if="session.stage.value !== 'idle'" class="audit-section">
            <div class="section-label">审校结论</div>
            <!-- ADF 锚点审计 -->
            <div v-if="session.adfAudit.value" class="audit-block">
              <div class="audit-row">
                <span class="audit-label">结构检查</span>
                <span class="audit-value" :class="`verdict-${session.adfAudit.value.verdict}`">{{ verdictLabel(session.adfAudit.value.verdict) }}</span>
              </div>
              <div v-if="session.adfAudit.value.climax_score" class="audit-row">
                <span class="audit-label">高潮评分</span>
                <span class="audit-value">{{ session.adfAudit.value.climax_score }}/10</span>
              </div>
              <div v-if="session.adfAudit.value.missing_preconditions?.length" class="audit-row">
                <span class="audit-label">未交代的要点</span>
                <span class="audit-value warn">{{ session.adfAudit.value.missing_preconditions.join(', ') }}</span>
              </div>
            </div>
            <!-- 精修整体回读 -->
            <div v-if="session.refineryHolisticVerdict.value" class="audit-block">
              <div class="audit-row">
                <span class="audit-label">通读检查</span>
                <span class="audit-value" :class="`verdict-${session.refineryHolisticVerdict.value.verdict}`">
                  {{ session.refineryHolisticVerdict.value.verdict === 'pass' ? '✓ 通过' : '⚠ 需要再修' }}
                </span>
              </div>
            </div>
          </section>

          <!-- Precondition 落地 -->
          <section v-if="session.adfPreconditions.value.length" class="precondition-section">
            <div class="section-label">铺垫要点（{{ session.adfPreconditions.value.filter((p: any) => p.landed).length }}/{{ session.adfPreconditions.value.length }} 已交代）</div>
            <div
              v-for="pc in session.adfPreconditions.value"
              :key="pc.id"
              class="precondition-item"
              :class="{ landed: pc.landed }"
            >
              <span class="pc-icon">{{ pc.landed ? '✓' : '○' }}</span>
              <span class="pc-text">{{ pc.description }}</span>
            </div>
          </section>
        </template>
      </div>

      <!-- ====== 节拍 tab：BS-ADF Track B 编辑 / 渲染进度 / Track A 预览 ====== -->
      <div v-else-if="activeTab === 'beats'" class="panel beats-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- Track B 暂停态：槽位卡编辑面板 -->
          <BeatSlotPanel
            v-if="session.stage.value === 'beat_pending' && session.beatSlots.value.length > 0 && session.beatRunId.value"
            :slots="session.beatSlots.value"
            :run-id="session.beatRunId.value"
            @confirm="handleBeatConfirm"
            @cancel="handleBeatCancel"
          />

          <!-- 渲染进度（Track A 全程 + Track B confirm 后） -->
          <BeatProgress
            v-else-if="(session.stage.value === 'beat_rendering' || session.stage.value === 'tier_classifying') && (session.renderProgress.value.length > 0 || session.generating.value) && session.bsadfTrack.value"
            :progress="session.renderProgress.value"
            :degraded="session.degradedBeats.value"
            :stage-label="session.stepProgress.value?.label || ''"
          />

          <!-- Track A 完成后的只读预览 -->
          <SlotPreview
            v-else-if="session.stage.value === 'done' && session.lastDoneMode.value === 'bsadf' && session.beatSlots.value.length > 0"
            :slots="session.beatSlots.value"
          />

          <!-- 空态 -->
          <div v-else class="beats-empty">
            <div class="empty-icon"><Icon name="bolt" :size="40" /></div>
            <p>本章尚未用 BS-ADF 引擎生成。</p>
            <p class="hint">在「规划」标签选择引擎 BS-ADF 与轨道 A/B 后生成。</p>
          </div>

          <!-- 降级段占位符列表（Phase 4d：独立于上方状态分支，有降级 beat 即显示） -->
          <section
            v-if="session.degradedBeats.value.length > 0"
            class="degraded-section"
          >
            <div class="section-label">降级段（{{ session.degradedBeats.value.length }}）</div>
            <DegradedBeatPlaceholder
              v-for="db in session.degradedBeats.value"
              :key="db.beat_id"
              :degraded="db"
              :slot="getSlotForDegraded(db.beat_id)"
              @rerender="handleRerenderBeat"
              @skip="handleSkipBeat(db.beat_id)"
            />
            <p class="hint">重新渲染调单卡重试；跳过则保留占位继续看其他段。</p>
          </section>
        </template>
      </div>

      <!-- ====== Canon tab：本章涉及的 Canon 节点 ====== -->
      <div v-else-if="activeTab === 'canon'" class="panel canon-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 本章 Precondition（来自 ADF） -->
          <section v-if="session.adfPreconditions.value.length" class="canon-section">
            <div class="section-label">本章铺垫要点</div>
            <div v-for="pc in session.adfPreconditions.value" :key="pc.id" class="canon-node-item">
              <span class="node-type" :class="`vis-${pc.landed ? 'public' : 'private'}`">{{ pc.landed ? '✓' : '○' }}</span>
              <div class="node-content">
                <div class="node-label">{{ pc.description }}</div>
                <div v-if="pc.must_use_terms?.length" class="node-terms">
                  关键词：{{ pc.must_use_terms.join('、') }}
                </div>
              </div>
            </div>
          </section>

          <!-- 情绪曲线（来自 ADF） -->
          <section v-if="session.adfEmotionCurve.value.length" class="canon-section">
            <div class="section-label">情绪走向</div>
            <div class="emotion-mini">
              <div
                v-for="(s, i) in session.adfEmotionCurve.value"
                :key="i"
                class="emotion-mini-point"
                :style="{
                  background: `hsl(${220 - s.energy * 22}, 70%, 55%)`,
                  height: `${22 + (s.energy || 0) * 3}px`
                }"
              >
                <span class="emotion-mini-label">{{ s.register }}</span>
                <span class="emotion-mini-energy">{{ s.energy }}</span>
              </div>
            </div>
          </section>

          <!-- 跳转 Canon 全图 -->
          <section class="canon-section">
            <button class="btn-refinery" @click="handleEditCanon">
              <Icon name="link" :size="14" />
              <span>前往 Canon 脑图</span>
            </button>
            <p class="hint">编辑作者脑中世界（private 设定 / 伏笔 / 关系图谱）</p>
          </section>

          <!-- 出场角色速查（原速查 tab 内容） -->
          <section class="canon-section">
            <div class="section-label">出场角色（{{ chapterCharacters.length }}）</div>
            <div v-if="chapterCharacters.length === 0" class="empty-inline">
              本章暂未关联角色。
            </div>
            <div v-else class="char-list">
              <div v-for="c in chapterCharacters" :key="c.id" class="char-item">
                <span class="char-name">{{ c.name }}</span>
                <span v-if="c.dynamic_state" class="char-state">{{ c.dynamic_state.slice(0, 60) }}</span>
              </div>
            </div>
          </section>
        </template>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  width: 100%;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-color);
  height: 100%;
  overflow: hidden;
}

/* tab 头 */
.tab-bar {
  display: flex;
  align-items: stretch;
  gap: 0.125rem;
  padding: 0.375rem 0.375rem 0;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.tab-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.1875rem;
  padding: 0.4375rem 0.25rem;
  background: transparent;
  border: none;
  border-radius: 0.375rem 0.375rem 0 0;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.tab-btn.active {
  color: var(--accent-500);
  background: var(--bg-secondary);
  box-shadow: inset 0 -2px 0 var(--accent-500);
}

.tab-label {
  font-size: 0.6875rem;
  font-weight: 500;
}

/* tab 内容 */
.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.875rem;
}

/* 内容区滚动条（与 PanelContainer 同款细滚动条） */
.tab-content::-webkit-scrollbar {
  width: 6px;
}
.tab-content::-webkit-scrollbar-track {
  background: transparent;
}
.tab-content::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 3px;
}
.tab-content::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

.panel {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
}
/* 规划 tab 撑满高度，大纲区可伸缩填满剩余空间 */
.plan-panel {
  height: 100%;
}

.empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8125rem;
}

/* 本章 tab */
.card-strip {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.625rem 0.75rem;
  /* 撑满规划 tab 剩余空间，让大纲 textarea 自动伸展 */
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.strip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.25rem;
}

.strip-num {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.strip-title-input {
  width: 100%;
  flex-shrink: 0;
  font-family: var(--font-heading);
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 0.25rem;
  padding: 0.1875rem 0.375rem;
  margin: 0;
}
.strip-title-input:hover {
  border-color: var(--border-color);
}
.strip-title-input:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
}

.strip-outline-input {
  width: 100%;
  flex: 1;
  min-height: 60px;
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.6;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 0.25rem;
  padding: 0.375rem;
  margin-top: 0.375rem;
  font-family: inherit;
}
.strip-outline-input:hover {
  border-color: var(--border-color);
}
.strip-outline-input:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
}

.section-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin-bottom: 0.375rem;
}

/* 小节标题前的强调条，提升信息层级 */
.section-label::before {
  content: '';
  width: 3px;
  height: 0.625rem;
  border-radius: 2px;
  background: var(--accent-500);
  opacity: 0.55;
  flex-shrink: 0;
}

.generate-section,
.stats-section,
.context-section {
  padding: 0.5rem 0;
  flex-shrink: 0;
}

/* V5 引擎切换（ADF / BS-ADF） */
.engine-toggle {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin: 0.5rem 0;
}
.engine-options {
  display: flex;
  gap: 0.5rem;
}
.engine-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.125rem;
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  background: var(--bg-canvas);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.engine-btn:hover {
  border-color: rgba(124, 106, 173, 0.45);
}
.engine-btn.active {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.12);
}
.engine-name {
  font-size: 0.8125rem;
  font-weight: 600;
}
.engine-desc {
  font-size: 0.6875rem;
  color: var(--text-muted);
}

/* 字数指定 */
.word-count-input {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.5rem 0;
}
.wc-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  white-space: nowrap;
}
.wc-field {
  width: 5rem;
  padding: 0.2rem 0.4rem;
  font-size: 0.8rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  background: var(--bg-canvas);
  color: var(--text-primary);
  text-align: center;
}
.wc-field:focus {
  outline: none;
  border-color: var(--accent-500);
}
.wc-hint {
  font-size: 0.68rem;
  color: var(--text-muted);
  font-style: italic;
}

.btn-generate {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  justify-content: center;
  padding: 0.5625rem;
  margin-top: 0.5rem;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.5rem;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(124, 106, 173, 0.25);
  transition: all 0.15s ease;
}

.btn-generate:hover {
  background: var(--accent-600);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(124, 106, 173, 0.35);
}

.btn-generate:active {
  transform: translateY(0);
  box-shadow: 0 1px 4px rgba(124, 106, 173, 0.25);
}

.refinery-trigger-section {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px dashed var(--border-color);
}

.btn-refinery {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  justify-content: center;
  padding: 0.5rem;
  background: var(--bg-secondary);
  color: var(--accent-500);
  border: 1px solid var(--accent-500);
  border-radius: 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-refinery:hover {
  background: var(--accent-500);
  color: white;
}

.btn-refinery.secondary {
  margin-top: 0.5rem;
  color: var(--text-secondary);
  border-color: var(--border-color);
  background: var(--bg-secondary);
}
.btn-refinery.secondary:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
  border-color: var(--accent-500);
}
.btn-refinery:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.reader-feedback-card {
  margin-top: 0.625rem;
  padding: 0.625rem;
  /* 半透明琥珀底：浅色/深色主题下均可读 */
  background: rgba(202, 138, 4, 0.1);
  border-left: 3px solid #ca8a04;
  border-radius: 0.375rem;
}
.rf-header {
  font-size: 0.6875rem;
  color: #d97706;
  margin-bottom: 0.375rem;
  font-weight: 600;
}
.rf-text {
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-primary);
  margin: 0;
  white-space: pre-wrap;
}

.hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0.375rem 0 0;
}

.stats-section {
  display: flex;
  gap: 0.75rem;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.5rem;
}

.stat-num {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1;
}

.stat-label {
  font-size: 0.625rem;
  color: var(--text-muted);
  margin-top: 0.125rem;
}

.empty .empty-icon {
  margin: 0 auto 0.75rem;
  opacity: 0.6;
}

/* 润色诊断过渡态：避免点击后 tab 空白"没反应"观感 */
.refine-loading {
  text-align: center;
  padding: 1.5rem 1rem;
  color: var(--text-dim, #888);
}
.refine-loading .empty-icon {
  margin: 0 auto 0.75rem;
  opacity: 0.7;
}
.refine-loading .empty-icon.spinning {
  animation: refine-spin 1.4s ease-in-out infinite;
}
.refine-loading .muted {
  font-size: 0.6875rem;
  margin-top: 0.375rem;
  opacity: 0.8;
}
@keyframes refine-spin {
  0% { transform: scale(1) rotate(0deg); opacity: 0.7; }
  50% { transform: scale(1.15) rotate(180deg); opacity: 1; }
  100% { transform: scale(1) rotate(360deg); opacity: 0.7; }
}

.empty .muted {
  font-size: 0.6875rem;
  margin-top: 0.375rem;
  opacity: 0.8;
}

/* V5 节拍 tab 空态 */
.beats-empty {
  padding: 2.5rem 1rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8125rem;
  line-height: 1.7;
}
.beats-empty .empty-icon {
  margin: 0 auto 0.75rem;
  opacity: 0.6;
}
.beats-empty .hint {
  margin-top: 0.5rem;
}

/* V5 节拍 tab：降级段占位符列表（Phase 4d） */
.degraded-section {
  margin-top: 0.875rem;
  padding-top: 0.75rem;
  border-top: 1px dashed var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.degraded-section .hint {
  font-size: 0.6875rem;
}

/* 速查 tab */
.char-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.char-item {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  padding: 0.4375rem 0.5rem;
}

.char-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  display: block;
}

.char-state {
  font-size: 0.6875rem;
  color: var(--text-muted);
  display: block;
  margin-top: 0.125rem;
}

.empty-inline {
  font-size: 0.6875rem;
  color: var(--text-muted);
  padding: 0.5rem;
  background: var(--bg-canvas);
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  line-height: 1.5;
}

/* 场景设定入口提示（规划 tab 内引导跳转） */
.setting-entry-hint {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0.625rem;
  font-size: 0.72rem;
  color: var(--text-secondary);
  background: rgba(124, 106, 173, 0.06);
  border: 1px dashed rgba(124, 106, 173, 0.35);
  border-radius: 0.5rem;
}
.link-btn {
  background: none;
  border: none;
  color: var(--accent-500);
  cursor: pointer;
  font-size: inherit;
  padding: 0;
  text-decoration: underline;
}
.link-btn:hover {
  opacity: 0.8;
}

/* ===== 反馈 tab：审校结论 ===== */
.audit-block {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.5rem 0.625rem;
  margin-bottom: 0.5rem;
}

.audit-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.75rem;
  padding: 0.125rem 0;
}

.audit-label {
  color: var(--text-muted);
  flex-shrink: 0;
}

.audit-value {
  color: var(--text-primary);
  font-weight: 500;
  text-align: right;
}

.audit-value.warn {
  color: #d97706;
  font-weight: 400;
}

.audit-value.verdict-pass { color: #16a34a; }
.audit-value.verdict-pass_with_fixes { color: #65a30d; }
.audit-value.verdict-needs_refinement,
.audit-value.verdict-needs_final_touch { color: #d97706; }
.audit-value.verdict-fail { color: #dc2626; }
.audit-value.verdict-unaudited { color: var(--text-muted); }

/* 反馈 tab：Precondition 落地 */
.precondition-item {
  display: flex;
  gap: 0.375rem;
  font-size: 0.75rem;
  padding: 0.375rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  background: var(--bg-canvas);
  margin-bottom: 0.375rem;
  color: var(--text-secondary);
}

.precondition-item.landed {
  color: var(--text-primary);
}

.pc-icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.precondition-item.landed .pc-icon {
  color: #16a34a;
}

.pc-text {
  line-height: 1.5;
}

/* ===== 润色 tab：润色记录 ===== */
.surgery-row {
  display: flex;
  gap: 0.375rem;
  font-size: 0.75rem;
  padding: 0.375rem 0.5rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  margin-bottom: 0.375rem;
}

.surgery-status {
  flex-shrink: 0;
  color: #16a34a;
}

.surgery-row.failed .surgery-status {
  color: #dc2626;
}

.surgery-diff {
  color: var(--text-secondary);
  line-height: 1.5;
}

.surgery-row.failed .surgery-diff {
  color: var(--text-muted);
}

.refine-history .btn-refinery {
  margin-top: 0.375rem;
}

/* ===== Canon tab ===== */
.canon-node-item {
  display: flex;
  gap: 0.5rem;
  padding: 0.5rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  margin-bottom: 0.375rem;
}

.node-type {
  flex-shrink: 0;
  font-size: 0.75rem;
}

.node-type.vis-public { color: #16a34a; }
.node-type.vis-private { color: var(--text-muted); }

.node-content {
  min-width: 0;
}

.node-label {
  font-size: 0.75rem;
  color: var(--text-primary);
  line-height: 1.5;
}

.node-terms {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin-top: 0.125rem;
}

/* Canon tab：情绪走向（高度随 energy 起伏形成曲线） */
.emotion-mini {
  display: flex;
  align-items: flex-end;
  gap: 0.25rem;
  padding: 0.5rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
}

.emotion-mini-point {
  flex: 1;
  min-width: 0;
  border-radius: 0.25rem;
  padding: 0.25rem 0.125rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 0.125rem;
  color: #fff;
  overflow: hidden;
}

.emotion-mini-label {
  font-size: 0.625rem;
  line-height: 1.2;
  text-align: center;
}

.emotion-mini-energy {
  font-size: 0.6875rem;
  font-weight: 600;
}

/* ===== 统一卡片语言：圆角、悬浮反馈、细节打磨 ===== */
.card-strip,
.stat,
.audit-block,
.precondition-item,
.surgery-row,
.canon-node-item,
.char-item,
.emotion-mini,
.reader-feedback-card {
  border-radius: 0.5rem;
}

.char-item,
.canon-node-item,
.precondition-item,
.surgery-row {
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.char-item:hover,
.canon-node-item:hover {
  border-color: rgba(124, 106, 173, 0.45);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.card-strip {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.stat {
  transition: border-color 0.15s ease;
}
.stat:hover {
  border-color: rgba(124, 106, 173, 0.4);
}

.stat-num {
  color: var(--accent-500);
}

/* 字数输入与章节标题/大纲输入的悬浮反馈 */
.wc-field {
  border-radius: 0.375rem;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.wc-field:hover {
  border-color: rgba(124, 106, 173, 0.45);
}
.wc-field:focus {
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.12);
}

.strip-title-input,
.strip-outline-input {
  transition: border-color 0.15s ease, background 0.15s ease;
}
.strip-title-input:hover,
.strip-outline-input:hover {
  background: var(--bg-primary);
}

/* 空状态更柔和 */
.empty {
  padding: 2.5rem 1rem;
  line-height: 1.7;
}
</style>
