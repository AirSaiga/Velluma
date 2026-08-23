<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { worldApi } from '../../../services/api/domain/world.api'
import type { EventDraft } from '../../../services/api/domain/world.api'
import { formatTime, breakdownTime, fromYMD } from '../../world/engine/timeFormat'
import { EVENT_TEMPLATES, getTemplate } from '../../world/engine/eventTemplates'
import type { EventType, WorldEntity, WorldLocation } from '../../world/engine/types'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'

/**
 * 速记框（docs/world-writing-bridge.md W3 一句话记历史）。
 *
 * 流程：一行口语 → parse-event 解析 → 预填轻表单（作者过目可改）→ 记入世界（既有
 * 事件创建端点）→ 撤销胶囊 6 秒可撤（删事件 + 刷新切片）。解析失败降级空白表单。
 *
 * 入口：Alt+N（捕获阶段，Alt+O 同款门控）｜浮卡「记一笔」（velluma:quick-note 事件）。
 * 契约红线：系统绝不自作主张直接入账——解析结果必须过作者的手。
 */
const props = defineProps<{
  bookId: string | null
  chapterId: string | null
}>()

const QUICK_NOTE_EVENT = 'velluma:quick-note'
const CAPSULE_MS = 6000

const visible = ref(false)
const inputText = ref('')
const parsing = ref(false)
const confidence = ref<'high' | 'low' | 'none'>('none')
const draft = ref<EventDraft | null>(null)
const saving = ref(false)
const entities = ref<WorldEntity[]>([])
const locations = ref<WorldLocation[]>([])

// 撤销胶囊（自管，不动通用 Toast——useToast 无动作按钮）
const capsule = ref<{ eventId: string; label: string } | null>(null)
let capsuleTimer: number | null = null

function openWith(prefill?: string) {
  if (!props.bookId || !props.chapterId) return
  visible.value = true
  if (prefill && !inputText.value) inputText.value = prefill
  if (!entities.value.length || !locations.value.length) void loadRoster()
}
function close() {
  visible.value = false
  parsing.value = false
  draft.value = null
  inputText.value = ''
  confidence.value = 'none'
}

async function loadRoster() {
  if (!props.bookId) return
  try {
    const [ents, locs] = await Promise.all([
      worldApi.listEntities(props.bookId),
      worldApi.listLocations(props.bookId),
    ])
    entities.value = ents || []
    locations.value = locs || []
  } catch {
    /* 名单缺席时表单仍可用（手填不了就取消） */
  }
}

// ---- 解析 ----
async function parse() {
  if (!props.bookId || !props.chapterId || !inputText.value.trim()) return
  parsing.value = true
  try {
    const r = await worldApi.parseEvent(props.bookId, props.chapterId, inputText.value.trim())
    draft.value = r.draft
    confidence.value = r.confidence
  } catch {
    draft.value = null
    confidence.value = 'none'
  } finally {
    parsing.value = false
  }
}

const typeLabel = computed(() =>
  draft.value ? getTemplate(draft.value.event_type as EventType)?.label || draft.value.event_type : ''
)
const timePreview = computed(() => (draft.value ? formatTime(draft.value.time_start) : ''))

// 时刻编辑走 年/月/日（内部存连续日数 Timestamp，作者不认日数；fromYMD 自带 1-12/1-30 钳位）
function ymdField(key: 'year' | 'month' | 'day') {
  return computed({
    get: () => breakdownTime(draft.value?.time_start ?? 0)[key],
    set: (v: number) => {
      if (!draft.value) return
      const cur = breakdownTime(draft.value.time_start)
      draft.value.time_start = fromYMD(
        key === 'year' ? v : cur.year,
        key === 'month' ? v : cur.month,
        key === 'day' ? v : cur.day,
      )
    },
  })
}
const draftYear = ymdField('year')
const draftMonth = ymdField('month')
const draftDay = ymdField('day')

function removeParticipant(idx: number) {
  if (!draft.value) return
  draft.value.participant_ids.splice(idx, 1)
  draft.value.participant_names.splice(idx, 1)
}
function addParticipant(entityId: string) {
  if (!draft.value || !entityId) return
  if (draft.value.participant_ids.includes(entityId)) return
  const ent = entities.value.find((e) => e.id === entityId)
  if (!ent) return
  draft.value.participant_ids.push(ent.id)
  draft.value.participant_names.push(ent.name)
}
function setLocation(locationId: string) {
  if (!draft.value) return
  if (!locationId) {
    draft.value.location_id = null
    draft.value.location_name = ''
    return
  }
  const loc = locations.value.find((l) => l.id === locationId)
  if (loc) {
    draft.value.location_id = loc.id
    draft.value.location_name = loc.name
  }
}

// ---- 入账 ----
async function commit() {
  const d = draft.value
  if (!d || !props.bookId || saving.value) return
  saving.value = true
  try {
    const ev = await worldApi.createEvent(props.bookId, {
      event_type: d.event_type,
      time_start: d.time_start,
      time_end: Math.max(d.time_end, d.time_start),
      location_id: d.location_id,
      participant_ids: d.participant_ids,
      payload: d.event_type === 'move'
        ? { character_ids: d.participant_ids, ...(d.location_id ? { to_location_id: d.location_id } : {}) }
        : d.event_type === 'birth' || d.event_type === 'death'
          ? { character_id: d.participant_ids[0] || null }
          : {},
      note: d.note || d.summary || undefined,
    })
    showCapsule(ev.id, `${d.summary || typeLabel.value} · ${formatTime(d.time_start)}`)
    dispatchCollabEvent('quick_note', { action: 'commit', event_type: d.event_type })
    close()
    window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
  } catch (e) {
    console.warn('[QuickEventNote] 入账失败', e)
  } finally {
    saving.value = false
  }
}

function showCapsule(eventId: string, label: string) {
  capsule.value = { eventId, label }
  if (capsuleTimer) window.clearTimeout(capsuleTimer)
  capsuleTimer = window.setTimeout(() => (capsule.value = null), CAPSULE_MS)
}

async function undo() {
  if (!capsule.value || !props.bookId) return
  const { eventId } = capsule.value
  capsule.value = null
  if (capsuleTimer) window.clearTimeout(capsuleTimer)
  try {
    await worldApi.deleteEvent(props.bookId, eventId)
    dispatchCollabEvent('quick_note', { action: 'undo' })
    window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
  } catch (e) {
    console.warn('[QuickEventNote] 撤销失败', e)
  }
}

// ---- 快捷键（Alt+N，捕获阶段；Alt+O 同款门控）+ 浮卡入口事件 ----
function onKeydown(e: KeyboardEvent) {
  if (e.altKey && !e.ctrlKey && !e.shiftKey && e.code === 'KeyN') {
    const target = e.target as HTMLElement | null
    const inField = target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    if (visible.value) {
      e.preventDefault()
      close()
      return
    }
    if (!inField) return // 只在写作上下文（编辑器聚焦）唤起
    e.preventDefault()
    e.stopPropagation()
    openWith()
  } else if (e.key === 'Escape' && visible.value) {
    close()
  }
}
function onQuickNoteRequest(ev: Event) {
  const detail = (ev as CustomEvent<{ keyword?: string }>).detail
  openWith(detail?.keyword)
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown, true)
  window.addEventListener(QUICK_NOTE_EVENT, onQuickNoteRequest as EventListener)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown, true)
  window.removeEventListener(QUICK_NOTE_EVENT, onQuickNoteRequest as EventListener)
  if (capsuleTimer) window.clearTimeout(capsuleTimer)
})
</script>

<template>
  <Teleport to="body">
    <!-- 速记模态 -->
    <div v-if="visible" class="qen-overlay" @click.self="close">
      <div class="qen-modal">
        <div class="qen-head">
          <span class="qen-title">记一笔 · 世界速记</span>
          <button class="qen-close" @click="close">×</button>
        </div>

        <template v-if="!draft">
          <p class="qen-hint">一句话记下刚发生的剧情事实，AI 解析成事件草稿，你过目后入账。</p>
          <div class="qen-row">
            <input
              v-model="inputText"
              class="qen-input"
              type="text"
              placeholder="例：第3年春，林尘率三百人攻下北岸要塞"
              maxlength="200"
              autofocus
              @keydown.enter.prevent="parse"
            />
            <button class="qen-btn primary" :disabled="parsing || !inputText.trim()" @click="parse">
              {{ parsing ? '解析中…' : '解析' }}
            </button>
          </div>
        </template>

        <template v-else>
          <!-- 解析置信提示 -->
          <div v-if="confidence !== 'high'" class="qen-warn">
            {{
              confidence === 'none'
                ? '未能自动解析——直接按下表手填即可。'
                : '解析把握不高——请核对草稿再入账。'
            }}
          </div>

          <div class="qen-form">
            <label class="qen-field">
              类型
              <select v-model="draft.event_type">
                <option v-for="tpl in EVENT_TEMPLATES" :key="tpl.type" :value="tpl.type">
                  {{ tpl.label }}
                </option>
              </select>
            </label>

            <div class="qen-field">
              参与者
              <div class="qen-chips">
                <span v-for="(name, i) in draft.participant_names" :key="draft.participant_ids[i]" class="qen-chip">
                  {{ name }}
                  <button class="qen-chip-x" @click="removeParticipant(i)">×</button>
                </span>
                <select class="qen-add" @change="addParticipant(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
                  <option value="">＋ 添加…</option>
                  <option v-for="e in entities.filter((x) => x.entity_type === 'character')" :key="e.id" :value="e.id">
                    {{ e.name }}
                  </option>
                </select>
              </div>
              <span v-if="draft.unresolved_names.length" class="qen-unresolved">
                名单外：{{ draft.unresolved_names.join('、') }}（未计入，可手动补）
              </span>
            </div>

            <div class="qen-grid">
              <label class="qen-field">
                地点
                <select :value="draft.location_id || ''" @change="setLocation(($event.target as HTMLSelectElement).value)">
                  <option value="">（无）</option>
                  <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
                </select>
              </label>
              <label class="qen-field">
                时刻
                <span class="qen-ymd">
                  第
                  <input v-model.number="draftYear" class="qen-ymd-year" type="number" min="1" step="1" />
                  年
                  <input v-model.number="draftMonth" type="number" min="1" max="12" step="1" />
                  月
                  <input v-model.number="draftDay" type="number" min="1" max="30" step="1" />
                  日
                </span>
                <span class="qen-preview">{{ timePreview }}</span>
              </label>
              <label v-if="draft.event_type === 'move'" class="qen-field">
                持续天数
                <input
                  :value="draft.time_end - draft.time_start"
                  type="number"
                  min="0"
                  step="1"
                  @input="draft.time_end = draft.time_start + Math.max(0, Number(($event.target as HTMLInputElement).value) || 0)"
                />
              </label>
            </div>

            <label class="qen-field">
              备注
              <input v-model="draft.note" type="text" maxlength="120" placeholder="谁对谁做了什么（可改）" />
            </label>
          </div>

          <div class="qen-actions">
            <button class="qen-btn" @click="draft = null">← 重新速记</button>
            <button class="qen-btn primary" :disabled="saving" @click="commit">
              {{ saving ? '入账中…' : '记入世界' }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- 撤销胶囊（自管，6 秒） -->
    <div v-if="capsule" class="qen-capsule">
      <span>已记录：{{ capsule.label }}</span>
      <button class="qen-capsule-undo" @click="undo">撤销</button>
    </div>
  </Teleport>
</template>

<style scoped>
.qen-overlay {
  position: fixed;
  inset: 0;
  z-index: 95;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 18vh;
}
.qen-modal {
  width: 460px;
  max-width: calc(100vw - 32px);
  background: var(--bg-panel, #fff);
  border: 1px solid var(--border-color);
  border-radius: 0.6rem;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.22);
  padding: 0.8rem 0.9rem;
}
.qen-head {
  display: flex;
  align-items: center;
  margin-bottom: 0.5rem;
}
.qen-title {
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--text-primary);
}
.qen-close {
  margin-left: auto;
  background: none;
  border: none;
  font-size: 1.05rem;
  color: var(--text-muted);
  cursor: pointer;
}
.qen-hint {
  font-size: 0.72rem;
  color: var(--text-muted);
  margin: 0 0 0.5rem;
  line-height: 1.5;
}
.qen-row {
  display: flex;
  gap: 0.5rem;
}
.qen-input {
  flex: 1;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--border-color);
  border-radius: 0.35rem;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 0.82rem;
}
.qen-btn {
  padding: 0.4rem 0.9rem;
  border: 1px solid var(--border-color);
  border-radius: 0.35rem;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 0.78rem;
  cursor: pointer;
}
.qen-btn.primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}
.qen-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.qen-warn {
  font-size: 0.72rem;
  color: #d4a017;
  background: rgba(212, 160, 23, 0.08);
  border-radius: 0.3rem;
  padding: 0.35rem 0.5rem;
  margin-bottom: 0.5rem;
}
.qen-form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.qen-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.72rem;
  color: var(--text-muted);
}
.qen-field select,
.qen-field input {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.3rem;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 0.78rem;
}
.qen-preview {
  font-size: 0.68rem;
  color: var(--accent-500);
}
.qen-ymd {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}
.qen-ymd input {
  width: 3rem;
  text-align: center;
}
.qen-ymd input.qen-ymd-year {
  width: 3.8rem;
}
.qen-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.6rem;
}
.qen-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}
.qen-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.12rem 0.5rem;
  border: 1px solid var(--accent-500);
  border-radius: 999px;
  color: var(--accent-500);
  font-size: 0.72rem;
}
.qen-chip-x {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  padding: 0;
  font-size: 0.8rem;
  line-height: 1;
}
.qen-add {
  padding: 0.2rem 0.4rem;
  border: 1px dashed var(--border-color);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font-size: 0.7rem;
}
.qen-unresolved {
  font-size: 0.66rem;
  color: var(--text-muted);
  font-style: italic;
}
.qen-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.7rem;
}

.qen-capsule {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 96;
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.45rem 0.8rem;
  background: var(--bg-panel, #2a2a33);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
  font-size: 0.75rem;
  color: var(--text-primary);
}
.qen-capsule-undo {
  background: none;
  border: 1px solid var(--accent-500);
  border-radius: 999px;
  color: var(--accent-500);
  font-size: 0.7rem;
  padding: 0.12rem 0.6rem;
  cursor: pointer;
}
</style>
