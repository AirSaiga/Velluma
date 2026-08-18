<script setup lang="ts">
/**
 * 应用外壳（V3.1 F1 新建，规格 §3 + §11.1）。
 *
 * 职责：
 * - 顶层 provide 全局 store（useAppStore）
 * - 渲染左侧 AppRail + router-view（路由出口）
 * - 全局 Toast / ConfirmDialog 挂载点
 * - 启动时加载书籍列表
 *
 * 取代旧 AppContainer 的"承载一切"职责：AppShell 只管外壳与全局状态，
 * 各视图内容由 router-view 渲染对应路由页面。
 */
import { onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import Toast from '../../../components/Toast.vue'
import ConfirmDialog from '../../../components/ConfirmDialog.vue'
import AppSettingsModal from '../../../components/AppSettingsModal.vue'
import AppRail from './AppRail.vue'
import { useTheme } from '../../../composables/useTheme'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { provideAppStore } from '../useAppStore'

const route = useRoute()
const { initTheme } = useTheme()
const { toasts, showToast, removeToast } = useToast()
const {
  visible: confirmDialogVisible,
  options: confirmDialogOptions,
  show: showConfirm,
  handleConfirm: handleConfirmDialog,
  handleCancel: handleCancelDialog,
} = useConfirmDialog()

// 顶层 provide store + 全局工具
const store = provideAppStore()
// 给 store 注入 toast/confirm（通过共享 composable 实例，store 自身不依赖它们）

const pageTitle = computed(() => (route.meta.title as string) || 'Velluma')

onMounted(async () => {
  initTheme()
  try {
    await store.loadBooks()
  } catch (e: any) {
    // 首屏加载失败必须可见：此前静默吞掉，用户把「后端没起」误判为「数据丢失（空书架）」
    showToast('加载书籍失败：' + (e?.message || '未知错误') + '（请确认后端服务已启动）', 'error')
  }
})

// 暴露给需要 toast/confirm 的深层组件（通过 provide/inject 或 app.config.globalProperties）
// 这里用 defineExpose 让根组件实例可被访问（用于兼容期过渡）
defineExpose({
  showToast,
  showConfirm,
  store,
})
</script>

<template>
  <!-- 全局 Toast / ConfirmDialog / 设置弹窗 -->
  <Toast :toasts="toasts" @remove="removeToast" />
  <ConfirmDialog
    :visible="confirmDialogVisible"
    :options="confirmDialogOptions"
    @confirm="handleConfirmDialog"
    @cancel="handleCancelDialog"
  />
  <AppSettingsModal />

  <div class="app-shell">
    <AppRail />
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

.app-main {
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow: hidden;
}

.fade-enter-active {
  transition: opacity 0.15s ease-out;
}
.fade-leave-active {
  transition: opacity 0.1s ease-in;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
