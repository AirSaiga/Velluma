<script setup lang="ts">
/**
 * 实体详情抽屉（M2：替代 CharacterPanel 大表单——档案是"长"出来的，不是"填"出来的）。
 *
 * 三段式：① 身份区（名字/别名/可见性/重要度/一句话）② 档案区（schema 表驱动，
 * 「+ 添加字段」按需出现，失焦即存无保存键）③ 编年史（涉及其的事件按时间排）+
 * 快捷事态动作（记录移动/死亡/疆域——全部只是预填事件表单，绝不越轨产生非事件数据）。
 *
 * 轻量编辑不进 undo（与改名/坐标微调同策略）。
 */
import { ref, computed, nextTick, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { useToast } from '../../../composables/useToast'
import { archiveFields } from '../engine/entitySchema'
import { formatTime } from '../engine/timeFormat'
import { getTemplate } from '../engine/eventTemplates'
import type { WorldEntity, WorldEvent, EventType } from '../engine/types'

const props = defineProps<{ bookId: string; entityId: string }>()

const emit = defineEmits<{
  close: []
  'quick-event': [type: EventType, entityId: string]
  'focus-event': [ev: WorldEvent]
}>()

const {
  entities,
  events,
  updateEntityArchive,
} = useWorld()
const { showToast } = useToast()

const entity = computed(
  () => entities.value.find((e) => e.id === props.entityId) || null,
)

const typeLabel: Record<string, string> = { character: '角色', faction: '势力', asset: '资产' }
const typeIcon: Record<string, string> = { character: 'user', faction: 'users', asset: 'star' }

// ===== 身份区（就地编辑）=====

const nameDraft = ref('')
const introDraft = ref('')
watch(
  entity,
  (e) => {
    nameDraft.value = e?.name || ''
    introDraft.value = e?.intro || ''
  },
  { immediate: true },
)

async function saveName() {
  if (!entity.value) return
  const n = nameDraft.value.trim()
  if (n && n !== entity.value.name) {
    await updateEntityArchive(props.bookId, entity.value.id, { name: n })
    showToast('已改名', 'success')
  }
}

async function saveIntro() {
  if (!entity.value) return
  if (introDraft.value !== entity.value.intro) {
    await updateEntityArchive(props.bookId, entity.value.id, { intro: introDraft.value })
  }
}

async function toggleVisibility() {
  if (!entity.value) return
  const v = (entity.value.visibility || 'public') === 'public' ? 'private' : 'public'
  await updateEntityArchive(props.bookId, entity.value.id, { visibility: v })
}

async function setImportance(n: number) {
  if (!entity.value) return
  await updateEntityArchive(props.bookId, entity.value.id, { importance: n })
}

// 别名 chips
const aliasDraft = ref('')
async function addAlias() {
  if (!entity.value) return
  const a = aliasDraft.value.trim()
  if (!a) return
  const list = entity.value.aliases || []
  if (!list.includes(a)) {
    await updateEntityArchive(props.bookId, entity.value.id, { aliases: [...list, a] })
  }
  aliasDraft.value = ''
}
async function removeAlias(a: string) {
  if (!entity.value) return
  await updateEntityArchive(props.bookId, entity.value.id, {
    aliases: (entity.value.aliases || []).filter((x) => x !== a),
  })
}

// ===== 档案区（schema 表驱动，失焦即存）=====

const fields = computed(() => (entity.value ? archiveFields(entity.value.entity_type) : []))
const addedFields = computed(() =>
  fields.value.filter((f) => {
    const v = entity.value?.props?.[f.key]
    return typeof v === 'string' ? v.length > 0 : v != null
  }),
)
const availableFields = computed(() =>
  fields.value.filter((f) => !addedFields.value.some((a) => a.key === f.key)),
)
const showFieldMenu = ref(false)

async function saveField(key: string, value: string) {
  if (!entity.value) return
  const prev = entity.value.props?.[key]
  const v = value.trim()
  if ((prev ?? '') === v) return
  await updateEntityArchive(props.bookId, entity.value.id, {
    props: { ...entity.value.props, [key]: v },
  })
  if (!v) showToast(`已清空字段（可随时再加）`, 'info')
}

async function addField(key: string) {
  showFieldMenu.value = false
  await saveField(key, ' ')
  await nextTick()
  const el = document.querySelector<HTMLInputElement>(`.edd-field-input[data-key="${key}"]`)
  el?.focus()
}

// ===== 编年史（涉及其的事件）=====

const chronicle = computed(() => {
  if (!entity.value) return []
  const id = entity.value.id
  return [...events.value]
    .filter(
      (ev) =>
        ev.participant_ids?.includes(id) ||
        ev.faction_ids?.includes(id) ||
        ev.payload?.character_id === id ||
        (Array.isArray(ev.payload?.character_ids) && ev.payload.character_ids.includes(id)) ||
        ev.payload?.faction_id === id ||
        ev.payload?.target_id === id,
    )
    .sort((a, b) => a.time_start - b.time_start)
    .slice(-8)
    .reverse()
})

const eventLabel = (t: string) => getTemplate(t as EventType)?.label || t
</script>

<template>
  <div v-if="entity" class="edd" @keydown.esc="emit('close')">
    <!-- 身份区 -->
    <div class="edd-head">
      <span class="edd-type" :title="typeLabel[entity.entity_type]">
        <Icon :name="typeIcon[entity.entity_type] || 'user'" :size="14" />
      </span>
      <input
        v-model="nameDraft"
        class="edd-name"
        @blur="saveName"
        @keyup.enter="(($event.target as HTMLInputElement).blur())"
      />
      <button
        class="edd-vis"
        :class="{ 'edd-vis--private': (entity.visibility || 'public') === 'private' }"
        :title="(entity.visibility || 'public') === 'public' ? '读者已知（点击转为作者私有）' : '作者私有（AI 写作时防泄底）'"
        @click="toggleVisibility"
      >
        {{ (entity.visibility || 'public') === 'public' ? '读者已知' : '私有' }}
      </button>
      <button class="edd-close" title="关闭 (Esc)" @click="emit('close')">
        <Icon name="x-mark" :size="14" />
      </button>
    </div>

    <!-- 重要度 -->
    <div class="edd-imp">
      <span class="edd-imp-label">重要度</span>
      <button
        v-for="n in 5"
        :key="n"
        class="edd-imp-dot"
        :class="{ on: (entity.importance || 1) >= n * 2 - 1 }"
        :title="`优先级 ${n * 2 - 1}`"
        @click="setImportance(n * 2 - 1)"
      ></button>
      <span class="edd-imp-num">{{ entity.importance || 1 }}</span>
    </div>

    <!-- 别名 -->
    <div class="edd-aliases">
      <span class="edd-lbl">别名</span>
      <span v-for="a in entity.aliases || []" :key="a" class="edd-alias">
        {{ a }}
        <button title="移除" @click="removeAlias(a)">×</button>
      </span>
      <input
        v-model="aliasDraft"
        class="edd-alias-in"
        placeholder="+ 别名（Enter 加）"
        @keydown.enter.prevent="addAlias"
      />
    </div>

    <!-- 一句话 -->
    <div class="edd-intro-row">
      <textarea
        v-model="introDraft"
        class="edd-intro"
        rows="2"
        placeholder="一句话介绍（可空）"
        @blur="saveIntro"
      ></textarea>
    </div>

    <!-- 档案区（生长式字段） -->
    <div class="edd-sec">
      <div class="edd-sec-title">档案</div>
      <div v-for="f in addedFields" :key="f.key" class="edd-field">
        <label class="edd-field-label">{{ f.label }}</label>
        <textarea
          v-if="f.multiline"
          class="edd-field-input"
          :data-key="f.key"
          rows="2"
          :placeholder="f.hint"
          :value="(entity.props?.[f.key] as string) || ''"
          @blur="saveField(f.key, ($event.target as HTMLTextAreaElement).value)"
        ></textarea>
        <input
          v-else
          class="edd-field-input"
          :data-key="f.key"
          :placeholder="f.hint"
          :value="(entity.props?.[f.key] as string) || ''"
          @blur="saveField(f.key, ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div v-if="availableFields.length" class="edd-addwrap">
        <button v-if="!showFieldMenu" class="edd-add" @click="showFieldMenu = true">
          <Icon name="plus" :size="12" />
          添加字段
        </button>
        <div v-else class="edd-fieldmenu">
          <button v-for="f in availableFields" :key="f.key" @click="addField(f.key)">
            {{ f.label }}<span class="edd-fieldmenu-hint">{{ f.hint }}</span>
          </button>
        </div>
      </div>
      <div v-if="!addedFields.length && !availableFields.length" class="edd-nofields">
        暂无档案字段——写到再补，或由沉淀建议生长。
      </div>
    </div>

    <!-- 编年史 -->
    <div class="edd-sec">
      <div class="edd-sec-title">编年史{{ chronicle.length ? ` · ${chronicle.length}` : '' }}</div>
      <div v-if="chronicle.length" class="edd-chron">
        <button
          v-for="ev in chronicle"
          :key="ev.id"
          class="edd-chron-item"
          title="定位到地图"
          @click="emit('focus-event', ev)"
        >
          <span class="edd-chron-type">{{ eventLabel(ev.event_type) }}</span>
          <span class="edd-chron-time">{{ formatTime(ev.time_start) }}</span>
        </button>
      </div>
      <div v-else class="edd-nofields">还没有涉及其的事件。用下方快捷动作记录第一条。</div>
    </div>

    <!-- 快捷事态动作（全部 = 预填事件表单） -->
    <div class="edd-actions">
      <template v-if="entity.entity_type === 'character'">
        <button class="edd-act" @click="emit('quick-event', 'move', entity.id)">
          <Icon name="arrows-right-left" :size="13" />
          记录移动
        </button>
        <button class="edd-act edd-act--danger" @click="emit('quick-event', 'death', entity.id)">
          <Icon name="x-circle" :size="13" />
          记录死亡
        </button>
      </template>
      <button
        v-if="entity.entity_type === 'faction'"
        class="edd-act"
        @click="emit('quick-event', 'territory_change', entity.id)"
      >
        <Icon name="globe" :size="13" />
        记录疆域变更
      </button>
    </div>
  </div>
</template>

<style scoped>
.edd {
  position: absolute;
  top: 48px;
  right: 12px;
  bottom: 12px;
  width: 320px;
  z-index: 700;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  box-shadow: 0 16px 44px rgba(0, 0, 0, 0.16);
  padding: 14px;
  overflow-y: auto;
  font-size: 13px;
}
.edd-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.edd-type {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--bg-tertiary);
  color: var(--accent-500);
  flex-shrink: 0;
}
.edd-name {
  flex: 1;
  min-width: 0;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: inherit;
  padding: 3px 6px;
  outline: none;
  transition: border-color 0.12s;
}
.edd-name:hover,
.edd-name:focus {
  border-color: var(--border-color);
}
.edd-name:focus {
  border-color: var(--accent-500);
}
.edd-vis {
  flex-shrink: 0;
  padding: 3px 8px;
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  background: var(--bg-canvas);
  color: var(--text-muted);
  font-size: 10px;
  font-family: inherit;
  cursor: pointer;
}
.edd-vis--private {
  border-color: #f59e0b;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
}
.edd-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
}
.edd-close:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

/* 重要度 */
.edd-imp {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 10px 0 8px;
}
.edd-imp-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-right: 2px;
}
.edd-imp-dot {
  width: 10px;
  height: 10px;
  border-radius: 9999px;
  border: 1px solid var(--border-color);
  background: var(--bg-canvas);
  cursor: pointer;
  padding: 0;
  transition: all 0.12s;
}
.edd-imp-dot.on {
  background: var(--accent-500);
  border-color: var(--accent-500);
}
.edd-imp-num {
  font-size: 11px;
  color: var(--text-secondary);
  font-family: ui-monospace, monospace;
  margin-left: 4px;
}

/* 别名 */
.edd-aliases {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 8px;
}
.edd-lbl {
  font-size: 11px;
  color: var(--text-muted);
}
.edd-alias {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 9999px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 11px;
}
.edd-alias button {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
  line-height: 1;
}
.edd-alias button:hover {
  color: #dc2626;
}
.edd-alias-in {
  width: 110px;
  padding: 2px 8px;
  border: 1px dashed var(--border-color);
  border-radius: 9999px;
  background: transparent;
  color: var(--text-primary);
  font-size: 11px;
  font-family: inherit;
  outline: none;
}
.edd-alias-in:focus {
  border-color: var(--accent-500);
  border-style: solid;
}

/* 一句话 */
.edd-intro {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 9px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  resize: vertical;
  outline: none;
}
.edd-intro:focus {
  border-color: var(--accent-500);
}

/* 档案区 */
.edd-sec {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.edd-sec-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 8px;
  letter-spacing: 0.05em;
}
.edd-field {
  margin-bottom: 8px;
}
.edd-field-label {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 3px;
}
.edd-field-input {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 9px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  outline: none;
  resize: vertical;
}
.edd-field-input:focus {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}
.edd-addwrap {
  position: relative;
}
.edd-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border: 1px dashed var(--border-color);
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}
.edd-add:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.edd-fieldmenu {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-canvas);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}
.edd-fieldmenu button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}
.edd-fieldmenu button:hover {
  background: var(--hover-bg);
  color: var(--accent-500);
}
.edd-fieldmenu-hint {
  font-size: 10px;
  color: var(--text-muted);
}
.edd-nofields {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.7;
}

/* 编年史 */
.edd-chron {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.edd-chron-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 9px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s;
}
.edd-chron-item:hover {
  border-color: var(--accent-500);
  color: var(--text-primary);
}
.edd-chron-time {
  font-size: 10px;
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
  flex-shrink: 0;
}

/* 快捷动作 */
.edd-actions {
  display: flex;
  gap: 6px;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.edd-act {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s;
}
.edd-act:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.edd-act--danger:hover {
  border-color: #dc2626;
  color: #dc2626;
}
</style>
