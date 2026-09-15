<script setup lang="ts">
/**
 * 全局共享模态骨架（原 world/presentation/ModalShell 晋升，00 期 §4.3）：
 * Teleport body + Transition modal + 遮罩 backdrop-blur + z: var(--z-modal)
 * + useFocusTrap + Esc 关闭栈（一次 Esc 只关栈顶；焦点陷阱作栈外兜底）。
 *
 * 消灭三套自绘 overlay（旧 draft-modal/qc-modal/bi-modal z-1000 违规、无焦点陷阱）。
 * 用法：
 *   <ModalShell title="新建实体" width="360px" @close="...">
 *     表单内容
 *     <template #footer>...</template>
 *   </ModalShell>
 */
import { computed, ref, watch, onScopeDispose } from 'vue'
import Icon from './Icon.vue'
import { useFocusTrap } from '../composables/useFocusTrap'
import { useEscStack } from '../composables/useEscStack'

const props = withDefaults(
  defineProps<{
    title: string
    /** 副标题/说明（标题下方小字） */
    subtitle?: string
    width?: string
    /**
     * 收起模式：不渲染遮罩+大卡，改为顶部居中悬浮小条（标题 + bar-actions 插槽）。
     * 用于「模态临时收起去地图上绘制」场景——小条不挡地图、不抢焦点，
     * 此期间 Esc 交由外层键盘编排处理（焦点陷阱同步关闭）。
     */
    minimized?: boolean
  }>(),
  { subtitle: '', width: '440px', minimized: false },
)

const emit = defineEmits<{ close: [] }>()

const cardRef = ref<HTMLElement | null>(null)
// 收起时不陷阱焦点、不接管 Esc（用户在地图上操作）
const active = computed(() => !props.minimized)
useFocusTrap(cardRef, active, { onEscape: () => emit('close') })

// Esc 分层关闭栈：打开即入栈（一次 Esc 只关栈顶一层），收起/关闭即出栈
const escStack = useEscStack()
let escId: symbol | null = null
watch(active, (on) => {
  if (on) {
    if (!escId) escId = escStack.push(() => emit('close'), 'modal-shell')
  } else if (escId) {
    escStack.remove(escId)
    escId = null
  }
}, { immediate: true })
onScopeDispose(() => {
  if (escId) {
    escStack.remove(escId)
    escId = null
  }
})
</script>

<template>
  <Teleport to="body">
    <!-- 收起态：顶部居中悬浮小条（无遮罩、不挡地图交互） -->
    <Transition name="modal">
      <div v-if="minimized" class="ms-bar elev-3" role="status">
        <Icon name="pencil-square" :size="14" class="ms-bar-icon" />
        <span class="ms-bar-title">{{ title }}</span>
        <span class="ms-bar-actions"><slot name="bar-actions" /></span>
      </div>
    </Transition>
    <Transition name="modal">
      <div v-if="!minimized" class="ms-overlay">
        <div class="ms-backdrop" @click="emit('close')"></div>
        <div
          ref="cardRef"
          class="modal-content ms-card elev-3"
          :style="{ width, maxWidth: '92vw' }"
          role="dialog"
          aria-modal="true"
        >
          <header class="ms-header">
            <div class="ms-headings">
              <div class="ms-title">{{ title }}</div>
              <div v-if="subtitle" class="ms-subtitle">{{ subtitle }}</div>
            </div>
            <button class="ms-close" title="关闭（Esc）" @click="emit('close')">
              <Icon name="x-mark" :size="16" />
            </button>
          </header>
          <div class="ms-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="ms-footer">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ms-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal); /* 全局分层表：模态层（00 期 §3.1） */
  display: flex;
  align-items: center;
  justify-content: center;
}
.ms-backdrop {
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  /* P1 §8.5：仅遮罩层 blur 2px→10px——纸面/滚动区永不上 blur */
  backdrop-filter: blur(10px);
}
.ms-card {
  position: relative;
  display: flex;
  flex-direction: column;
  /* 弹窗卡自身作 container（00 期 §2.2-C）：内容分区按卡宽而非视口响应 */
  container-type: inline-size;
  max-height: 86vh;
  background: var(--bg-primary);
  border-radius: var(--radius-xl);
  overflow: hidden;
}
.ms-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--border-color);
}
.ms-title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
}
.ms-subtitle {
  margin-top: 3px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}
.ms-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}
.ms-close:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}
.ms-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
}
.ms-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--line-faint); /* N2 §3.8：footer 顶 hairline */
  background: var(--bg-secondary);
}
/* ---- 收起态悬浮小条 ---- */
.ms-bar {
  position: fixed;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-modal); /* 与模态同层（绘制期间全页只有这一个浮层） */
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 14px;
  background: var(--bg-primary);
  border-radius: var(--radius-pill);
  white-space: nowrap;
}
.ms-bar-icon {
  color: var(--accent-500);
  flex-shrink: 0;
}
.ms-bar-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.ms-bar-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
