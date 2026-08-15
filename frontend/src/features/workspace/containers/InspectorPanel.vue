<script setup lang="ts">
/**
 * 智能副驾（Inspector，V3.1 F2 骨架 + F3 接入生成流程，规格 §4.3）。
 *
 * 右栏六 tab：
 * - 规划：生成主控（定档、V5 引擎切换 ADF/BS-ADF、轨道 A/B、「生成本章」、V4.2 介入点 1 规划确认、生成进度）
 * - 设定：场景设定（角色/地点/资产）
 * - 润色：V4.1 Refinery（诊断问题清单 → 作者确认 → 手术 + 回读 + 抛光）
 * - 反馈：V4.3 读者反馈 + 审校结论（ADF 锚点审计 / Refinery 整体回读）+ Precondition 落地
 * - 节拍：V5 BS-ADF（分镜工作台：Track B 暂停编辑 + 剧情走向选择 / 渲染进度 / 定点重渲染 / 救援内联卡）
 * - Canon：本章 Precondition / 情绪曲线 / 出场角色速查，并跳转 Canon 脑图
 *
 * Ctrl+1~6 切 tab。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import ChapterBadges from '../presentation/ChapterBadges.vue'
import TierSelector from '../../../components/TierSelector.vue'
import RefineryIssuesPanel from '../../generation/presentation/RefineryIssuesPanel.vue'
import RefineryProgress from '../../generation/presentation/RefineryProgress.vue'
import StoryboardPanel from '../../generation/presentation/StoryboardPanel.vue'
import CurrentTaskBar from '../../generation/presentation/CurrentTaskBar.vue'
import BranchDecisionPanel from '../../generation/presentation/BranchDecisionPanel.vue'
import type { IssueDecision, RefineryIssue, BeatSlot } from '../../../services/api/domain'
import { refineryApi } from '../../../services/api/domain'
import GenerationStepper from '../../generation/presentation/GenerationStepper.vue'
import BeatSlotCardView from '../../generation/presentation/BeatSlotCardView.vue'
import FocusAssetsPanel from '../../generation/presentation/FocusAssetsPanel.vue'
import SceneSettingsPanel from '../presentation/SceneSettingsPanel.vue'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { countChapterWords } from '../../../shared/utils/htmlText'

type InspectorTab = 'plan' | 'setting' | 'refine' | 'feedback' | 'canon' | 'beats' | 'focus'

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
const { show: showConfirm } = useConfirmDialog()

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
  { key: 'focus', label: '聚焦', icon: 'users', ready: true },
]

const activeTab = ref<InspectorTab>('plan')

// 生成会话（V4.x：优先用外部传入的，否则自建）
const session = props.externalSession || useGenerationSession()
// P1 焦点条「重写本段」面板展开态：当前展开的 beat_id（null=收起）。
// P2/P3：正文直编/回退已接真实 session 调用（lock_with_text / back action）。
const rewritePanelBeatId = ref<string | null>(null)
/** 焦点条「重写本段」内联编辑草稿（深拷贝自 readyBeatCard，提交才生效） */
const rewriteDraft = ref<BeatSlot | null>(null)

/** 深拷贝分镜卡（编辑草稿隔离，不污染 session） */
function deepClone<T>(v: T): T {
  try {
    return structuredClone(v)
  } catch {
    return JSON.parse(JSON.stringify(v))
  }
}
const tierSelection = ref<'auto' | 'climax' | 'turn' | 'progress' | 'transition'>('auto')
// V3.5：字数指定（null = 自动按定档推导；用户填了就用用户的）
const targetWordCount = ref<number | null>(null)

// V5 BS-ADF：引擎固定 BS-ADF + 步进模式（enable_stepping=true），Track A/B 暂停编辑流程已下线。

// V4.3 介入点 3：读者反馈
const readerFeedback = ref('')
const loadingFeedback = ref(false)

// 生成完成后自动切到反馈 tab；精修诊断完成切到精修 tab
// V5：BS-ADF 渲染中（beat_rendering）切到节拍 tab 看进度；
//    beat_pending（Track B 暂停）也切到节拍 tab——分镜工作台已内联在该 tab
// NLE-ADF：beat_stepping（逐段推进）与 assembling（拼接）也切到节拍 tab
watch(
  () => session.stage.value,
  (newStage) => {
    if (['beat_rendering', 'beat_pending', 'beat_stepping', 'beat_branch_choosing', 'assembling'].includes(newStage)) {
      activeTab.value = 'beats'
    } else if (newStage === 'done') {
      // BS-ADF 完成后停在节拍 tab 看分镜卡；ADF/Refinery 完成切到反馈
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

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  // NLE-ADF 调试 hook：URL 含 ?autogen=1 时自动触发生成（绕过 IAB 点击限制）
  if (new URLSearchParams(window.location.hash.split('?')[1] || '').get('autogen') === '1') {
    setTimeout(() => {
      if (selectedChapterId.value && !session.generating.value) {
        console.log('[Inspector] autogen hook: 触发 startGenerate')
        startGenerate()
      }
    }, 2000)
  }
})
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))

const chapterCharacters = computed(() => {
  if (!selectedChapter.value) return []
  const ids = (selectedChapter.value as any).character_ids || []
  return characters.value.filter((c) => ids.includes(c.id))
})

// 字数口径：剥 HTML 标签后计字符（此前 .length 把 <p>/mark 标签计入，虚高）
const wordCount = computed(() => countChapterWords(selectedChapter.value?.content_text || ''))

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

async function startGenerate() {
  if (!selectedChapterId.value) {
    console.warn('[Inspector] startGenerate: 无选中章节')
    return
  }
  // 完成态再点 = 重新生成：新管线完成后会覆盖本章正文，先确认（此前无提示直接覆盖）
  if (session.stage.value === 'done' && (selectedChapter.value?.content_text || '').replace(/<[^>]*>/g, '').trim()) {
    const ok = await showConfirm({
      title: '重新生成本章',
      message: '重新生成完成后将用新正文覆盖本章现有内容。',
      warning: '建议在覆盖前确认当前正文已无需保留（生成过程可随时取消）。',
      confirmText: '重新生成',
    })
    if (!ok) return
  }
  console.log('[Inspector] startGenerate:', { tier: tierSelection.value, chapterId: selectedChapterId.value })
  // 引擎已固定 BS-ADF：用 BeatSlot 卡作为介入点，不再走 plan-suggestion 弹窗
  startBeatGenerate()
}

/** BS-ADF：启动步进生成（固定 enable_stepping=true）。Track 参数仅向后端兼容传递。 */
function startBeatGenerate() {
  if (!selectedChapterId.value) {
    console.warn('[Inspector] startBeatGenerate: 无选中章节')
    return
  }
  console.log('[Inspector] startBeatGenerate:', {
    tier: tierSelection.value,
    chapterId: selectedChapterId.value,
  })
  session.startBeat(selectedChapterId.value, tierSelection.value, {
    targetWordCount: targetWordCount.value,
    steppingEnabled: true,
    // NLE-ADF 2.0 作者模式：拍不自动渲染，画布写碎片微缝合 / 空行 Space 召唤代笔
    enableAuthoring: true,
    enableOutlineSelfCheck: true,
    enableMemoryIngestion: true,
  })
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

/** V5 BS-ADF：作者确认分镜卡编辑 + 剧情走向选择，恢复渲染（历史 Track B 入口；当前步进模式不再调用）。 */
function handleBeatConfirm(payload: { edited_slots: BeatSlot[]; branch_choices: Record<string, string>; skipped: boolean }) {
  if (!selectedChapterId.value) return
  session.confirmBeats(selectedChapterId.value, payload.edited_slots, {
    branchChoices: payload.branch_choices,
    skipped: payload.skipped,
  })
}

/** V5 BS-ADF：作者取消（回滚到 idle） */
function handleBeatCancel() {
  session.cancelBeat()
}

/** NLE-ADF：接受本段并推进（作者改过正文时 session 自动改走 lock_with_text） */
function onAdvancePass() {
  if (!selectedChapterId.value || !session.readyBeatId.value) return
  session.acceptReadySegment(selectedChapterId.value)
}

/** NLE-ADF：跳过本段（确认后执行——段文本不进终稿，此前无确认误点即丢段） */
async function onAdvanceSkip() {
  if (!selectedChapterId.value || !session.readyBeatId.value) return
  const ok = await showConfirm({
    title: '跳过本段',
    message: '跳过后该段的已生成文本将被丢弃，不会进入终稿。',
    warning: '如误点可在下一段就绪后用「回到上一段」挽回。',
    confirmText: '跳过本段',
  })
  if (!ok) return
  session.advanceBeat(selectedChapterId.value, 'skip', { beatId: session.readyBeatId.value })
}

/** P1 焦点条：展开/收起当前段「重写本段」面板（切换 rewritePanelBeatId）。
 *  展开时从 readyBeatCard 深拷贝草稿——编辑在焦点条内联卡上完成，
 *  不污染 session（提交才走 handleRerenderBeat → 步进态 advanceBeat('edit')）。 */
function toggleRewritePanel() {
  const cur = session.readyBeatId.value
  if (!cur) return
  if (rewritePanelBeatId.value === cur) {
    rewritePanelBeatId.value = null
    rewriteDraft.value = null
    return
  }
  const card = session.readyBeatCard.value
  if (card) rewriteDraft.value = deepClone(card)
  rewritePanelBeatId.value = cur
}

/** 段推进/回退/重渲后自动收起焦点条编辑面板（草稿只对当时的就绪段有效） */
watch(() => session.readyBeatId.value, () => {
  if (rewritePanelBeatId.value) {
    rewritePanelBeatId.value = null
    rewriteDraft.value = null
  }
})

/** P1 焦点条：当前段「重写本段」面板是否展开 */
const rewritePanelOpen = computed(() =>
  !!rewritePanelBeatId.value && rewritePanelBeatId.value === session.readyBeatId.value,
)

/** P3：是否可回退（首段无快照时禁用；按 lockedBeatIds 数量推断已推进段数） */
const canBack = computed(() => {
  // 当前段是第 0 段时不可回退（无上一段）
  const slot = session.readyBeatCard.value
  return !!slot && slot.segment_index > 0
})

/** P3 焦点条：「回到上一段」——back action，后端弹快照栈恢复，循环重渲该段 */
function onBackBeat() {
  if (!selectedChapterId.value || !session.readyBeatId.value) return
  rewritePanelBeatId.value = null
  session.advanceBeat(selectedChapterId.value, 'back', {
    beatId: session.readyBeatId.value,
  })
}

/** P1 焦点条：「重写本段」提交——把焦点条内联编辑后的整卡重渲。
 *  handleRerenderBeat 已正确处理步进分支：就绪段（readyBeatId 匹配）走
 *  advanceBeat('edit')（/rerender-beat 与 SteppingRun 脱节，结果不进步进循环）；
 *  其余态走 /rerender-beat。 */
function submitRewriteFromDraft() {
  const slot = rewriteDraft.value
  if (!slot || !session.readyBeatId.value) return
  rewritePanelBeatId.value = null
  rewriteDraft.value = null
  void handleRerenderBeat(slot)
}

/**
 * V5 BS-ADF：降级/救援单卡恢复。
 * - rerender：拿编辑后的整卡调 session.rerenderBeat（/rerender-beat 携带 edited_slot）。
 *   卡来源：session.beatSlots（confirm 后不再清空，始终持卡）。
 * - NLE-ADF 步进态特例：当前待裁决段的「微调后重渲」必须走 advanceBeat('edit')
 *   ——/rerender-beat 与 SteppingRun 完全脱节，渲染结果不进步进循环、不进正文
 *   （此前步进态点「定点渲染本段」等于白点的根因）。
 * - skip-degraded：直接从 degradedBeats 移除该 beat（保留正文中的占位，作者手动放弃）。
 * - dismiss-rescue：从 rescueNeeded 移除该条（作者确认不救）。
 */
async function handleRerenderBeat(slot: BeatSlot) {
  if (!selectedChapterId.value) return
  if (
    session.stage.value === 'beat_stepping' &&
    session.readyBeatId.value === slot.beat_id
  ) {
    session.advanceBeat(selectedChapterId.value, 'edit', { beatId: slot.beat_id, editedSlot: slot })
    return
  }
  await session.rerenderBeat(selectedChapterId.value, slot.beat_id, slot)
}

function handleSkipBeat(beatId: string) {
  session.degradedBeats.value = session.degradedBeats.value.filter(d => d.beat_id !== beatId)
  session.persist()  // 忽略降级需持久化（刷新后不再复活）
}

function handleDismissRescue(beatId: string) {
  session.rescueNeeded.value = session.rescueNeeded.value.filter(r => r.beat_id !== beatId)
  session.persist()  // 忽略救援标记需持久化
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

function handleDismissInflight(idx: number) {
  session.inflightEvents.value.splice(idx, 1)
}

// collapse 逻辑已移除（不再收起副驾）

// 注：原 generate/generated 两个 emit 已删除——WorkspaceView 从未监听，
// 其 watch(session.stage) 已独立覆盖完成检测（写章节 + 弹窗 + 系统通知）。
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
            @dismiss-inflight="handleDismissInflight"
            @retry="session.retry"
          />

          <!-- 生成主控（未生成 / 完成时显示） -->
          <section v-if="!session.generating.value" class="generate-section">
            <div class="section-label">篇幅</div>
            <TierSelector v-model="tierSelection" />

            <!-- 引擎固定 BS-ADF + 步进模式（Track 选择与 Track A 通道已随
                 TrackSelector 一并删除） -->

            <div class="word-count-input">
              <label class="wc-label">目标字数</label>
              <input
                type="number"
                class="wc-field"
                :value="targetWordCount ?? ''"
                placeholder="自动"
                min="500"
                max="15000"
                step="100"
                @input="(e) => {
                  const v = parseInt((e.target as HTMLInputElement).value)
                  // 与后端 GenerateBsadfRequest 的 le=15000 对齐（超出会 422）
                  targetWordCount = (isNaN(v) || v < 500) ? null : Math.min(v, 15000)
                }"
              />
              <span class="wc-hint">{{ targetWordCount ? '已指定' : '按定档自动' }}</span>
            </div>
            <button class="btn-generate" :disabled="session.generating.value" @click="startGenerate">
              <Icon name="sparkles" :size="15" />
              <span>{{ session.stage.value === 'done' ? '重新生成' : '生成本章' }}</span>
            </button>
            <p class="hint">
              步进模式：AI 先为每一段建分镜卡，再逐段渲染；每段就绪后你按 Space 推进，也可回退或改写。
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

          <!-- ====== NLE-ADF 3.0 自适应写作：完稿 + 审计 + 沉淀结果 ====== -->
          <template v-if="session.adaptiveMode?.value && session.authorLane?.value === 'composing'">
            <!-- 意图反推（后台规划的淡建议；此前后端算出的 intent_source/arc 无任何渲染点） -->
            <section v-if="session.planSuggestions?.value" class="adaptive-settle">
              <div class="section-label">意图反推</div>
              <div class="settle-block">
                <div class="settle-item">
                  <span class="muted">{{ session.planSuggestions.value.source === 'author' ? '来自作者意图' : 'AI 推测' }}</span>
                  <template v-if="session.planSuggestions.value.arc"> · 走向建议：{{ session.planSuggestions.value.arc }}</template>
                </div>
              </div>
            </section>

            <!-- 沉淀抽取结果（涌现实体 + 冲突；作者主权：冲突不自动改） -->
            <section v-if="session.settleResult?.value?.emergent_facts || session.settleResult?.value?.conflicts?.length" class="adaptive-settle">
              <div class="section-label">沉淀抽取</div>
              <!-- 涌现实体 -->
              <div v-if="session.settleResult.value.emergent_facts?.new_entities?.length" class="settle-block">
                <div class="settle-block-label">涌现实体</div>
                <div
                  v-for="(ent, i) in session.settleResult.value.emergent_facts.new_entities.slice(0, 5)"
                  :key="'ent' + i"
                  class="settle-item"
                >{{ ent.name }}<span v-if="ent.description" class="muted"> · {{ ent.description }}</span></div>
              </div>
              <!-- 冲突（设定矛盾——浮给作者确认，不自动改） -->
              <div v-if="session.settleResult.value.conflicts?.length" class="settle-block settle-block--warn">
                <div class="settle-block-label">⚠️ 设定冲突（待你确认）</div>
                <div
                  v-for="(c, i) in session.settleResult.value.conflicts.slice(0, 5)"
                  :key="'conf' + i"
                  class="settle-item settle-item--conflict"
                >
                  <span class="conflict-entity">{{ c.entity }}</span>
                  <span class="muted">已有：{{ c.existing }}</span>
                  <span class="muted">正文：{{ c.new }}</span>
                </div>
              </div>
            </section>

            <!-- 完稿审计报告 -->
            <section v-if="session.finishReport?.value?.report" class="adaptive-report">
              <div class="section-label">完稿审计</div>
              <!-- 残句 -->
              <div v-if="session.finishReport.value.report.sentence_defects?.length" class="report-block report-block--warn">
                <div class="report-block-label">残句（{{ session.finishReport.value.report.sentence_defects.length }}）</div>
                <div
                  v-for="(d, i) in session.finishReport.value.report.sentence_defects.slice(0, 5)"
                  :key="'sd' + i"
                  class="report-item"
                >{{ typeof d === 'string' ? d : (d.text || d.fragment || JSON.stringify(d)) }}</div>
              </div>
              <!-- 必达覆盖率 -->
              <div v-if="session.finishReport.value.report.coverage?.checked" class="report-block">
                <div class="report-block-label">
                  必达覆盖 {{ session.finishReport.value.report.coverage.hit_count }}/{{ session.finishReport.value.report.coverage.hit_count + session.finishReport.value.report.coverage.miss_count }}
                </div>
                <div v-if="session.finishReport.value.report.coverage.misses?.length" class="report-item report-item--miss">
                  未达：{{ session.finishReport.value.report.coverage.misses.join('；') }}
                </div>
              </div>
              <!-- Canon 泄露 -->
              <div v-if="session.finishReport.value.report.canon_check?.private_breaches?.length" class="report-block report-block--warn">
                <div class="report-block-label">⚠️ Canon 泄露</div>
                <div
                  v-for="(b, i) in session.finishReport.value.report.canon_check.private_breaches"
                  :key="'cb' + i"
                  class="report-item"
                >{{ b }}</div>
              </div>
              <!-- LLM 审阅 -->
              <div v-if="session.finishReport.value.report.critique?.issues?.length" class="report-block">
                <div class="report-block-label">编辑审阅（{{ session.finishReport.value.report.critique.verdict === 'pass' ? '通过' : '需修改' }}）</div>
                <div
                  v-for="(iss, i) in session.finishReport.value.report.critique.issues.slice(0, 5)"
                  :key="'iss' + i"
                  class="report-item"
                  :class="{ 'report-item--warn': iss.severity === 'warning' }"
                >
                  <span class="issue-cat">{{ iss.category }}</span>
                  {{ iss.detail }}
                </div>
              </div>
              <!-- 记忆倒灌：本章已入向量记忆（供后续章节前情召回） -->
              <div v-if="session.finishReport.value.report.memory_indexed" class="report-block">
                <div class="report-item">记忆索引 +{{ session.finishReport.value.report.memory_indexed }} 段（后续章节可呼应本章细节）</div>
              </div>
            </section>

            <!-- 完稿按钮 -->
            <section class="adaptive-finish">
              <button
                class="btn-finish"
                :disabled="session.aiLane?.value === 'analyzing'"
                @click="session.triggerAdaptiveFinish()"
              >
                <Icon :name="session.aiLane?.value === 'analyzing' ? 'loader' : 'check-circle'" :size="14" />
                <span>{{ session.aiLane?.value === 'analyzing' ? '审计中…' : '完稿审计' }}</span>
              </button>
              <p class="hint">触发全章审计：残句 / 必达覆盖 / Canon 泄露 / 编辑审阅</p>
            </section>
          </template>
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

      <!-- ====== 节拍 tab：BS-ADF 分镜工作台 + 渲染进度 ====== -->
      <div v-else-if="activeTab === 'beats'" class="panel beats-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 步进岔路门顶部决策区：走向选择/大纲缺口补充的唯一交互入口（独占焦点位，
               岔路态 currentTask 为 idle、焦点条不渲染，两者互斥同槽）。
               接管态下分镜卡列表隐藏，卡上下文（核心转折/必现画面）已内嵌面板。 -->
          <BranchDecisionPanel
            v-if="session.stage.value === 'beat_branch_choosing' && session.branchChoicePending.value"
            :pending="session.branchChoicePending.value"
            :seg-total="session.beatSlots.value.length"
            @submit="session.submitBranchChoice"
            @cancel="session.cancel"
          />

          <!-- P1「当前任务」焦点条：渲染阶段唯一焦点。
               把原散落的 branch-choice-bar / stepping-bar / 卡级动作引导收敛到此。
               task 由 session.currentTask 派生（纯只读）；动作 emit 回本组件调 session。 -->
          <CurrentTaskBar
            :task="session.currentTask.value"
            :busy="session.generating.value"
            :rewrite-panel-open="rewritePanelOpen"
            :author-dirty="session.readySegmentDirty.value"
            :can-back="canBack"
            @accept="onAdvancePass"
            @open-rewrite="toggleRewritePanel"
            @revert-edit="session.revertReadySegment"
            @back="onBackBeat"
            @skip="onAdvanceSkip"
            @cancel="session.cancel"
          >
            <!-- ② 重写本段：内联卡编辑（草稿隔离，提交才生效）。
                 步进态下卡级「重写本段」被隐藏（StoryboardPanel 注释：归焦点条②），
                 这里补上真正可用的编辑入口。 -->
            <template #rewrite>
              <div v-if="rewriteDraft" class="rewrite-card-panel">
                <div class="rw-head">
                  <span class="rw-label">🎬 改这张分镜卡后重渲染本段</span>
                  <span class="rw-tip">AI 按新卡重写当前段；改完点「重生成本段」。</span>
                </div>
                <BeatSlotCardView :slot="rewriteDraft" />
                <div class="rw-actions">
                  <button class="rw-btn ghost" @click="toggleRewritePanel">收起</button>
                  <button class="rw-btn primary" @click="submitRewriteFromDraft">重生成本段</button>
                </div>
              </div>
            </template>
          </CurrentTaskBar>

          <!-- 渲染进度定位由状态轨（含岔路标记）+ 焦点面承担
               （原 BeatProgress 统计行已删除：步进逐段渲染下其批量口径失真，
               且与 CurrentTaskBar / 底部 GenerationOverlay 三重重复）。 -->

          <!-- 分镜工作台：Track B 暂停态可编辑；其余态（含接管态）= 状态轨 + 点击单卡展开；
               救援/降级段内联高亮（路线 C）。
               接管式单焦点：岔路决策/段裁决时交互只在焦点面（BranchDecisionPanel /
               CurrentTaskBar），此处自然塌缩为一行状态轨供进度定位（非编辑入口）。 -->
          <StoryboardPanel
            v-if="session.beatSlots.value.length > 0"
            :slots="session.beatSlots.value"
            :decision-set="session.decisionSet.value"
            :rescue-needed="session.rescueNeeded.value"
            :degraded="session.degradedBeats.value"
            :render-progress="session.renderProgress.value"
            :climax-summary="session.adfAnchor.value?.climax_description || ''"
            :editable="session.stage.value === 'beat_pending'"
            :busy="session.generating.value"
            :rerendering-beat-id="session.rerenderingBeatId.value"
            :stepping-locked-ids="session.lockedBeatIds.value"
            :stepping-ready-id="session.readyBeatId.value"
            :stepping-ready-degraded="!!session.readyBeatDegraded.value"
            :stepping-rendering-id="session.renderingBeatId.value"
            :branch-choice-pending-beat-id="session.stage.value === 'beat_branch_choosing' ? session.branchChoicePending.value?.beat_id : null"
            @confirm="handleBeatConfirm"
            @cancel="handleBeatCancel"
            @rerender="handleRerenderBeat"
            @skip-degraded="handleSkipBeat"
            @dismiss-rescue="handleDismissRescue"
          />

          <!-- 岔路门决策已上移顶部 BranchDecisionPanel，步进推进引导在 CurrentTaskBar，
               原 branch-choice-bar / stepping-bar / 卡内选择块均已移除，避免多入口困惑 -->

          <!-- 空态 -->
          <div v-if="session.beatSlots.value.length === 0 && session.stage.value !== 'beat_rendering' && session.stage.value !== 'tier_classifying'" class="beats-empty">
            <div class="empty-icon"><Icon name="bolt" :size="40" /></div>
            <p>本章尚未用 BS-ADF 引擎生成。</p>
            <p class="hint">在「规划」标签点击「生成本章」开始创建。</p>
          </div>
        </template>
      </div>

      <!-- ====== 聚焦 tab：NLE-ADF 2.0 本章聚焦资产 + 涌现记录（记忆倒灌可视化） ====== -->
      <div v-else-if="activeTab === 'focus'" class="panel">
        <FocusAssetsPanel
          :session="session"
          :characters="characters"
          :linked-ids="selectedChapter?.character_ids || []"
        />
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

/* ====== NLE-ADF 3.0 自适应：完稿 / 审计 / 沉淀结果 ====== */
.adaptive-settle,
.adaptive-report,
.adaptive-finish {
  margin-top: 0.75rem;
}

.adaptive-settle .settle-block,
.adaptive-report .report-block {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
}

.settle-block--warn,
.report-block--warn {
  border-color: rgba(245, 158, 11, 0.4);
  background: rgba(245, 158, 11, 0.05);
}

.settle-block-label,
.report-block-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}

.settle-item,
.report-item {
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-primary);
  padding: 0.125rem 0;
}

.settle-item .muted,
.report-item .muted {
  color: var(--text-muted);
}

.settle-item--conflict {
  display: flex;
  flex-direction: column;
  padding: 0.25rem 0;
  border-bottom: 1px dashed var(--border-color);
}
.settle-item--conflict:last-child {
  border-bottom: none;
}
.conflict-entity {
  font-weight: 600;
  color: #f59e0b;
}

.report-item--miss {
  color: #f59e0b;
}
.report-item--warn {
  color: #ef4444;
}
.issue-cat {
  display: inline-block;
  font-size: 0.625rem;
  padding: 0 0.25rem;
  border-radius: 0.1875rem;
  background: var(--border-color);
  color: var(--text-muted);
  margin-right: 0.25rem;
}

.btn-finish {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: none;
  border-radius: 0.375rem;
  background: var(--accent, #6366f1);
  color: #fff;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s ease;
}
.btn-finish:hover:not(:disabled) {
  opacity: 0.9;
}
.btn-finish:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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

/* P2 焦点条「重写本段」内联卡面板 */
.rewrite-card-panel {
  margin-top: 0.75rem;
  padding: 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.rw-head {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}
.rw-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
}
.rw-tip {
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.5;
}
.rw-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.375rem;
}
.rw-btn {
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  border: 1px solid var(--border-color);
  background: var(--bg-canvas);
  color: var(--text-primary);
  border-radius: 0.25rem;
  cursor: pointer;
  transition: all 0.15s;
}
.rw-btn:hover:not(:disabled) { opacity: 0.85; }
.rw-btn.primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.rw-btn.primary:hover:not(:disabled) { background: var(--accent-600); }
.rw-btn.ghost {
  background: transparent;
  border-color: transparent;
  color: var(--text-secondary);
}
.rw-btn.ghost:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}
</style>
