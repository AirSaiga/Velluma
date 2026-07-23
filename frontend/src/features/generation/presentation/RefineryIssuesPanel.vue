<script setup lang="ts">
/**
 * 精修问题清单 UI（V4.1 新建，对话式介入点 2）。
 *
 * 职责：
 * - 展示诊断产出的问题清单
 * - 作者逐条决策（确认 / 否决 / 编辑）
 * - 作者可补充自定义问题
 * - 全部决策后触发 confirm
 *
 * 设计依据：docs/generation-v4.1-refinery.md §3.2
 */
import { ref, computed, reactive } from 'vue'
import type { RefineryIssue, IssueDecision, IssueSeverity } from '../../../services/api/domain'

const props = defineProps<{
  issues: RefineryIssue[]
  runId: string
}>()

const emit = defineEmits<{
  (e: 'confirm', payload: { run_id: string; decisions: IssueDecision[]; custom_issues: RefineryIssue[] }): void
  (e: 'cancel'): void
  (e: 'edit-canon'): void
}>()

// 每个 issue 的决策状态：'pending' | 'confirmed' | 'ignored'
const decisions = reactive<Record<string, 'pending' | 'confirmed' | 'ignored'>>({})
for (const iss of props.issues) {
  decisions[iss.id] = 'pending'
}

// 自定义问题
const customIssues = ref<RefineryIssue[]>([])
const customDiagnosis = ref('')
const showCustomForm = ref(false)

const severityColor: Record<IssueSeverity, string> = {
  high: '#dc2626',
  medium: '#f59e0b',
  low: '#6b7280',
}

const severityIcon: Record<IssueSeverity, string> = {
  high: '🔴',
  medium: '🟡',
  low: '⚪',
}

const typeLabel: Record<string, string> = {
  tell_not_show: '直陈该用动作',
  pacing_drag: '节奏拖沓',
  pacing_break: '节奏断裂',
  scene_jump: '场景切换突兀',
  info_leak: '信息泄露',
  character_off: '角色行为不符',
  redundancy: '冗余重复',
  weak_hook: '章末钩子弱',
  emotion_mismatch: '情绪与曲线不符',
  custom: '作者补充',
}

const stats = computed(() => {
  const confirmed = Object.values(decisions).filter(d => d === 'confirmed').length
  const ignored = Object.values(decisions).filter(d => d === 'ignored').length
  const pending = Object.values(decisions).filter(d => d === 'pending').length
  return { confirmed, ignored, pending, total: props.issues.length + customIssues.value.length }
})

function setDecision(id: string, dec: 'confirmed' | 'ignored') {
  decisions[id] = decisions[id] === dec ? 'pending' : dec
}

function confirmAll() {
  for (const iss of props.issues) {
    if (decisions[iss.id] === 'pending') decisions[iss.id] = 'confirmed'
  }
}

function ignoreAll() {
  for (const iss of props.issues) {
    decisions[iss.id] = 'ignored'
  }
}

function addCustomIssue() {
  if (!customDiagnosis.value.trim()) return
  const id = `C${Date.now()}`
  customIssues.value.push({
    id,
    location: { quote: '' },
    type: 'custom',
    severity: 'medium',
    diagnosis: customDiagnosis.value,
    suggestion: '',
    impact_radius: 'local',
    status: 'pending',
  })
  decisions[id] = 'confirmed' // 自定义问题默认确认
  customDiagnosis.value = ''
  showCustomForm.value = false
}

function handleConfirm() {
  const decArr: IssueDecision[] = []
  for (const iss of props.issues) {
    decArr.push({
      issue_id: iss.id,
      decision: decisions[iss.id] === 'ignored' ? 'ignored' : 'confirmed',
    })
  }
  for (const ci of customIssues.value) {
    decArr.push({
      issue_id: ci.id,
      decision: 'confirmed',
    })
  }
  emit('confirm', {
    run_id: props.runId,
    decisions: decArr,
    custom_issues: customIssues.value,
  })
}
</script>

<template>
  <div class="refinery-issues">
    <header class="header">
      <h3>润色检查</h3>
      <p class="stats">
        共 {{ stats.total }} 个问题
        · 确认 {{ stats.confirmed }}
        · 否决 {{ stats.ignored }}
        · 待定 {{ stats.pending }}
      </p>
    </header>

    <div class="actions">
      <button class="btn-mini" @click="confirmAll">全部确认</button>
      <button class="btn-mini" @click="ignoreAll">全部否决</button>
      <button class="btn-mini" @click="showCustomForm = !showCustomForm">+ 补充问题</button>
      <button class="btn-mini canon-btn" @click="emit('edit-canon')">前往 Canon 补设定</button>
    </div>

    <div v-if="showCustomForm" class="custom-form">
      <textarea
        v-model="customDiagnosis"
        rows="2"
        placeholder="描述你发现的问题（如：'第 5 段读起来不顺'）"
      ></textarea>
      <button class="btn-mini primary" @click="addCustomIssue">添加</button>
    </div>

    <div class="issue-list">
      <div
        v-for="iss in issues"
        :key="iss.id"
        class="issue-card"
        :class="[
          `severity-${iss.severity}`,
          decisions[iss.id] ? `decision-${decisions[iss.id]}` : '',
        ]"
      >
        <div class="issue-head">
          <span class="severity-icon">{{ severityIcon[iss.severity] }}</span>
          <span class="type-tag">{{ typeLabel[iss.type] || iss.type }}</span>
          <span class="impact-tag" v-if="iss.impact_radius !== 'local'">
            {{ iss.impact_radius === 'multi_paragraph' ? '多段' : '全局' }}
          </span>
        </div>

        <div class="issue-quote" v-if="iss.location?.quote">
          "{{ iss.location.quote }}"
        </div>

        <div class="issue-diagnosis">{{ iss.diagnosis }}</div>

        <div class="issue-suggestion" v-if="iss.suggestion">
          <span class="suggestion-label">建议：</span>{{ iss.suggestion }}
        </div>

        <div class="issue-actions">
          <button
            class="btn-mini"
            :class="{ active: decisions[iss.id] === 'confirmed' }"
            @click="setDecision(iss.id, 'confirmed')"
          >
            ✓ 确认修改
          </button>
          <button
            class="btn-mini"
            :class="{ active: decisions[iss.id] === 'ignored' }"
            @click="setDecision(iss.id, 'ignored')"
          >
            ✗ 有意为之
          </button>
        </div>
      </div>

      <!-- 自定义问题 -->
      <div
        v-for="ci in customIssues"
        :key="ci.id"
        class="issue-card severity-custom decision-confirmed"
      >
        <div class="issue-head">
          <span class="type-tag custom">作者补充</span>
        </div>
        <div class="issue-diagnosis">{{ ci.diagnosis }}</div>
      </div>
    </div>

    <footer class="footer">
      <button class="btn-secondary" @click="emit('cancel')">取消润色</button>
      <button class="btn-primary" :disabled="stats.confirmed === 0" @click="handleConfirm">
        开始润色（{{ stats.confirmed }} 处修改）
      </button>
    </footer>
  </div>
</template>

<style scoped>
.refinery-issues {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  padding: 1rem;
  overflow: hidden;
}
.header {
  margin-bottom: 0.75rem;
}
.header h3 {
  font-size: 1rem;
  margin: 0 0 0.25rem;
}
.stats {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0;
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
}
.btn-mini {
  padding: 0.25rem 0.625rem;
  font-size: 0.6875rem;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: 0.25rem;
  cursor: pointer;
  color: var(--text-primary);
}
.btn-mini.primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.btn-mini.active {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.btn-mini:hover { opacity: 0.85; }

.custom-form {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
  margin-bottom: 0.75rem;
  padding: 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
}
.custom-form textarea {
  flex: 1;
  padding: 0.375rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  background: var(--bg-primary);
  font-size: 0.75rem;
  resize: vertical;
  font-family: inherit;
}

.issue-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  padding-right: 0.25rem;
}
.issue-card {
  padding: 0.75rem;
  border-radius: 0.375rem;
  background: var(--bg-secondary);
  border-left: 3px solid var(--text-muted);
}
.issue-card.severity-high { border-left-color: #dc2626; }
.issue-card.severity-medium { border-left-color: #f59e0b; }
.issue-card.severity-low { border-left-color: #6b7280; }
.issue-card.severity-custom { border-left-color: #8b5cf6; }
.issue-card.decision-confirmed { background: #ecfdf5; }
.issue-card.decision-ignored { opacity: 0.5; }

.issue-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  font-size: 0.6875rem;
}
.severity-icon { font-size: 0.75rem; }
.type-tag {
  padding: 0.125rem 0.375rem;
  background: var(--hover-bg);
  border-radius: 0.25rem;
  color: var(--text-secondary);
}
.type-tag.custom { background: #ede9fe; color: #6d28d9; }
.impact-tag {
  padding: 0.125rem 0.375rem;
  background: #fef3c7;
  color: #92400e;
  border-radius: 0.25rem;
}
.issue-quote {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-style: italic;
  margin-bottom: 0.375rem;
  padding-left: 0.5rem;
  border-left: 2px solid var(--border-color);
}
.issue-diagnosis {
  font-size: 0.8125rem;
  line-height: 1.5;
  margin-bottom: 0.375rem;
}
.issue-suggestion {
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}
.suggestion-label {
  color: var(--accent-500);
  font-weight: 500;
}
.issue-actions {
  display: flex;
  gap: 0.375rem;
}

.footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
  margin-top: 0.75rem;
}
.btn-primary, .btn-secondary {
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  cursor: pointer;
  border: 1px solid var(--border-color);
}
.btn-primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn-secondary { background: var(--bg-primary); }
</style>
