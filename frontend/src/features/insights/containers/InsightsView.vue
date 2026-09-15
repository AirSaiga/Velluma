<script setup lang="ts">
/**
 * 数据视图（V3.1 F5 实现，规格 §3 + §8）。
 *
 * 三个面板：
 * - 成本（按章/按阶段 token，costReportApi）
 * - 质量（最近章节的质量报告，qualityReportApi）
 * - 降级事件流（从成本报告的 degraded_count 与质量报告的 degraded 提取）
 *
 * 时间范围筛选：F5 简化为"最近 N 章"。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import { costReportApi, qualityReportApi, styleApi } from '../../../services/api/domain'
import { reviewApi } from '../../../services/api/domain/review.api'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import { usageApi } from '../../../services/api/domain/usage.api'
import type { BookUsage, ChapterUsage } from '../../../services/api/domain/usage.api'
import { buildTrendChart, formatCost, groupStagesByLane, stageBarPercent } from '../usageChart'
import PriceSettingsModal from '../presentation/PriceSettingsModal.vue'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import type { CostReport, QualityReport, FindingItem } from '../../../types'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const sortedChapters = store.sortedChapters

/** 协作埋点 kind → 中文标签（未收录的键原样显示，防新埋点漏映射） */
const COLLAB_KIND_LABELS: Record<string, string> = {
  card_burst: '走向卡弹出',
  cards_delivered: '走向卡送达',
  dock_delivered: '灵感零件送达',
  ghost_request: '请求幽灵续写',
  ghost_adopt: '采纳幽灵稿',
  ghost_discard: '蒸发幽灵稿',
  capsule_create: '记细纲胶囊',
  capsule_expand: '扩写细纲胶囊',
  quick_note: '世界速记',
  sentence_fix: '句子修复',
  context_card: '情境浮卡',
  slice_mode: '切片读者档切换',
  branch_resolved: '选定走向',
  ignition: 'AI 开头（点火）',
  ignition_dismiss: '放弃 AI 开头',
  settle: '沉淀',
  finish: '完稿体检',
  spine_intent_set: '定方向一句话',
  spine_anchor_add: '加关键情节',
  spine_anchor_drop: '划掉情节',
  spine_anchor_remove: '删情节',
  spine_suggest: '要 AI 建议',
  spine_suggest_adopt: '收下 AI 建议',
  spine_suggest_discard: '不用 AI 建议',
  batch_accept: '批量入账',
  // 学着闭嘴（2026-08-25）：幽灵蒸发理由反馈 + 感知带提醒收起
  ghost_discard_reason: '幽灵稿蒸发理由',
  hint_dismiss: '收起提醒',
}
function collabKindLabel(k: string): string {
  return COLLAB_KIND_LABELS[k] || k
}

const bookIdFromRoute = computed(() => (route.params.bookId as string) || null)
watch(
  bookIdFromRoute,
  (newBookId) => {
    if (newBookId && newBookId !== store.currentBookId.value) {
      store.selectBook(newBookId)
    }
  },
  { immediate: true }
)

const loading = ref(false)
const error = ref<string | null>(null)
type PanelKey = 'cost' | 'quality' | 'collab'
const activePanel = ref<PanelKey>('cost')

const costReports = ref<{ chapterId: string; chapterNumber: number; report: CostReport | null }[]>([])
const qualityReports = ref<{ chapterId: string; chapterNumber: number; report: QualityReport | null }[]>([])
const collabReports = ref<{ chapterId: string; chapterNumber: number; report: Awaited<ReturnType<typeof adaptiveApi.collabEventsSummary>> | null }[]>([])

// ===== B3 · 用量可见（generation_runs 聚合，独立于协作埋点数据源）=====
const chapterUsage = ref<ChapterUsage | null>(null)
const bookUsage = ref<BookUsage | null>(null)
/** 「最近一章」消耗对应的章节号（标签展示用） */
const usageChapterNumber = ref<number | null>(null)
/** 「最近一章」消耗对应的章节 id（清空台账按钮的作用对象） */
const usageChapterId = ref<string | null>(null)

async function loadAll() {
  const bid = bookIdFromRoute.value
  if (!bid) return
  loading.value = true
  error.value = null
  try {
    // 同步当前书的章节。切书竞态修复（2026-09-04 审计）：selectBook 同步改
    // currentBookId、章节列表异步加载——旧判据「currentBookId 不一致」在
    // loadAll 执行时恒 false，读到的是上一本书的章节（成本/质量/协作三面板
    // 按错误章号集合拉报告）。改为无条件补拉并 await（与 StyleView 按书取数
    // 同哲学；store.load 自身幂等）。
    if (bookIdFromRoute.value) {
      await store.loadCurrentBookData()
    }
    const chaps = sortedChapters.value.slice(-10) // 最近 10 章
    const latestChap = chaps.length ? chaps[chaps.length - 1] : null
    const [costs, qualities, collabs, chapUsage, bkUsage] = await Promise.all([
      Promise.all(
        chaps.map(async (c) => {
          try {
            const r = await costReportApi.get(c.id)
            return { chapterId: c.id, chapterNumber: c.chapter_number, report: r }
          } catch {
            return { chapterId: c.id, chapterNumber: c.chapter_number, report: null }
          }
        })
      ),
      Promise.all(
        chaps.map(async (c) => {
          try {
            const r = await qualityReportApi.get(c.id)
            return { chapterId: c.id, chapterNumber: c.chapter_number, report: r }
          } catch {
            return { chapterId: c.id, chapterNumber: c.chapter_number, report: null }
          }
        })
      ),
      Promise.all(
        chaps.map(async (c) => {
          try {
            const r = await adaptiveApi.collabEventsSummary(c.id)
            return { chapterId: c.id, chapterNumber: c.chapter_number, report: r }
          } catch {
            return { chapterId: c.id, chapterNumber: c.chapter_number, report: null }
          }
        })
      ),
      // B3：最近一章 + 本书消耗（零值结构也是有效响应；失败降级 null 由模板空态兜底）
      latestChap
        ? usageApi.getChapterUsage(latestChap.id).catch(() => null)
        : Promise.resolve(null),
      usageApi.getBookUsage(bookIdFromRoute.value).catch(() => null),
    ])
    // 过期守卫（2026-09-04 切书竞态修复）：await 期间已切书 → 本轮结果整体丢弃
    if (bookIdFromRoute.value !== bid) return
    costReports.value = costs
    qualityReports.value = qualities
    collabReports.value = collabs
    chapterUsage.value = chapUsage
    bookUsage.value = bkUsage
    usageChapterNumber.value = latestChap?.chapter_number ?? null
    usageChapterId.value = latestChap?.id ?? null
  } catch (e: any) {
    error.value = e.message
  } finally {
    if (bookIdFromRoute.value === bid) loading.value = false
  }
}

onMounted(loadAll)
watch(bookIdFromRoute, loadAll)

const totalTokens = computed(() =>
  costReports.value.reduce((sum, r) => sum + (r.report?.totals?.total_tokens || 0), 0)
)

const totalCost = computed(() =>
  costReports.value.reduce((sum, r) => sum + (r.report?.totals?.calls || 0), 0)
)


function backToLibrary() {
  router.push({ name: 'library' })
}

// ===== 协作采纳率聚合（P1.3 走向卡质量环：个人镜子——roadmap §2.3）=====
const collabTotals = computed(() => {
  const by: Record<string, number> = {}
  for (const cr of collabReports.value) {
    if (!cr.report) continue
    for (const [k, v] of Object.entries(cr.report.by_kind || {})) by[k] = (by[k] || 0) + v
  }
  return by
})
const collabRate = (num: string, den: string) => {
  const n = collabTotals.value[num] || 0
  const d = collabTotals.value[den] || 0
  return d > 0 ? Math.round((n / d) * 100) + '%' : '—'
}
const collabHasData = computed(() => collabReports.value.some((r) => r.report?.total))

// ===== B3 · 用量可见 computed（本书汇总 + 按日趋势几何）=====
const usageHasData = computed(() => (bookUsage.value?.totals?.calls || 0) > 0)
/** AI 消耗卡分组（真实调用流程：感知→续写→沉淀完稿→自动阅读；组内条形归一） */
const usageLaneGroups = computed(() =>
  groupStagesByLane(
    bookUsage.value?.by_stage || [],
    bookUsage.value?.by_lane || [],
    bookUsage.value?.totals?.total_tokens || 0,
  ),
)
const usageTrend = computed(() => buildTrendChart(bookUsage.value?.by_date || []))

/** 价目弹窗（成本核算 2026-09-11）：保存后刷新用量，金额立即上屏 */
const showPriceModal = ref(false)
const usageUnpriced = computed(() => bookUsage.value?.totals?.unpriced_tokens || 0)
function onPricesSaved() {
  loadAll()
}

// ===== 清空本章用量台账（测试用，2026-09-11；走全局 ConfirmDialog 确认）=====
const { show: showConfirm } = useConfirmDialog()
const clearingUsage = ref(false)
const chapterUsageEmpty = computed(() => (chapterUsage.value?.totals?.calls || 0) === 0)

async function resetLatestChapterUsage() {
  const chId = usageChapterId.value
  if (!chId || clearingUsage.value || chapterUsageEmpty.value) return
  const ok = await showConfirm({
    title: '清空本章用量',
    message: `确定要清空第 ${usageChapterNumber.value ?? '?'} 章的 AI 用量台账吗？本章的 token、调用与成本记录将归零，方便重新测试。`,
    warning: '正文与世界数据不受影响；记录删除后不可恢复',
    confirmText: '清空',
  })
  if (!ok) return
  clearingUsage.value = true
  try {
    const r = await usageApi.resetChapterUsage(chId)
    showToast(`已清空第 ${usageChapterNumber.value ?? '?'} 章 ${r.deleted} 条用量记录`, 'success')
    await loadAll()
  } catch (e: any) {
    showToast('清空失败：' + (e?.message || '未知错误'), 'error')
  } finally {
    clearingUsage.value = false
  }
}

// ===== 清空本书协作埋点（测试用，2026-09-11；数据源 data/collab_events.jsonl）=====
const clearingCollab = ref(false)

async function clearCollabData() {
  const bid = bookIdFromRoute.value
  if (!bid || clearingCollab.value) return
  const ok = await showConfirm({
    title: '清空协作数据',
    message: `确定要清空《${store.currentBook.value?.title || '本书'}》的全部协作埋点吗？采纳率与协作明细将归零，方便重新测试。`,
    warning: '「学着闭嘴」的提醒拒收史一并清零（静音集合重置）；正文与世界数据不受影响',
    confirmText: '清空',
  })
  if (!ok) return
  clearingCollab.value = true
  try {
    const r = await adaptiveApi.clearCollabEvents(bid)
    showToast(`已清空 ${r.deleted} 条协作记录`, 'success')
    await loadAll()
  } catch (e: any) {
    showToast('清空失败：' + (e?.message || '未知错误'), 'error')
  } finally {
    clearingCollab.value = false
  }
}

function formatTokens(n: number): string {
  if (n > 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

// 质量报告重跑（POST /quality-report/rerun，后端双层审计）
const { showToast } = useToast()

/** 抓虫回流（补全批，设计稿 §6.4）：从审计报告的陈词命中提取高频短语 → 文风收件箱候选。
 *  解析 ClichéAuditor 的「高频项：词×N、词×N」格式；候选过目才生效（红线）。 */
async function collectClicheCandidates(qr: { chapterId: string; chapterNumber: number; report: QualityReport | null }) {
  const bookId = bookIdFromRoute.value
  if (!bookId || !qr.report?.findings?.length) return
  const styleFindings = qr.report.findings.filter(
    (f: FindingItem) => f.category === 'style' && f.detail?.includes('高频项：'),
  )
  const phrases: string[] = []
  for (const f of styleFindings) {
    const m = f.detail.match(/高频项：(.+)$/)
    if (!m) continue
    for (const part of m[1].split('、')) {
      const word = part.replace(/×\d+$/, '').trim()
      if (word && word.length >= 2 && !phrases.includes(word)) phrases.push(word)
    }
  }
  if (phrases.length === 0) {
    showToast('这章的检查报告里没有可提取的陈词命中', 'info')
    return
  }
  try {
    for (const word of phrases.slice(0, 5)) {
      await styleApi.addInboxItem(
        bookId, 'negative_candidate',
        { word, source_text: `第${qr.chapterNumber}章检查命中` },
        'audit',
      )
    }
    styleApi.logStyleEvent(bookId, 'audit_collect')
    showToast(`已把 ${Math.min(phrases.length, 5)} 个陈词投进文风收件箱——去文风页过目`, 'success')
  } catch (e: any) {
    showToast('投递失败: ' + (e?.message || ''), 'error')
  }
}
const rerunningIds = ref<Set<string>>(new Set())

async function rerunQuality(chapterId: string) {
  if (rerunningIds.value.has(chapterId)) return
  rerunningIds.value.add(chapterId)
  try {
    const report = await reviewApi.rerunQualityReport(chapterId)
    const item = qualityReports.value.find((r) => r.chapterId === chapterId)
    if (item) {
      item.report = report
    } else {
      const chap = sortedChapters.value.find((c) => c.id === chapterId)
      qualityReports.value.push({ chapterId, chapterNumber: chap?.chapter_number ?? 0, report })
    }
    showToast('质量检查已完成', 'success')
  } catch (e: any) {
    showToast(`质量检查失败：${e?.message || '未知错误'}`, 'error')
  } finally {
    rerunningIds.value.delete(chapterId)
  }
}
</script>

<template>
  <div class="insights-view">
    <header class="insights-header">
      <div class="header-left">
        <button class="icon-btn icon-btn-instrument" @click="backToLibrary" title="返回书架">
          <Icon name="arrow-left" :size="16" />
        </button>
        <div>
          <h1 class="page-title">数据</h1>
          <p class="page-subtitle">{{ store.currentBook.value?.title || '' }} · 最近 {{ costReports.length }} 章</p>
        </div>
      </div>
      <button class="btn-secondary" @click="loadAll" :disabled="loading">
        <Icon name="arrow-path" :size="14" :class="{ spin: loading }" />
        <span>刷新</span>
      </button>
    </header>

    <!-- 汇总卡片 -->
    <section class="summary-cards">
      <div class="summary-card">
        <span class="summary-num">{{ formatTokens(totalTokens) }}</span>
        <span class="summary-label">累计用量</span>
      </div>
      <div class="summary-card">
        <span class="summary-num">{{ totalCost }}</span>
        <span class="summary-label">累计调用</span>
      </div>
    </section>

    <!-- 面板切换 -->
    <div class="panel-tabs">
        <button
        v-for="p in [
          { k: 'cost', l: '成本' },
          { k: 'quality', l: '质量' },
          { k: 'collab', l: '协作' },
        ]"
        :key="p.k"
        class="panel-tab"
        :class="{ active: activePanel === p.k }"
        @click="activePanel = p.k as PanelKey"
      >{{ p.l }}</button>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="error">{{ error }}</div>

    <!-- 成本面板 -->
    <section v-else-if="activePanel === 'cost'" class="data-panel">
      <div v-if="costReports.every((r) => !r.report)" class="empty">
        <p>暂无用量数据。生成章节后，AI 的消耗会在此汇总。</p>
      </div>
      <div v-else class="chapter-cost-list">
        <article v-for="cr in costReports.filter((r) => r.report)" :key="cr.chapterId" class="cost-item card-well">
          <header class="cost-header">
            <span class="cost-chapter">第 {{ cr.chapterNumber }} 章</span>
            <span class="cost-total tnum">{{ formatTokens(cr.report?.totals?.total_tokens || 0) }} token</span>
          </header>
          <div class="stage-bars">
            <div
              v-for="stage in cr.report?.stages || []"
              :key="stage.stage"
              class="stage-bar"
              :title="`${stage.stage}: ${stage.calls} 次, ${formatTokens((stage.prompt_tokens || 0) + (stage.completion_tokens || 0))} token`"
            >
              <span class="stage-name">{{ stage.stage.split('.').pop() }}</span>
              <span class="stage-calls">{{ stage.calls }}×</span>
            </div>
          </div>
        </article>
      </div>
    </section>

    <!-- 质量面板 -->
    <section v-else-if="activePanel === 'quality'" class="data-panel">
      <div v-if="qualityReports.length === 0" class="empty">
        <p>暂无章节数据。</p>
      </div>
      <div v-else class="chapter-quality-list">
        <article v-for="qr in qualityReports" :key="qr.chapterId" class="quality-item">
          <header class="quality-header">
            <span class="quality-chapter">第 {{ qr.chapterNumber }} 章</span>
            <div class="quality-actions">
              <span v-if="qr.report?.verdict" class="quality-verdict" :class="qr.report?.verdict">{{ qr.report?.verdict }}</span>
              <button
                class="rerun-btn btn-ghost btn-ghost--xs"
                :disabled="rerunningIds.has(qr.chapterId)"
                :title="qr.report ? '基于当前正文重新做一遍质量检查' : '本章尚无质量报告，点击做首次检查'"
                @click="rerunQuality(qr.chapterId)"
              >
                <Icon name="arrow-path" :size="12" :class="{ spin: rerunningIds.has(qr.chapterId) }" />
                <span>{{ rerunningIds.has(qr.chapterId) ? '检查中…' : qr.report ? '重新检查' : '立即检查' }}</span>
              </button>
            </div>
          </header>
          <template v-if="qr.report">
            <div v-if="qr.report?.metrics" class="quality-metrics">
              <div v-for="(v, k) in (qr.report.metrics as Record<string, any>)" :key="k" class="metric-pair">
                <span class="metric-key">{{ k }}</span>
                <span class="metric-val">{{ typeof v === 'number' ? v.toFixed(2) : v }}</span>
              </div>
            </div>
            <p v-if="qr.report?.findings?.length" class="findings-count">
              {{ qr.report.findings.length }} 条审校发现
            </p>
            <!-- 抓虫回流（补全批）：陈词命中 → 文风收件箱候选（过目才生效） -->
            <button
              v-if="qr.report?.findings?.some((f: FindingItem) => f.category === 'style' && f.detail?.includes('禁词/AI 腔命中'))"
              class="collect-btn"
              @click="collectClicheCandidates(qr)"
            >＋ 收入负面清单（候选）</button>
          </template>
          <p v-else class="no-report">尚无质量报告。</p>
        </article>
      </div>
    </section>

    <!-- 协作面板（P1.3 走向卡质量环：本地埋点的个人镜子——采纳率决定协作件调优方向） -->
    <section v-else-if="activePanel === 'collab'" class="data-panel">
      <!-- B3 · 用量可见两卡（generation_runs 聚合；独立于协作埋点数据源，二者可独立有/无数据） -->
      <div v-if="usageHasData" class="usage-cards">
        <article class="cost-item card-well">
          <header class="cost-header">
            <span class="cost-chapter">AI 消耗</span>
            <span class="cost-header-right">
              <span class="cost-total tnum">
                {{ formatTokens(bookUsage?.totals?.total_tokens || 0) }} token · {{ bookUsage?.totals?.calls || 0 }} 次调用<template v-if="(bookUsage?.totals?.cost || 0) > 0"> · {{ formatCost(bookUsage?.totals?.cost || 0) }}</template>
              </span>
              <button class="price-btn" title="按各厂商公布页填写模型价格（元/百万 token），金额立即生效" @click="showPriceModal = true">价格</button>
            </span>
          </header>
          <div class="usage-cells">
            <div class="usage-cell">
              <span class="usage-num">{{ formatTokens(bookUsage?.totals?.total_tokens || 0) }}</span>
              <span class="usage-cap">本书 token</span>
            </div>
            <div class="usage-cell">
              <span class="usage-num">{{ chapterUsage?.totals?.calls ?? 0 }}</span>
              <span class="usage-cap">{{ usageChapterNumber ? `第 ${usageChapterNumber} 章调用` : '最近一章调用' }}</span>
            </div>
            <div class="usage-cell">
              <span class="usage-num">{{ formatTokens(chapterUsage?.totals?.total_tokens || 0) }}</span>
              <span class="usage-cap">最近一章 token</span>
            </div>
          </div>
          <div class="usage-lane-list">
            <section v-for="g in usageLaneGroups" :key="g.lane" class="usage-lane">
              <header class="usage-lane-head">
                <span class="usage-lane-name">{{ g.label }}</span>
                <span class="usage-lane-total">
                  {{ formatTokens(g.totalTokens) }} token · {{ g.share }}%<template v-if="g.cost > 0"> · {{ formatCost(g.cost) }}</template>
                </span>
              </header>
              <div class="usage-stage-list">
                <div
                  v-for="s in g.rows"
                  :key="s.stage"
                  class="usage-stage-row"
                  :title="`${s.label}（${s.stage}）：${s.calls} 次 · ${formatTokens(s.total_tokens)} token`"
                >
                  <span class="usage-stage-label">{{ s.label }}</span>
                  <span class="usage-bar-track"><span class="usage-bar" :style="{ width: stageBarPercent(s.total_tokens, g.rowMax) }" /></span>
                  <span class="usage-stage-val">{{ s.calls }}× · {{ formatTokens(s.total_tokens) }}</span>
                </div>
              </div>
            </section>
          </div>
          <!-- 未计价提示（不冒充零成本）：哪些模型没配价，一键去补 -->
          <p v-if="usageUnpriced > 0" class="usage-unpriced">
            另有 {{ formatTokens(usageUnpriced) }} token 未计价（
            {{ (bookUsage?.by_model || []).filter((m) => !m.priced && m.total_tokens > 0).map((m) => m.model).join('、') || '部分模型' }}
            未配价格）——<button class="usage-unpriced-btn" @click="showPriceModal = true">去补价格</button>
          </p>
          <div class="usage-card-footer">
            <button
              class="usage-clear-btn btn-ghost btn-ghost--xs"
              :disabled="clearingUsage || chapterUsageEmpty"
              :title="chapterUsageEmpty
                ? '最近一章没有用量记录'
                : `清空第 ${usageChapterNumber ?? '?'} 章的用量台账（token/调用/成本归零，方便测试）——正文与世界数据不受影响`"
              @click="resetLatestChapterUsage"
            >
              <Icon name="arrow-path" :size="12" :class="{ spin: clearingUsage }" />
              <span>{{ clearingUsage ? '清空中…' : `清空第 ${usageChapterNumber ?? '?'} 章用量` }}</span>
            </button>
          </div>
        </article>
        <article class="cost-item card-well">
          <header class="cost-header">
            <span class="cost-chapter">按日趋势</span>
            <span class="cost-total tnum">近 {{ usageTrend.bars.length }} 天 · 峰值 {{ formatTokens(usageTrend.maxTotal) }} token/日</span>
          </header>
          <svg
            :viewBox="`0 0 ${usageTrend.width} ${usageTrend.height}`"
            class="usage-trend-svg"
            role="img"
            aria-label="AI 消耗按日趋势"
          >
            <line
              :x1="0" :y1="usageTrend.height - 14"
              :x2="usageTrend.width" :y2="usageTrend.height - 14"
              class="usage-trend-axis"
            />
            <rect
              v-for="b in usageTrend.bars"
              :key="b.date"
              :x="b.x" :y="b.y" :width="b.w" :height="b.h"
              class="usage-trend-bar"
            >
              <title>{{ b.date }}：{{ b.calls }} 次 · {{ b.totalTokens }} token</title>
            </rect>
          </svg>
          <div class="usage-trend-labels">
            <span>{{ usageTrend.firstLabel }}</span>
            <span>{{ usageTrend.lastLabel }}</span>
          </div>
        </article>
      </div>
      <p v-else class="usage-empty">
        AI 消耗：暂无记录。用 AI 辅助写作（写作中感知、Space 续写、沉淀与完稿体检、系统自己去读）后，这里会照出每章与每日的用量。
      </p>
      <div v-if="!collabHasData" class="empty">
        <p>暂无协作数据。在写作台用 AI 辅助写一章（走向卡 / Space 续写 / 细纲胶囊），这里会照出你的采纳习惯。</p>
      </div>
      <template v-else>
        <div class="summary-cards">
          <div class="summary-card">
            <span class="summary-num">{{ collabRate('card_burst', 'cards_delivered') }}</span>
            <span class="summary-label">走向卡连写率</span>
          </div>
          <div class="summary-card">
            <span class="summary-num">{{ collabRate('ghost_adopt', 'ghost_request') }}</span>
            <span class="summary-label">幽灵稿采纳率</span>
          </div>
          <div class="summary-card">
            <span class="summary-num">{{ (collabTotals['capsule_expand'] || 0) + (collabTotals['capsule_create'] || 0) }}</span>
            <span class="summary-label">细纲胶囊使用</span>
          </div>
          <div class="summary-card">
            <span class="summary-num">{{ collabTotals['quick_note'] || 0 }}</span>
            <span class="summary-label">世界速记入账</span>
          </div>
        </div>
        <div class="chapter-cost-list">
          <article v-for="cr in collabReports.filter((r) => r.report?.total)" :key="cr.chapterId" class="cost-item card-well">
            <header class="cost-header">
              <span class="cost-chapter">第 {{ cr.chapterNumber }} 章</span>
              <span class="cost-total tnum">{{ cr.report?.total }} 次协作交互</span>
            </header>
            <div class="stage-bars">
              <div v-for="(v, k) in cr.report?.by_kind || {}" :key="k" class="stage-bar" :title="`${collabKindLabel(String(k))}: ${v} 次`">
                <span class="stage-name">{{ collabKindLabel(String(k)) }}</span>
                <span class="stage-calls">{{ v }}×</span>
              </div>
            </div>
          </article>
        </div>
        <div class="usage-card-footer">
          <button
            class="usage-clear-btn btn-ghost btn-ghost--xs"
            :disabled="clearingCollab"
            title="清空本书全部协作埋点（采纳率/协作明细归零，方便测试）——「学着闭嘴」拒收史一并重置，正文与世界数据不受影响"
            @click="clearCollabData"
          >
            <Icon name="arrow-path" :size="12" :class="{ spin: clearingCollab }" />
            <span>{{ clearingCollab ? '清空中…' : '清空协作数据' }}</span>
          </button>
        </div>
      </template>
    </section>

    <!-- 模型价目表编辑（成本核算 2026-09-11） -->
    <PriceSettingsModal
      v-if="showPriceModal"
      :models="bookUsage?.by_model || []"
      @close="showPriceModal = false"
      @saved="onPricesSaved"
    />
  </div>
</template>

<style scoped>
.insights-view {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-primary);
  padding: var(--space-8) var(--space-10);
}

.insights-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.25rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.page-title {
  font-family: var(--font-heading);
  font-size: var(--text-2xl);
  letter-spacing: 0.08em;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0.125rem 0 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: var(--radius-xs);
  color: var(--text-secondary);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--state-hover);
}

.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
  background: var(--bg-canvas);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spin {
  animation: spin 1.2s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 汇总卡片 */
.summary-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}

.summary-card {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.summary-num {
  font-family: var(--font-heading);
  font-variant-numeric: tabular-nums;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--accent-500);
  line-height: 1;
}

.summary-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* 面板 tabs */
/* N2 §3.6：页签体系——h-32/px12，选中=主色 600 + 2px accent 下划条（scaleX 滑动 dur-2） */
.panel-tabs {
  display: flex;
  gap: 0.25rem;
  border-bottom: 1px solid var(--line-faint);
  margin-bottom: 1rem;
}

.panel-tab {
  position: relative;
  min-height: var(--control-h-md);
  padding: 0 12px;
  font-size: var(--text-sm);
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--dur-2) var(--ease-out);
}
.panel-tab::after {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: -1px;
  height: 2px;
  background: var(--accent-500);
  transform: scaleX(0);
  transition: transform var(--dur-2) var(--ease-out);
}
.panel-tab:hover {
  color: var(--text-primary);
}
.panel-tab.active {
  color: var(--text-primary);
  font-weight: 600;
}
.panel-tab.active::after {
  transform: scaleX(1);
}

.loading,
.error,
.empty {
  padding: 2rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.875rem;
}

/* 成本列表 */
.chapter-cost-list,
.chapter-quality-list,
.degraded-list {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

/* N3 §3.7 统一：四张成本/用量/collab 卡收编 .card-well 凹槽档——cost-item 从共享规则拆出
   （质量/降级卡保留原样），N2 的 usage-cards 特例随之下线 */
.quality-item,
.degraded-item {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0.75rem 0.875rem;
}

.cost-item {
  /* 挂点：皮肤由 .card-well 提供（4 处模板已挂类） */
}

.cost-header,
.quality-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.cost-chapter,
.quality-chapter {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.cost-total {
  font-size: 0.75rem;
  color: var(--accent-500);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

.cost-header-right {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.price-btn {
  padding: 0.125rem 0.5rem;
  font-size: var(--text-xs);
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  cursor: pointer;
}

.price-btn:hover {
  color: var(--text-primary);
  background: var(--state-hover);
}

.usage-unpriced {
  margin: 0.5rem 0 0;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}

.usage-unpriced-btn {
  padding: 0;
  font-size: var(--text-xs);
  color: var(--accent-500);
  background: transparent;
  border: none;
  cursor: pointer;
}

.usage-unpriced-btn:hover {
  text-decoration: underline;
}

.usage-card-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.625rem;
}

.usage-clear-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1875rem 0.5rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  border-radius: var(--radius-xs);
  cursor: pointer;
}

.usage-clear-btn:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger);
  background: transparent;
}

.usage-clear-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.stage-bars {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.stage-bar {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1875rem 0.4375rem;
  background: var(--bg-secondary);
  border-radius: var(--radius-xs);
  font-size: var(--text-xs);
}

.stage-name {
  color: var(--text-secondary);
}

.stage-calls {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

/* ===== B3 · 用量可见两卡（协作面板内） ===== */
.usage-cards {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  margin-bottom: 0.625rem;
}

.usage-cells {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
  margin-bottom: 0.625rem;
}

.usage-cell {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-secondary);
  border-radius: var(--radius-sm);
}

.usage-num {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--accent-500);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.usage-cap {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.usage-lane-list {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.usage-lane-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.usage-lane-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
}

.usage-lane-total {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.usage-stage-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.usage-stage-row {
  display: grid;
  grid-template-columns: 8.5rem 1fr auto;
  align-items: center;
  gap: 0.5rem;
  font-size: var(--text-xs);
}

.usage-stage-label {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.usage-bar-track {
  display: block;
  height: 0.375rem;
  background: var(--bg-secondary);
  border-radius: var(--radius-xs);
  overflow: hidden;
}

.usage-bar {
  display: block;
  height: 100%;
  background: var(--accent-500);
  border-radius: inherit;
  opacity: 0.75;
}

.usage-stage-val {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.usage-trend-svg {
  display: block;
  width: 100%;
  height: 6rem;
}

.usage-trend-axis {
  stroke: var(--border-color);
  stroke-width: 1;
}

.usage-trend-bar {
  fill: var(--accent-500);
  opacity: 0.8;
}

.usage-trend-labels {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-top: 0.25rem;
}

.usage-empty {
  margin: 0 0 0.625rem;
  padding: 0.75rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  text-align: center;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
}

.quality-verdict {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 0.125rem 0.4375rem;
  border-radius: var(--radius-xs);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}
.quality-verdict.pass { background: color-mix(in srgb, var(--ok) 12%, transparent); color: var(--ok); }
.quality-verdict.pass_with_fixes { background: color-mix(in srgb, var(--warn) 12%, transparent); color: var(--warn); }
.quality-verdict.fail { background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--danger); }
.quality-verdict.unaudited { background: var(--bg-tertiary); color: var(--text-muted); }

.quality-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.375rem;
}

.metric-pair {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-xs);
  padding: 0.1875rem 0;
  border-bottom: 1px dashed var(--border-color);
}

.metric-key {
  color: var(--text-muted);
}

.metric-val {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

.findings-count {
  margin: 0.5rem 0 0;
  font-size: var(--text-xs);
  color: var(--warn);
}

.collect-btn {
  margin-top: 0.375rem;
  padding: 0.25rem 0.625rem;
  font-size: var(--text-xs);
  color: var(--warn);
  background: var(--warn-bg);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.collect-btn:hover {
  background: var(--warn-bg);
}

.quality-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.rerun-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  border-radius: var(--radius-xs);
  cursor: pointer;
}
.rerun-btn:hover:not(:disabled) {
  background: var(--state-hover);
  color: var(--text-primary);
}
.rerun-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.no-report {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.degraded-item {
  display: flex;
  gap: 0.625rem;
  align-items: center;
  font-size: 0.75rem;
}

.deg-chapter {
  font-weight: 600;
  color: var(--text-primary);
}

.deg-stage {
  color: var(--text-secondary);
  font-family: monospace;
}

.deg-reason {
  color: var(--danger);
}
</style>
