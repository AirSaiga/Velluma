<script setup lang="ts">
/**
 * 左缘感知带（写中常驻 180px 列）。
 *
 * 承载 Canon 感知提示（角色出场 / 伏笔回收 / private 泄露），数据来自
 * session.adaptiveSuggestions（useAdaptiveAssist 心跳接 canon_watch 产出）。
 *
 * 设计约束：任何内容都不许盖正文文字——本带是 editor-host 内的独立列，
 * 与正文区（editor-main）flex 并列，物理隔离。镜头碎片舱（SparkDock）经
 * #dock slot 注入。
 *
 * 按行对齐（批次 6.1/6.2）：感知卡锚定到正文里对应词的垂直位置（usePerceptionAlignment
 * 查 .canon-mark 标记元素视口 Y）。找到位置的卡在锚定层 absolute 渲染；
 * 找不到的（orphan/leak，label 不在当前段落）落底部兜底区 + 折叠。
 */
import { ref, computed } from 'vue'
import type { CanonHint } from '../../../services/api/domain/adaptive.api'
import { usePerceptionAlignment } from '../composables/usePerceptionAlignment'

/** 兜底区折叠阈值（空间有限） */
const COLLAPSE_AT = 4

const props = defineProps<{
  suggestions: CanonHint[]
}>()

function kindMeta(kind: string) {
  switch (kind) {
    case 'appearance':
      return { label: '角色', icon: '👤', cls: 'hint-card--character' }
    case 'callback':
      return { label: '伏笔', icon: '🔑', cls: 'hint-card--hook' }
    case 'leak':
      return { label: '泄露', icon: '⚠', cls: 'hint-card--leak' }
    case 'contradiction':
      return { label: '矛盾', icon: '⚡', cls: 'hint-card--leak' }
    default:
      return { label: 'Canon', icon: '·', cls: 'hint-card--canon' }
  }
}

// 按行对齐：感知带元素 + labels → anchors（每个 label 的 top，null=找不到）
const bandEl = ref<HTMLElement | null>(null)
const labels = computed(() => props.suggestions.map((h) => h.node_label))
const { anchors } = usePerceptionAlignment(labels, bandEl)

// 锚定卡（找到正文位置）—— absolute 渲染到对应行
const located = computed(() => {
  const out: { hint: CanonHint; top: number }[] = []
  for (let i = 0; i < props.suggestions.length; i++) {
    const top = anchors.value[i]
    if (top !== null && top !== undefined) {
      out.push({ hint: props.suggestions[i], top })
    }
  }
  return out
})
// 兜底卡（找不到正文位置：orphan/leak 等）—— 底部列表 + 折叠
const floating = computed(() =>
  props.suggestions.filter((_, i) => anchors.value[i] === null || anchors.value[i] === undefined),
)

const floatingExpanded = ref(false)
const visibleFloating = computed(() => {
  if (floatingExpanded.value || floating.value.length <= COLLAPSE_AT) return floating.value
  return floating.value.slice(0, COLLAPSE_AT)
})
const floatingHidden = computed(() =>
  floatingExpanded.value ? 0 : Math.max(0, floating.value.length - COLLAPSE_AT),
)
</script>

<template>
  <aside ref="bandEl" class="perception-band">
    <!-- 顶部固定区：header + 镜头碎片舱（slot） -->
    <div class="band-header">Canon 感知</div>
    <slot name="dock" />
    <div v-if="suggestions.length === 0" class="band-empty">
      写到相关角色 / 伏笔时，<br />这里会浮现提醒
    </div>

    <!-- 锚定层：感知卡按正文行 Y 对齐（absolute，pointer-events 放行顶部区交互） -->
    <div class="hint-anchor-layer">
      <div
        v-for="(item, i) in located"
        :key="'loc' + i"
        class="hint-card hint-card--anchor"
        :class="kindMeta(item.hint.kind).cls"
        :style="{ top: item.top + 'px' }"
      >
        <div class="hint-card__head">
          <span class="hint-card__icon">{{ kindMeta(item.hint.kind).icon }}</span>
          <span class="hint-card__label" :title="item.hint.node_label">{{ item.hint.node_label }}</span>
          <span class="hint-card__tag">{{ kindMeta(item.hint.kind).label }}</span>
        </div>
        <div v-if="item.hint.detail" class="hint-card__detail">{{ item.hint.detail }}</div>
      </div>
    </div>

    <!-- 兜底区：找不到正文位置的提醒（底部固定，流式列表 + 折叠） -->
    <div v-if="floating.length" class="hint-floating">
      <div class="band-sub">其他提醒</div>
      <div
        v-for="(hint, i) in visibleFloating"
        :key="'flt' + i"
        class="hint-card"
        :class="kindMeta(hint.kind).cls"
      >
        <div class="hint-card__head">
          <span class="hint-card__icon">{{ kindMeta(hint.kind).icon }}</span>
          <span class="hint-card__label" :title="hint.node_label">{{ hint.node_label }}</span>
          <span class="hint-card__tag">{{ kindMeta(hint.kind).label }}</span>
        </div>
        <div v-if="hint.detail" class="hint-card__detail">{{ hint.detail }}</div>
      </div>
      <button v-if="floatingHidden > 0" class="band-more" @click="floatingExpanded = true">
        +{{ floatingHidden }} 更多
      </button>
    </div>
  </aside>
</template>

<style scoped>
.perception-band {
  width: 260px;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
  height: 100%;
  order: -1;  /* 放正文左侧，避开右边 InspectorPanel 抽屉遮挡 */
  border-right: 1px solid #e2e8f0;
  background: rgba(248, 250, 252, 0.6);
}
.band-header {
  position: relative;
  z-index: 2;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  margin-bottom: 8px;
  padding: 8px 8px 0;
  font-family: ui-monospace, monospace;
}
/* 顶部固定区 slot（SparkDock）置顶，盖在锚定层之上 */
.perception-band > :slotted(*) {
  position: relative;
  z-index: 2;
}
.band-empty {
  font-size: 11px;
  color: #cbd5e1;
  line-height: 1.6;
  padding: 12px 8px;
}

/* 锚定层：覆盖整个带，pointer-events 放行（不挡顶部区交互）；卡片自身回收事件 */
.hint-anchor-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.hint-card--anchor {
  position: absolute;
  left: 8px;
  right: 8px;
  pointer-events: auto;
}

/* 兜底区：底部固定，顶部渐变避免和锚定卡硬碰 */
.hint-floating {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  max-height: 55%;
  overflow-y: auto;
  padding: 14px 8px 8px;
  background: linear-gradient(to top, rgba(248, 250, 252, 0.98) 72%, rgba(248, 250, 252, 0));
  z-index: 3;
}
.band-sub {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  margin-bottom: 5px;
  font-family: ui-monospace, monospace;
}
.band-more {
  margin-top: 4px;
  padding: 4px;
  width: 100%;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  font-size: 11px;
  cursor: pointer;
}
.band-more:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.hint-list,
.hint-card {
  /* 卡片基类（锚定 + 兜底共用） */
}
.hint-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 7px 9px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  margin-bottom: 6px;
}
.hint-card__head {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 3px;
}
.hint-card__icon {
  font-size: 12px;
  line-height: 1;
}
.hint-card__label {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hint-card__tag {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 9999px;
  background: #f1f5f9;
  color: #64748b;
  flex-shrink: 0;
}
.hint-card__detail {
  font-size: 11px;
  color: #64748b;
  line-height: 1.5;
}
/* 角色出场 —— indigo */
.hint-card--character {
  border-color: #c7d2fe;
  background: #eef2ff;
}
.hint-card--character .hint-card__tag {
  background: #e0e7ff;
  color: #4f46e5;
}
/* 伏笔回收 —— amber */
.hint-card--hook {
  border-color: #fcd34d;
  background: #fffbeb;
}
.hint-card--hook .hint-card__tag {
  background: #fef3c7;
  color: #b45309;
}
/* private 泄露 —— rose（高优先级） */
.hint-card--leak {
  border-color: #fca5a5;
  background: #fef2f2;
}
.hint-card--leak .hint-card__label {
  color: #b91c1c;
}
.hint-card--leak .hint-card__tag {
  background: #fee2e2;
  color: #b91c1c;
}
</style>
