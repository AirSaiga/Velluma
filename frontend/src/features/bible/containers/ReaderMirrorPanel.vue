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
 * 设计依据：第 7 轮修正——仪表盘不是方向盘，所有数据都是建议
 */
import { ref, computed, onMounted, watch } from 'vue'
import { readerMirrorApi, EXPECTATION_TYPE_LABELS, EXPECTATION_STATUS_LABELS, EXPECTATION_STATUS_COLORS, type Expectation, type ExpectationType, type ChapterPlanSuggestion } from '../../../services/api/domain/reader-mirror.api'

const props = defineProps<{
  bookId: string
  chapterNumber?: number
}>()

const expectations = ref<Expectation[]>([])
const tensionCurve = ref<any[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const plan = ref<ChapterPlanSuggestion | null>(null)

// 新建表单
const showForm = ref(false)
const newExp = ref<{ id: string; type: ExpectationType; description: string; tension: number; payoffChapter: number | null }>({
  id: '', type: 'power_reveal', description: '', tension: 5, payoffChapter: null,
})

const sortedExpectations = computed(() => {
  return [...expectations.value].sort((a, b) => {
    // 活跃的在前
    const aActive = a.status === 'setup' || a.status === 'accumulating' ? 0 : 1
    const bActive = b.status === 'setup' || b.status === 'accumulating' ? 0 : 1
    if (aActive !== bActive) return aActive - bActive
    return b.current_tension - a.current_tension
  })
})

const stats = computed(() => {
  const active = expectations.value.filter(e => e.status === 'setup' || e.status === 'accumulating')
  const high = active.filter(e => e.current_tension >= 8)
  return {
    total: expectations.value.length,
    active: active.length,
    highTension: high.length,
  }
})

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

async function handleCreate() {
  if (!newExp.value.id || !newExp.value.description) return
  try {
    await readerMirrorApi.createExpectation(props.bookId, {
      id: newExp.value.id,
      type: newExp.value.type,
      description: newExp.value.description,
      current_tension: newExp.value.tension,
      expected_payoff_chapter: newExp.value.payoffChapter,
    })
    showForm.value = false
    newExp.value = { id: '', type: 'power_reveal', description: '', tension: 5, payoffChapter: null }
    await loadData()
  } catch (e: any) {
    error.value = e.message
  }
}

async function handleAccumulate(exp: Expectation) {
  await readerMirrorApi.updateExpectation(props.bookId, exp.id, {
    tension_delta: 1,
    tension_event: '手动累积',
    chapter_number: props.chapterNumber || 0,
  })
  await loadData()
}

async function handlePayoff(exp: Expectation) {
  if (!confirm(`确认释放期待 [${exp.description.slice(0, 30)}]？这是爽点。`)) return
  await readerMirrorApi.updateExpectation(props.bookId, exp.id, {
    tension_delta: -5,
    new_status: 'payoff',
    tension_event: '手动释放',
    chapter_number: props.chapterNumber || 0,
  })
  await loadData()
}

async function handleDelete(exp: Expectation) {
  if (!confirm(`删除期待 [${exp.description.slice(0, 30)}]？`)) return
  await readerMirrorApi.deleteExpectation(props.bookId, exp.id)
  await loadData()
}

onMounted(loadData)
watch(() => props.bookId, loadData)
</script>

<template>
  <div class="reader-mirror">
    <header class="rm-header">
      <h3>期待账本（Reader Mirror）</h3>
      <p class="stats">
        {{ stats.total }} 个期待 · {{ stats.active }} 活跃 · {{ stats.highTension }} 高张力
      </p>
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

    <!-- 新建表单 -->
    <div v-if="showForm" class="form-card">
      <input v-model="newExp.id" placeholder="ID（如 EXP_LANSTAR_POWER）" class="input" />
      <select v-model="newExp.type" class="input">
        <option v-for="(lbl, key) in EXPECTATION_TYPE_LABELS" :key="key" :value="key">{{ lbl }}</option>
      </select>
      <input v-model="newExp.description" placeholder="期待描述（读者视角，如'读者想看兰星打脸贵族'）" class="input" />
      <div class="form-row">
        <label>初始张力 <input v-model.number="newExp.tension" type="number" min="1" max="10" /></label>
        <label>预期释放章 <input v-model.number="newExp.payoffChapter" type="number" min="1" /></label>
      </div>
      <button class="btn-mini primary" @click="handleCreate">添加</button>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="error" class="empty error">{{ error }}</div>

    <!-- 期待列表 -->
    <div v-else class="exp-list">
      <div
        v-for="exp in sortedExpectations"
        :key="exp.id"
        class="exp-card"
        :class="{ inactive: exp.status === 'payoff' || exp.status === 'dropped' || exp.status === 'subverted' }"
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

        <!-- 张力条 -->
        <div class="tension-bar">
          <div class="tension-fill" :style="{ width: (exp.current_tension * 10) + '%', background: EXPECTATION_STATUS_COLORS[exp.status] }"></div>
          <span class="tension-num">{{ exp.current_tension }}/10</span>
        </div>

        <div class="exp-meta">
          <span v-if="exp.expected_payoff_chapter">预期第 {{ exp.expected_payoff_chapter }} 章释放</span>
          <span v-if="exp.tension_history.length">最近：{{ exp.tension_history[exp.tension_history.length - 1].event }}</span>
        </div>

        <div v-if="exp.author_override" class="author-override">作者意图：{{ exp.author_override }}</div>

        <div class="exp-actions" v-if="exp.status === 'setup' || exp.status === 'accumulating'">
          <button class="btn-mini" @click="handleAccumulate(exp)">+1 累积</button>
          <button class="btn-mini payoff" @click="handlePayoff(exp)">⚡ 释放（爽点）</button>
          <button class="btn-mini danger" @click="handleDelete(exp)">删除</button>
        </div>
      </div>

      <div v-if="!sortedExpectations.length" class="empty">
        还没有期待。点击"+ 添加期待"开始建立读者的期待账本。
      </div>
    </div>

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

.form-card {
  padding: 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  margin-bottom: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.input {
  padding: 0.375rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  background: var(--bg-primary);
  font-family: inherit;
}
.form-row { display: flex; gap: 0.75rem; }
.form-row label { font-size: 0.6875rem; display: flex; align-items: center; gap: 0.25rem; flex: 1; }
.form-row input { width: 60px; padding: 0.25rem; }

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
