<script setup lang="ts">
/**
 * 真相账本侧栏分组（C1：Canon 融入世界页——信息层账本，替代旧 CanonView 节点列表 tab）。
 *
 * 2026-09-03 人话化重修（设计稿 docs/design/truth-ux/）：标题下常驻一句价值句
 * （记在这里的秘密 AI 替你守住）；次动作（从章节找漏记/旧条目挂接）收为小字行；
 * 底部「查看因果图谱 ↗」入口摘除——建边零入口，图谱永远是一屏孤立圆点。
 *
 * 主过滤轴 = 表里三态（全部/秘密/半露/公开），类型是行上的次级徽标——作者翻这本账
 * 时的问题是「读者还不知道什么」，不是「这是角色还是物件」。
 * 句子优先录入：一句话即「里」的全文，Enter 建条**不弹详情**（行落账顶闪朱 + toast
 * 确认即闭环——2026-09-03 实测修正，曾自动滑出详情表单致「记一句话跳出一屏字段」；
 * 要补两面/揭示由作者点行打开）。C1 无对象挂接，过渡期默认建「叙事」自由节点。
 * 本组件只读 + 创建——编辑集中在真相详情抽屉。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useCanon, NODE_TYPE_LABELS, NODE_TYPE_COLORS } from '../composables/useCanon'
import { useWorld } from '../composables/useWorld'
import { worldApi, type CanonMigrateRow } from '../../../services/api/domain/world.api'
import { useToast } from '../../../composables/useToast'
import { canonApi } from '../../../services/api/domain/canon.api'
import type { CanonNode, CanonVisibility } from '../../../services/api/domain/canon.api'
import { deriveFieldLayerRows } from '../engine/fieldLayers'
import { ARCHIVE_FIELDS } from '../engine/entitySchema'

const props = defineProps<{ bookId: string }>()

const emit = defineEmits<{
  select: [nodeId: string]
  'select-entity': [entityId: string]
}>()

const { nodes, ensureLoaded, refresh: refreshCanon, createNode, loading } = useCanon()
const { entities, locations } = useWorld()
const { showToast } = useToast()

void ensureLoaded(props.bookId)

// 世界刷新 → 真相账本跟新（C3：待确认池的 canon 候选 ✓ 转正后广播）
function _onWorldRefresh() {
  void refreshCanon()
}
onMounted(() => window.addEventListener('velluma:world-refresh', _onWorldRefresh))
onBeforeUnmount(() => window.removeEventListener('velluma:world-refresh', _onWorldRefresh))

/** C3：从最新有正文的章节提取真相候选 → 待确认收件箱（绝不直接进真相账本） */
const extracting = ref(false)
async function extractToInbox() {
  if (extracting.value) return
  extracting.value = true
  try {
    const r = await canonApi.extractToInbox(props.bookId)
    showToast(r.message, r.created ? 'success' : 'info')
    if (r.created) window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
  } catch (e: any) {
    showToast('提取失败：' + (e?.message || ''), 'error')
  } finally {
    extracting.value = false
  }
}

/** C2：ref 节点显示世界侧真名（漂移根治的读者视角；查不到回退 label） */
function displayName(n: CanonNode): string {
  if (n.ref_type === 'entity' && n.ref_id) {
    const hit = entities.value.find((e) => e.id === n.ref_id)
    if (hit) return hit.name
  }
  if (n.ref_type === 'location' && n.ref_id) {
    const hit = locations.value.find((l) => l.id === n.ref_id)
    if (hit) return hit.name
  }
  return n.label
}

// ===== C2 迁移：canon 节点挂接世界对象（预览 → 作者 ✓/✗ → 幂等落库）=====
const migrating = ref(false)
const migrateRows = ref<(CanonMigrateRow & { checked: boolean })[]>([])
const migrateApplying = ref(false)

async function startMigrate() {
  migrating.value = true
  migrateApplying.value = true
  try {
    const r = await worldApi.migrateCanon(props.bookId, { confirm: false })
    migrateRows.value = (r as { rows: CanonMigrateRow[] }).rows.map((row) => ({
      ...row,
      checked: row.action !== 'skip',
    }))
  } catch (e: any) {
    showToast('迁移预览失败：' + (e?.message || ''), 'error')
    migrating.value = false
  } finally {
    migrateApplying.value = false
  }
}

async function applyMigrate() {
  migrateApplying.value = true
  try {
    const r = await worldApi.migrateCanon(props.bookId, {
      confirm: true,
      decisions: migrateRows.value.map((row) => ({
        node_id: row.node_id,
        action: row.checked ? row.action : 'skip',
        target_id: row.target_id,
      })),
    })
    const done = r as { link: number; to_ledger: number; create_ledger: number }
    showToast(
      `已挂接 ${done.link} 条 · 伏笔并入账本 ${(done.to_ledger || 0) + (done.create_ledger || 0)} 条`,
      'success',
    )
    migrating.value = false
    migrateRows.value = []
    await ensureLoaded(props.bookId)
    window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
  } catch (e: any) {
    showToast('迁移失败：' + (e?.message || ''), 'error')
  } finally {
    migrateApplying.value = false
  }
}

const filter = ref<'all' | CanonVisibility>('all')

const FILTER_OPTS = [
  { k: 'all', l: '全部' },
  { k: 'private', l: '秘密' },
  { k: 'partial', l: '半露' },
  { k: 'public', l: '公开' },
] as const

const counts = computed(() => ({
  all: nodes.value.length,
  private: nodes.value.filter((n) => n.visibility === 'private').length,
  partial: nodes.value.filter((n) => n.visibility === 'partial').length,
  public: nodes.value.filter((n) => n.visibility === 'public').length,
}))

// 秘密优先，同态按更新时间倒序（最近操持的在前）
const VIS_RANK: Record<string, number> = { private: 0, partial: 1, public: 2 }
const shown = computed(() => {
  const list =
    filter.value === 'all'
      ? nodes.value
      : nodes.value.filter((n) => n.visibility === filter.value)
  return [...list].sort(
    (a, b) =>
      (VIS_RANK[a.visibility] ?? 9) - (VIS_RANK[b.visibility] ?? 9) ||
      b.updated_at.localeCompare(a.updated_at),
  )
})

function typeBadge(n: CanonNode) {
  return NODE_TYPE_LABELS[n.type] || n.type
}

// ===== 字段级真相分层（2026-09-03）派生区：档案里标了 半露/秘密 的字段在此可见 =====
// 派生而非节点副本——内容唯一事实源仍是实体档案；点击深链回实体抽屉编辑现场。
// 受三态过滤但故意不计入 counts（counts 是真实节点数，派生行只是视图）。
const ARCHIVE_FIELD_LABELS: Record<string, string> = {
  intro: '一句话',
  ...Object.fromEntries(
    Object.values(ARCHIVE_FIELDS)
      .flat()
      .map((f) => [f.key, f.label]),
  ),
}
const fieldRows = computed(() => {
  const rows = deriveFieldLayerRows(entities.value, (k) => ARCHIVE_FIELD_LABELS[k] || k)
  return filter.value === 'all' ? rows : rows.filter((r) => r.level === filter.value)
})

// ===== 句子优先录入：写下这句话就行（Enter 建条并开详情继续补表/揭示计划） =====
const adding = ref(false)
const addDraft = ref('')
const addInputRef = ref<HTMLInputElement | null>(null)

async function startAdd() {
  adding.value = true
  await nextTick()
  addInputRef.value?.focus()
}

async function submitAdd() {
  const sentence = addDraft.value.trim()
  adding.value = false
  if (!sentence) return
  addDraft.value = ''
  try {
    const node = await createNode(props.bookId, {
      book_id: props.bookId,
      type: 'event', // C1 过渡：叙事自由节点；C2 起主语按实体名/别名自动挂接
      label: sentence.length > 40 ? sentence.slice(0, 40) + '…' : sentence,
      canon_text: sentence,
      visibility: 'private', // 特意记下的真相默认是秘密，可就近改
    })
    // 2026-09-03 实测修正：记账是轻动作——不再自动弹详情表单（曾令作者
    // 「输入一段文字后就跳出这个面板，非常令人迷惑」）。行落账顶闪朱 + toast
    // 确认即闭环；要补「读者看到的版本/揭示计划」由作者主动点行打开详情。
    freshId.value = node.id
    if (freshTimer) clearTimeout(freshTimer)
    freshTimer = setTimeout(() => (freshId.value = ''), 2600)
    showToast('已记下——AI 会替你守住', 'success')
  } catch (e: any) {
    console.warn('[CanonSection] create failed:', e)
  }
}

/** 新记账条目的短暂闪朱高亮（记账反馈——「它落在哪」一眼可见） */
const freshId = ref('')
let freshTimer: ReturnType<typeof setTimeout> | null = null
</script>

<template>
  <div class="side-section">
    <div class="side-title">
      <span class="cs-mark" title="真相账本——读者知道与不知道的事，秘密 AI 替你守住"></span>
      <span>真相</span>
      <span class="side-count">{{ counts.all }}</span>
    </div>
    <p class="cs-value">记在这里的秘密，AI 写作时替你守住——不剧透、防写漏、到点提醒该抖了。</p>

    <div v-if="counts.all" class="cs-filter">
      <button
        v-for="opt in FILTER_OPTS"
        :key="opt.k"
        class="cs-chip"
        :class="{ active: filter === opt.k }"
        @click="filter = opt.k"
      >
        {{ opt.l }} {{ counts[opt.k] }}
      </button>
    </div>

    <ul v-if="shown.length" class="side-list">
      <li
        v-for="n in shown"
        :key="n.id"
        class="side-card side-card--click cs-row"
        :class="[`cs-row--${n.visibility}`, { 'cs-row--fresh': n.id === freshId }]"
        title="打开真相详情"
        @click="emit('select', n.id)"
      >
        <div class="sc-body">
          <div class="cs-head">
            <span class="cs-dot" :class="n.visibility"></span>
            <span class="cs-name">{{ displayName(n) }}</span>
            <span class="cs-type" :style="{ background: NODE_TYPE_COLORS[n.type] || 'var(--text-secondary)' }">
              {{ typeBadge(n) }}
            </span>
            <span v-if="n.visibility === 'partial'" class="cs-biao-neq" title="读者见过伪装版——表里两面都要维护">表≠里</span>
            <span v-if="n.expected_reveal_chapter" class="cs-reveal">第 {{ n.expected_reveal_chapter }} 章揭</span>
          </div>
          <div v-if="n.canon_text" class="cs-what">{{ n.canon_text }}</div>
        </div>
      </li>
    </ul>
    <div v-else-if="filter !== 'all'" class="side-empty">没有该状态的真相。</div>
    <div v-else-if="loading" class="side-empty">正在翻开真相账本…</div>
    <div v-else class="side-empty">
      还没有记录真相——秘而不宣的身世、读者尚不知道的事实，先记在这里。写作时 AI 会替你守住它们。
    </div>

    <!-- 字段级真相分层派生区：档案里标了 半露/秘密 的字段（点击回实体抽屉编辑） -->
    <template v-if="fieldRows.length">
      <div class="cs-group-title">来自角色档案 · 字段分层</div>
      <ul class="side-list">
        <li
          v-for="r in fieldRows"
          :key="`${r.entityId}:${r.fieldKey}`"
          class="side-card side-card--click cs-row"
          :class="`cs-row--${r.level}`"
          title="打开该角色的档案（分层在字段旁维护）"
          @click="emit('select-entity', r.entityId)"
        >
          <div class="sc-body">
            <div class="cs-head">
              <span class="cs-dot" :class="r.level"></span>
              <span class="cs-name">{{ r.entityName }} · {{ r.fieldLabel }}</span>
              <span class="cs-type cs-type--archive">档案</span>
              <span v-if="r.level === 'partial'" class="cs-biao-neq" title="读者见过伪装版——表里两面都要维护">表≠里</span>
              <span v-if="r.revealChapter" class="cs-reveal">第 {{ r.revealChapter }} 章揭</span>
            </div>
            <div class="cs-what">{{ r.fullText }}</div>
          </div>
        </li>
      </ul>
    </template>

    <!-- 句子优先录入 -->
    <div class="cs-add">
      <input
        v-if="adding"
        ref="addInputRef"
        v-model="addDraft"
        class="cs-add-input"
        placeholder="一句话写下真相（Enter 记下 · Esc 取消）"
        @keydown.enter.prevent="submitAdd"
        @keydown.esc="((adding = false), (addDraft = ''))"
        @blur="submitAdd"
      />
      <template v-else>
        <button class="cs-add-btn cs-add-btn--main" @click="startAdd">＋ 记一条真相</button>
        <div class="cs-sub-acts">
          <button
            class="cs-sub-act"
            :disabled="extracting"
            title="从最新有正文的章节抽取真相候选——先进待确认池，✓ 才入账"
            @click="extractToInbox"
          >{{ extracting ? '正在找…' : '从最近章节找漏记的真相' }}</button>
          <span class="cs-sub-sep">·</span>
          <button
            class="cs-sub-act"
            title="把旧条目按名字挂到世界对象/伏笔账本——挂上后对象改名将跟随"
            @click="startMigrate"
          >旧条目挂接到世界对象</button>
        </div>
      </template>
    </div>

    <!-- C2 迁移面板：canon 节点挂接世界对象（预览 → ✓/✗ → 落库） -->
    <div v-if="migrating" class="cs-migrate">
      <div class="cs-migrate-head">
        按名字挂到世界对象（改名将跟随）
        <button class="cs-migrate-x" @click="migrating = false">✕</button>
      </div>
      <div v-if="migrateApplying" class="side-empty">处理中…</div>
      <template v-else-if="migrateRows.length">
        <label v-for="row in migrateRows" :key="row.node_id" class="cs-migrate-row">
          <input type="checkbox" v-model="row.checked" :disabled="row.action === 'skip' && !row.target_id" />
          <span class="cs-migrate-label">{{ row.label }}</span>
          <span class="cs-migrate-target">
            <template v-if="row.action === 'link'">→ {{ row.target_name }}</template>
            <template v-else-if="row.action === 'to_ledger'">并入伏笔「{{ row.target_name }}」</template>
            <template v-else-if="row.action === 'create_ledger'">新建伏笔账本条目</template>
            <template v-else>未匹配到世界对象（留作自由节点）</template>
          </span>
        </label>
        <button class="cs-add-btn" @click="applyMigrate">确认迁移</button>
      </template>
      <div v-else class="side-empty">没有可迁移的条目——都挂好了。</div>
    </div>
  </div>
</template>

<style scoped>
/* 复刻 ForeshadowSection 的侧栏语言（其样式 scoped 不可复用） */
.side-section {
  padding: 0.375rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
}
.side-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  padding: 0.25rem 0.125rem;
  user-select: none;
}
.side-count {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
}

/* 朱点——信息层的视觉签名（docs/design/canon-fusion §朱点贯穿） */
.cs-mark {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 9999px;
  background: #a63e2a;
  box-shadow: 0 0 0 2px rgba(166, 62, 42, 0.14);
  flex-shrink: 0;
}

/* 常驻价值句（2026-09-03 人话化重修：翻账第一眼看到「记这个有什么用」） */
.cs-value {
  margin: 0;
  padding: 0 0.125rem 0.25rem;
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-muted);
}

.cs-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  padding: 0.25rem 0 0.375rem;
}
.cs-chip {
  font-size: var(--text-xs);
  padding: 0.125rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  /* 小字号 + 过浅灰会读作「模糊」——过滤词是高频阅读对象，提到次级墨色 */
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.12s ease;
}
.cs-chip:hover { color: var(--text-secondary); }
.cs-chip.active {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}

.side-list {
  list-style: none;
  margin: 0;
  padding: 0.125rem 0 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.side-card {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left-width: 2.5px;
  border-radius: 0.375rem;
}
.side-card--click { cursor: pointer; }
.side-card--click:hover { border-color: var(--accent-500); }

.sc-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}
.cs-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}
.cs-dot {
  width: 0.4375rem;
  height: 0.4375rem;
  border-radius: 9999px;
  flex-shrink: 0;
}
.cs-dot.private { background: #a63e2a; }
.cs-dot.partial { background: #7c5faf; }
.cs-dot.public { background: #5f7d5a; }

.cs-row--private { border-left-color: #a63e2a; }
.cs-row--partial { border-left-color: #7c5faf; }
.cs-row--public { border-left-color: #5f7d5a; }

/* 新记账短暂闪朱（记账反馈，2.6s 后消退） */
.cs-row--fresh {
  animation: cs-fresh 2.6s ease-out;
}
@keyframes cs-fresh {
  0% { box-shadow: 0 0 0 3px rgba(166, 62, 42, 0.28); background: rgba(166, 62, 42, 0.07); }
  100% { box-shadow: 0 0 0 0 rgba(166, 62, 42, 0); background: var(--bg-secondary); }
}

.cs-name {
  font-size: var(--text-base);
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-type {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: #fff;
  border-radius: 0.1875rem;
  padding: 0.0625rem 0.3125rem;
}
.cs-reveal {
  margin-left: auto;
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--accent-500, #b08d3e);
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
}
/* 半露小标：表里不一一眼可辨，不必点开猜 */
.cs-biao-neq {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: #7c5faf;
  border: 1px solid rgba(124, 95, 175, 0.4);
  border-radius: 0.1875rem;
  padding: 0 0.25rem;
}
/* 字段级真相分层派生区（2026-09-03）：来自角色档案 */
.cs-group-title {
  margin: 10px 0 6px;
  font-size: var(--text-xs);
  color: var(--text-muted);
  letter-spacing: 0.05em;
}
.cs-type--archive {
  background: #8b8578;
}
.cs-what {
  font-size: var(--text-xs);
  /* 摘要行是账本的主体文字，text-muted 在 11px 下太浅 */
  color: var(--text-secondary);
  line-height: 1.55;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-empty {
  padding: 0.5rem 0.25rem 0.625rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.6;
}

.cs-add { padding: 0.125rem 0 0.375rem; }
.cs-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  font-size: var(--text-xs);
  font-family: inherit;
  color: #a63e2a;
  background: transparent;
  border: 1px dashed rgba(166, 62, 42, 0.5);
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.cs-add-btn:hover { background: rgba(166, 62, 42, 0.08); }
/* 主按钮独占整行：账本只剩这一个主动作 */
.cs-add-btn--main {
  width: 100%;
  justify-content: center;
  padding: 6px 0;
}
.cs-add-input {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 9px;
  font-size: var(--text-sm);
  font-family: inherit;
  color: var(--text-primary);
  background: var(--bg-canvas);
  border: 1px solid #a63e2a;
  border-radius: 7px;
  outline: none;
}

/* 次动作收为小字行（提取候选/迁移挂接——低频，不占按钮位） */
.cs-sub-acts {
  margin-top: 6px;
  text-align: center;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.cs-sub-act {
  border: none;
  background: none;
  padding: 0;
  font-size: var(--text-xs);
  font-family: inherit;
  color: var(--text-muted);
  border-bottom: 1px dotted var(--text-muted);
  cursor: pointer;
}
.cs-sub-act:hover:not(:disabled) { color: var(--text-secondary); }
.cs-sub-act:disabled { cursor: default; opacity: 0.6; }
.cs-sub-sep { margin: 0 7px; color: var(--border-color); }

/* C2 迁移面板 */
.cs-migrate {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 6px 0;
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
}
.cs-migrate-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.cs-migrate-x {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: var(--text-xs);
}
.cs-migrate-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: var(--text-xs);
  cursor: pointer;
}
.cs-migrate-label {
  color: var(--text-primary);
}
.cs-migrate-target {
  color: var(--text-muted);
}
</style>
