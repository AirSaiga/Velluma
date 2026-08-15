<script setup lang="ts">
/**
 * Reader Mirror 面板（V4.2 路径 B）。
 *
 * 职责：
 * - 显示期待账本（双层：作者声明 + 自动推断）
 * - 显示张力曲线（按章号）
 * - 添加/编辑/删除期待
 * - 显示本章规划建议（如果有 chapterNumber）
 *
 * UX 说明（人话层重构）：
 * - 输入侧零数据库语言：ID 前端自动生成不可见；类型随描述关键词预填可改；
 *   张力以「火候」四档录入；释放时机以模糊档位录入（写入 author_override）
 * - 列表侧按「该收了 / 在憋着 / 已收官」分组，火候词替代裸数字
 *
 * 设计依据：第 7 轮修正——仪表盘不是方向盘，所有数据都是建议
 */
import { ref, computed, onMounted, watch } from 'vue'
import { readerMirrorApi, EXPECTATION_TYPE_LABELS, EXPECTATION_STATUS_LABELS, EXPECTATION_STATUS_COLORS, HEAT_LEVELS, TIMING_OPTIONS, tensionToHeat, guessTypeFromDescription, type Expectation, type ExpectationType, type ChapterPlanSuggestion } from '../../../services/api/domain/reader-mirror.api'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const props = defineProps<{
  bookId: string
  chapterNumber?: number
}>()

const expectations = ref<Expectation[]>([])
const tensionCurve = ref<any[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const plan = ref<ChapterPlanSuggestion | null>(null)

// 新建表单：描述为唯一必填，其余字段均有人话默认值
const showForm = ref(false)
const form = ref({ description: '', type: 'mystery' as ExpectationType, heat: 'brewing', timing: 'unknown' })
// 用户手动改过类型后，关键词猜测不再覆盖
const typeTouched = ref(false)

watch(() => form.value.description, (desc) => {
  if (!typeTouched.value) form.value.type = guessTypeFromDescription(desc)
})

const ACTIVE_STATUSES = ['setup', 'accumulating']
const isActive = (e: Expectation) => ACTIVE_STATUSES.includes(e.status)
const byTensionDesc = (a: Expectation, b: Expectation) => b.current_tension - a.current_tension

// 火候看板三组：该收了（高张力活跃）/ 在憋着（其余活跃）/ 已收官（终态）
const dueGroup = computed(() => expectations.value.filter(e => isActive(e) && e.current_tension >= 8).sort(byTensionDesc))
const brewingGroup = computed(() => expectations.value.filter(e => isActive(e) && e.current_tension < 8).sort(byTensionDesc))
const closedGroup = computed(() => expectations.value.filter(e => !isActive(e)))

const groups = computed(() => [
  { key: 'due', title: `该收了（${dueGroup.value.length}）`, items: dueGroup.value, collapsible: false },
  { key: 'brewing', title: `在憋着（${brewingGroup.value.length}）`, items: brewingGroup.value, collapsible: false },
  { key: 'closed', title: `已收官（${closedGroup.value.length}）`, items: closedGroup.value, collapsible: true },
])
const closedExpanded = ref(false)

const statsText = computed(() => {
  const parts: string[] = []
  if (brewingGroup.value.length) parts.push(`${brewingGroup.value.length} 条在憋`)
  if (dueGroup.value.length) parts.push(`${dueGroup.value.length} 条该收了`)
  if (closedGroup.value.length) parts.push(`${closedGroup.value.length} 条已收官`)
  return parts.length ? parts.join(' · ') : '账本还是空的'
})

// 「憋了 N 章」为零成本近似：以张力记录的首末章号跨度估算（本面板无当前章号上下文）
function heldChaptersText(exp: Expectation): string {
  const chapters = (exp.tension_history || []).map(h => h.chapter).filter(n => typeof n === 'number')
  if (!chapters.length) return '刚埋下'
  const span = Math.max(...chapters) - Math.min(...chapters)
  return span <= 0 ? '刚埋下' : `憋了 ${span} 章`
}

async function loadData() {
  loading.value = true
  error.value = null
  try {
    const data = await readerMirrorApi.get(props.bookId)
    expectations.value = data.expectations || []
    tensionCurve.value = data.tension_curve || []
    if (props.chapterNumber) {
      plan.value = await readerMirrorApi.getPlan(props.bookId, props.chapterNumber)
    }
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.value = { description: '', type: 'mystery', heat: 'brewing', timing: 'unknown' }
  typeTouched.value = false
}

async function handleCreate() {
  const description = form.value.description.trim()
  if (!description) return
  const heat = HEAT_LEVELS.find(h => h.key === form.value.heat) ?? HEAT_LEVELS[1]
  const timing = TIMING_OPTIONS.find(t => t.key === form.value.timing) ?? TIMING_OPTIONS[0]
  try {
    await readerMirrorApi.createExpectation(props.bookId, {
      // ID 对用户不可见，前端自动生成
      id: `EXP_${Date.now().toString(36).toUpperCase()}`,
      type: form.value.type,
      description,
      current_tension: heat.tension,
      // 模糊时机写入 author_override（作者处理意图），具体章号一律留空
      expected_payoff_chapter: null,
      author_override: timing.override,
    })
    showForm.value = false
    resetForm()
    await loadData()
  } catch (e: any) {
    showToast('登记失败: ' + (e?.message || '未知错误'), 'error')
  }
}

async function handleAccumulate(exp: Expectation) {
  try {
    await readerMirrorApi.updateExpectation(props.bookId, exp.id, {
      tension_delta: 1,
      tension_event: '手动加了一把火',
      chapter_number: props.chapterNumber || 0,
    })
    await loadData()
  } catch (e: any) {
    showToast('累积失败: ' + (e?.message || '未知错误'), 'error')
  }
}

async function handlePayoff(exp: Expectation) {
  const ok = await showConfirm({
    title: '兑现期待',
    message: `确认收掉「${exp.description.slice(0, 30)}」？这会标记为已兑现（爽点）。`,
    confirmText: '确认收线',
  })
  if (!ok) return
  try {
    await readerMirrorApi.updateExpectation(props.bookId, exp.id, {
      tension_delta: -5,
      new_status: 'payoff',
      tension_event: '手动收线',
      chapter_number: props.chapterNumber || 0,
    })
    await loadData()
  } catch (e: any) {
    showToast('释放失败: ' + (e?.message || '未知错误'), 'error')
  }
}

async function handleDelete(exp: Expectation) {
  const ok = await showConfirm({
    title: '删除期待',
    message: `删除期待 [${exp.description.slice(0, 30)}]？`,
    warning: '删除后不可恢复。',
  })
  if (!ok) return
  try {
    await readerMirrorApi.deleteExpectation(props.bookId, exp.id)
    await loadData()
  } catch (e: any) {
    showToast('删除失败: ' + (e?.message || '未知错误'), 'error')
  }
}

onMounted(loadData)
watch(() => props.bookId, loadData)
</script>

<template>
  <div class="reader-mirror">
    <header class="rm-header">
      <h3>期待账本（Reader Mirror）</h3>
      <p class="stats">{{ statsText }}</p>
    </header>

    <!-- 本章规划建议（如果有 chapterNumber） -->
    <div v-if="plan" class="plan-card" :class="{ 'payoff-recommended': plan.is_payoff_chapter_recommended }">
      <div class="plan-head">
        <span class="plan-title">第 {{ plan.chapter_number }} 章规划建议</span>
        <span class="plan-tension">建议张力 {{ plan.suggested_tension }}/10</span>
      </div>
      <p class="plan-rationale">{{ plan.rationale }}</p>
      <div class="plan-badges">
        <span v-if="plan.is_payoff_chapter_recommended" class="badge payoff">⚡ 建议释放爽点</span>
        <span v-if="plan.expectations_to_accumulate.length" class="badge accumulate">
          累积 {{ plan.expectations_to_accumulate.length }}
        </span>
        <span v-if="plan.expectations_to_setup.length" class="badge setup">
          推进 {{ plan.expectations_to_setup.length }}
        </span>
      </div>
      <p class="hint">★ 这是仪表盘建议，不是强制——作者主权至上</p>
    </div>

    <div class="actions">
      <button class="btn-mini" @click="showForm = !showForm">+ 添加期待</button>
      <button class="btn-mini" @click="loadData">刷新</button>
    </div>

    <!-- 新建表单：一句话 + 三个人话选项，零数据库语言 -->
    <div v-if="showForm" class="form-card">
      <textarea
        v-model="form.description"
        class="input desc-input"
        rows="2"
        placeholder="读者在等什么？如「读者想知道血噬到底是什么来历、为什么被统合局保管」"
      ></textarea>

      <div class="field-row">
        <span class="field-label">类型</span>
        <select v-model="form.type" class="input type-select" @change="typeTouched = true">
          <option v-for="(lbl, key) in EXPECTATION_TYPE_LABELS" :key="key" :value="key">{{ lbl }}</option>
        </select>
        <span class="field-hint">随描述自动预填，可改</span>
      </div>

      <div class="field-row">
        <span class="field-label">火候</span>
        <label v-for="h in HEAT_LEVELS" :key="h.key" class="radio-label">
          <input v-model="form.heat" type="radio" :value="h.key" />{{ h.label }}
        </label>
      </div>

      <div class="field-row">
        <span class="field-label">打算什么时候收</span>
        <label v-for="t in TIMING_OPTIONS" :key="t.key" class="radio-label">
          <input v-model="form.timing" type="radio" :value="t.key" />{{ t.label }}
        </label>
      </div>

      <button class="btn-mini primary" :disabled="!form.description.trim()" @click="handleCreate">登记</button>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="error" class="empty error">{{ error }}</div>

    <!-- 期待列表：火候看板分组 -->
    <template v-else>
      <div
        v-for="g in groups"
        v-show="g.items.length"
        :key="g.key"
        class="exp-group"
        :class="`group-${g.key}`"
      >
        <h4
          class="group-title"
          :class="{ clickable: g.collapsible }"
          @click="g.collapsible && (closedExpanded = !closedExpanded)"
        >
          {{ g.title }}<span v-if="g.collapsible" class="collapse-arrow">{{ closedExpanded ? '▾' : '▸' }}</span>
        </h4>

        <div v-show="!g.collapsible || closedExpanded" class="exp-list">
          <div
            v-for="exp in g.items"
            :key="exp.id"
            class="exp-card"
            :class="{ inactive: g.key === 'closed' }"
          >
            <div class="exp-head">
              <span class="type-tag" :style="{ background: EXPECTATION_STATUS_COLORS[exp.status] + '22', color: EXPECTATION_STATUS_COLORS[exp.status] }">
                {{ EXPECTATION_TYPE_LABELS[exp.type] }}
              </span>
              <span class="status-tag">{{ EXPECTATION_STATUS_LABELS[exp.status] }}</span>
              <span v-if="exp.source === 'author_declared'" class="source-tag">作者声明</span>
              <span v-else class="source-tag auto">自动推断</span>
            </div>

            <div class="exp-desc">{{ exp.description }}</div>

            <!-- 火候条（底层数字张力进 tooltip） -->
            <div class="tension-bar" :title="`张力 ${exp.current_tension}/10`">
              <div class="tension-fill" :style="{ width: (exp.current_tension * 10) + '%', background: EXPECTATION_STATUS_COLORS[exp.status] }"></div>
              <span class="tension-num">{{ tensionToHeat(exp.current_tension) }}</span>
            </div>

            <div class="exp-meta">
              <span>{{ heldChaptersText(exp) }}</span>
              <span v-if="exp.expected_payoff_chapter">预期第 {{ exp.expected_payoff_chapter }} 章收</span>
              <span v-if="exp.tension_history.length">最近：{{ exp.tension_history[exp.tension_history.length - 1].event }}</span>
            </div>

            <div v-if="exp.author_override" class="author-override">作者意图：{{ exp.author_override }}</div>

            <div v-if="isActive(exp)" class="exp-actions">
              <button class="btn-mini" @click="handleAccumulate(exp)">加一把火</button>
              <button class="btn-mini payoff" @click="handlePayoff(exp)">⚡ 收了它</button>
              <button class="btn-mini danger" @click="handleDelete(exp)">删除</button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!expectations.length" class="empty">
        还没有期待。用一句话记下读者此刻最想知道的事。
      </div>
    </template>

    <!-- 张力曲线 -->
    <div v-if="tensionCurve.length" class="curve-section">
      <h4>张力曲线</h4>
      <div class="curve">
        <div
          v-for="sample in tensionCurve"
          :key="sample.chapter_number"
          class="curve-bar"
          :class="{ payoff: sample.is_payoff_chapter }"
          :title="`第 ${sample.chapter_number} 章: 张力 ${sample.overall_tension}${sample.is_payoff_chapter ? '（爽点）' : ''}`"
        >
          <div class="bar-fill" :style="{ height: (sample.overall_tension * 10) + '%' }"></div>
          <span class="bar-label">{{ sample.chapter_number }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reader-mirror { padding: 1rem; height: 100%; overflow-y: auto; }
.rm-header { margin-bottom: 0.75rem; }
.rm-header h3 { font-size: 1rem; margin: 0 0 0.25rem; }
.stats { font-size: 0.75rem; color: var(--text-muted); margin: 0; }

.plan-card {
  padding: 0.75rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  margin-bottom: 0.75rem;
  border-left: 3px solid var(--accent-500);
}
.plan-card.payoff-recommended {
  border-left-color: #dc2626;
  background: #fef2f2;
}
.plan-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.375rem;
}
.plan-title { font-weight: 600; font-size: 0.8125rem; }
.plan-tension { font-size: 0.75rem; color: var(--text-muted); }
.plan-rationale { font-size: 0.75rem; color: var(--text-secondary); margin: 0 0 0.5rem; line-height: 1.5; }
.plan-badges { display: flex; gap: 0.375rem; margin-bottom: 0.375rem; }
.badge {
  padding: 0.125rem 0.5rem;
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  font-weight: 500;
}
.badge.payoff { background: #fee2e2; color: #dc2626; }
.badge.accumulate { background: #fef3c7; color: #b45309; }
.badge.setup { background: #f1f5f9; color: #475569; }
.hint { font-size: 0.6875rem; color: var(--text-muted); margin: 0; font-style: italic; }

.actions { display: flex; gap: 0.375rem; margin-bottom: 0.75rem; }
.btn-mini {
  padding: 0.25rem 0.625rem;
  font-size: 0.6875rem;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: 0.25rem;
  cursor: pointer;
}
.btn-mini.primary { background: var(--accent-500); color: white; border-color: var(--accent-500); }
.btn-mini.payoff { color: #dc2626; border-color: #dc2626; }
.btn-mini.danger { color: #dc2626; }
.btn-mini:hover { opacity: 0.85; }
.btn-mini:disabled { opacity: 0.5; cursor: not-allowed; }

.form-card {
  padding: 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  margin-bottom: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.input {
  padding: 0.375rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  background: var(--bg-primary);
  font-family: inherit;
}
.desc-input { resize: vertical; line-height: 1.5; }
.type-select { width: auto; }
.field-row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.field-label { font-size: 0.6875rem; color: var(--text-muted); }
.field-hint { font-size: 0.625rem; color: var(--text-muted); }
.radio-label {
  font-size: 0.6875rem;
  display: flex;
  align-items: center;
  gap: 0.2rem;
  color: var(--text-secondary);
  cursor: pointer;
}

.exp-group { margin-bottom: 0.25rem; }
.group-title {
  font-size: 0.75rem;
  margin: 0.75rem 0 0.375rem;
  color: var(--text-secondary);
}
.group-due > .group-title { color: #dc2626; }
.group-title.clickable { cursor: pointer; user-select: none; }
.collapse-arrow { margin-left: 0.25rem; font-size: 0.625rem; }

.exp-list { display: flex; flex-direction: column; gap: 0.5rem; }
.exp-card {
  padding: 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  border-left: 3px solid transparent;
}
.exp-card.inactive { opacity: 0.5; }
.exp-head {
  display: flex;
  gap: 0.375rem;
  align-items: center;
  margin-bottom: 0.375rem;
  font-size: 0.625rem;
}
.type-tag { padding: 0.125rem 0.375rem; border-radius: 0.25rem; font-weight: 500; }
.status-tag { padding: 0.125rem 0.375rem; background: var(--hover-bg); border-radius: 0.25rem; color: var(--text-muted); }
.source-tag { padding: 0.125rem 0.375rem; background: #dbeafe; color: #1e40af; border-radius: 0.25rem; }
.source-tag.auto { background: #f1f5f9; color: #64748b; }
.exp-desc { font-size: 0.8125rem; margin-bottom: 0.375rem; line-height: 1.4; }
.tension-bar {
  position: relative;
  height: 16px;
  background: var(--hover-bg);
  border-radius: 999px;
  margin-bottom: 0.375rem;
  overflow: hidden;
}
.tension-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}
.tension-num {
  position: absolute;
  right: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.625rem;
  color: white;
  font-weight: 600;
  text-shadow: 0 0 2px rgba(0,0,0,0.5);
}
.exp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  font-size: 0.625rem;
  color: var(--text-muted);
  margin-bottom: 0.375rem;
}
.author-override {
  padding: 0.25rem 0.5rem;
  background: #fef3c7;
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  color: #92400e;
  margin-bottom: 0.375rem;
}
.exp-actions { display: flex; gap: 0.375rem; }

.empty {
  padding: 2rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8125rem;
}
.empty.error { color: #dc2626; }

.curve-section { margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--border-color); }
.curve-section h4 { font-size: 0.75rem; margin: 0 0 0.5rem; }
.curve { display: flex; gap: 2px; height: 60px; align-items: flex-end; }
.curve-bar {
  flex: 1;
  min-width: 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  position: relative;
}
.bar-fill {
  background: var(--accent-500);
  border-radius: 2px 2px 0 0;
  width: 100%;
}
.curve-bar.payoff .bar-fill { background: #dc2626; }
.bar-label {
  font-size: 0.5rem;
  color: var(--text-muted);
  text-align: center;
  margin-top: 2px;
}
</style>
