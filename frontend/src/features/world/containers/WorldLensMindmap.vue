<script setup lang="ts">
/**
 * 脑图透镜（语义投影）：实体为节点、关系为边的力导向图。
 *
 * 与地图透镜共享同一份 useWorld 数据与时间轴游标：
 * - 事件锚定边随 currentTime 推演激活/失活（拖游标看结盟变宣战——设定→事态）
 * - ⇧+按下节点拖到另一节点 = 建关系（橡皮筋线 + 内联表单）；点击边 = 编辑
 * - 增量同步（增删节点不动既有布局），仅首次非空时跑 cose 布局
 *
 * Cytoscape 用法对齐 CanonGraph.vue（同依赖同模式）。
 * 连线手势实现：容器捕获阶段拦截 ⇧+mousedown（stopPropagation，Cytoscape
 * 不感知 → 不触发节点拖动），window pointerup 手动命中检测落到目标节点。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import cytoscape, { type Core, type NodeSingular } from 'cytoscape'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { relationTypeMeta } from '../engine/relationTypes'
import RelationInlineForm from '../presentation/RelationInlineForm.vue'
import type { WorldRelation } from '../engine/types'

const props = defineProps<{ bookId: string }>()

const emit = defineEmits<{ 'entity-click': [entityId: string] }>()

const { entities, relations, worldState } = useWorld()

const containerRef = ref<HTMLDivElement | null>(null)
let cy: Core | null = null
let resizeObs: ResizeObserver | null = null

const ENTITY_COLOR: Record<string, string> = {
  character: '#7c6aad',
  faction: '#10b981',
  asset: '#f59e0b',
}
const entColor = (t: string) => ENTITY_COLOR[t] || ENTITY_COLOR.character

// ===== 增量同步：实体/关系列表变化时增删节点/边，不重排既有布局 =====

let laidOut = false

function syncElements() {
  if (!cy) return
  const entIds = new Set(entities.value.map((e) => e.id))
  cy.nodes().forEach((n) => {
    if (!entIds.has(n.id())) n.remove()
  })
  for (const e of entities.value) {
    if (cy.getElementById(e.id).empty()) {
      cy.add({
        group: 'nodes',
        data: { id: e.id, label: e.name, type: e.entity_type, color: entColor(e.entity_type) },
        position: { x: 220 + (Math.random() - 0.5) * 160, y: 200 + (Math.random() - 0.5) * 160 },
      })
    } else {
      cy.getElementById(e.id).data('label', e.name) // 改名同步
    }
  }
  const relIds = new Set(relations.value.map((r) => r.id))
  cy.edges().forEach((ed) => {
    if (!relIds.has(ed.id())) ed.remove()
  })
  for (const r of relations.value) {
    const meta = relationTypeMeta(r.relation_type)
    const bothEnds = entIds.has(r.source_entity_id) && entIds.has(r.target_entity_id)
    if (!bothEnds) continue // 悬空引用不渲染（实体被删的残边）
    if (cy.getElementById(r.id).empty()) {
      cy.add({
        group: 'edges',
        data: {
          id: r.id,
          source: r.source_entity_id,
          target: r.target_entity_id,
          color: meta.color,
          label: r.label || meta.label,
        },
      })
    } else {
      cy.getElementById(r.id).data({
        source: r.source_entity_id,
        target: r.target_entity_id,
        color: meta.color,
        label: r.label || meta.label,
      })
    }
  }
  // 首次有 ≥2 节点时跑一次布局；之后新增不重排（保持作者摆好的位置）
  if (!laidOut && cy.nodes().length >= 2) {
    laidOut = true
    cy.layout({ name: 'cose', animate: true, nodeRepulsion: () => 9000 }).run()
  }
  applyEdgeActivity()
}

/** 事件锚定边随游标激活/失活（世界状态推演结果的投影） */
function applyEdgeActivity() {
  if (!cy) return
  const activeById = new Map(worldState.value.relation_states.map((rs) => [rs.relation_id, rs.active]))
  for (const r of relations.value) {
    const ed = cy.getElementById(r.id)
    if (ed.nonempty()) ed.toggleClass('inactive', activeById.get(r.id) === false)
  }
}

watch([entities, relations], () => syncElements())
watch(() => worldState.value, () => applyEdgeActivity())

// ===== ⇧+拖线建关系（免模式手势：抓起即操作）=====

interface DraftForm {
  x: number
  y: number
  sourceId: string
  targetId: string
  existing: WorldRelation | null
}
const draftForm = ref<DraftForm | null>(null)
/** 橡皮筋线（容器坐标），null = 未在拖线 */
const rubber = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
let linking: { sourceId: string } | null = null

/** 手动命中检测：容器坐标 → 节点（渲染坐标包围圆） */
function hitNode(x: number, y: number): NodeSingular | null {
  if (!cy) return null
  let best: NodeSingular | null = null
  let bestD = Infinity
  cy.nodes().forEach((n) => {
    const p = n.renderedPosition()
    if (!p) return
    const d = (p.x - x) ** 2 + (p.y - y) ** 2
    const r = Math.max(24, (n.renderedOuterWidth() || 46) / 2)
    if (d <= r * r && d < bestD) {
      best = n
      bestD = d
    }
  })
  return best
}

/** 捕获阶段拦截 ⇧+mousedown：Cytoscape 收不到 → 不触发节点拖动 */
function onContainerMousedownCapture(e: MouseEvent) {
  if (!e.shiftKey || !containerRef.value) return
  const r = containerRef.value.getBoundingClientRect()
  const hit = hitNode(e.clientX - r.left, e.clientY - r.top)
  if (!hit) return
  e.preventDefault()
  e.stopPropagation()
  linking = { sourceId: hit.id() }
  const p = hit.renderedPosition()
  if (p) rubber.value = { x1: p.x, y1: p.y, x2: p.x, y2: p.y }
}

function onPointerMove(e: PointerEvent) {
  if (!linking || !rubber.value || !containerRef.value) return
  const r = containerRef.value.getBoundingClientRect()
  rubber.value.x2 = e.clientX - r.left
  rubber.value.y2 = e.clientY - r.top
}

function onPointerUp(e: PointerEvent) {
  if (!linking) return
  const src = linking.sourceId
  const rub = rubber.value
  linking = null
  rubber.value = null
  if (!rub || !containerRef.value) return
  const r = containerRef.value.getBoundingClientRect()
  const hit = hitNode(e.clientX - r.left, e.clientY - r.top)
  if (hit && hit.id() !== src) {
    // 中点偏下弹表单（避开连线本身），并钳制在容器内
    const fx = Math.min(Math.max((rub.x1 + rub.x2) / 2 - 150, 8), Math.max(8, r.width - 308))
    const fy = Math.min(Math.max((rub.y1 + rub.y2) / 2 + 12, 8), Math.max(8, r.height - 280))
    draftForm.value = { x: fx, y: fy, sourceId: src, targetId: hit.id(), existing: null }
  }
}

function onFormSaved() {
  draftForm.value = null
}

// ===== 生命周期 =====

const hasEntities = computed(() => entities.value.length > 0)

onMounted(async () => {
  await nextTick()
  if (!containerRef.value) return
  cy = cytoscape({
    container: containerRef.value,
    elements: [],
    wheelSensitivity: 0.2,
    style: [
      {
        selector: 'node',
        style: {
          'label': 'data(label)',
          'background-color': 'data(color)',
          'width': 46,
          'height': 46,
          'font-size': '11px',
          'color': '#6b7280',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 5,
          'text-wrap': 'ellipsis',
          'text-max-width': '90px',
          'border-width': 2,
          'border-color': '#ffffff',
        },
      },
      // 节点形状按实体类型分发（角色●/势力■/资产◆）
      { selector: 'node[type = "character"]', style: { shape: 'ellipse' } },
      { selector: 'node[type = "faction"]', style: { shape: 'rectangle' } },
      { selector: 'node[type = "asset"]', style: { shape: 'diamond' } },
      {
        selector: 'edge',
        style: {
          'width': 2,
          'line-color': 'data(color)',
          'target-arrow-color': 'data(color)',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'label': 'data(label)',
          'font-size': '10px',
          'color': '#9ca3af',
          'text-background-color': '#ffffff',
          'text-background-opacity': 0.85,
          'text-background-padding': '2px',
          'text-rotation': 'autorotate',
          'opacity': 0.9,
        },
      },
      {
        // 事件锚定边：锚事件未回放 → 失活（虚线淡显）
        selector: 'edge.inactive',
        style: {
          'line-style': 'dashed',
          'opacity': 0.18,
        },
      },
      {
        selector: 'node:selected',
        style: {
          'border-width': 3,
          'border-color': '#3b82f6',
        },
      },
    ],
  })
  cy.on('tap', 'node', (e) => emit('entity-click', e.target.id()))
  cy.on('tap', 'edge', (e) => {
    const rel = relations.value.find((x) => x.id === e.target.id())
    if (!rel || !containerRef.value || !cy) return
    const r = containerRef.value.getBoundingClientRect()
    const mid = e.target.isEdge() ? e.target.midpoint() : { x: r.width / 2, y: r.height / 2 }
    const rp = e.target.renderedPosition()
    const px = rp ? rp.x : mid.x
    const py = rp ? rp.y : mid.y
    const fx = Math.min(Math.max(px - 150, 8), Math.max(8, r.width - 308))
    const fy = Math.min(Math.max(py + 12, 8), Math.max(8, r.height - 280))
    draftForm.value = { x: fx, y: fy, sourceId: rel.source_entity_id, targetId: rel.target_entity_id, existing: rel }
  })
  syncElements()

  containerRef.value.addEventListener('mousedown', onContainerMousedownCapture, true)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  resizeObs = new ResizeObserver(() => cy?.resize())
  resizeObs.observe(containerRef.value)
})

onBeforeUnmount(() => {
  containerRef.value?.removeEventListener('mousedown', onContainerMousedownCapture, true)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  resizeObs?.disconnect()
  cy?.destroy()
  cy = null
})
</script>

<template>
  <div class="wmm">
    <div ref="containerRef" class="wmm-cy"></div>

    <!-- 橡皮筋连线（⇧+拖节点时） -->
    <svg v-if="rubber" class="wmm-rubber">
      <line
        :x1="rubber.x1"
        :y1="rubber.y1"
        :x2="rubber.x2"
        :y2="rubber.y2"
        stroke="#7c6aad"
        stroke-width="2"
        stroke-dasharray="6 4"
      />
    </svg>

    <!-- 操作提示 -->
    <div v-if="hasEntities" class="wmm-hint">⇧ + 拖动节点到另一节点 = 建关系 · 点击边编辑 · 拖动节点自由摆放</div>

    <!-- 空状态 -->
    <div v-if="!hasEntities" class="wmm-empty">
      <Icon name="users" :size="28" />
      <p>还没有实体。点上方「实体」创建角色 / 势力 / 资产，再回这里理关系。</p>
    </div>

    <!-- 建关系 / 编辑关系 内联表单 -->
    <div
      v-if="draftForm"
      class="wmm-form"
      :style="{ left: draftForm.x + 'px', top: draftForm.y + 'px' }"
    >
      <RelationInlineForm
        :book-id="bookId"
        :source-id="draftForm.sourceId"
        :target-id="draftForm.targetId"
        :existing="draftForm.existing"
        @saved="onFormSaved"
        @cancel="draftForm = null"
      />
    </div>
  </div>
</template>

<style scoped>
.wmm {
  position: relative;
  width: 100%;
  height: 100%;
  background: var(--bg-canvas);
}
.wmm-cy {
  position: absolute;
  inset: 0;
}
.wmm-rubber {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 20;
}
.wmm-hint {
  position: absolute;
  top: 10px;
  left: 12px;
  padding: 4px 10px;
  border-radius: 9999px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  font-size: 11px;
  pointer-events: none;
  z-index: 10;
}
.wmm-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
  pointer-events: none;
}
.wmm-empty p {
  font-size: 13px;
  margin: 0;
  max-width: 320px;
  text-align: center;
  line-height: 1.7;
}
.wmm-form {
  position: absolute;
  z-index: 30;
}
</style>
