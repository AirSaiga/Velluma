<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { worldApi } from '../../../services/api/domain/world.api'
import { useToast } from '../../../composables/useToast'

/**
 * 设定页收敛引导卡（M4/M5）：角色/资产/地图/伏笔/期待/世界观分区退役为跳转入口。
 *
 * 主按钮 = 前往世界页；次按钮 = 一键导入旧设定并前往（migrateLegacy 幂等，已导入的自动跳过）。
 * 迁移失败不阻断跳转（作者可能只是想先看看世界页）。
 */
const props = defineProps<{
  bookId: string
  icon: string
  title: string
  description: string
  /** 可选深链 query（如 { panel: 'expectations' }），随跳转带给世界页 */
  query?: Record<string, string>
}>()

const router = useRouter()
const { showToast } = useToast()
const migrating = ref(false)

function goWorld() {
  router.push({ path: `/world/${props.bookId}`, query: props.query || {} })
}

async function migrateAndGo() {
  if (migrating.value || !props.bookId) return
  migrating.value = true
  try {
    const r: any = await worldApi.migrateLegacy(props.bookId)
    showToast(
      `已导入 ${r?.characters?.migrated ?? 0} 角色 · ${r?.relations?.migrated ?? 0} 关系 · ` +
        `${r?.assets?.migrated ?? 0} 资产 · ${r?.locations?.migrated ?? 0} 地点`,
      'success',
    )
  } catch (e: any) {
    showToast('导入旧设定失败：' + (e?.message || '未知错误'), 'error')
  } finally {
    migrating.value = false
  }
  goWorld()
}
</script>

<template>
  <div class="world-redirect-card">
    <div class="wrc-icon"><Icon :name="icon" :size="26" /></div>
    <h2>{{ title }}</h2>
    <p class="wrc-desc">{{ description }}</p>
    <div class="wrc-actions">
      <button class="wrc-primary" @click="goWorld">前往世界页</button>
      <button class="wrc-secondary" :disabled="migrating" @click="migrateAndGo">
        {{ migrating ? '导入中…' : '没用过世界页？一键导入旧设定并前往' }}
      </button>
    </div>
    <p class="wrc-hint">
      静态设定的编辑已收敛至世界页（地图 · 时间轴 · 侧栏账本）；写作辅助会自动使用世界页数据。
    </p>
  </div>
</template>

<style scoped>
.world-redirect-card {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 2rem;
  color: var(--text-secondary);
}

.wrc-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 3.5rem;
  height: 3.5rem;
  border-radius: 0.75rem;
  background: var(--bg-tertiary);
  color: var(--accent-500);
  margin-bottom: 1rem;
}

.world-redirect-card h2 {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0 0 0.5rem;
}

.wrc-desc {
  max-width: 26rem;
  font-size: 0.8125rem;
  line-height: 1.7;
  margin: 0 0 1.25rem;
}

.wrc-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.wrc-primary {
  padding: 0.5rem 1.5rem;
  background: var(--accent-500);
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease;
}

.wrc-primary:hover {
  background: var(--accent-600);
}

.wrc-secondary {
  padding: 0.375rem 1rem;
  background: transparent;
  color: var(--text-muted);
  border: 1px dashed var(--border-color);
  border-radius: 0.375rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.wrc-secondary:hover:not(:disabled) {
  color: var(--text-secondary);
  border-color: var(--text-muted);
}

.wrc-hint {
  margin-top: 1.25rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
}
</style>
