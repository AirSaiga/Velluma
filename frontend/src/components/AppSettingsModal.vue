<script setup lang="ts">
/**
 * 通用设置弹窗（2026-09-15 设置拆分后瘦身）。
 *
 * 旧「设置」大弹窗一分为三：外观 → 左缘抽屉（AppearancePanel）、模型与 API →
 * 独立弹窗（ApiSettingsModal）、这里只留应用级通用偏好（通知偏好——即时生效、
 * localStorage 设备本地）。入口仍在 AppRail 底部齿轮，任何页面（含无书书架）可达。
 */
import ModalShell from './ModalShell.vue'
import { useAppSettings } from '../composables/useAppSettings'
import { useNotifyPrefs } from '../composables/useNotifyPrefs'
import { setOpeningCardEnabled, openingCardEnabled } from '../composables/useUiPrefs'

const { visible, close } = useAppSettings()
const { prefs: notifyPrefs, setInApp, setSystem } = useNotifyPrefs()

// 开章卡开关（01 下一阶段）：响应式镜像+存储双写——关掉副驾里的卡即时消失
// （GUI 交叉验证缺陷 #1a 修复：localStorage 直读无响应性）
</script>

<template>
  <ModalShell
    v-if="visible"
    title="设置"
    subtitle="通用偏好 · 外观与模型设置已各有独立入口（左下角）"
    width="460px"
    @close="close"
  >
    <section class="notify-section">
      <div class="section-title">通知偏好</div>
      <label class="check-row">
        <input
          type="checkbox"
          :checked="notifyPrefs.inApp"
          @change="setInApp(($event.target as HTMLInputElement).checked)"
        />
        <span>生成完成时弹出提示框</span>
      </label>
      <label class="check-row">
        <input
          type="checkbox"
          :checked="notifyPrefs.system"
          @change="setSystem(($event.target as HTMLInputElement).checked)"
        />
        <span>切走时使用 Windows 系统通知</span>
      </label>
      <p class="section-hint">只保存在这台设备上，改完即生效。</p>
    </section>

    <section class="notify-section">
      <div class="section-title">写作台</div>
      <label class="check-row">
        <input
          type="checkbox"
          :checked="openingCardEnabled"
          @change="setOpeningCardEnabled(($event.target as HTMLInputElement).checked)"
        />
        <span>开新章时，在「打算」页顶部显示开章卡（该揭的事 / 不能说破的 / 没收的线头）</span>
      </label>
      <p class="section-hint">卡片只汇总你自己录入的揭示计划、真相与伏笔——不出主意，只提醒你在哪。</p>
    </section>
  </ModalShell>
</template>

<style scoped>
.notify-section {
  padding: 2px 0 4px;
}

.section-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--accent-500);
  margin-bottom: 10px;
}

.check-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: var(--text-sm);
  color: var(--text-primary);
  cursor: pointer;
}

.section-hint {
  margin: 6px 0 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
</style>
