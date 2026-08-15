<script setup lang="ts">
/**
 * World 模块共享模态骨架（对齐全局新式模态写法）：
 * Teleport body + Transition modal + 遮罩 backdrop-blur + z-110 + useFocusTrap。
 *
 * 消灭三套自绘 overlay（旧 draft-modal/qc-modal/bi-modal z-1000 违规、无焦点陷阱）。
 * 用法：
 *   <ModalShell title="新建实体" width="360px" @close="...">
 *     表单内容
 *     <template #footer>...</template>
 *   </ModalShell>
 */
import { computed, ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'

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
</script>

<template>
  <Teleport to="body">
    <!-- 收起态：顶部居中悬浮小条（无遮罩、不挡地图交互） -->
    <Transition name="modal">
      <div v-if="minimized" class="ms-bar" role="status">
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
          class="modal-content ms-card"
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
  z-index: 110; /* 全局分层表：模态层 */
  display: flex;
  align-items: center;
  justify-content: center;
}
.ms-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(2px);
}
.ms-card {
  position: relative;
  display: flex;
  flex-direction: column;
  max-height: 86vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  box-shadow: 0 18px 48px rgba(40, 32, 18, 0.22);
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
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.ms-subtitle {
  margin-top: 3px;
  font-size: 12px;
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
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.ms-close:hover {
  background: var(--hover-bg);
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
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
/* ---- 收起态悬浮小条 ---- */
.ms-bar {
  position: fixed;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 110; /* 与模态同层（绘制期间全页只有这一个浮层） */
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 14px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  box-shadow: 0 10px 30px rgba(40, 32, 18, 0.22);
  white-space: nowrap;
}
.ms-bar-icon {
  color: var(--accent-500);
  flex-shrink: 0;
}
.ms-bar-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.ms-bar-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
