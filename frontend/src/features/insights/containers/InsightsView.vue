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
import { useToast } from '../../../composables/useToast'
import type { CostReport, QualityReport, FindingItem } from '../../../types'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const sortedChapters = store.sortedChapters

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
type PanelKey = 'cost' | 'quality' | 'degraded'
const activePanel = ref<PanelKey>('cost')

const costReports = ref<{ chapterId: string; chapterNumber: number; report: CostReport | null }[]>([])
const qualityReports = ref<{ chapterId: string; chapterNumber: number; report: QualityReport | null }[]>([])

async function loadAll() {
  if (!bookIdFromRoute.value) return
  loading.value = true
  error.value = null
  try {
    // 同步当前书的章节
    if (store.currentBookId.value !== bookIdFromRoute.value) {
      await store.loadCurrentBookData()
    }
    const chaps = sortedChapters.value.slice(-10) // 最近 10 章
    const [costs, qualities] = await Promise.all([
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
    ])
    costReports.value = costs
    qualityReports.value = qualities
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
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

const degradedEvents = computed(() => {
  const events: { chapter: number; stage: string; reason: string; action: string }[] = []
  for (const cr of costReports.value) {
    if (!cr.report) continue
    for (const stage of cr.report.stages) {
      if (stage.degraded_count > 0) {
        events.push({
          chapter: cr.chapterNumber,
          stage: stage.stage,
          reason: `${stage.degraded_count} 次降级`,
          action: '',
        })
      }
    }
  }
  return events
})

function backToLibrary() {
  router.push({ name: 'library' })
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
    showToast('这章的审计报告里没有可提取的陈词命中', 'info')
    return
  }
  try {
    for (const word of phrases.slice(0, 5)) {
      await styleApi.addInboxItem(
        bookId, 'negative_candidate',
        { word, source_text: `第${qr.chapterNumber}章审计命中` },
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
    showToast('质量审计已完成', 'success')
  } catch (e: any) {
    showToast(`质量审计失败：${e?.message || '未知错误'}`, 'error')
  } finally {
    rerunningIds.value.delete(chapterId)
  }
}
</script>

<template>
  <div class="insights-view">
    <header class="insights-header">
      <div class="header-left">
        <button class="icon-btn" @click="backToLibrary" title="返回书架">
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
        <span class="summary-label">累计 token</span>
      </div>
      <div class="summary-card">
        <span class="summary-num">{{ totalCost }}</span>
        <span class="summary-label">累计调用</span>
      </div>
      <div class="summary-card">
        <span class="summary-num">{{ degradedEvents.length }}</span>
        <span class="summary-label">降级事件</span>
      </div>
    </section>

    <!-- 面板切换 -->
    <div class="panel-tabs">
      <button
        v-for="p in [
          { k: 'cost', l: '成本' },
          { k: 'quality', l: '质量' },
          { k: 'degraded', l: '降级事件' },
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
        <p>暂无成本数据。生成章节后，token 消耗会在此汇总。</p>
      </div>
      <div v-else class="chapter-cost-list">
        <article v-for="cr in costReports.filter((r) => r.report)" :key="cr.chapterId" class="cost-item">
          <header class="cost-header">
            <span class="cost-chapter">第 {{ cr.chapterNumber }} 章</span>
            <span class="cost-total">{{ formatTokens(cr.report?.totals?.total_tokens || 0) }} token</span>
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
                class="rerun-btn"
                :disabled="rerunningIds.has(qr.chapterId)"
                :title="qr.report ? '基于当前正文重新执行双层质量审计' : '本章尚无质量报告，点击触发首次审计'"
                @click="rerunQuality(qr.chapterId)"
              >
                <Icon name="arrow-path" :size="12" :class="{ spin: rerunningIds.has(qr.chapterId) }" />
                <span>{{ rerunningIds.has(qr.chapterId) ? '审计中…' : qr.report ? '重新审计' : '立即审计' }}</span>
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

    <!-- 降级事件面板 -->
    <section v-else-if="activePanel === 'degraded'" class="data-panel">
      <div v-if="degradedEvents.length === 0" class="empty">
        <p>无降级事件。所有生成阶段都正常执行。</p>
      </div>
      <div v-else class="degraded-list">
        <article v-for="(ev, i) in degradedEvents" :key="i" class="degraded-item">
          <span class="deg-chapter">第 {{ ev.chapter }} 章</span>
          <span class="deg-stage">{{ ev.stage }}</span>
          <span class="deg-reason">{{ ev.reason }}</span>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.insights-view {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-primary);
  padding: 1.5rem 2rem;
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
  font-size: 1.25rem;
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
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--hover-bg);
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
  border-radius: 0.375rem;
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
  border-radius: 0.5rem;
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.summary-num {
  font-family: var(--font-heading);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--accent-500);
  line-height: 1;
}

.summary-label {
  font-size: 0.6875rem;
  color: var(--text-muted);
}

/* 面板 tabs */
.panel-tabs {
  display: flex;
  gap: 0.25rem;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 1rem;
}

.panel-tab {
  padding: 0.4375rem 0.875rem;
  font-size: 0.8125rem;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}
.panel-tab:hover {
  color: var(--text-primary);
}
.panel-tab.active {
  color: var(--accent-500);
  border-bottom-color: var(--accent-500);
  font-weight: 500;
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

.cost-item,
.quality-item,
.degraded-item {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.75rem 0.875rem;
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
  border-radius: 0.1875rem;
  font-size: 0.625rem;
}

.stage-name {
  color: var(--text-secondary);
}

.stage-calls {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.quality-verdict {
  font-size: 0.625rem;
  font-weight: 600;
  padding: 0.125rem 0.4375rem;
  border-radius: 0.1875rem;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}
.quality-verdict.pass { background: rgba(22, 163, 74, 0.12); color: #16a34a; }
.quality-verdict.pass_with_fixes { background: rgba(217, 119, 6, 0.12); color: #d97706; }
.quality-verdict.fail { background: rgba(220, 38, 38, 0.12); color: #dc2626; }
.quality-verdict.unaudited { background: var(--bg-tertiary); color: var(--text-muted); }

.quality-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.375rem;
}

.metric-pair {
  display: flex;
  justify-content: space-between;
  font-size: 0.6875rem;
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
  font-size: 0.6875rem;
  color: #d97706;
}

.collect-btn {
  margin-top: 0.375rem;
  padding: 0.25rem 0.625rem;
  font-size: 0.6875rem;
  color: #b45309;
  background: #fef3c7;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}

.collect-btn:hover {
  background: #fde68a;
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
  font-size: 0.625rem;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.1875rem;
  cursor: pointer;
}
.rerun-btn:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.rerun-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.no-report {
  margin: 0;
  font-size: 0.6875rem;
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
  color: #dc2626;
}
</style>
