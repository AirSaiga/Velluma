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
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { useCanon } from '../composables/useCanon'
import { useToast } from '../../../composables/useToast'
import { useEscStack } from '../../../composables/useEscStack'
import { archiveFields } from '../engine/entitySchema'
import { listGroupNames } from '../engine/entityGroups'
import {
  FIELD_LAYER_LABELS,
  FIELD_LAYER_TITLES,
  cycleFieldLayer,
  fieldLayerLevel,
  getFieldLayer,
  mergeFieldLayer,
} from '../engine/fieldLayers'
import { formatTime } from '../engine/timeFormat'
import { getTemplate } from '../engine/eventTemplates'
import { vAutogrow } from './autogrow'
import type { WorldEntity, WorldEvent, EventType } from '../engine/types'

const props = defineProps<{ bookId: string; entityId: string; canGoBack?: boolean }>()

const emit = defineEmits<{
  close: []
  /** 返回上一级（从图标栏面板钻入时才有上一级；由 WorldView 恢复来路面板） */
  back: []
  'quick-event': [type: EventType, entityId: string]
  'focus-event': [ev: WorldEvent]
}>()

const {
  entities,
  events,
  updateEntityArchive,
} = useWorld()
const { showToast } = useToast()

// Esc 分层关闭栈（00 期 §4.2）：挂载即入栈（一次 Esc 只关栈顶、焦点不在层内也生效），
// 卸载即出栈——替代根元素 @keydown.esc（旧路径焦点不在抽屉内时失效）
const escStack = useEscStack()
let escId: symbol | null = null
onMounted(() => { escId = escStack.push(() => emit('close'), 'entity-detail-drawer') })
onUnmounted(() => { if (escId) escStack.remove(escId) })


// ===== 读者认知（C2 §5.3：实体信息面 overlay——本实体的真相/读者所见）=====
const { nodes: canonNodes, ensureLoaded: ensureCanon, createNode, updateNode } = useCanon()
void ensureCanon(props.bookId)

/** 本实体的信息面（应用层唯一：一对象一 overlay；后端 create 幂等兜底） */
const overlay = computed(
  () => (canonNodes.value || []).find((n) => n.ref_type === 'entity' && n.ref_id === props.entityId) || null,
)

async function createOverlay(visibility: 'private' | 'public') {
  const e = entity.value
  if (!e) return
  try {
    await createNode(props.bookId, {
      book_id: props.bookId,
      type: e.entity_type === 'asset' ? 'object' : 'character', // 迁移期快照；读取时由世界推演
      label: e.name,
      canon_text: '',
      public_text: '',
      visibility,
      ref_type: 'entity',
      ref_id: e.id,
    })
  } catch (err: any) {
    showToast('创建信息面失败：' + (err?.message || ''), 'error')
  }
}

function setOverlayVisibility(v: 'public' | 'private' | 'partial') {
  if (overlay.value) void updateNode(props.bookId, overlay.value.id, { visibility: v })
}

function saveOverlayField(field: 'canon_text' | 'public_text' | 'reveal_plan', value: string) {
  if (overlay.value) void updateNode(props.bookId, overlay.value.id, { [field]: value })
}

function saveOverlayChapter(value: string) {
  const n = parseInt(value, 10)
  if (overlay.value) void updateNode(props.bookId, overlay.value.id, {
    expected_reveal_chapter: Number.isFinite(n) && n > 0 ? n : null,
  })
}

const VIS_LABELS: Record<string, string> = { private: '秘密', partial: '半露', public: '公开' }

const entity = computed(
  () => entities.value.find((e) => e.id === props.entityId) || null,
)

const typeLabel: Record<string, string> = { character: '角色', faction: '势力', asset: '资产' }
const typeIcon: Record<string, string> = { character: 'user', faction: 'users', asset: 'star' }

// ===== 身份区（就地编辑）=====

const nameDraft = ref('')
const introDraft = ref('')
const groupDraft = ref('')
watch(
  entity,
  (e) => {
    nameDraft.value = e?.name || ''
    introDraft.value = e?.intro || ''
    groupDraft.value = e?.group_name || ''
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

// ===== 分组（单分组，2026-09-03）：资产抽屉按它折叠归组；组织元数据不进 prompt =====

/** 本书既有资产分组名（输入候选，防「机甲/机甲 」这类手滑重名裂出两组） */
const groupSuggestions = computed(() =>
  listGroupNames(entities.value.filter((e) => e.entity_type === 'asset' && e.id !== props.entityId)),
)

async function saveGroup() {
  if (!entity.value) return
  const g = groupDraft.value.trim()
  const cur = (entity.value.group_name || '').trim()
  if (g === cur) return
  await updateEntityArchive(props.bookId, entity.value.id, { group_name: g || null })
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
  const v = value.trim()
  // 函数式 patch：锁内对最新 store 态做「值未变」判定与合并（防亚秒连续编辑互相覆盖）
  const saved = await updateEntityArchive(props.bookId, entity.value.id, (ent) => {
    const prev = ent?.props?.[key]
    if ((prev ?? '') === v) return null
    return { props: { ...ent?.props, [key]: v } }
  })
  if (saved && !v) showToast(`已清空字段（可随时再加）`, 'info')
}

async function addField(key: string) {
  if (!entity.value) return
  showFieldMenu.value = false
  // 占位须直接落库：saveField 会 trim 成空串再被「值未变」守卫拦下，走它新字段永远写不进去
  await updateEntityArchive(props.bookId, entity.value.id, (ent) => ({
    props: { ...ent?.props, [key]: ' ' },
  }))
  await nextTick()
  const el = document.querySelector<HTMLInputElement>(`.edd-field-input[data-key="${key}"]`)
  el?.focus()
}

// ===== 字段级真相分层（2026-09-03）：字段内容本身即「里」，半露只需补「表」=====
// 分层状态存 field_layers（缺键=公开）；prompt 注入/泄密检测/揭示提醒由后端自动感知，
// 作者不两边维护（派生感知取代物料迁移，不建真相节点副本）。

function layerOf(key: string) {
  return fieldLayerLevel(entity.value, key)
}
function layerSpec(key: string) {
  return getFieldLayer(entity.value, key)
}

async function cycleLayer(key: string) {
  if (!entity.value) return
  await updateEntityArchive(props.bookId, entity.value.id, (ent) =>
    ent ? { field_layers: cycleFieldLayer(ent, key) } : null,
  )
}

async function saveLayerPublicText(key: string, value: string) {
  if (!entity.value) return
  const v = value.trim()
  await updateEntityArchive(props.bookId, entity.value.id, (ent) => {
    const spec = ent ? getFieldLayer(ent, key) : null
    if ((spec?.public_text || '') === v) return null
    return ent ? { field_layers: mergeFieldLayer(ent, key, { public_text: v }) } : null
  })
}

async function saveLayerChapter(key: string, value: string) {
  if (!entity.value) return
  const n = parseInt(value, 10)
  const ch = Number.isFinite(n) && n > 0 ? n : null
  await updateEntityArchive(props.bookId, entity.value.id, (ent) => {
    const spec = ent ? getFieldLayer(ent, key) : null
    if ((spec?.reveal_chapter ?? null) === ch) return null
    return ent ? { field_layers: mergeFieldLayer(ent, key, { reveal_chapter: ch }) } : null
  })
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
  <div v-if="entity" class="edd">
    <!-- 身份区 -->
    <div class="edd-head">
      <button v-if="canGoBack" class="edd-back" title="返回上一级" @click="emit('back')">
        <Icon name="arrow-left" :size="14" />
      </button>
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
    <!-- 私有语义消歧（A1 + 2026-09-03 字段分层）：让作者知道两档粒度各管什么 -->
    <p class="edd-vis-note">
      整人私有 = 全部档案只给 AI 知晓；单条设定的保密或逐步揭示，用档案字段旁的「公开/半露/秘密」分层
    </p>

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

    <!-- 分组（仅资产；单分组——资产抽屉按它折叠归组，清空即移出分组） -->
    <div v-if="entity.entity_type === 'asset'" class="edd-aliases">
      <span class="edd-lbl">分组</span>
      <input
        v-model="groupDraft"
        class="edd-alias-in edd-group-in"
        list="edd-group-options"
        placeholder="未分组（如：机甲 / 武器）"
        @blur="saveGroup"
        @keyup.enter="(($event.target as HTMLInputElement).blur())"
      />
      <datalist id="edd-group-options">
        <option v-for="g in groupSuggestions" :key="g" :value="g" />
      </datalist>
    </div>

    <!-- 一句话（2026-09-03 起可分层：作者最常把混合内容写在这里——「速度极快」是表，
         「5 马赫/10G」是里；全文存 intro，半露只需补表） -->
    <div class="edd-intro-row">
      <div class="edd-field-head">
        <span class="edd-lbl edd-lbl--block">一句话</span>
        <button
          class="edd-layer"
          :class="`edd-layer--${layerOf('intro')}`"
          :title="FIELD_LAYER_TITLES[layerOf('intro')]"
          @click="cycleLayer('intro')"
        >{{ FIELD_LAYER_LABELS[layerOf('intro')] }}</button>
      </div>
      <textarea
        v-model="introDraft"
        v-autogrow
        class="edd-intro"
        rows="2"
        placeholder="一句话介绍（可空）"
        @blur="saveIntro"
      ></textarea>
      <div v-if="layerOf('intro') === 'partial'" class="edd-field-layerbox">
        <label class="edd-field-layerlabel">读者目前看到的版本（表）——留空则整条按秘密处理</label>
        <textarea
          v-autogrow
          class="edd-field-input"
          rows="2"
          placeholder="如：这套机甲飞行速度极快（具体数据留在上面，AI 替你守住）"
          :value="layerSpec('intro')?.public_text || ''"
          @blur="saveLayerPublicText('intro', ($event.target as HTMLTextAreaElement).value)"
        ></textarea>
        <label class="edd-field-layerlabel">第几章揭（可空——写了就会在临近时提醒）</label>
        <input
          class="edd-field-input edd-field-layerch"
          type="number"
          min="1"
          placeholder="—"
          :value="layerSpec('intro')?.reveal_chapter ?? ''"
          @change="saveLayerChapter('intro', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div v-else-if="layerOf('intro') === 'private'" class="edd-field-layerhint">
        只有 AI 知道——可用于铺垫暗示，绝不直接写出；写完可贴段正文查泄密
      </div>
    </div>

    <!-- 档案区（生长式字段） -->
    <div class="edd-sec">
      <div class="edd-sec-title">档案</div>
      <div v-for="f in addedFields" :key="f.key" class="edd-field">
        <div class="edd-field-head">
          <label class="edd-field-label">{{ f.label }}</label>
          <button
            class="edd-layer"
            :class="`edd-layer--${layerOf(f.key)}`"
            :title="FIELD_LAYER_TITLES[layerOf(f.key)]"
            @click="cycleLayer(f.key)"
          >{{ FIELD_LAYER_LABELS[layerOf(f.key)] }}</button>
        </div>
        <textarea
          v-if="f.multiline"
          v-autogrow
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
        <!-- 半露内联：字段内容=里，只需补「表」；留空则整条按秘密处理 -->
        <div v-if="layerOf(f.key) === 'partial'" class="edd-field-layerbox">
          <label class="edd-field-layerlabel">读者目前看到的版本（表）——留空则整条按秘密处理</label>
          <textarea
            v-autogrow
            class="edd-field-input"
            rows="2"
            placeholder="读者目前看到的描述（可空）"
            :value="layerSpec(f.key)?.public_text || ''"
            @blur="saveLayerPublicText(f.key, ($event.target as HTMLTextAreaElement).value)"
          ></textarea>
          <label class="edd-field-layerlabel">第几章揭（可空——写了就会在临近时提醒）</label>
          <input
            class="edd-field-input edd-field-layerch"
            type="number"
            min="1"
            placeholder="—"
            :value="layerSpec(f.key)?.reveal_chapter ?? ''"
            @change="saveLayerChapter(f.key, ($event.target as HTMLInputElement).value)"
          />
        </div>
        <div v-else-if="layerOf(f.key) === 'private'" class="edd-field-layerhint">
          只有 AI 知道——可用于铺垫暗示，绝不直接写出；写完可贴段正文查泄密
        </div>
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

    <!-- 读者认知（C2 §5.3：实体信息面——表里两面就地编辑，折叠态默认；09-03 文案对齐 truth-ux 稿） -->
    <details class="edd-canon">
      <summary class="edd-sec-title">读者认知{{ overlay ? ` · ${VIS_LABELS[overlay.visibility] || overlay.visibility}` : '' }}</summary>
      <template v-if="overlay">
        <div class="edd-canon-vis">
          <button
            v-for="(lbl, v) in VIS_LABELS"
            :key="v"
            class="edd-canon-vis-btn"
            :class="{ 'is-on': overlay.visibility === v }"
            @click="setOverlayVisibility(v as any)"
          >{{ lbl }}</button>
        </div>
        <label class="edd-canon-field">
          <span class="edd-canon-label">实际真相（里）——AI 死守，绝不写进正文</span>
          <textarea v-autogrow rows="2" :value="overlay.canon_text" placeholder="此人此物的真相……" @change="(e) => saveOverlayField('canon_text', (e.target as HTMLTextAreaElement).value)"></textarea>
        </label>
        <label class="edd-canon-field">
          <span class="edd-canon-label">读者目前看到的版本（表）</span>
          <textarea v-autogrow rows="2" :value="overlay.public_text" placeholder="读者目前看到的描述（可空）" @change="(e) => saveOverlayField('public_text', (e.target as HTMLTextAreaElement).value)"></textarea>
        </label>
        <label class="edd-canon-field">
          <span class="edd-canon-label">打算怎么抖出来</span>
          <input
            class="edd-canon-input"
            :value="overlay.reveal_plan"
            placeholder="何时、如何揭示真相"
            @change="(e) => saveOverlayField('reveal_plan', (e.target as HTMLInputElement).value)"
          />
        </label>
        <label class="edd-canon-field edd-canon-field--half">
          <span class="edd-canon-label">第几章揭</span>
          <input
            class="edd-canon-input"
            type="number" min="1"
            :value="overlay.expected_reveal_chapter ?? ''"
            placeholder="—"
            @change="(e) => saveOverlayChapter((e.target as HTMLInputElement).value)"
          />
        </label>
      </template>
      <div v-else class="edd-canon-empty">
        <p>此人还没有真相记录。</p>
        <div class="edd-canon-empty-actions">
          <button class="edd-act" @click="createOverlay('private')">记为秘密</button>
          <button class="edd-act" @click="createOverlay('public')">记为公开事实</button>
        </div>
      </div>
    </details>

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
  right: 58px; /* 避让 M6 图标栏（右缘 46px + 间隙） */
  bottom: 12px;
  width: 340px;
  z-index: 700;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  box-shadow: 0 16px 44px rgba(0, 0, 0, 0.16);
  padding: 16px;
  overflow-y: auto;
  font-size: 13px;
}
.edd::-webkit-scrollbar {
  width: 8px;
}
.edd::-webkit-scrollbar-thumb {
  background: rgba(120, 95, 50, 0.22);
  border-radius: 4px;
}
.edd::-webkit-scrollbar-thumb:hover {
  background: rgba(120, 95, 50, 0.38);
}
.edd::-webkit-scrollbar-track {
  background: transparent;
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
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  font-family: "Noto Serif SC", "Source Han Serif SC", "STSong", "SimSun", serif;
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
  font-size: var(--text-xs);
  font-family: inherit;
  cursor: pointer;
}
.edd-vis--private {
  border-color: var(--warn);
  color: var(--warn);
  background: rgba(245, 158, 11, 0.08);
}
/* 私有语义消歧（A1）：切换旁的一行说明，两条底线——知晓不写出 / 强制力在真相层 */
.edd-vis-note {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
  opacity: 0.9;
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
/* 返回上一级（仅从图标栏面板钻入时出现，与关闭分权：← 回列表 / × 全关） */
.edd-back {
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
.edd-back:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

/* 重要度 */
.edd-imp {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 10px 0 8px;
}
.edd-imp-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-right: 2px;
}
.edd-imp-dot {
  width: 12px;
  height: 12px;
  border-radius: 9999px;
  border: 1px solid var(--border-color);
  background: var(--bg-canvas);
  cursor: pointer;
  padding: 0;
  transition: all 0.12s;
}
.edd-imp-dot:hover {
  transform: scale(1.25);
  border-color: var(--accent-500);
}
.edd-imp-dot.on {
  background: var(--accent-500);
  border-color: var(--accent-500);
}
.edd-imp-num {
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.edd-lbl--block {
  display: block;
  margin-bottom: 4px;
}
.edd-alias {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 9999px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 12px;
}
.edd-alias button {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
  padding: 0;
  line-height: 1;
}
.edd-alias button:hover {
  color: var(--danger);
}
.edd-alias-in {
  flex: 1;
  min-width: 96px;
  padding: 3px 10px;
  border: 1px dashed var(--border-color);
  border-radius: 9999px;
  background: transparent;
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.edd-alias-in:focus {
  border-color: var(--accent-500);
  border-style: solid;
}
.edd-group-in {
  min-width: 160px;
  border-radius: 6px;
}

/* 一句话（v-autogrow 随内容长高，超 max-height 才滚动） */
.edd-intro-row {
  margin-top: 2px;
}
.edd-intro {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.7;
  font-family: inherit;
  resize: none;
  max-height: 180px;
  outline: none;
}
.edd-intro:focus {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

/* 档案区 */
.edd-sec {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.edd-sec-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 8px;
  letter-spacing: 0.05em;
}
.edd-field {
  margin-bottom: 10px;
}
.edd-field-label {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-bottom: 4px;
}
/* 字段级真相分层（2026-09-03）：label 行右侧的三态 chip */
.edd-field-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.edd-field-head .edd-field-label {
  margin-bottom: 4px;
}
.edd-layer {
  flex: none;
  padding: 1px 8px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-family: inherit;
  line-height: 1.6;
  cursor: pointer;
  opacity: 0.75;
}
.edd-layer:hover {
  opacity: 1;
  border-color: var(--border-color);
}
.edd-layer--partial {
  color: #7c5faf;
  border-color: rgba(124, 95, 175, 0.45);
  opacity: 1;
}
.edd-layer--private {
  color: #a63e2a;
  border-color: rgba(166, 62, 42, 0.45);
  opacity: 1;
}
.edd-field-layerbox {
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px dashed rgba(124, 95, 175, 0.4);
  border-radius: 8px;
}
.edd-field-layerbox .edd-field-input {
  margin-bottom: 6px;
}
.edd-field-layerlabel {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: 4px;
}
.edd-field-layerch {
  width: 90px;
}
.edd-field-layerhint {
  margin-top: 4px;
  font-size: var(--text-xs);
  color: #a63e2a;
  opacity: 0.85;
}
/* 单行/多行共用；多行走 v-autogrow，resize 交给自动高度（手动拖拽会与自动量高打架） */
.edd-field-input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.7;
  font-family: inherit;
  outline: none;
  resize: none;
  max-height: 240px;
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
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.edd-nofields {
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
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
  border-color: var(--danger);
  color: var(--danger);
}

/* 读者认知（C2 §5.3：实体信息面 overlay 分区，折叠态默认） */
.edd-canon {
  padding: 0 14px 10px;
}
.edd-canon > summary {
  cursor: pointer;
  list-style: none;
  user-select: none;
}
.edd-canon > summary::-webkit-details-marker {
  display: none;
}
.edd-canon-vis {
  display: flex;
  gap: 4px;
  margin-top: 8px;
}
.edd-canon-vis-btn {
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: none;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  padding: 2px 10px;
  cursor: pointer;
}
.edd-canon-vis-btn.is-on {
  border-color: #c2725a;
  color: #c2725a;
}
.edd-canon-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 8px;
}
.edd-canon-field--half {
  max-width: 180px;
}
.edd-canon-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.edd-canon-field textarea,
.edd-canon-input {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: transparent;
  font-size: 12px;
  color: var(--text-primary);
  padding: 5px 8px;
  line-height: 1.5;
  resize: none;
  overflow: hidden;
  font-family: inherit;
}
.edd-canon-field textarea:focus,
.edd-canon-input:focus {
  outline: none;
  border-color: var(--accent-400, #9685c2);
}
.edd-canon-empty p {
  font-size: 12px;
  color: var(--text-muted);
  margin: 8px 0 6px;
}
.edd-canon-empty-actions {
  display: flex;
  gap: 6px;
}
</style>
