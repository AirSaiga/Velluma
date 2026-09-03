<script setup lang="ts">
/**
 * 地点详情抽屉（docs/location-interior.md）——地点的「二级面板」。
 *
 * 大地点上图、内部细节进这里：parent_id 树的子地点一律不上地图，
 * 只在本抽屉的「内部构造」区呈现。面包屑下钻支持任意深度
 * （基地 › B2 拘留层 › 拘留室），一套交互走完整棵树。
 *
 * 轻量编辑不进 undo（与实体档案/改名同策略）；建/删进 undo
 * （useWorld createLocation/deleteLocation 自带逆命令）。
 */
import { ref, computed, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { vAutogrow } from './autogrow'
import { childrenIndex, collectSubtree } from '../engine/locationTree'
import type { WorldLocation } from '../engine/types'

const props = defineProps<{ bookId: string; locationId: string; canGoBack?: boolean }>()

const emit = defineEmits<{
  close: []
  /** 返回上一级（从图标栏面板钻入时才有上一级；由 WorldView 恢复来路面板） */
  back: []
  locate: [loc: WorldLocation]
}>()

const { locations, createLocation, updateLocation, deleteLocation } = useWorld()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

// ===== 当前层与面包屑 =====

/** 当前下钻层（初始 = 打开时传入的地点；点子级切换） */
const currentId = ref(props.locationId)
watch(
  () => props.locationId,
  (v) => (currentId.value = v),
)

const byId = computed(() => {
  const m = new Map<string, WorldLocation>()
  for (const l of locations.value) m.set(l.id, l)
  return m
})
const kids = computed(() => childrenIndex(locations.value))

const current = computed(() => byId.value.get(currentId.value) || null)

/** 面包屑：从当前层向上爬到顶层 [{id, name}, ...] */
const crumbs = computed(() => {
  const out: { id: string; name: string }[] = []
  let cur = current.value
  const seen = new Set<string>()
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id)
    out.unshift({ id: cur.id, name: cur.name })
    cur = cur.parent_id ? byId.value.get(cur.parent_id) || null : null
  }
  return out
})

// 当前层被外部删除（undo 链/列表删除）→ 回退父层，无父则关抽屉
watch(current, (loc) => {
  if (!loc) {
    const parent = crumbs.value.length > 1 ? crumbs.value[crumbs.value.length - 2] : null
    if (parent) currentId.value = parent.id
    else emit('close')
  }
})

const LOC_KIND_LABEL: Record<string, string> = { point: '地点', region: '区域', route: '路径' }

// ===== 基本区（就地编辑，失焦即存）=====

const nameDraft = ref('')
const introDraft = ref('')
watch(
  current,
  (loc) => {
    nameDraft.value = loc?.name || ''
    introDraft.value = loc?.intro || ''
  },
  { immediate: true },
)

async function saveName() {
  const loc = current.value
  if (!loc) return
  const n = nameDraft.value.trim()
  if (n && n !== loc.name) {
    await updateLocation(props.bookId, loc.id, { name: n })
    showToast('已改名', 'success')
  }
}

async function saveIntro() {
  const loc = current.value
  if (!loc) return
  if (introDraft.value !== loc.intro) {
    await updateLocation(props.bookId, loc.id, { intro: introDraft.value })
  }
}

// ===== tags（chips，照实体别名模式）=====

const tagDraft = ref('')
async function addTag() {
  const loc = current.value
  if (!loc) return
  const t = tagDraft.value.trim()
  if (!t) return
  if (!(loc.tags || []).includes(t)) {
    await updateLocation(props.bookId, loc.id, { tags: [...(loc.tags || []), t] })
  }
  tagDraft.value = ''
}
async function removeTag(t: string) {
  const loc = current.value
  if (!loc) return
  await updateLocation(props.bookId, loc.id, { tags: (loc.tags || []).filter((x) => x !== t) })
}

// ===== 位置区 =====

const isInterior = computed(() => !!current.value?.parent_id)

async function clearCoords() {
  const loc = current.value
  if (!loc) return
  await updateLocation(props.bookId, loc.id, { coord_x: null, coord_y: null })
  showToast('已清除坐标——这个地点不再上图', 'info')
}

// ===== 内部构造区 =====

const childrenOfCurrent = computed(() => kids.value.get(current.value?.id || '') || [])

function childCount(id: string): number {
  return (kids.value.get(id) || []).length
}

const adding = ref(false)
const addName = ref('')
const addIntro = ref('')
async function submitAdd() {
  const loc = current.value
  const n = addName.value.trim()
  if (!loc || !n) return
  await createLocation(props.bookId, {
    name: n,
    kind: 'point',
    parent_id: loc.id,
    intro: addIntro.value.trim(),
  })
  adding.value = false
  addName.value = ''
  addIntro.value = ''
  showToast('内部构造已添加', 'success')
}
function cancelAdd() {
  adding.value = false
  addName.value = ''
  addIntro.value = ''
}

// ===== 删除（树删，确认声明子树）=====

async function removeCurrent() {
  const loc = current.value
  if (!loc) return
  const tree = collectSubtree(locations.value, loc.id)
  const ok = await showConfirm({
    title: '删除地点',
    message: `确定删除「${loc.name}」吗？`,
    warning:
      tree.length > 1
        ? `含 ${tree.length - 1} 个内部构造，将一并删除。关联事件的地点引用会被清空（可用 Ctrl+Z 撤销）。`
        : '关联事件的地点引用会被清空（可用 Ctrl+Z 撤销）。',
    confirmText: '删除',
  })
  if (!ok) return
  await deleteLocation(props.bookId, loc.id)
  showToast('地点已删除', 'success')
}
</script>

<template>
  <div v-if="current" class="ldd" @keydown.esc="emit('close')">
    <!-- 面包屑（下钻路径） -->
    <div v-if="crumbs.length > 1" class="ldd-crumbs">
      <template v-for="(c, i) in crumbs" :key="c.id">
        <button v-if="i < crumbs.length - 1" class="ldd-crumb" @click="currentId = c.id">
          {{ c.name }}
        </button>
        <span v-else class="ldd-crumb ldd-crumb--cur">{{ c.name }}</span>
        <Icon v-if="i < crumbs.length - 1" name="chevron-right" :size="11" class="ldd-crumb-sep" />
      </template>
    </div>

    <!-- 头部 -->
    <div class="ldd-head">
      <button v-if="canGoBack" class="ldd-back" title="返回上一级" @click="emit('back')">
        <Icon name="arrow-left" :size="14" />
      </button>
      <span class="ldd-type" :title="isInterior ? '内部构造' : LOC_KIND_LABEL[current.kind] || current.kind">
        <Icon :name="isInterior ? 'chevron-down' : 'map-pin'" :size="14" />
      </span>
      <input
        v-model="nameDraft"
        class="ldd-name"
        @blur="saveName"
        @keyup.enter="(($event.target as HTMLInputElement).blur())"
      />
      <button class="ldd-close" title="关闭 (Esc)" @click="emit('close')">
        <Icon name="x-mark" :size="14" />
      </button>
    </div>

    <!-- 简述（完整编辑——地图 popup 只有一行的那个） -->
    <div class="ldd-intro-row">
      <span class="ldd-lbl">简述</span>
      <textarea
        v-model="introDraft"
        v-autogrow
        class="ldd-intro"
        rows="2"
        placeholder="这个地点是什么样的？一两句给未来的自己和 AI。"
        @blur="saveIntro"
      ></textarea>
    </div>

    <!-- 标签 -->
    <div class="ldd-tags">
      <span class="ldd-lbl">标签</span>
      <span v-for="t in current.tags || []" :key="t" class="ldd-tag">
        {{ t }}
        <button title="移除" @click="removeTag(t)">×</button>
      </span>
      <input
        v-model="tagDraft"
        class="ldd-tag-in"
        placeholder="＋ 标签"
        @keyup.enter="addTag"
        @blur="addTag"
      />
    </div>

    <!-- 位置区 -->
    <div class="ldd-pos">
      <template v-if="isInterior">
        <Icon name="chevron-down" :size="12" />
        <span>内部构造 · 不上图，只在这里与父地点的列表里出现</span>
      </template>
      <template v-else-if="current.coord_x != null && current.coord_y != null">
        <Icon name="map-pin" :size="12" />
        <span>已上图</span>
        <button class="ldd-link" title="在地图上定位" @click="emit('locate', current)">定位</button>
        <button class="ldd-link ldd-link--danger" title="清除坐标，保留地点" @click="clearCoords">
          移下地图
        </button>
      </template>
      <template v-else>
        <Icon name="map-pin" :size="12" />
        <span>未上图</span>
        <button
          class="ldd-link"
          title="回到地图点击拾取，即可补上坐标"
          @click="emit('locate', current)"
        >
          去地图放置
        </button>
      </template>
    </div>

    <!-- 内部构造区 -->
    <div class="ldd-sec">
      <div class="ldd-sec-title">
        内部构造
        <span v-if="childrenOfCurrent.length" class="ldd-sec-count">{{ childrenOfCurrent.length }}</span>
      </div>
      <p class="ldd-sec-note">这个地点里面的房间、楼层、设施——录入后事件可以钉到这一级（速记「在拘留室审讯」即达）。</p>
      <div v-for="c in childrenOfCurrent" :key="c.id" class="ldd-child" @click="currentId = c.id">
        <div class="ldd-child-main">
          <span class="ldd-child-name">{{ c.name }}</span>
          <span v-if="c.intro" class="ldd-child-intro">{{ c.intro }}</span>
        </div>
        <span v-if="childCount(c.id)" class="ldd-child-sub">{{ childCount(c.id) }} 内部 ›</span>
        <Icon v-else name="chevron-right" :size="12" class="ldd-child-arrow" />
      </div>
      <div v-if="!adding" class="ldd-add" @click="adding = true">
        <Icon name="plus" :size="12" />
        <span>添加内部构造</span>
      </div>
      <div v-else class="ldd-add-form">
        <input v-model="addName" class="ldd-add-name" placeholder="名字，如「B2 拘留层」" @keyup.enter="submitAdd" />
        <textarea
          v-model="addIntro"
          v-autogrow
          class="ldd-add-intro"
          rows="2"
          placeholder="简述（可选）"
        ></textarea>
        <div class="ldd-add-actions">
          <button class="ldd-btn" :disabled="!addName.trim()" @click="submitAdd">添加</button>
          <button class="ldd-btn ldd-btn--ghost" @click="cancelAdd">取消</button>
        </div>
      </div>
    </div>

    <!-- 删除 -->
    <div class="ldd-foot">
      <button class="ldd-del" @click="removeCurrent">
        <Icon name="trash" :size="12" />
        删除{{ childrenOfCurrent.length ? `（含内部构造）` : '' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ldd {
  position: absolute;
  top: 48px;
  right: 58px; /* 避让 M6 图标栏（右缘 46px + 间隙）——与实体抽屉同位 */
  bottom: 12px;
  width: 340px;
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

/* 面包屑 */
.ldd-crumbs {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--text-muted, #888);
}
.ldd-crumb {
  background: none;
  border: none;
  color: var(--accent-400, #8b6de8);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  font-size: 11px;
}
.ldd-crumb:hover {
  background: rgba(139, 109, 232, 0.1);
}
.ldd-crumb--cur {
  color: var(--text-muted, #888);
  cursor: default;
}
.ldd-crumb-sep {
  opacity: 0.5;
}

/* 头部 */
.ldd-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ldd-type {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: rgba(107, 90, 68, 0.1);
  color: var(--text-secondary, #6b5a44);
  flex: none;
}
.ldd-name {
  flex: 1;
  min-width: 0;
  font-size: 15px;
  font-weight: 600;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-primary, #333);
  padding: 3px 6px;
}
.ldd-name:hover,
.ldd-name:focus {
  border-color: var(--border-color, #ddd);
  outline: none;
}
.ldd-close {
  background: none;
  border: none;
  color: var(--text-muted, #999);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
}
.ldd-close:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-primary, #333);
}
/* 返回上一级（仅从图标栏面板钻入时出现，与关闭分权：← 回列表 / × 全关） */
.ldd-back {
  background: none;
  border: none;
  color: var(--text-muted, #999);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  flex-shrink: 0;
}
.ldd-back:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-primary, #333);
}

/* 简述 */
.ldd-intro-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 12px;
}
.ldd-lbl {
  font-size: 11px;
  color: var(--text-muted, #999);
}
.ldd-intro {
  width: 100%;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 8px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.02));
  color: var(--text-primary, #333);
  padding: 7px 9px;
  font-size: 12.5px;
  line-height: 1.55;
  resize: none;
  font-family: inherit;
}
.ldd-intro:focus {
  outline: none;
  border-color: var(--accent-400, #8b6de8);
}

/* 标签 */
.ldd-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 10px;
}
.ldd-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(107, 90, 68, 0.1);
  color: var(--text-secondary, #6b5a44);
}
.ldd-tag button {
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  padding: 0;
  font-size: 12px;
  line-height: 1;
}
.ldd-tag-in {
  width: 64px;
  border: none;
  border-bottom: 1px dashed var(--border-color, #ccc);
  background: transparent;
  font-size: 11px;
  padding: 2px 4px;
  color: var(--text-primary, #333);
}
.ldd-tag-in:focus {
  outline: none;
  border-bottom-color: var(--accent-400, #8b6de8);
}

/* 位置区 */
.ldd-pos {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  font-size: 11.5px;
  color: var(--text-muted, #888);
}
.ldd-link {
  background: none;
  border: none;
  color: var(--accent-400, #8b6de8);
  cursor: pointer;
  font-size: 11.5px;
  padding: 2px 4px;
  border-radius: 4px;
}
.ldd-link:hover {
  background: rgba(139, 109, 232, 0.1);
}
.ldd-link--danger {
  color: #b4543f;
}
.ldd-link--danger:hover {
  background: rgba(180, 84, 63, 0.1);
}

/* 内部构造区 */
.ldd-sec {
  margin-top: 14px;
  border-top: 1px solid var(--border-color, #e5e0d5);
  padding-top: 10px;
}
.ldd-sec-title {
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ldd-sec-count {
  font-size: 10px;
  background: rgba(107, 90, 68, 0.12);
  border-radius: 999px;
  padding: 1px 6px;
  color: var(--text-secondary, #6b5a44);
}
.ldd-sec-note {
  font-size: 11px;
  color: var(--text-muted, #999);
  margin: 6px 0 8px;
  line-height: 1.5;
}
.ldd-child {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px;
  border: 1px solid var(--border-color, #e5e0d5);
  border-radius: 8px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: border-color 0.12s;
}
.ldd-child:hover {
  border-color: var(--accent-400, #8b6de8);
}
.ldd-child-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.ldd-child-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary, #333);
}
.ldd-child-intro {
  font-size: 11px;
  color: var(--text-muted, #999);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ldd-child-sub {
  font-size: 10.5px;
  color: var(--text-muted, #999);
  flex: none;
}
.ldd-child-arrow {
  color: var(--text-muted, #bbb);
  flex: none;
}

/* 添加 */
.ldd-add {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px;
  border: 1px dashed var(--border-color, #ccc);
  border-radius: 8px;
  color: var(--text-muted, #888);
  cursor: pointer;
  font-size: 12px;
}
.ldd-add:hover {
  border-color: var(--accent-400, #8b6de8);
  color: var(--accent-400, #8b6de8);
}
.ldd-add-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ldd-add-name,
.ldd-add-intro {
  width: 100%;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 8px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.02));
  padding: 6px 9px;
  font-size: 12.5px;
  color: var(--text-primary, #333);
  font-family: inherit;
}
.ldd-add-intro {
  resize: none;
  line-height: 1.5;
}
.ldd-add-name:focus,
.ldd-add-intro:focus {
  outline: none;
  border-color: var(--accent-400, #8b6de8);
}
.ldd-add-actions {
  display: flex;
  gap: 6px;
}
.ldd-btn {
  border: none;
  border-radius: 7px;
  background: var(--accent-400, #8b6de8);
  color: #fff;
  font-size: 12px;
  padding: 5px 12px;
  cursor: pointer;
}
.ldd-btn:disabled {
  opacity: 0.45;
  cursor: default;
}
.ldd-btn--ghost {
  background: transparent;
  color: var(--text-muted, #888);
  border: 1px solid var(--border-color, #ddd);
}

/* 底部删除 */
.ldd-foot {
  margin-top: auto;
  padding-top: 12px;
}
.ldd-del {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  color: #b4543f;
  font-size: 11.5px;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
}
.ldd-del:hover {
  background: rgba(180, 84, 63, 0.08);
}
</style>
