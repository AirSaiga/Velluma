<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, onScopeDispose, ref, watch } from 'vue'
import { worldApi } from '../../../services/api/domain/world.api'
import type { EventDraft } from '../../../services/api/domain/world.api'
import { formatTime, breakdownTime, fromYMD } from '../engine/timeFormat'
import { EVENT_TEMPLATES, getTemplate } from '../engine/eventTemplates'
import type { EventType, WorldEntity, WorldLocation, Point } from '../engine/types'
import { useEscStack } from '../../../composables/useEscStack'
import { useToast } from '../../../composables/useToast'

/**
 * 速记框（docs/world-writing-bridge.md W3 一句话记历史；2026-09-05 关联式录入升级）。
 *
 * 流程：一行口语 → parse-event 解析 → 预填轻表单（作者过目可改）→ 记入世界（既有
 * 事件创建端点）→ 撤销胶囊 6 秒可撤（删事件 + 连带删本次新建，见下）。解析失败降级空白表单。
 *
 * 关联式录入：解析返回的 new_entities/new_locations（速记里名单外的名字，后端
 * evidence 硬闸校验过）在过目单上呈现「同时新建」勾选区——名字可改、类型可改、
 * 默认勾选；入账串行「地点 → 实体 → 事件」（各端点幂等，用返回 id 回填引用）。
 * 口述原词在改名时回填 aliases（下次速记才认得出）。
 * 撤销语义=撤销「这次记账动作」整体：先删事件再删实体/地点（刚建的空壳不留）。
 *
 * 入口：Alt+N（捕获阶段；写作台传 require-in-field 保持「编辑器聚焦才唤起」，
 * 世界页缺省=页面激活即可）｜浮卡「记一笔」（velluma:quick-note 事件）。
 * 模态内「按模板逐栏录 →」emit open-template-form 桥接到世界页事件表单（单向：
 * 能进表单的人就是奔着表单来的）。committed 供世界页入账后刷新主数据。
 * 契约红线：系统绝不自作主张直接入账——解析结果必须过作者的手。
 */
const props = defineProps<{
  bookId: string | null
  chapterId: string | null
  /** 写作台 true：只在编辑器聚焦（写作上下文）才响应 Alt+N；世界页缺省 false */
  requireInField?: boolean
  /** 宿主有地图（世界页 true）：新地点行显示「放到地图」——点地图标位随本笔上图 */
  enableMapPick?: boolean
}>()
const emit = defineEmits<{
  /** 入账成功（世界页据此全量刷新事件/实体/地点） */
  committed: []
  /** 「按模板逐栏录 →」：关掉自己，由宿主打开结构化事件表单 */
  'open-template-form': []
  /** 新地点行点了「放到地图」：宿主进地图点选模式，点完回调 applyMapPoint */
  'request-map-pick': [index: number]
  /** 标点中点了取消：宿主清 pickingMode，组件自己恢复模态 */
  'request-map-pick-cancel': []
}>()

const QUICK_NOTE_EVENT = 'velluma:quick-note'
const CAPSULE_MS = 8000

const { showToast } = useToast()

const visible = ref(false)
const inputText = ref('')
const parsing = ref(false)
const confidence = ref<'high' | 'low' | 'none'>('none')
const draft = ref<EventDraft | null>(null)
const saving = ref(false)
const entities = ref<WorldEntity[]>([])
const locations = ref<WorldLocation[]>([])

// ---- 「同时新建」勾选区（解析草稿的本地可编辑副本；original 留作 aliases 回填）----
interface EditableEntityDraft {
  checked: boolean
  name: string
  kind: string
  evidence: string
  original: string
}
interface EditableLocationDraft {
  checked: boolean
  name: string
  evidence: string
  original: string
  /** 地图上标的位置（enableMapPick 时「放到地图」回灌；有=入账即上图） */
  point: Point | null
}
const newEntDrafts = ref<EditableEntityDraft[]>([])
const newLocDrafts = ref<EditableLocationDraft[]>([])

// 地图标点进行中：模态收成顶部悬浮条让出地图视野，pickIndex 记正在标哪一行
const pickIndex = ref<number | null>(null)
const minimized = computed(() => pickIndex.value !== null)

// Esc 分层关闭栈（00 期 §4.2）：开即入栈、关即出栈，替代 window capture 抢跑监听
// （旧路径在速记上叠 ConfirmDialog 时一次 Esc 两层同关）。
// **标点收起态同样出栈**（2026-09-07 审计修复）：悬浮条承诺的「Esc 取消」只取消
// 标点——栈层若仍压顶，Esc 会先命中 close() 把整张草稿销毁，而 WorldView 的
// 取消分支（只退标点、恢复模态保草稿）因 defaultPrevented 永不可达
const qenEsc = useEscStack()
let qenEscId: symbol | null = null
const escActive = computed(() => visible.value && !minimized.value)
watch(escActive, (on) => {
  if (on && !qenEscId) qenEscId = qenEsc.push(() => close(), 'quick-event-note')
  else if (!on && qenEscId) {
    qenEsc.remove(qenEscId)
    qenEscId = null
  }
})
onScopeDispose(() => {
  if (qenEscId) qenEsc.remove(qenEscId)
})

/** 这句话更像设定不像事件时（解析把握低 + custom + 无参与者），允许只建名字不记事件 */
const skipEvent = ref(false)
const canSkipEvent = computed(
  () =>
    confidence.value !== 'high' &&
    !!draft.value &&
    draft.value.event_type === 'custom' &&
    draft.value.participant_ids.length === 0 &&
    (newEntDrafts.value.some((d) => d.checked) || newLocDrafts.value.some((d) => d.checked)),
)

// 撤销胶囊（自管，不动通用 Toast——useToast 无动作按钮）：连带删本次新建。
// failed=true 是部分失败态（无「已记录」前缀、按钮语义改为只撤已建产物）——
// 与成功态共用容器但语义区分，防「撤销」与「再点一次续上」两个相反动作混淆
const capsule = ref<{
  eventId: string | null
  createdEntityIds: string[]
  createdLocationIds: string[]
  label: string
  failed?: boolean
} | null>(null)
let capsuleTimer: number | null = null

function openWith(prefill?: string) {
  if (!props.bookId) return
  visible.value = true
  if (prefill && !inputText.value) inputText.value = prefill
  // 名单每次打开都刷新（2026-09-06 审计修复）：旧「只在空时加载」让缓存与库脱节，
  // commit 的幂等误删防线（快照）会建立在过期名单上；顺带保住下拉的新鲜度
  void loadRoster()
}
function close() {
  visible.value = false
  parsing.value = false
  draft.value = null
  inputText.value = ''
  confidence.value = 'none'
  newEntDrafts.value = []
  newLocDrafts.value = []
  skipEvent.value = false
  // 标点中关速记（Alt+N 翻关/Esc）：同步撤掉宿主的地图点选态，防悬空
  if (pickIndex.value !== null) emit('request-map-pick-cancel')
  pickIndex.value = null
}

/** 刷新实体/地点名单。@returns 是否成功（失败时旧缓存仍在，仅供表单下拉应急） */
async function loadRoster(): Promise<boolean> {
  if (!props.bookId) return false
  try {
    const [ents, locs] = await Promise.all([
      worldApi.listEntities(props.bookId),
      worldApi.listLocations(props.bookId),
    ])
    entities.value = ents || []
    locations.value = locs || []
    return true
  } catch {
    /* 名单缺席时表单仍可用（手填不了就取消）；commit 侧另有防线 */
    return false
  }
}

// ---- 解析 ----
async function parse() {
  if (!props.bookId || !inputText.value.trim()) return
  parsing.value = true
  try {
    const r = await worldApi.parseEvent(props.bookId, props.chapterId, inputText.value.trim())
    draft.value = r.draft
    confidence.value = r.confidence
    newEntDrafts.value = (r.new_entities || []).map((d) => ({
      checked: true,
      name: d.name,
      kind: d.kind === 'faction' || d.kind === 'asset' ? d.kind : 'character',
      evidence: d.evidence,
      original: d.name,
    }))
    newLocDrafts.value = (r.new_locations || []).map((d) => ({
      checked: true,
      name: d.name,
      evidence: d.evidence,
      original: d.name,
      point: null,
    }))
  } catch {
    draft.value = null
    confidence.value = 'none'
    newEntDrafts.value = []
    newLocDrafts.value = []
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
function openTemplateForm() {
  emit('open-template-form')
  close()
}

// ---- 新地点地图标点（enableMapPick）：收起模态让出地图 → 宿主点选回调回灌 ----
function startMapPick(index: number) {
  if (pickIndex.value !== null) return
  pickIndex.value = index
  emit('request-map-pick', index)
}
/** 宿主点选完成（WorldView 的 map pick 分流） */
function applyMapPoint(index: number, point: Point) {
  const nd = newLocDrafts.value[index]
  if (nd) nd.point = point
  pickIndex.value = null
}
/** 宿主点选取消（Esc / 悬浮条取消） */
function cancelMapPick() {
  pickIndex.value = null
}
function cancelPick() {
  emit('request-map-pick-cancel')
  cancelMapPick()
}

// ---- 入账：地点 → 实体 → 事件（串行；各端点幂等，失败中断不脏）----
const _ENTITY_KINDS = new Set(['character', 'faction', 'asset'])

async function commit() {
  const d = draft.value
  if (!d || !props.bookId || saving.value) return
  saving.value = true
  // 拍快照前重拉名单（2026-09-06 审计修复）：快照防线只在「与库上一致」时成立——
  // 组件常驻挂起，其他入口（InlineCreate/抽屉/候选池/AI 沉淀）随时可能建新实体；
  // 旧缓存缺它时幂等创建返回的既有 id 会被误记进撤销清单，8 秒撤销即删掉有历史
  // 的既有物。
  // 刷新失败且有勾选新建行时直接中止（2026-09-07 审计修复）：回落旧缓存的假设
  // 「后续创建多半同样失败」对瞬时失败不成立（列表查询更重易超时，POST 更轻），
  // 宁停勿错——撤销误删是地点子树级联删，代价不可逆
  const rosterFresh = await loadRoster()
  const hasNewPicks =
    newEntDrafts.value.some((d) => d.checked && d.name.trim()) ||
    newLocDrafts.value.some((d) => d.checked && d.name.trim())
  if (!rosterFresh && hasNewPicks) {
    saving.value = false
    showToast('名单刷新失败——为防「撤销」误删既有设定，这笔先不记，请稍后重试', 'warning')
    return
  }
  // 快照既有名单 id：勾选行名字可编辑，作者可能改成既有实体/地点的名——幂等闸
  // 命中时返回的是旧物，照常并入引用但绝不进撤销清单（否则撤销会删掉有自己
  // 历史的既有实体，地点甚至是整棵子树+canon 级联——P0 审查修复 2026-09-05）
  const preEntityIds = new Set(entities.value.map((e) => e.id))
  const preLocationIds = new Set(locations.value.map((l) => l.id))
  const createdLocationIds: string[] = []
  const createdEntityIds: string[] = []
  const createdJustNowNames: string[] = []
  try {
    // ① 勾选的新地点：有标点带坐标上图，否则无坐标建档（补坐标随时可在地图点选，绝不伪造）
    for (const nd of newLocDrafts.value) {
      if (!nd.checked || !nd.name.trim()) continue
      const loc = await worldApi.createLocation(props.bookId, {
        name: nd.name.trim(),
        ...(nd.point ? { coord_x: nd.point[0], coord_y: nd.point[1] } : {}),
      })
      if (!preLocationIds.has(loc.id)) {
        createdLocationIds.push(loc.id)
        createdJustNowNames.push(loc.name)
        locations.value = [...locations.value, loc]
      }
      // 解析没匹配到地点而作者勾了新地点 → 第一个勾选地点就是发生地
      if (!d.location_id) {
        d.location_id = loc.id
        d.location_name = loc.name
      }
    }
    // ② 勾选的新实体：改名时口述原词回填 aliases（下次速记名单匹配才认得出）
    for (const nd of newEntDrafts.value) {
      if (!nd.checked || !nd.name.trim()) continue
      const name = nd.name.trim()
      const kind = _ENTITY_KINDS.has(nd.kind) ? (nd.kind as 'character' | 'faction' | 'asset') : 'character'
      const ent = await worldApi.createEntity(props.bookId, {
        entity_type: kind,
        name,
        aliases: nd.original !== name ? [nd.original] : undefined,
      })
      if (!preEntityIds.has(ent.id)) {
        createdEntityIds.push(ent.id)
        createdJustNowNames.push(ent.name)
        entities.value = [...entities.value, ent]
      }
      // 新角色自动并入参与者（幂等创建命中既有实体时同样并入，去重）
      if (kind === 'character' && !d.participant_ids.includes(ent.id)) {
        d.participant_ids.push(ent.id)
        d.participant_names.push(ent.name)
      }
    }
    // ③ 事件（只建档模式跳过）
    let eventId: string | null = null
    if (!skipEvent.value) {
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
      eventId = ev.id
    }
    // 成功 label 用真实新建名（createdJustNowNames）：改名命中既有实体时勾选名≠新建，
    // 说「新建 白塞翁」就是撒谎；零新建（全部幂等命中）回落事件摘要
    const label = [
      ...(eventId ? [d.summary || typeLabel.value] : createdJustNowNames.length ? ['只建档'] : ['未新建（名字已存在）']),
      createdJustNowNames.length ? `新建 ${createdJustNowNames.join('、')}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
    showCapsule({ eventId, createdEntityIds, createdLocationIds, label })
    close()
    window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
    emit('committed')
  } catch (e) {
    // 部分失败：已建的实体/地点是作者勾选确认过的真实设定，不回滚（世界账本没有
    // 事务，只有作者确认过的事实）；草稿保留，重试时幂等闸不会重复建
    console.warn('[QuickEventNote] 入账失败', e)
    showCapsule({
      eventId: null,
      createdEntityIds,
      createdLocationIds,
      failed: true,
      label:
        (createdJustNowNames.length ? `${createdJustNowNames.join('、')} 已建，` : '') +
        '这笔记没记上——再点一次「记入世界」续上',
    })
  } finally {
    saving.value = false
  }
}

function showCapsule(c: { eventId: string | null; createdEntityIds: string[]; createdLocationIds: string[]; label: string; failed?: boolean }) {
  capsule.value = c
  if (capsuleTimer) window.clearTimeout(capsuleTimer)
  // 多产物时读完标题就需要几秒，6 秒偏紧——8 秒起步
  capsuleTimer = window.setTimeout(() => (capsule.value = null), CAPSULE_MS)
}

async function undo() {
  if (!capsule.value || !props.bookId) return
  const { eventId, createdEntityIds, createdLocationIds } = capsule.value
  capsule.value = null
  if (capsuleTimer) window.clearTimeout(capsuleTimer)
  // 撤销顺序：先删事件（摘掉对新建实体的唯一引用）→ 实体 → 地点；尽力而为逐个删
  try {
    if (eventId) await worldApi.deleteEvent(props.bookId, eventId)
    for (const id of createdEntityIds) await worldApi.deleteEntity(props.bookId, id).catch(() => {})
    for (const id of createdLocationIds) await worldApi.deleteLocation(props.bookId, id).catch(() => {})
    // 本地名单同步剔除已删项：缓存与库即刻一致（openWith 的刷新是下次打开才兜底）
    entities.value = entities.value.filter((e) => !createdEntityIds.includes(e.id))
    locations.value = locations.value.filter((l) => !createdLocationIds.includes(l.id))
    window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
    emit('committed')
  } catch (e) {
    console.warn('[QuickEventNote] 撤销失败', e)
  }
}

// ---- 快捷键（Alt+N，捕获阶段）+ 浮卡入口事件 ----
function onKeydown(e: KeyboardEvent) {
  if (e.altKey && !e.ctrlKey && !e.shiftKey && e.code === 'KeyN') {
    const target = e.target as HTMLElement | null
    const inField = target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    if (visible.value) {
      e.preventDefault()
      close()
      return
    }
    if (props.requireInField && !inField) return // 写作台：只在写作上下文唤起（世界页不受此限）
    e.preventDefault()
    e.stopPropagation()
    openWith()
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

defineExpose({ openWith, applyMapPoint, cancelMapPick })
</script>

<template>
  <Teleport to="body">
    <!-- 速记模态（标点中收起让出地图，顶部悬浮条接管提示） -->
    <div v-if="visible && !minimized" class="qen-overlay" @click.self="close">
      <div class="qen-modal">
        <div class="qen-head">
          <span class="qen-title">记一笔 · 世界速记</span>
          <button class="qen-close" @click="close">×</button>
        </div>

        <template v-if="!draft">
          <p class="qen-hint">一句话记下刚发生的剧情事实，AI 整理成事件草稿，你过目后才记入世界。新提到的人名、地名也会一并认出来。</p>
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
          <button class="qen-template-link" @click="openTemplateForm">
            想精确选类型、在地图上圈画？按模板逐栏录 →
          </button>
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
                名单外：{{ draft.unresolved_names.join('、') }}（未计入，可在下方勾选建档或手动补）
              </span>
            </div>

            <!-- 关联式录入：速记里名单外的名字，勾选即随本笔一并建档 -->
            <div v-if="newEntDrafts.length || newLocDrafts.length" class="qen-new">
              <div class="qen-new-title">这句话里的新名字（勾选即一并建立）：</div>
              <label v-for="(nd, i) in newEntDrafts" :key="'e' + i" class="qen-new-row">
                <input v-model="nd.checked" type="checkbox" />
                <input v-model="nd.name" class="qen-new-name" />
                <select v-model="nd.kind" class="qen-new-kind">
                  <option value="character">角色</option>
                  <option value="faction">势力</option>
                  <option value="asset">资产</option>
                </select>
                <span class="qen-new-evidence" :title="nd.evidence">「{{ nd.evidence }}」</span>
              </label>
              <label v-for="(nd, i) in newLocDrafts" :key="'l' + i" class="qen-new-row">
                <input v-model="nd.checked" type="checkbox" />
                <input v-model="nd.name" class="qen-new-name" />
                <span class="qen-new-kind qen-new-kind--loc">地点</span>
                <button
                  v-if="enableMapPick"
                  type="button"
                  class="qen-map-btn"
                  :title="nd.point ? '重新在地图上点选位置' : '在地图上点选位置（建后直接上图）'"
                  @click.prevent="startMapPick(i)"
                >{{ nd.point ? `已标 (${nd.point[0].toFixed(0)}, ${nd.point[1].toFixed(0)})` : '放到地图' }}</button>
                <span class="qen-new-evidence" :title="nd.evidence">「{{ nd.evidence }}」{{ nd.point ? '' : ' · 暂未放置到地图' }}</span>
              </label>
              <label v-if="canSkipEvent" class="qen-skip-row">
                <input v-model="skipEvent" type="checkbox" />
                只建上面勾选的名字，不记事件（这更像一条设定）
              </label>
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
              {{ saving ? '记入中…' : skipEvent ? '建立名字' : '记入世界' }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- 撤销胶囊（自管，8 秒；连带删本次新建的实体/地点。failed=部分失败态：
         无「已记录」前缀，按钮只撤已建产物） -->
    <div v-if="capsule" class="qen-capsule" :class="{ 'qen-capsule--warn': capsule.failed }">
      <span>{{ capsule.failed ? capsule.label : `已记录：${capsule.label}` }}</span>
      <button class="qen-capsule-undo" @click="undo">{{ capsule.failed ? '撤销已建' : '撤销' }}</button>
    </div>

    <!-- 地图标点中：模态收成顶部悬浮条让出地图视野（宿主 pickingMode='quick-note'） -->
    <div v-if="visible && minimized" class="qen-pickbar">
      <span>在地图上点选「{{ newLocDrafts[pickIndex ?? 0]?.name || '新地点' }}」的位置…（Esc 取消）</span>
      <button class="qen-pickbar-cancel" @click="cancelPick()">取消</button>
    </div>
  </Teleport>
</template>

<style scoped>
/* 共享结构/配色收 style.css 组件层 .qen-* 块（05 §7.6 双份合一）。
   此处仅保留本副本 token 档字号 + 胶囊/撤销钮的两条本副本独有声明
   （max-width / flex-shrink）；workspace 副本保留其裸 rem 覆盖，漂移
   统一留 P2（01 §9-5 裸字号项）。 */
.qen-title { font-size: var(--text-lg); }
.qen-hint { font-size: var(--text-xs); }
.qen-btn { font-size: var(--text-sm); }
.qen-warn { font-size: var(--text-xs); }
.qen-field { font-size: var(--text-xs); }
.qen-field select,
.qen-field input { font-size: var(--text-sm); }
.qen-preview { font-size: var(--text-xs); }
.qen-chip { font-size: var(--text-xs); }
.qen-chip-x { font-size: var(--text-xs); }
.qen-add { font-size: var(--text-xs); }
.qen-unresolved { font-size: var(--text-xs); }
.qen-capsule { max-width: calc(100vw - 48px); }
.qen-capsule-undo { font-size: var(--text-xs); flex-shrink: 0; }
</style>
