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
    console.warn('[QuickEventNote] 记入世界失败', e)
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
          <p class="qen-hint">一句话记下刚发生的剧情事实，AI 整理成事件草稿，你过目后才记入世界。</p>
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
            <button class="qen-btn btn-primary-instrument" :disabled="parsing || !inputText.trim()" @click="parse">
              {{ parsing ? '整理中…' : '整理' }}
            </button>
          </div>
        </template>

        <template v-else>
          <!-- 解析置信提示 -->
          <div v-if="confidence !== 'high'" class="qen-warn">
            {{
              confidence === 'none'
                ? '未能自动解析——直接按下表手填即可。'
                : '整理把握不高——请核对草稿，认可后再记入世界。'
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
            <button class="qen-btn btn-ghost" @click="draft = null">← 重新速记</button>
            <button class="qen-btn btn-primary-instrument" :disabled="saving" @click="commit">
              {{ saving ? '记入中…' : '记入世界' }}
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
/* 共享结构/配色收 style.css 组件层 .qen-* 块（05 §7.6 双份合一）。
   本副本历史裸 rem 字号已于 P2（05 §9.2）统一映射最近 token 档——
   0.85→text-base / 0.78→text-xs / 0.8→text-sm / 0.72/0.7/0.68/0.66→text-xs；
   与 world 副本的 token 档漂移自此收敛（逐值映射表见 P2 施工报告）。 */
.qen-title { font-size: var(--text-base); }
.qen-hint { font-size: var(--text-xs); }
.qen-btn { font-size: var(--text-xs); }
.qen-warn { font-size: var(--text-xs); }
.qen-field { font-size: var(--text-xs); }
.qen-field select,
.qen-field input { font-size: var(--text-xs); }
.qen-preview { font-size: var(--text-xs); }
.qen-chip { font-size: var(--text-xs); }
.qen-chip-x { font-size: var(--text-sm); }
.qen-add { font-size: var(--text-xs); }
.qen-unresolved { font-size: var(--text-xs); }
.qen-capsule-undo { font-size: var(--text-xs); }
</style>
