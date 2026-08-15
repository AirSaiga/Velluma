<script setup lang="ts">
/**
 * 事件录入/编辑面板（去表单化：选模板 → 预填 → ≤15 秒录一条）。
 *
 * 设计（照搬世界绘卷）：
 * - 表驱动模板（EVENT_TEMPLATES），requiredPayloadFields 决定显示哪些字段
 * - move 的 path 默认 from/to 直线，可「点选途经点」升级为折线（弧长插值已支持任意折线）
 * - territory_change 的 polygon 一律「在地图上圈绘」录入（不再手填坐标文本）
 * - 绘制交互：点「圈绘/点选」→ emit draw-start → 面板收起为顶部悬浮条（drawing prop 驱动
 *   ModalShell minimized，表单状态保留）→ 完成 drawResult 回灌对应字段
 * - 编辑模式：传入 existing 预填并走 updateEvent（event_type 不可改——
 *   payload 语义随类型而定，改类型等于换事件，应删除重建）
 */
import { ref, computed, watch } from 'vue'
import ModalShell from './ModalShell.vue'
import InlineCreate from './InlineCreate.vue'
import { EVENT_TEMPLATES, getTemplate, EVENT_TYPE_COLOR } from '../engine/eventTemplates'
import type { EventType, WorldEvent, Point, DrawMode } from '../engine/types'
import { fromYMD, breakdownTime } from '../engine/timeFormat'
import { useWorld } from '../composables/useWorld'

/** 绘制回灌结果（WorldView 在 draw-complete 后传入，watch 应用到对应字段） */
interface DrawResult {
  kind: Exclude<DrawMode, null>
  points: Point[]
}

const props = defineProps<{
  bookId: string
  existing?: WorldEvent | null
  /** 正在地图上绘制（面板收起为悬浮条） */
  drawing?: boolean
  drawResult?: DrawResult | null
  /** 新建事件的默认时刻（时间轴游标 / 右键时刻——游标即输入焦点） */
  initialTime?: number | null
  /** 预设事件类型（实体抽屉快捷动作：记录移动/死亡/疆域） */
  initialType?: EventType | null
  /** 预设角色（快捷动作带入实体 id） */
  presetCharacterId?: string | null
}>()
const emit = defineEmits<{
  saved: []
  cancel: []
  'draw-start': [kind: Exclude<DrawMode, null>]
  'draw-finish': []
  'draw-cancel': []
}>()

const { locations, characters, factions, createEvent, updateEvent } = useWorld()

const isEdit = computed(() => !!props.existing)

// ===== 表单状态（编辑模式预填）=====
const ex = props.existing
const exYmd = ex
  ? breakdownTime(ex.time_start)
  : props.initialTime != null
    ? breakdownTime(props.initialTime)
    : { year: 1, month: 1, day: 1 }

const selectedType = ref<EventType>(
  (ex?.event_type as EventType) || props.initialType || 'birth',
)
const year = ref(exYmd.year)
const month = ref(exYmd.month)
const day = ref(exYmd.day)
const note = ref(ex?.note || '')
const characterId = ref(
  (ex?.payload.character_id as string | undefined) || props.presetCharacterId || '',
)
const selectedCharacterIds = ref<string[]>(
  (ex?.payload.character_ids as string[] | undefined) ||
    (props.initialType === 'move' && props.presetCharacterId ? [props.presetCharacterId] : []),
)
const fromLocId = ref((ex?.payload.from_location_id as string | undefined) || '')
const toLocId = ref((ex?.payload.to_location_id as string | undefined) || '')
const locId = ref(
  (ex?.payload.location_id as string | undefined) || ex?.location_id || '',
)
const targetId = ref((ex?.payload.target_id as string | undefined) || '')

// move 途经点（不含起终点；提交时 path=[from, ...waypoints, to]）
const waypoints = ref<Point[]>(
  ex?.event_type === 'move'
    ? ((ex.payload.path as Point[] | undefined) || []).slice(1, -1)
    : [],
)

// territory_change 字段（polygon 结构化点数组，地图圈绘录入）
const territoryFactionId = ref((ex?.payload.faction_id as string | undefined) || '')
const territoryAction = ref<'gain' | 'lose' | 'establish'>(
  (ex?.payload.action as 'gain' | 'lose' | 'establish' | undefined) || 'gain',
)
const territoryPolygon = ref<Point[]>((ex?.payload.polygon as Point[] | undefined) || [])

// 当前在画哪一类（驱动悬浮条标题；draw-start 时记录，结果回灌/取消后清空）
const activeDrawKind = ref<Exclude<DrawMode, null> | null>(null)

function toggleCharacter(id: string) {
  const i = selectedCharacterIds.value.indexOf(id)
  if (i === -1) selectedCharacterIds.value = [...selectedCharacterIds.value, id]
  else selectedCharacterIds.value = [...selectedCharacterIds.value.filter((c) => c !== id)]
}

const template = computed(() => getTemplate(selectedType.value))
const requires = (field: string) => (template.value?.requiredPayloadFields || []).includes(field)

function locCoord(id: string): Point | null {
  const loc = locations.value.find((l) => l.id === id)
  if (loc && loc.coord_x != null && loc.coord_y != null) return [loc.coord_x, loc.coord_y]
  return null
}

/** move 起终点均有坐标时才允许点选途经点（否则路径无从锚定） */
const canPickWaypoints = computed(
  () => !!(fromLocId.value && toLocId.value && locCoord(fromLocId.value) && locCoord(toLocId.value)),
)

/** territory gain/establish 必须圈出 ≥3 顶点的多边形，否则禁提交 */
const territoryInvalid = computed(
  () =>
    selectedType.value === 'territory_change' &&
    territoryAction.value !== 'lose' &&
    territoryPolygon.value.length < 3,
)

function startDraw(kind: Exclude<DrawMode, null>) {
  activeDrawKind.value = kind
  emit('draw-start', kind)
}

// 绘制完成 → 结果回灌对应字段
watch(
  () => props.drawResult,
  (r) => {
    if (!r) return
    if (r.kind === 'territory') territoryPolygon.value = [...r.points]
    else if (r.kind === 'move-path') waypoints.value = [...r.points]
    activeDrawKind.value = null
  },
)
// 取消/外部结束绘制 → 清标记（结果保留与否由字段本身决定，取消时 draft 被地图丢弃）
watch(
  () => props.drawing,
  (d) => {
    if (!d) activeDrawKind.value = null
  },
)

const modalTitle = computed(() => {
  if (props.drawing) {
    return activeDrawKind.value === 'territory'
      ? '疆域圈绘中 · 连点加顶点，双击/Enter 闭合'
      : '途经点选择中 · 连点加途经点，双击/Enter 完成'
  }
  return isEdit.value ? '编辑事件' : '记录事件'
})

/** Enter 提交（焦点在按钮上时跳过——按钮有自己的点击语义） */
function onEnter(e: KeyboardEvent) {
  if ((e.target as HTMLElement).tagName === 'BUTTON') return
  submit()
}

async function submit() {
  if (territoryInvalid.value) return
  const t = fromYMD(year.value, month.value, day.value)
  let payload: Record<string, unknown> = {}
  let timeEnd = t
  let eventLocationId: string | null = locId.value || null

  if (selectedType.value === 'birth') {
    payload = { character_id: characterId.value, location_id: locId.value || null }
  } else if (selectedType.value === 'death') {
    payload = { character_id: characterId.value }
  } else if (selectedType.value === 'move') {
    const cids = selectedCharacterIds.value
    const fromC = locCoord(fromLocId.value)
    const toC = locCoord(toLocId.value)
    payload = {
      character_ids: cids,
      from_location_id: fromLocId.value,
      to_location_id: toLocId.value,
      path: fromC && toC ? [fromC, ...waypoints.value, toC] : [],
    }
    // move 持续区间：新建默认 30 天；编辑保留原时长
    const duration = ex && ex.event_type === 'move' ? ex.time_end - ex.time_start : 30
    timeEnd = t + duration
    eventLocationId = fromLocId.value || null
  } else if (selectedType.value === 'found' || selectedType.value === 'destroy') {
    payload = { target_id: targetId.value }
    eventLocationId = targetId.value || null
  } else if (selectedType.value === 'territory_change') {
    const polygon = territoryAction.value === 'lose' ? [] : territoryPolygon.value
    payload = {
      faction_id: territoryFactionId.value,
      polygon,
      action: territoryAction.value,
    }
  }

  if (isEdit.value && ex) {
    await updateEvent(props.bookId, ex.id, {
      time_start: t,
      time_end: timeEnd,
      location_id: eventLocationId,
      payload,
      note: note.value,
    })
  } else {
    await createEvent(props.bookId, {
      event_type: selectedType.value,
      time_start: t,
      time_end: timeEnd,
      location_id: eventLocationId,
      payload,
      note: note.value,
    })
  }
  emit('saved')
}
</script>

<template>
  <ModalShell
    :title="modalTitle"
    :subtitle="drawing ? '' : '事件是世界状态的唯一事实源——谁在哪、谁活着、疆域如何，都由事件流推演'"
    width="480px"
    :minimized="drawing"
    @close="emit('cancel')"
  >
    <!-- 收起态悬浮条动作 -->
    <template #bar-actions>
      <button class="bar-btn" @click="emit('draw-cancel')">取消</button>
      <button class="bar-btn bar-btn--primary" @click="emit('draw-finish')">完成</button>
    </template>
    <div class="qc-body" @keydown.enter="onEnter">
    <!-- 模板选择（编辑模式锁定类型） -->
    <div class="qc-row">
      <label class="qc-label">模板</label>
      <div v-if="!isEdit" class="qc-templates">
        <button
          v-for="t in EVENT_TEMPLATES"
          :key="t.type"
          class="qc-tpl"
          :class="{ active: t.type === selectedType }"
          @click="selectedType = t.type"
        >
          <span class="qc-dot" :style="{ background: EVENT_TYPE_COLOR[t.type] }"></span>
          {{ t.label }}
        </button>
      </div>
      <div v-else class="qc-templates">
        <span class="qc-tpl qc-tpl--locked active">
          <span class="qc-dot" :style="{ background: EVENT_TYPE_COLOR[selectedType] }"></span>
          {{ template?.label }}
        </span>
      </div>
      <div class="qc-desc">{{ template?.description }}</div>
    </div>

    <div class="qc-row">
      <label class="qc-label">时间</label>
      <div class="qc-time">
        第 <input v-model.number="year" type="number" min="1" class="qc-num" /> 年
        <input v-model.number="month" type="number" min="1" max="12" class="qc-num" /> 月
        <input v-model.number="day" type="number" min="1" max="30" class="qc-num" /> 日
      </div>
    </div>

    <div v-if="requires('character_id')" class="qc-row">
      <label class="qc-label">角色</label>
      <div class="qc-selrow">
        <select v-model="characterId" class="qc-select">
          <option value="">选择角色</option>
          <option v-for="c in characters" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <InlineCreate :book-id="bookId" kind="character" @created="characterId = $event.id" />
      </div>
    </div>

    <div v-if="selectedType === 'birth'" class="qc-row">
      <label class="qc-label">出生地</label>
      <div class="qc-selrow">
        <select v-model="locId" class="qc-select">
          <option value="">（无）</option>
          <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
        </select>
        <InlineCreate :book-id="bookId" kind="location" @created="locId = $event.id" />
      </div>
    </div>

    <template v-if="selectedType === 'move'">
      <div class="qc-row">
        <label class="qc-label">角色（可多选）</label>
        <div class="qc-chips">
          <button
            v-for="c in characters"
            :key="c.id"
            type="button"
            class="qc-chip"
            :class="{ active: selectedCharacterIds.includes(c.id) }"
            @click="toggleCharacter(c.id)"
          >{{ c.name }}</button>
          <span v-if="!characters.length" class="qc-empty-hint">点 ＋ 快速创建角色</span>
          <InlineCreate :book-id="bookId" kind="character" @created="toggleCharacter($event.id)" />
        </div>
      </div>
      <div class="qc-grid2">
        <div class="qc-row">
          <label class="qc-label">从</label>
          <div class="qc-selrow">
            <select v-model="fromLocId" class="qc-select">
              <option value="">起点</option>
              <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
            </select>
            <InlineCreate :book-id="bookId" kind="location" @created="fromLocId = $event.id" />
          </div>
        </div>
        <div class="qc-row">
          <label class="qc-label">到</label>
          <div class="qc-selrow">
            <select v-model="toLocId" class="qc-select">
              <option value="">终点</option>
              <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
            </select>
            <InlineCreate :book-id="bookId" kind="location" @created="toLocId = $event.id" />
          </div>
        </div>
      </div>
      <div v-if="fromLocId && toLocId" class="qc-path-row">
        <template v-if="canPickWaypoints">
          <button
            v-if="waypoints.length === 0"
            type="button"
            class="qc-draw-btn"
            @click="startDraw('move-path')"
          >
            在地图上点选途经点
          </button>
          <div v-else class="qc-draw-summary">
            <span class="qc-draw-ok">✓ 起点 → {{ waypoints.length }} 个途经点 → 终点</span>
            <button type="button" class="qc-link" @click="startDraw('move-path')">重新点选</button>
            <button type="button" class="qc-link" @click="waypoints = []">清除</button>
          </div>
        </template>
        <div class="qc-hint">
          {{ waypoints.length ? '路径沿「起点→途经点→终点」折线，在途位置按弧长插值' : '不点选则自动从「起点→终点」连成直线（在途位置沿路插值）' }}
        </div>
      </div>
    </template>

    <div v-if="requires('target_id')" class="qc-row">
      <label class="qc-label">目标地点</label>
      <div class="qc-selrow">
        <select v-model="targetId" class="qc-select">
          <option value="">选择地点</option>
          <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
        </select>
        <InlineCreate :book-id="bookId" kind="location" @created="targetId = $event.id" />
      </div>
    </div>

    <template v-if="selectedType === 'territory_change'">
      <div class="qc-grid2">
        <div class="qc-row">
          <label class="qc-label">势力</label>
          <div class="qc-selrow">
            <select v-model="territoryFactionId" class="qc-select">
              <option value="">选择势力</option>
              <option v-for="f in factions" :key="f.id" :value="f.id">{{ f.name }}</option>
            </select>
            <InlineCreate :book-id="bookId" kind="faction" @created="territoryFactionId = $event.id" />
          </div>
        </div>
        <div class="qc-row">
          <label class="qc-label">动作</label>
          <select v-model="territoryAction" class="qc-select">
            <option value="gain">gain（获得/设定疆域）</option>
            <option value="establish">establish（建立）</option>
            <option value="lose">lose（失去全部疆域）</option>
          </select>
        </div>
      </div>
      <div v-if="territoryAction !== 'lose'" class="qc-row">
        <label class="qc-label">疆域范围</label>
        <button
          v-if="territoryPolygon.length === 0"
          type="button"
          class="qc-draw-btn"
          @click="startDraw('territory')"
        >
          在地图上圈绘
        </button>
        <div v-else class="qc-draw-summary">
          <span class="qc-draw-ok">✓ 已圈绘 {{ territoryPolygon.length }} 个顶点</span>
          <button type="button" class="qc-link" @click="startDraw('territory')">重新圈绘</button>
          <button type="button" class="qc-link" @click="territoryPolygon = []">清除</button>
        </div>
        <div class="qc-hint" :class="{ 'qc-hint--warn': territoryInvalid }">
          {{ territoryInvalid ? '需要至少 3 个顶点才能构成疆域' : '拖时间线可见疆域随时间变化' }}
        </div>
      </div>
    </template>

    <div class="qc-row">
      <label class="qc-label">备注</label>
      <input v-model="note" placeholder="（可选）发生了什么" class="qc-input" />
      <div class="qc-hint qc-hint--dim">
        小贴士：备注中写 @x,y（如 @500,300）可把事件定位到地图任意点
      </div>
    </div>
    </div>

    <template #footer>
      <button class="wbtn" @click="emit('cancel')">取消</button>
      <button
        class="wbtn wbtn--primary"
        :disabled="territoryInvalid"
        :title="territoryInvalid ? '请先在地图上圈绘至少 3 个顶点的疆域' : ''"
        @click="submit"
      >
        {{ isEdit ? '保存修改' : '记录' }}
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
.qc-row {
  margin-bottom: 14px;
}
.qc-label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.qc-templates {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.qc-tpl {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  background: var(--bg-canvas);
  font-size: 12px;
  color: var(--text-secondary);
  font-family: inherit;
  cursor: pointer;
  transition: all 0.13s;
}
.qc-tpl:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.qc-tpl.active {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.1);
  color: var(--accent-500);
  font-weight: 600;
}
.qc-tpl--locked {
  cursor: default;
}
.qc-dot {
  width: 7px;
  height: 7px;
  border-radius: 9999px;
}
.qc-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 7px;
}
.qc-time {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  color: var(--text-secondary);
}
.qc-num {
  width: 56px;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 13px;
  font-family: ui-monospace, monospace;
}
.qc-num:focus {
  outline: none;
  border-color: var(--accent-500);
}
.qc-input,
.qc-select {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  transition: border-color 0.15s;
}
.qc-input:focus,
.qc-select:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.12);
}
.qc-selrow {
  display: flex;
  align-items: center;
  gap: 6px;
}
.qc-selrow .qc-select {
  flex: 1;
  min-width: 0;
}
.qc-grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.qc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.qc-chip {
  padding: 5px 12px;
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  background: var(--bg-canvas);
  font-size: 12px;
  color: var(--text-secondary);
  font-family: inherit;
  cursor: pointer;
  transition: all 0.13s;
}
.qc-chip.active {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.12);
  color: var(--accent-500);
  font-weight: 600;
}
.qc-empty-hint {
  font-size: 12px;
  color: var(--text-muted);
}
.qc-hint {
  font-size: 12px;
  color: #a855f7;
  margin-top: 5px;
}
.qc-hint--dim {
  color: var(--text-muted);
}
.qc-hint--warn {
  color: #d97706;
}

/* 绘制入口按钮：虚线框，邀请「去地图上画」 */
.qc-draw-btn {
  width: 100%;
  padding: 9px 12px;
  border: 1.5px dashed var(--accent-500);
  border-radius: 9px;
  background: rgba(124, 106, 173, 0.05);
  color: var(--accent-500);
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.qc-draw-btn:hover {
  background: rgba(124, 106, 173, 0.12);
}
.qc-draw-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.qc-draw-ok {
  color: var(--text-primary);
  font-weight: 600;
}
.qc-link {
  border: none;
  background: none;
  padding: 0;
  font-size: 12px;
  color: var(--accent-500);
  font-family: inherit;
  cursor: pointer;
}
.qc-link:hover {
  text-decoration: underline;
}
.qc-path-row {
  margin-top: 4px;
}

/* 悬浮条按钮（收起态） */
.bar-btn {
  padding: 5px 14px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.13s;
}
.bar-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.bar-btn--primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}
.bar-btn--primary:hover {
  background: var(--accent-600);
  border-color: var(--accent-600);
  color: #fff;
}
.wbtn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* footer 按钮（与 WorldView 同一套 wbtn 体系，模态内局部复刻） */
.wbtn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease-out;
}
.wbtn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
  background: rgba(124, 106, 173, 0.06);
}
.wbtn--primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}
.wbtn--primary:hover:not(:disabled) {
  background: var(--accent-600);
  border-color: var(--accent-600);
  color: #fff;
  box-shadow: 0 4px 12px rgba(124, 106, 173, 0.25);
  transform: translateY(-1px);
}
</style>
