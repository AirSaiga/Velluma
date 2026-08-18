<script setup lang="ts">
/**
 * 副驾抽屉（NLE-ADF 3.0「纸面优先」写作台重构）。
 *
 * 三 tab（Ctrl+1~3 切换）：
 * - 此刻：世界切片「此刻此地」+ 候选回流收件箱（WorldSceneSlice，与生成上下文同源）
 * - 章节：大纲编辑 / 意图反推 / 统计 / 出场角色速查 / Canon 脑图跳转
 * - 审校：完稿审计（按钮 + 报告）、沉淀抽取、润色（Refinery）、读者反馈、润色记录
 *
 * 旧 BS-ADF 步进工作台（节拍/聚焦/生成主控/Stepper）已随写作台重构移除；
 * 润色与读者反馈的门控从 stage==='done' 改为「本章有正文」——adaptive 模式 stage 恒 idle，
 * 旧门控使手写章节永远进不了润色/反馈（已知洞的修复）。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import ChapterBadges from '../presentation/ChapterBadges.vue'
import RefineryIssuesPanel from '../../generation/presentation/RefineryIssuesPanel.vue'
import RefineryProgress from '../../generation/presentation/RefineryProgress.vue'
import WorldSceneSlice from '../presentation/WorldSceneSlice.vue'
import SpinePanel from '../presentation/SpinePanel.vue'
import { useChapterSpine } from '../composables/useChapterSpine'
import type { IssueDecision, RefineryIssue } from '../../../services/api/domain'
import { refineryApi, styleApi } from '../../../services/api/domain'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'
import { countChapterWords } from '../../../shared/utils/htmlText'

type InspectorTab = 'now' | 'chapter' | 'review'

interface TabDef {
  key: InspectorTab
  label: string
  icon: string
}

const store = useAppStore()
// 章级谋篇（P1.4 M1：与 WorkspaceView 复合谋篇卡共享同一单例状态）
const chapterSpine = useChapterSpine()
const selectedChapter = store.selectedChapter
const characters = store.characters
const selectedChapterId = store.selectedChapterId

// session 从外部传入（由 WorkspaceView 创建并与画布辅助层共享）；独立使用时自建兜底
const props = withDefaults(defineProps<{
  externalSession?: ReturnType<typeof useGenerationSession> | null
}>(), {
  externalSession: null,
})
const session = props.externalSession || useGenerationSession()

const tabs: TabDef[] = [
  { key: 'now', label: '此刻', icon: 'map' },
  { key: 'chapter', label: '章节', icon: 'document' },
  { key: 'review', label: '审校', icon: 'check-circle' },
]

const activeTab = ref<InspectorTab>('now')

// 诊断完成（问题清单就绪）/ 完稿报告 / 沉淀结果到达时切到审校 tab
watch(
  () => session.stage.value,
  (newStage) => {
    if (newStage === 'refining' && session.refineryIssues.value.length > 0) {
      activeTab.value = 'review'
    }
  }
)
watch(() => session.finishReport?.value, (report) => {
  if (report) activeTab.value = 'review'
  fixStates.value = {}  // 新一轮审计 → 残句修复裁决态复位
})
watch(() => session.settleResult?.value, (result) => {
  if (result) activeTab.value = 'review'
})

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

// 字数口径：剥 HTML 标签后计字符（此前 .length 把 <p>/mark 标签计入，虚高）
const wordCount = computed(() => countChapterWords(selectedChapter.value?.content_text || ''))

/** 本章有正文：润色/读者反馈的启用门槛（取代旧 stage==='done' 门控） */
const chapterHasContent = computed(() => wordCount.value > 0)

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

/** 更新章节大纲，带简易防抖避免每次按键写库（标题编辑在纸面页面头） */
let outlineTimer: ReturnType<typeof setTimeout> | undefined
function updateOutline(value: string) {
  if (!selectedChapterId.value) return
  clearTimeout(outlineTimer)
  outlineTimer = setTimeout(() => {
    store.updateChapter(selectedChapterId.value!, { outline_text: value })
  }, 500)
}

/** 启动润色（诊断阶段）。门槛：本章有正文（手写章节亦可，不再要求走完生成管线）。 */
function handleStartRefinery() {
  if (!selectedChapterId.value || !chapterHasContent.value) return
  session.startRefinery(selectedChapterId.value, { mode: 'deep', enablePolish: true })
}

/** 作者确认问题清单后，执行手术+回读+抛光 */
function handleRefineryConfirm(payload: { run_id: string; decisions: IssueDecision[]; custom_issues: RefineryIssue[] }) {
  if (!selectedChapterId.value) return
  session.confirmRefinery(selectedChapterId.value, payload.decisions, payload.custom_issues)
}

/** 取消润色（清空 refinery 状态，stage 回 idle——adaptive 模式 stage 恒 idle 的约定不被打破） */
function handleRefineryCancel() {
  session.refineryIssues.value = []
  session.refineryRunId.value = null
  session.stage.value = 'idle'
}

/** 获取读者反馈（AI 扮演读者写叙述性感受）。门槛：本章有正文。 */
const readerFeedback = ref('')
const loadingFeedback = ref(false)
async function handleReaderFeedback() {
  if (!selectedChapterId.value || !chapterHasContent.value) return
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

/** 跳世界页真相账本（C1 Canon 融合；RefineryIssuesPanel 改设定 / 章节 tab 入口共用） */
const router = useRouter()
function handleEditCanon() {
  const bookId = store.currentBookId.value
  if (!bookId) return
  router.push({ name: 'world', params: { bookId }, query: { panel: 'canon' } })
}

// ===== 世界模型快照（P0-5：/adaptive/model 调试入口，展开即拉一次）=====
const worldModelOpen = ref(false)
const worldModelText = ref('')

async function toggleWorldModelDebug() {
  worldModelOpen.value = !worldModelOpen.value
  if (!worldModelOpen.value) return
  const chapterId = selectedChapterId.value
  if (!chapterId) return
  worldModelText.value = '读取中…'
  try {
    const snap = await adaptiveApi.model(chapterId)
    // 摘要视图：意图 + 事实条数 + 投影标题（原文太长，调试只看骨架）
    const intent = snap.intent || {}
    const facts = (snap.facts || []).slice(-5).map((f: any) => `· ${String(f.text || '').slice(0, 50)}`)
    const projections = (snap.projections || [])
      .filter((p: any) => !p.__dock__ && !p.__canon_watch__)
      .map((p: any) => {
        const beat = p.possible_beats?.[0]
        return `· ${String(beat?.event || '').slice(0, 50)}`
      })
      .slice(0, 3)
    worldModelText.value = [
      `意图：${intent.source === 'none' ? '（无）' : `${intent.source} · ${(intent.arc || '').slice(0, 40)}`}`,
      `事实：${snap.fact_count ?? 0} 条（最近 ${facts.length} 条）`,
      ...facts,
      `走向：${projections.length} 条`,
      ...projections,
      `字数（沉淀）：${snap.total_words ?? 0}`,
    ].join('\n')
  } catch (e: any) {
    worldModelText.value = `读取失败：${e.message}`
  }
}

// ===== 残句定点修复（P1.2 作者裁决式：修复句过目 → 采纳才替换正文）=====
interface SentenceFixState { loading?: boolean; fixed?: string; error?: string; reason?: string; adopted?: boolean }
const fixStates = ref<Record<number, SentenceFixState>>({})

async function handleFixSentence(i: number, d: any) {
  const chapterId = selectedChapterId.value
  const sentence = typeof d === 'string' ? d : d?.sentence
  if (!chapterId || !sentence) return
  fixStates.value = { ...fixStates.value, [i]: { loading: true } }
  dispatchCollabEvent('sentence_fix', { action: 'propose' })
  try {
    const r = await adaptiveApi.fixSentence(chapterId, {
      sentence,
      defect_type: d?.type || '',
      description: d?.description || '',
    })
    fixStates.value = {
      ...fixStates.value,
      [i]: r.fixed ? { fixed: r.fixed } : { reason: r.reason },
    }
  } catch (e: any) {
    fixStates.value = { ...fixStates.value, [i]: { error: e?.message || '修复失败' } }
  }
}

/** 在文档中定位原句并替换（逐 textblock 搜索；编辑器自身的 update-chapter 机制落库） */
function replaceSentenceInDoc(editor: any, original: string, fixed: string): boolean {
  let done = false
  editor.state.doc.descendants((node: any, pos: number) => {
    if (done || !node.isTextblock) return true
    const idx = node.textContent.indexOf(original)
    if (idx < 0) return true
    const from = pos + 1 + idx
    editor.chain().insertText(fixed, from, from + original.length).run()
    done = true
    return false
  })
  return done
}

function adoptFix(i: number, d: any) {
  const original = typeof d === 'string' ? d : d?.sentence
  const fixed = fixStates.value[i]?.fixed
  const editor = chapterEditorHandle.value
  if (!editor || !original || !fixed) return
  if (!replaceSentenceInDoc(editor, original, fixed)) {
    fixStates.value = { ...fixStates.value, [i]: { error: '未在正文中定位到该句（可能已改动）' } }
    return
  }
  fixStates.value = { ...fixStates.value, [i]: { fixed, adopted: true } }
  dispatchCollabEvent('sentence_fix', { action: 'adopt' })
}

function dismissFix(i: number) {
  fixStates.value = { ...fixStates.value, [i]: {} }
  dispatchCollabEvent('sentence_fix', { action: 'reject' })
}

// ===== 本章文风卡（S3：章级特例状态 + 跳文风页深链）=====
const chapterStyleOverride = ref<any>(null)
const chapterStyleLoading = ref(false)

watch(selectedChapterId, async (chapterId) => {
  chapterStyleOverride.value = null
  const bookId = store.currentBookId.value
  if (!chapterId || !bookId) return
  chapterStyleLoading.value = true
  try {
    chapterStyleOverride.value = await styleApi.get(bookId, chapterId).catch(() => null)
  } finally {
    chapterStyleLoading.value = false
  }
}, { immediate: true })

function handleEditChapterStyle() {
  const bookId = store.currentBookId.value
  if (!bookId || !selectedChapterId.value) return
  router.push({ name: 'style', params: { bookId }, query: { chapter: selectedChapterId.value } })
}

async function handleResetChapterStyle() {
  const bookId = store.currentBookId.value
  if (!bookId || !selectedChapterId.value || !chapterStyleOverride.value) return
  try {
    await styleApi.deleteChapterOverride(bookId, selectedChapterId.value)
    chapterStyleOverride.value = null
  } catch (e: any) {
    console.warn('恢复继承失败:', e)
  }
}
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
      <!-- ====== 此刻 tab：此刻此地世界切片 + 候选收件箱 ====== -->
      <div v-if="activeTab === 'now'" class="panel now-panel">
        <WorldSceneSlice :chapter-id="selectedChapterId" />
      </div>

      <!-- ====== 章节 tab：大纲 + 意图反推 + 统计 + 出场角色 ====== -->
      <div v-else-if="activeTab === 'chapter'" class="panel chapter-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 谋篇区（P1.4 M1：章级软脉络——方向先于情节，永远在最上） -->
          <SpinePanel
            :spine="chapterSpine.spine.value"
            :suggestions="chapterSpine.spineSuggestions.value"
            :suggesting="chapterSpine.spineSuggesting.value"
            @update-intent="chapterSpine.setIntent"
            @add-anchor="chapterSpine.addAnchor"
            @update-anchor="(id, patch) => chapterSpine.updateAnchor(id, patch)"
            @remove-anchor="chapterSpine.removeAnchor"
            @suggest="chapterSpine.suggest"
            @adopt="(part) => chapterSpine.adoptSuggestion(part)"
            @discard-suggestions="chapterSpine.discardSuggestions"
          />

          <!-- 章节卡（大纲编辑；标题编辑在纸面页面头） -->
          <section class="card-strip">
            <header class="strip-header">
              <span class="strip-num">第 {{ selectedChapter.chapter_number }} 章</span>
              <ChapterBadges :chapter="selectedChapter" />
            </header>
            <textarea
              class="strip-outline-input"
              :value="selectedChapter.outline_text"
              placeholder="一句话主旨 / 大纲（AI 辅助写作时会参考）"
              rows="6"
              @input="(e) => updateOutline((e.target as HTMLTextAreaElement).value)"
            ></textarea>
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

          <!-- 意图反推（心跳带回的后台规划淡建议） -->
          <section v-if="session.planSuggestions?.value" class="adaptive-settle">
            <div class="section-label">意图反推</div>
            <div class="settle-block">
              <div class="settle-item">
                <span class="muted">{{ session.planSuggestions.value.source === 'author' ? '来自作者意图' : 'AI 推测' }}</span>
                <template v-if="session.planSuggestions.value.arc"> · 走向建议：{{ session.planSuggestions.value.arc }}</template>
              </div>
            </div>
          </section>

          <!-- 出场角色速查 -->
          <section>
            <div class="section-label">出场角色（{{ chapterCharacters.length }}）</div>
            <div v-if="chapterCharacters.length === 0" class="empty-inline">
              本章暂未关联角色——在正文用 @ 提及即可关联。
            </div>
            <div v-else class="char-list">
              <div v-for="c in chapterCharacters" :key="c.id" class="char-item">
                <span class="char-name">{{ c.name }}</span>
                <span v-if="c.dynamic_state" class="char-state">{{ c.dynamic_state.slice(0, 60) }}</span>
              </div>
            </div>
          </section>

          <!-- 本章文风（S3：章级特例状态一眼可见） -->
          <section class="style-status-section">
            <div class="section-label">本章文风</div>
            <div class="style-status-row">
              <span v-if="chapterStyleLoading" class="muted">读取中…</span>
              <template v-else>
                <span v-if="chapterStyleOverride" class="style-override-badge">章级特例</span>
                <span v-else class="muted">继承书级文风</span>
                <button
                  v-if="chapterStyleOverride"
                  class="btn-mini-reset"
                  title="删除本章特例，恢复继承书级文风"
                  @click="handleResetChapterStyle"
                >恢复继承</button>
              </template>
            </div>
            <button class="btn-refinery" @click="handleEditChapterStyle">
              <Icon name="paint-brush" :size="14" />
              <span>{{ chapterStyleOverride ? '编辑本章文风特例' : '为本章设文风特例' }}</span>
            </button>
            <p class="hint">回忆章换个腔调？章级特例只影响这一章的生成，其余章节仍用书级文风。</p>
          </section>

          <!-- 跳世界页真相账本（C1：Canon 融入世界页） -->
          <section>
            <button class="btn-refinery" @click="handleEditCanon">
              <Icon name="truth" :size="14" />
              <span>在世界页查看真相</span>
            </button>
            <p class="hint">表（读者所见）与里（作者真相）的账本——秘密设定 / 揭示计划 / 因果图谱</p>
          </section>

          <!-- 世界模型快照（P0-5：/adaptive/model 的调试入口，默认折叠） -->
          <section>
            <button class="btn-refinery" @click="toggleWorldModelDebug">
              <Icon name="magnifying-glass" :size="14" />
              <span>{{ worldModelOpen ? '收起世界模型' : '世界模型（调试）' }}</span>
            </button>
            <pre v-if="worldModelOpen" class="world-model-debug">{{ worldModelText }}</pre>
          </section>
        </template>
      </div>

      <!-- ====== 审校 tab：完稿审计 + 沉淀 + 润色 + 读者反馈 ====== -->
      <div v-else-if="activeTab === 'review'" class="panel review-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 完稿审计 -->
          <section class="adaptive-finish">
            <div class="section-label">完稿审计</div>
            <button
              class="btn-finish"
              :disabled="session.aiLane?.value === 'analyzing' || !(session.adaptiveMode?.value && session.authorLane?.value === 'composing')"
              :title="session.adaptiveMode?.value && session.authorLane?.value === 'composing' ? '触发全章审计' : '在章节内写满 4 字激活 AI 辅助后可用'"
              @click="session.triggerAdaptiveFinish()"
            >
              <Icon :name="session.aiLane?.value === 'analyzing' ? 'loader' : 'check-circle'" :size="14" />
              <span>{{ session.aiLane?.value === 'analyzing' ? '审计中…' : '完稿审计' }}</span>
            </button>
            <p class="hint">触发全章审计：残句 / 必达覆盖 / Canon 泄露 / 编辑审阅，并重索引记忆。</p>
          </section>

          <!-- 完稿审计报告 -->
          <section v-if="session.finishReport?.value?.report" class="adaptive-report">
            <div class="section-label">审计报告</div>
            <!-- 残句（P1.2：每条可定点修复——修复句过目，采纳才落正文） -->
            <div v-if="session.finishReport.value.report.sentence_defects?.length" class="report-block report-block--warn">
              <div class="report-block-label">残句（{{ session.finishReport.value.report.sentence_defects.length }}）</div>
              <div
                v-for="(d, i) in session.finishReport.value.report.sentence_defects.slice(0, 5)"
                :key="'sd' + i"
                class="report-item report-item--fixable"
              >
                <template v-if="typeof d === 'string'">{{ d }}</template>
                <template v-else>
                  <div class="fix-sent">{{ d.sentence }}</div>
                  <div v-if="d.description" class="fix-desc">{{ d.description }}</div>
                </template>
                <!-- 修复流：修复中 → 失败原因 / 修复句+采纳·放弃 / 已采纳 -->
                <button v-if="!fixStates[i]" class="btn-mini-reset" title="AI 补全这句，过目后决定采不采纳" @click="handleFixSentence(i, d)">修复</button>
                <span v-else-if="fixStates[i].loading" class="fix-status">修复中…</span>
                <span v-else-if="fixStates[i].error" class="fix-status fix-status--err">{{ fixStates[i].error }}</span>
                <span v-else-if="fixStates[i].adopted" class="fix-status fix-status--ok">✓ 已采纳</span>
                <template v-else-if="fixStates[i].fixed">
                  <div class="fix-sent fix-sent--result">{{ fixStates[i].fixed }}</div>
                  <div class="fix-actions">
                    <button class="btn-mini-reset btn-mini-reset--primary" @click="adoptFix(i, d)">采纳</button>
                    <button class="btn-mini-reset" @click="dismissFix(i)">放弃</button>
                  </div>
                </template>
                <span v-else class="fix-status">未能修复（{{ fixStates[i].reason }}）</span>
              </div>
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
            <!-- 谋篇附注（P1.4 §3.5：仅提示不阻塞） -->
            <div v-if="session.finishReport.value.report.spine_note" class="report-block">
              <div class="report-block-label">谋篇</div>
              <div class="report-item">{{ session.finishReport.value.report.spine_note }}</div>
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

          <!-- 润色（Refinery：诊断 → 确认 → 手术 + 回读 + 抛光） -->
          <section class="refine-entry">
            <div class="section-label">润色</div>
            <!-- 无正文空态 -->
            <div v-if="!chapterHasContent" class="empty-inline">
              本章还没有正文。写一段之后，这里可以启动 AI 润色与读者反馈。
            </div>
            <!-- 诊断进行中（stage='auditing'）：过渡态，避免"空白没反应"观感 -->
            <div v-else-if="session.stage.value === 'auditing' && session.generating.value" class="refine-loading">
              <div class="empty-icon spinning"><Icon name="sparkles" :size="32" /></div>
              <p>正在通读全文找问题…</p>
              <p class="muted">检查 + 归类需要一点时间，请稍候。</p>
            </div>
            <!-- 可启动（有正文且不在润色流程中） -->
            <template v-else-if="session.stage.value !== 'refining'">
              <button
                v-if="!session.refineryRunId.value"
                class="btn-refinery"
                @click="handleStartRefinery"
              >
                <Icon name="sparkles" :size="14" />
                <span>启动润色（检查 + 修改）</span>
              </button>
              <p class="hint">
                AI 通读全文找问题 → 你确认 → 逐处修改 → 通读检查 → 定稿润色。
              </p>
            </template>
          </section>

          <!-- 润色问题清单（诊断完成、等作者确认） -->
          <RefineryIssuesPanel
            v-if="session.stage.value === 'refining' && session.refineryIssues.value.length > 0 && session.refineryRunId.value"
            :issues="session.refineryIssues.value"
            :run-id="session.refineryRunId.value"
            @confirm="handleRefineryConfirm"
            @cancel="handleRefineryCancel"
            @edit-canon="handleEditCanon"
          />

          <!-- 润色手术进度 -->
          <RefineryProgress
            v-if="session.stage.value === 'refining' && session.refineryRunId.value === null && (session.generating.value || session.refinerySurgeries.value.length > 0)"
            :surgeries="session.refinerySurgeries.value"
            :holistic-verdict="session.refineryHolisticVerdict.value"
            :stage-label="session.stepProgress.value?.label || ''"
            :stage="session.stage.value"
          />

          <!-- 润色完成后的手术历史 -->
          <section v-if="session.refinerySurgeries.value.length && session.stage.value !== 'refining' && session.stage.value !== 'auditing'" class="refine-history">
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

          <!-- 读者反馈 -->
          <section v-if="chapterHasContent" class="feedback-section">
            <div class="section-label">读者反馈</div>
            <button
              class="btn-refinery secondary"
              :disabled="loadingFeedback"
              title="AI 扮演读者写叙述性感受"
              @click="handleReaderFeedback"
            >
              <Icon name="chat" :size="14" />
              <span>{{ loadingFeedback ? '读者阅读中…' : '获取读者反馈' }}</span>
            </button>
            <div v-if="readerFeedback" class="reader-feedback-card">
              <div class="rf-header">📖 读者反馈</div>
              <p class="rf-text">{{ readerFeedback }}</p>
            </div>
            <p v-else class="hint">
              AI 扮演读者写叙述性感受（不是检查清单）。
            </p>
          </section>

          <!-- 审校结论（结构检查 / 润色回读；有数据才显示） -->
          <section v-if="session.adfAudit.value || session.refineryHolisticVerdict.value" class="audit-section">
            <div class="section-label">审校结论</div>
            <!-- 结构审计 -->
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
            <!-- 润色整体回读 -->
            <div v-if="session.refineryHolisticVerdict.value" class="audit-block">
              <div class="audit-row">
                <span class="audit-label">通读检查</span>
                <span class="audit-value" :class="`verdict-${session.refineryHolisticVerdict.value.verdict}`">
                  {{ session.refineryHolisticVerdict.value.verdict === 'pass' ? '✓ 通过' : '⚠ 需要再修' }}
                </span>
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

/* 内容区滚动条（细滚动条） */
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
/* 此刻 tab 的世界切片自带满高布局 */
.now-panel {
  height: 100%;
}
/* 章节 tab 撑满高度，大纲区可伸缩填满剩余空间 */
.chapter-panel {
  height: 100%;
}

.empty {
  padding: 2.5rem 1rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8125rem;
  line-height: 1.7;
}

/* 章节卡（大纲编辑，撑满章节 tab 剩余空间） */
.card-strip {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.625rem 0.75rem;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
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

.strip-outline-input {
  width: 100%;
  flex: 1;
  min-height: 72px;
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.6;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 0.25rem;
  padding: 0.375rem;
  margin-top: 0.375rem;
  font-family: inherit;
  resize: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.strip-outline-input:hover {
  border-color: var(--border-color);
  background: var(--bg-primary);
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

.stats-section {
  display: flex;
  gap: 0.75rem;
  flex-shrink: 0;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.5rem;
  transition: border-color 0.15s ease;
}
.stat:hover {
  border-color: rgba(124, 106, 173, 0.4);
}

.stat-num {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--accent-500);
  line-height: 1;
}

.stat-label {
  font-size: 0.625rem;
  color: var(--text-muted);
  margin-top: 0.125rem;
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

/* ===== 本章文风卡（S3）===== */
.style-status-section {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.style-status-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 1.5rem;
}

.style-override-badge {
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  color: #b45309;
  background: #fef3c7;
  border-radius: 0.25rem;
}

.btn-mini-reset {
  padding: 0.1875rem 0.5rem;
  font-size: 0.625rem;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}

.btn-mini-reset:hover {
  color: #dc2626;
  background: #fee2e2;
}

.style-status-section .btn-refinery {
  margin-top: 0.125rem;
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
  border-radius: 0.5rem;
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

/* 世界模型调试快照（P0-5）：等宽小字摘要视图 */
.world-model-debug {
  margin: 0.5rem 0 0;
  padding: 0.5rem 0.625rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.6875rem;
  line-height: 1.6;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 16rem;
  overflow-y: auto;
}

/* 残句定点修复（P1.2）：句子 + 描述 + 修复裁决流 */
.report-item--fixable {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.fix-sent {
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-primary);
}
.fix-sent--result {
  padding: 0.375rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--accent-400, #9685c2);
  border-radius: 6px;
}
.fix-desc {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.fix-status {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.fix-status--ok { color: var(--ok, #4a9); }
.fix-status--err { color: var(--danger, #c66); }
.fix-actions {
  display: flex;
  gap: 0.375rem;
}
.btn-mini-reset--primary {
  color: #fff;
  background: var(--accent-500, #7c6aad);
  border-color: var(--accent-500, #7c6aad);
}

/* ====== 完稿审计 / 沉淀抽取 ===== */
.adaptive-settle,
.adaptive-report,
.adaptive-finish {
  flex-shrink: 0;
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

/* 润色诊断过渡态：避免点击后"空白没反应"观感 */
.refine-loading {
  text-align: center;
  padding: 1.5rem 1rem;
  color: var(--text-secondary);
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

/* 出场角色速查 */
.char-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.char-item {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.4375rem 0.5rem;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.char-item:hover {
  border-color: rgba(124, 106, 173, 0.45);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
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

/* ===== 审校结论 ===== */
.audit-block {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
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

/* ===== 润色记录 ===== */
.surgery-row {
  display: flex;
  gap: 0.375rem;
  font-size: 0.75rem;
  padding: 0.375rem 0.5rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
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
</style>
