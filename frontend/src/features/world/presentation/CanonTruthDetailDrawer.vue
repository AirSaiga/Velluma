<script setup lang="ts">
/**
 * 真相详情抽屉（2026-09-03 人话化重修，设计稿 docs/design/truth-ux/）。
 *
 * 一屏只回答两个作者问题：问一「读者现在知道吗？」（表里三态 + 表/里两卡，
 * 失焦即存；表 = 普通纸面卡，里 = 朱晕卡 + 密印 + 泄密警示——仅秘密/半露态）；
 * 问二「打算怎么抖出来？」（计划 + 章号；章号带提醒回声——写到第 N−2 章感知带
 * 会提醒，把 canon_watch 既有 ≤2 章规则显性化，零后端改动）与标签收进「补充」
 * 折叠区（2026-09-03 实测修正：详情第一眼只留「读者知道吗 + 表里两面」，低频
 * 字段不抢视线，有值自动展开）。详情只由作者主动点行打开——录入不再自动弹出。
 * 动作行只剩「贴段正文查泄密」（纯节点短语比对，不依赖边）与「删除」。
 *
 * 退役（同轮，拍板见设计稿 §07）：因果图谱入口与连锁分析（建边零入口——边恒为零，
 * 两者永远答「没有」，留着是谎话；后端边表/CRUD 与 impact 路由保留，零数据风险）、
 * 「钩子」字段区（与伏笔账本重复，存量 hook 条目改显示迁移指引行）、已挂接条目的
 * 类型下拉（C2 起类型随挂接对象推演，改类型到世界对象侧）。
 *
 * 壳契约与 EntityDetailDrawer / ForeshadowDetailDrawer 一致：absolute 浮于画布右上
 * （right: 58px 避让图标栏，top: 48px 避让胶囊工具条，z-index 700 与兄弟抽屉同层）。
 * ⚠ 本组件曾长期无壳（纯内容 div 混入 .world-canvas 的 flex 流），整幅摊开压在地图、
 * 胶囊条与图标栏上——壳是修复重叠的根，勿拆。
 *
 * 编辑框设计：textarea 无边框融入卡片，焦点反馈落在卡片级（:focus-within 描边 + 浮环），
 * 让「正在编辑哪一面」有明确视觉边界；autogrow 随内容长高，超 max-height 恢复内部滚动。
 */
import { ref, computed, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useCanon, NODE_TYPE_LABELS } from '../composables/useCanon'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { vAutogrow } from './autogrow'
import type { CanonNodeType, CanonVisibility } from '../../../services/api/domain/canon.api'

const props = defineProps<{ bookId: string; nodeId: string; canGoBack?: boolean }>()

const emit = defineEmits<{
  close: []
  /** 返回上一级（从真相账本钻入时才有上一级；由 WorldView 恢复来路面板） */
  back: []
}>()

const { nodes, updateNode, deleteNode, checkConsistency } = useCanon()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

// ===== C3 片段一致性检查（贴一段正文，对照全部真相查泄露/矛盾；纯节点比对，不依赖边）=====
const checkOpen = ref(false)
const checkText = ref('')
const checkRunning = ref(false)
const checkIssues = ref<any[] | null>(null)
async function runCheck() {
  if (checkRunning.value || !checkText.value.trim()) return
  checkRunning.value = true
  try {
    const r = await checkConsistency(props.bookId, checkText.value.trim())
    checkIssues.value = (r as any).issues || []
  } catch (e: any) {
    showToast('检查失败：' + (e?.message || ''), 'error')
  } finally {
    checkRunning.value = false
  }
}

const node = computed(() => nodes.value.find((n) => n.id === props.nodeId) || null)

/** 已挂接世界对象的条目：类型随对象推演，头部降级为只读徽标（C2 方向） */
const isLinked = computed(() => !!(node.value?.ref_type && node.value?.ref_id))
const typeLabel = computed(() => (node.value ? NODE_TYPE_LABELS[node.value.type] || node.value.type : ''))

/** 提醒回声：填「第几章揭」即把感知带 ≤2 章规则显性化（canon_watch 既有行为，零后端改动） */
const revealEcho = computed(() => {
  const n = chapterDraft.value
  if (!n || n < 1) return ''
  return `⏳ 写到第 ${Math.max(n - 2, 1)} 章时，写作台会提醒你。`
})

/**
 * 补充区（抖出来的计划 · 标签）默认折叠——2026-09-03 实测修正：
 * 详情第一眼只留「读者知道吗 + 表里两面」，低频字段不抢视线；有值时自动展开。
 */
const moreOpen = computed(
  () =>
    !!(node.value?.reveal_plan || node.value?.expected_reveal_chapter || (node.value?.tags || []).length),
)

const VIS_OPTS: { k: CanonVisibility; l: string }[] = [
  { k: 'private', l: '秘密' },
  { k: 'partial', l: '半露' },
  { k: 'public', l: '公开' },
]
const TYPE_OPTS = Object.entries(NODE_TYPE_LABELS).map(([k, l]) => ({ k: k as CanonNodeType, l }))

/** 三态的一句释义（分段控件下方的常驻说明行） */
const visNote = computed(() => {
  switch (node.value?.visibility) {
    case 'public':
      return '已建立的事实，读者已知——AI 必须遵守。'
    case 'partial':
      return '读者见过伪装版（表 ≠ 里）——两面都要维护。'
    default:
      return '读者全然不知——下面的「实际真相」AI 绝不写进正文，只当隐藏动机。'
  }
})

// ===== 表单草稿（失焦即存：与 store 不同才写） =====
const labelDraft = ref('')
const canonDraft = ref('') // 里
const publicDraft = ref('') // 表
const planDraft = ref('')
const chapterDraft = ref<number | null>(null)
const tagsDraft = ref('')

watch(
  node,
  (n) => {
    if (!n) return
    labelDraft.value = n.label
    canonDraft.value = n.canon_text || ''
    publicDraft.value = n.public_text || ''
    planDraft.value = n.reveal_plan || ''
    chapterDraft.value = n.expected_reveal_chapter ?? null
    tagsDraft.value = (n.tags || []).join(', ')
  },
  { immediate: true },
)

function parseTags(s: string): string[] {
  return s.split(',').map((t) => t.trim()).filter(Boolean)
}

async function saveField(patch: Record<string, unknown>, toast?: string) {
  if (!node.value) return
  try {
    await updateNode(props.bookId, node.value.id, patch)
    if (toast) showToast(toast, 'success')
  } catch (e: any) {
    showToast('保存失败：' + (e?.message || '未知错误'), 'error')
  }
}

async function saveLabel() {
  const v = labelDraft.value.trim()
  if (v && v !== node.value?.label) await saveField({ label: v })
}

async function saveCanonText() {
  if (canonDraft.value !== node.value?.canon_text) await saveField({ canon_text: canonDraft.value })
}

async function savePublicText() {
  if (publicDraft.value !== node.value?.public_text) await saveField({ public_text: publicDraft.value })
}

async function savePlan() {
  if (planDraft.value !== node.value?.reveal_plan) await saveField({ reveal_plan: planDraft.value })
}

async function saveChapter() {
  const v = chapterDraft.value && chapterDraft.value > 0 ? Math.floor(chapterDraft.value) : null
  if (v !== (node.value?.expected_reveal_chapter ?? null)) {
    await saveField({ expected_reveal_chapter: v })
  }
}

async function saveTags() {
  if (parseTags(tagsDraft.value).join(',') !== (node.value?.tags || []).join(',')) {
    await saveField({ tags: parseTags(tagsDraft.value) })
  }
}

async function saveType(e: Event) {
  const v = (e.target as HTMLSelectElement).value as CanonNodeType
  if (v && v !== node.value?.type) await saveField({ type: v }, '类型已更新')
}

async function saveVisibility(v: CanonVisibility) {
  if (v !== node.value?.visibility) await saveField({ visibility: v })
}

async function remove() {
  if (!node.value) return
  const ok = await showConfirm({
    title: '删除真相条目',
    message: `确定删除「${node.value.label}」吗？`,
    warning: '相连的因果边会一并删除，删除后不可恢复。',
    confirmText: '删除',
  })
  if (!ok) return
  try {
    await deleteNode(props.bookId, node.value.id)
    showToast('真相条目已删除', 'success')
    emit('close')
  } catch (e: any) {
    showToast('删除失败：' + (e?.message || '未知错误'), 'error')
  }
}
</script>

<template>
  <aside v-if="node" class="ctd" aria-label="真相详情" @keydown.esc="emit('close')">
    <!-- 头部：条目名 + 类型（已挂接 = 只读徽标，类型随对象推演）+ 关闭 -->
    <header class="ctd-head">
      <button v-if="canGoBack" class="ctd-back" title="返回上一级" @click="emit('back')">
        <Icon name="arrow-left" :size="14" />
      </button>
      <input
        v-model="labelDraft"
        class="ctd-name"
        placeholder="这条真相属于谁/关于什么"
        title="失焦即存"
        @blur="saveLabel"
        @keyup.enter="($event.target as HTMLInputElement).blur()"
      />
      <span
        v-if="isLinked"
        class="ctd-type ctd-type--linked"
        title="类型随挂接对象推演——改类型请到世界对象侧调整挂接"
      >
        {{ typeLabel }} · 已挂接
      </span>
      <select
        v-else
        class="ctd-type"
        :value="node.type"
        title="类型（自由叙事条目可改；挂接到世界对象后随对象推演）"
        @change="saveType"
      >
        <option v-for="t in TYPE_OPTS" :key="t.k" :value="t.k">{{ t.l }}</option>
      </select>
      <button class="ctd-close" title="关闭 (Esc)" @click="emit('close')">
        <Icon name="x-mark" :size="14" />
      </button>
    </header>

    <!-- 存量 hook 条目迁移指引（钩子字段区已退役——伏笔账本承接强度/状态/埋设手法） -->
    <p v-if="node.type === 'hook'" class="ctd-hook-note">
      这是旧「钩子」类型条目——伏笔的强度/状态/埋设手法已由「伏笔」账本承接。
      可到真相账本底部「旧条目挂接到世界对象」把它并入伏笔账本。
    </p>

    <!-- 问一：读者现在知道吗？（表里三态 + 表/里两卡） -->
    <section class="ctd-sec ctd-sec--first">
      <div class="ctd-q-title"><span class="ctd-q-num">问一</span>读者现在知道吗？</div>

      <div class="ctd-vis" role="group" aria-label="表里状态">
        <button
          v-for="o in VIS_OPTS"
          :key="o.k"
          class="ctd-vis-seg"
          :class="[`ctd-vis-seg--${o.k}`, { active: node.visibility === o.k }]"
          @click="saveVisibility(o.k)"
        >
          {{ o.l }}
        </button>
      </div>
      <p class="ctd-vis-note">{{ visNote }}</p>

      <div v-if="node.visibility !== 'public'" class="ctd-face ctd-face--biao">
        <div class="ctd-face-head">
          <span class="ctd-face-key">读者目前看到的版本</span>
          <span class="ctd-face-badge">表</span>
        </div>
        <textarea
          v-model="publicDraft"
          v-autogrow
          class="ctd-face-text"
          rows="2"
          aria-label="表 · 读者目前看到的版本"
          placeholder="读者目前从正文看到的（截断/伪装/错认的版本；空 = 一无所知）"
          @blur="savePublicText"
        ></textarea>
      </div>
      <p v-else class="ctd-public-note">
        公开条目：读者已知——「里」即必须遵守的已建立事实，无需单独维护表象。
      </p>

      <div class="ctd-face ctd-face--li">
        <div class="ctd-face-head">
          <span class="ctd-face-key">实际真相 · AI 死守</span>
          <span class="ctd-face-badge ctd-face-badge--li">里</span>
          <span class="ctd-seal" title="密级内容：不进正文，只影响 AI 行为">密</span>
        </div>
        <textarea
          v-model="canonDraft"
          v-autogrow
          class="ctd-face-text"
          rows="3"
          aria-label="里 · 实际真相"
          placeholder="只有你知道的完整真相"
          @blur="saveCanonText"
        ></textarea>
        <div v-if="node.visibility !== 'public'" class="ctd-warn">
          ★ AI 会把它当隐藏动机，绝不直接写出；完稿体检会比对泄密，写作时左缘感知带会提醒。
        </div>
      </div>
    </section>

    <!-- 补充：抖出来的计划 · 标签（默认折叠，有值自动展开） -->
    <details class="ctd-more" :open="moreOpen">
      <summary class="ctd-more-summary">补充：抖出来的计划 · 标签</summary>

      <!-- 问二：打算怎么抖出来？ -->
      <section class="ctd-sec ctd-sec--inmore">
        <div class="ctd-q-title"><span class="ctd-q-num">问二</span>打算怎么抖出来？</div>
        <div class="ctd-row">
          <label class="ctd-lbl">怎么揭</label>
          <input
            v-model="planDraft"
            class="ctd-input"
            placeholder="如：第 30 章通过局长遗言半揭"
            @blur="savePlan"
            @keyup.enter="($event.target as HTMLInputElement).blur()"
          />
        </div>
        <div class="ctd-row">
          <label class="ctd-lbl">第几章揭</label>
          <input
            v-model.number="chapterDraft"
            class="ctd-input ctd-input--num"
            type="number"
            min="1"
            placeholder="可选"
            @blur="saveChapter"
            @keyup.enter="($event.target as HTMLInputElement).blur()"
          />
        </div>
        <p v-if="revealEcho" class="ctd-reveal-echo">{{ revealEcho }}</p>
      </section>

      <!-- 标签 -->
      <section class="ctd-sec ctd-sec--inmore">
        <div class="ctd-sec-title">标 签</div>
        <input
          v-model="tagsDraft"
          class="ctd-input"
          placeholder="逗号分隔，如：身世, 主线"
          @blur="saveTags"
          @keyup.enter="($event.target as HTMLInputElement).blur()"
        />
      </section>
    </details>

    <!-- C3 片段一致性检查（贴一段正文，对照真相账本查泄露/矛盾） -->
    <section v-if="checkOpen" class="ctd-check">
      <div class="ctd-sec-title">贴段正文查泄密</div>
      <textarea
        v-model="checkText"
        class="ctd-check-input"
        rows="3"
        v-autogrow
        placeholder="粘贴一段正文（通常是要发布的段落），对照真相账本查泄露与矛盾…"
      ></textarea>
      <div v-if="checkIssues" class="ctd-check-result">
        <p v-if="!checkIssues.length" class="ctd-check-empty">✓ 无泄露、无矛盾。</p>
        <ul v-else class="ctd-check-list">
          <li v-for="(iss, i) in checkIssues.slice(0, 6)" :key="i" class="ctd-check-item">
            {{ iss.node_label ? `【${iss.node_label}】` : '' }}{{ iss.detail || iss.kind }}
          </li>
        </ul>
      </div>
      <div class="ctd-check-actions">
        <button class="ctd-act" :disabled="checkRunning || !checkText.trim()" @click="runCheck">{{ checkRunning ? '检查中…' : '检查' }}</button>
        <button class="ctd-act" @click="((checkOpen = false), (checkIssues = null))">收起</button>
      </div>
    </section>

    <!-- 动作 -->
    <footer class="ctd-actions">
      <button class="ctd-act" title="贴一段正文，对照真相账本查泄露与矛盾" @click="((checkOpen = true), (checkIssues = null))">贴段正文查泄密</button>
      <button class="ctd-act ctd-act--danger" @click="remove">删除</button>
    </footer>
  </aside>
</template>

<style scoped>
/* ===== 壳（修复重叠的根）：与 edd/fdd 同契约，absolute 浮于画布右上 ===== */
.ctd {
  position: absolute;
  top: 48px; /* 避让胶囊工具条 */
  right: 58px; /* 避让 M6 图标栏（右缘 46px + 间隙） */
  bottom: 12px;
  width: 360px; /* 比兄弟抽屉宽 20px：两面长文本编辑需要多一点呼吸 */
  z-index: 700; /* 与实体/伏笔抽屉同层；低于图标栏(750)与账本抽屉(740) */
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
.ctd::-webkit-scrollbar {
  width: 8px;
}
.ctd::-webkit-scrollbar-thumb {
  background: rgba(120, 95, 50, 0.22);
  border-radius: 4px;
}
.ctd::-webkit-scrollbar-thumb:hover {
  background: rgba(120, 95, 50, 0.38);
}
.ctd::-webkit-scrollbar-track {
  background: transparent;
}

/* ===== 头部 ===== */
.ctd-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ctd-name {
  flex: 1;
  min-width: 0;
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--text-primary);
  background: transparent;
  border: none;
  border-bottom: 1px dashed transparent;
  outline: none;
  padding: 2px 0;
}
.ctd-name:hover {
  border-bottom-color: var(--border-color);
}
.ctd-name:focus {
  border-bottom-color: var(--accent-500);
}
.ctd-type {
  flex-shrink: 0;
  font-size: 11px;
  font-family: inherit;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 7px;
  padding: 3px 4px;
  outline: none;
}
.ctd-type:focus {
  border-color: var(--accent-500);
}
.ctd-type--linked {
  font-size: 10px;
  padding: 2px 7px;
  color: var(--text-muted);
  cursor: default;
}
.ctd-close {
  flex-shrink: 0;
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
}
.ctd-close:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
/* 返回上一级（仅从真相账本钻入时出现，与关闭分权：← 回账本 / × 全关） */
.ctd-back {
  flex-shrink: 0;
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
}
.ctd-back:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

/* ===== 存量 hook 条目迁移指引 ===== */
.ctd-hook-note {
  margin: 10px 0 0;
  padding: 8px 10px;
  border: 1px dashed var(--border-color);
  border-radius: 8px;
  font-size: 11px;
  line-height: 1.7;
  color: var(--text-muted);
}

/* ===== 表里三态：分段控件 ===== */
.ctd-vis {
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--bg-tertiary);
  border-radius: 9999px;
}
.ctd-vis-seg {
  flex: 1;
  padding: 5px 0;
  font-size: 11px;
  font-family: inherit;
  border: none;
  border-radius: 9999px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s ease;
}
.ctd-vis-seg:hover:not(.active) {
  color: var(--text-secondary);
}
.ctd-vis-seg--private.active {
  background: #a63e2a;
  color: #fff;
}
.ctd-vis-seg--partial.active {
  background: #7c5faf;
  color: #fff;
}
.ctd-vis-seg--public.active {
  background: #5f7d5a;
  color: #fff;
}
.ctd-vis-note {
  margin: 6px 2px 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-muted);
}

/* ===== 分区与问句小标题 ===== */
.ctd-sec {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.ctd-sec--first {
  margin-top: 12px;
  padding-top: 0;
  border-top: none;
}
.ctd-q-title {
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 13px;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
  margin-bottom: 8px;
  user-select: none;
}
.ctd-q-num {
  color: #a63e2a;
  font-size: 11px;
  margin-right: 6px;
}
.ctd-sec-title {
  font-size: 11px;
  letter-spacing: 0.28em;
  color: var(--text-muted);
  margin-bottom: 8px;
  user-select: none;
}

/* ===== 补充区折叠（问二+标签：低频字段，默认收起不抢视线） ===== */
.ctd-more {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.ctd-more-summary {
  cursor: pointer;
  font-size: 11px;
  color: var(--text-muted);
  user-select: none;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ctd-more-summary::-webkit-details-marker {
  display: none;
}
.ctd-more-summary::before {
  content: "▸";
  font-size: 10px;
  transition: transform 0.12s ease;
}
.ctd-more[open] > .ctd-more-summary::before {
  transform: rotate(90deg);
}
.ctd-more-summary:hover {
  color: var(--text-secondary);
}
.ctd-sec--inmore {
  border-top: none;
  padding-top: 0;
  margin-top: 12px;
}

/* ===== 两面卡片（编辑框本体） =====
   textarea 无边框融入纸面；焦点反馈在卡片级（:focus-within），
   让「正在编辑哪一面、失焦即存的边界在哪」一眼可辨。 */
.ctd-face {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 9px 12px 10px;
  background: var(--bg-secondary);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  margin-top: 8px;
}
.ctd-face--biao:focus-within {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}
.ctd-face--li {
  background: rgba(166, 62, 42, 0.07);
  border-color: rgba(166, 62, 42, 0.32);
  border-left: 3px solid #a63e2a;
}
.ctd-face--li:focus-within {
  border-color: #a63e2a;
  box-shadow: 0 0 0 3px rgba(166, 62, 42, 0.1);
}
.ctd-face-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 4px;
}
.ctd-face-key {
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}
.ctd-face--li .ctd-face-key {
  color: #a63e2a;
}
/* 表/里退居角标（品牌词保留，不占主标题位） */
.ctd-face-badge {
  margin-left: auto;
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 10px;
  color: var(--text-muted);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  padding: 0 5px;
  letter-spacing: 0.1em;
  user-select: none;
}
.ctd-face-badge--li {
  color: #a63e2a;
  border-color: #a63e2a;
}
/* 密印收进头部行内（原位是 absolute 叠卡片右上角，窄宽下会压文字） */
.ctd-seal {
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 10.5px;
  color: #a63e2a;
  border: 1px solid #a63e2a;
  border-radius: 3px;
  padding: 0 4px;
  letter-spacing: 0.1em;
  user-select: none;
}
.ctd-face-text {
  display: block;
  width: 100%;
  box-sizing: border-box;
  font-family: var(--font-serif, 'Noto Serif SC', 'STSong', serif);
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-primary);
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  padding: 0;
}
/* autogrow 的上限：超过后恢复内部滚动，抽屉其余分区不被顶出视野 */
.ctd-face--biao .ctd-face-text {
  max-height: 180px;
}
.ctd-face--li .ctd-face-text {
  max-height: 240px;
}
.ctd-face-text::placeholder {
  color: var(--text-muted);
  opacity: 0.85;
}
.ctd-warn {
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px dashed rgba(166, 62, 42, 0.45);
  font-size: 10.5px;
  line-height: 1.7;
  color: #a63e2a;
}
.ctd-public-note {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.7;
  padding: 0 2px;
}

/* ===== 行式字段（怎么揭/第几章揭/标签） ===== */
.ctd-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.ctd-row:last-child {
  margin-bottom: 0;
}
.ctd-lbl {
  flex-shrink: 0;
  width: 64px;
  font-size: 11px;
  color: var(--text-muted);
}
.ctd-input {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 6px 10px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.ctd-input:focus {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}
.ctd-input--num {
  max-width: 96px;
}
/* 提醒回声：填章号即见规则（金色，与世界页「还有 N 章」转金同族） */
.ctd-reveal-echo {
  margin: 2px 2px 0 72px;
  font-size: 10.5px;
  line-height: 1.7;
  color: #b08d3e;
}

/* ===== 动作 ===== */
.ctd-actions {
  display: flex;
  gap: 6px;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.ctd-act {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s ease;
}
.ctd-act:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.ctd-act--danger {
  margin-left: auto;
  color: #a63e2a;
}
.ctd-act--danger:hover {
  border-color: #a63e2a;
  color: #a63e2a;
  background: rgba(166, 62, 42, 0.06);
}

/* C3 片段检查 */
.ctd-check {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.ctd-check-list {
  list-style: none;
  margin: 6px 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ctd-check-item {
  font-size: 12px;
  color: #b45309;
}
.ctd-check-empty {
  font-size: 12px;
  color: var(--text-muted);
  margin: 6px 0;
}
.ctd-check-input {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: transparent;
  font-size: 12px;
  color: var(--text-primary);
  padding: 6px 8px;
  line-height: 1.5;
  resize: none;
  font-family: inherit;
}
.ctd-check-input:focus {
  outline: none;
  border-color: var(--accent-400, #9685c2);
}
.ctd-check-actions {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
.ctd-check-result {
  margin-top: 6px;
}
</style>
