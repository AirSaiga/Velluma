<script setup lang="ts">
/**
 * 真相详情抽屉（C1：一页两面——表（读者所见）与里（作者真相），替代旧 NodeEditModal）。
 *
 * 壳契约与 EntityDetailDrawer / ForeshadowDetailDrawer 一致：absolute 浮于画布右上
 * （right: 58px 避让图标栏，top: 48px 避让胶囊工具条，z-index 700 与兄弟抽屉同层）。
 * ⚠ 本组件曾长期无壳（纯内容 div 混入 .world-canvas 的 flex 流），整幅摊开压在地图、
 * 胶囊条与图标栏上——壳是修复重叠的根，勿拆。
 *
 * 三段式：① 两面区（表/里 textarea 失焦即存；表 = 普通纸面卡，里 = 朱晕卡 + 密印 +
 * 泄密警示——仅秘密/半露态）② 揭示区（计划 + 章号）③ 关联/状态动作（图谱跳转、
 * 删除带确认）。轻量编辑不进 undo（与伏笔详情同策略）。
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

const props = defineProps<{ bookId: string; nodeId: string }>()

const emit = defineEmits<{
  close: []
  'open-graph': []
}>()

const { nodes, edges, updateNode, deleteNode, analyzeImpact, checkConsistency } = useCanon()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

// ===== C3 激活：变更连锁分析 + 片段一致性检查（休眠 API 接 UI）=====
const impactResult = ref<{ affected: any[]; total_affected: number } | null>(null)
const impactRunning = ref(false)
async function runImpact() {
  if (impactRunning.value || !node.value) return
  impactRunning.value = true
  try {
    const r = await analyzeImpact(props.bookId, props.nodeId)
    impactResult.value = { affected: (r as any).affected || [], total_affected: (r as any).total_affected || 0 }
  } catch (e: any) {
    showToast('连锁分析失败：' + (e?.message || ''), 'error')
  } finally {
    impactRunning.value = false
  }
}

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
const neighborCount = computed(
  () => edges.value.filter((e) => e.source_id === props.nodeId || e.target_id === props.nodeId).length,
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
      return '读者全然不知——「里」绝不许写进正文。'
  }
})

// ===== 表单草稿（失焦即存：与 store 不同才写） =====
const labelDraft = ref('')
const canonDraft = ref('') // 里
const publicDraft = ref('') // 表
const planDraft = ref('')
const chapterDraft = ref<number | null>(null)
const tagsDraft = ref('')
const hookStrength = ref(5)
const hookStatus = ref('open')
const hookBury = ref('implicit')

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
    hookStrength.value = n.metadata?.strength || 5
    hookStatus.value = n.metadata?.status || 'open'
    hookBury.value = n.metadata?.bury_style || 'implicit'
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

async function saveHookMeta() {
  if (!node.value || node.value.type !== 'hook') return
  const m = node.value.metadata || {}
  if (
    m.strength !== hookStrength.value ||
    m.status !== hookStatus.value ||
    m.bury_style !== hookBury.value
  ) {
    await saveField({
      metadata: { ...m, strength: hookStrength.value, status: hookStatus.value, bury_style: hookBury.value },
    })
  }
}

async function remove() {
  if (!node.value) return
  const ok = await showConfirm({
    title: '删除真相条目',
    message: `确定删除「${node.value.label}」吗？`,
    warning: '相连的因果边会一并删除，删除后不可恢复（C2 接入对象挂接后入撤销栈）。',
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
    <!-- 头部：条目名 + 类型 + 关闭 -->
    <header class="ctd-head">
      <input
        v-model="labelDraft"
        class="ctd-name"
        placeholder="这条真相属于谁/关于什么"
        title="失焦即存"
        @blur="saveLabel"
        @keyup.enter="($event.target as HTMLInputElement).blur()"
      />
      <select class="ctd-type" :value="node.type" title="类型（C1 过渡期可改；C2 起由挂接对象推演）" @change="saveType">
        <option v-for="t in TYPE_OPTS" :key="t.k" :value="t.k">{{ t.l }}</option>
      </select>
      <button class="ctd-close" title="关闭 (Esc)" @click="emit('close')">
        <Icon name="x-mark" :size="14" />
      </button>
    </header>

    <!-- 表里三态：分段控件直切 + 常驻释义行 -->
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

    <!-- 两面：表（读者所见）/ 里（作者真相） -->
    <section class="ctd-sec">
      <div class="ctd-sec-title">两 面</div>

      <div v-if="node.visibility !== 'public'" class="ctd-face ctd-face--biao">
        <div class="ctd-face-head">
          <span class="ctd-face-key">表</span>
          <span class="ctd-face-desc">读者目前所见</span>
        </div>
        <textarea
          v-model="publicDraft"
          v-autogrow
          class="ctd-face-text"
          rows="2"
          aria-label="表 · 读者目前所见"
          placeholder="读者目前从正文看到的（截断/伪装/错认的版本；空 = 一无所知）"
          @blur="savePublicText"
        ></textarea>
      </div>
      <p v-else class="ctd-public-note">
        公开条目：读者已知——「里」即必须遵守的已建立事实，无需单独维护表象。
      </p>

      <div class="ctd-face ctd-face--li">
        <div class="ctd-face-head">
          <span class="ctd-face-key">里</span>
          <span class="ctd-face-desc">作者知道的真相</span>
          <span class="ctd-seal" title="密级内容：不进正文，只影响 AI 行为">密</span>
        </div>
        <textarea
          v-model="canonDraft"
          v-autogrow
          class="ctd-face-text"
          rows="3"
          aria-label="里 · 作者知道的真相"
          placeholder="作者知道的完整真相"
          @blur="saveCanonText"
        ></textarea>
        <div v-if="node.visibility !== 'public'" class="ctd-warn">
          ★ 绝不许在正文直接写出——AI 会把它当作隐藏动机影响行为；完稿体检会比对泄密，写作时左缘感知带会提醒。
        </div>
      </div>
    </section>

    <!-- 揭示计划 -->
    <section class="ctd-sec">
      <div class="ctd-sec-title">揭 示</div>
      <div class="ctd-row">
        <label class="ctd-lbl">计划</label>
        <input
          v-model="planDraft"
          class="ctd-input"
          placeholder="如：第 30 章通过局长遗言半揭"
          @blur="savePlan"
          @keyup.enter="($event.target as HTMLInputElement).blur()"
        />
      </div>
      <div class="ctd-row">
        <label class="ctd-lbl">揭示章</label>
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
    </section>

    <!-- 钩子字段（C1 过渡：hook 类型保留旧能力，C2 并入伏笔账本后退役） -->
    <section v-if="node.type === 'hook'" class="ctd-sec">
      <div class="ctd-sec-title">钩 子</div>
      <div class="ctd-row">
        <label class="ctd-lbl">强度</label>
        <input
          v-model.number="hookStrength"
          class="ctd-input ctd-input--num"
          type="number" min="1" max="10"
          @blur="saveHookMeta"
          @keyup.enter="($event.target as HTMLInputElement).blur()"
        />
      </div>
      <div class="ctd-row">
        <label class="ctd-lbl">状态</label>
        <select class="ctd-input" :value="hookStatus" @change="hookStatus = ($event.target as HTMLSelectElement).value; saveHookMeta()">
          <option value="open">未回收</option>
          <option value="callback">已回收</option>
          <option value="echoed">已呼应</option>
          <option value="subverted">被反转</option>
        </select>
      </div>
      <div class="ctd-row">
        <label class="ctd-lbl">埋设手法</label>
        <select class="ctd-input" :value="hookBury" @change="hookBury = ($event.target as HTMLSelectElement).value; saveHookMeta()">
          <option value="explicit">明确提及</option>
          <option value="implicit">隐晦暗示</option>
          <option value="half">半埋（故意说一半）</option>
          <option value="denial">角色否认</option>
        </select>
      </div>
    </section>

    <!-- 标签 -->
    <section class="ctd-sec">
      <div class="ctd-sec-title">标 签</div>
      <input
        v-model="tagsDraft"
        class="ctd-input"
        placeholder="逗号分隔，如：身世, 主线"
        @blur="saveTags"
        @keyup.enter="($event.target as HTMLInputElement).blur()"
      />
    </section>

    <!-- C3 变更连锁分析（休眠 API 激活：改这条真相会波及哪些关联条目） -->
    <section v-if="impactResult" class="ctd-impact">
      <div class="ctd-sec-title">变更连锁（{{ impactResult.total_affected }} 条受波及）</div>
      <ul v-if="impactResult.affected?.length" class="ctd-impact-list">
        <li v-for="(a, i) in impactResult.affected.slice(0, 8)" :key="i" class="ctd-impact-item">
          <span class="ctd-impact-depth">×{{ a.depth ?? '?' }}</span>
          {{ a.node?.label || a.label || '关联条目' }}
          <span class="ctd-impact-via" v-if="a.via">（经 {{ a.via }}）</span>
        </li>
      </ul>
      <p v-else class="ctd-impact-empty">没有连锁波及——这条真相相对独立。</p>
      <button class="ctd-act" @click="impactResult = null">收起</button>
    </section>

    <!-- C3 片段一致性检查（贴一段正文，对照全部真相查泄露/矛盾） -->
    <section v-if="checkOpen" class="ctd-check">
      <div class="ctd-sec-title">片段一致性检查</div>
      <textarea
        v-model="checkText"
        class="ctd-check-input"
        rows="3"
        v-autogrow
        placeholder="粘贴一段正文（通常是要发布的段落），对照真相账本查泄露与矛盾…"
      ></textarea>
      <div v-if="checkIssues" class="ctd-check-result">
        <p v-if="!checkIssues.length" class="ctd-impact-empty">✓ 无泄露、无矛盾。</p>
        <ul v-else class="ctd-impact-list">
          <li v-for="(iss, i) in checkIssues.slice(0, 6)" :key="i" class="ctd-impact-item ctd-impact-item--warn">
            {{ iss.node_label ? `【${iss.node_label}】` : '' }}{{ iss.detail || iss.kind }}
          </li>
        </ul>
      </div>
      <div class="ctd-check-actions">
        <button class="ctd-act" :disabled="checkRunning || !checkText.trim()" @click="runCheck">{{ checkRunning ? '检查中…' : '检查' }}</button>
        <button class="ctd-act" @click="((checkOpen = false), (checkIssues = null))">收起</button>
      </div>
    </section>

    <!-- 关联与动作 -->
    <footer class="ctd-actions">
      <button class="ctd-act" title="在因果图谱中查看该条目的一度邻居" @click="emit('open-graph')">
        因果图谱 · 一度 {{ neighborCount }}
      </button>
      <button class="ctd-act" :disabled="impactRunning" :title="'连锁分析：改这条真相会波及哪些关联条目（沿因果边扩散）'" @click="runImpact">{{ impactRunning ? '分析中…' : '连锁分析' }}</button>
      <button class="ctd-act" title="贴一段正文对照真相账本查泄露与矛盾" @click="((checkOpen = true), (checkIssues = null))">查片段</button>
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

/* ===== 表里三态：分段控件 ===== */
.ctd-vis {
  display: flex;
  gap: 2px;
  margin-top: 12px;
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

/* ===== 分区 ===== */
.ctd-sec {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.ctd-sec-title {
  font-size: 11px;
  letter-spacing: 0.28em;
  color: var(--text-muted);
  margin-bottom: 8px;
  user-select: none;
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
}
.ctd-face + .ctd-face {
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
.ctd-face-desc {
  font-size: 10.5px;
  color: var(--text-muted);
}
/* 密印收进头部行内（原位是 absolute 叠卡片右上角，窄宽下会压文字） */
.ctd-seal {
  margin-left: auto;
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
  margin: 0 0 8px;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.7;
  padding: 0 2px;
}

/* ===== 行式字段（揭示/钩子/标签） ===== */
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
  width: 52px;
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

/* C3 连锁分析 + 片段检查 */
.ctd-impact, .ctd-check {
  padding: 0 16px 10px;
}
.ctd-impact-list {
  list-style: none;
  margin: 6px 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ctd-impact-item {
  font-size: 12px;
  color: var(--text-secondary);
}
.ctd-impact-item--warn {
  color: #b45309;
}
.ctd-impact-depth {
  font-size: 10px;
  color: var(--text-muted);
  margin-right: 4px;
  font-family: ui-monospace, monospace;
}
.ctd-impact-via {
  color: var(--text-muted);
  font-size: 11px;
}
.ctd-impact-empty {
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
